"""GTK 应用：装配上下文、驱动定时器、接入托盘与窗口。

定时器职责（对齐 macOS 版的 Poller / PomodoroEngine / LimitsEngine 节奏）：
* 采集 tick：2 秒
* 番茄 tick：1 秒
* 限额检查：60 秒
* 休息/喝水提醒：5 秒
* 界面刷新：2 秒
* 快照落盘：60 秒（``widget-snapshot.json``，供第三方/小组件读取）
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .context import AppContext  # noqa: E402
from .core import models  # noqa: E402
from .core.applog import setup_logging  # noqa: E402
from .core.brain_level import for_total  # noqa: E402
from .core.forfeit import ForfeitStore  # noqa: E402
from .core.l10n import set_language, set_system_language  # noqa: E402
from .core.pomodoro import PomodoroEngine  # noqa: E402
from .core.settings import Settings  # noqa: E402
from .core.store import Store  # noqa: E402
from .core.wellbeing import (  # noqa: E402
    LimitCheckInputs,
    LimitsEngine,
    LimitSettings,
    ReminderSettings,
    RemindersEngine,
)
from .platform.notify import Notifier  # noqa: E402
from .platform.tracker import Tracker  # noqa: E402
from .platform.x11 import X11Display  # noqa: E402
from .ui.introspect import count_widgets, widget_texts  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402
from .ui.theme import install_css  # noqa: E402

log = logging.getLogger("timebook.app")

APP_ID = "io.github.phanerozoicc.Timebook"


def snapshot_path() -> Path:
    from .core.store import default_data_dir

    return default_data_dir() / "widget-snapshot.json"


class TimebookApp(Adw.Application):
    """应用主类。``--screenshot`` 等参数在 ``main.py`` 里解析。"""

    def __init__(self, options: dict | None = None) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.options = options or {}
        self.ctx: AppContext | None = None
        self.window: MainWindow | None = None
        self.tray = None
        self._tick_sources: list[int] = []
        self._last_snapshot = 0.0
        self._pomodoro_fired: set[str] = set()
        self._break_overlay = None

        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    # ------------------------------------------------------------------ #
    # 装配
    # ------------------------------------------------------------------ #

    def _on_startup(self, _app) -> None:
        install_css()
        db_path = self.options.get("db_path") or os.environ.get("TIMEBOOK_DB")
        store = Store(db_path)
        settings = Settings(store)

        set_language(settings.language)
        if settings.language != "auto":
            set_system_language("zh" if settings.language == "zh" else "en")

        notifier = Notifier(app=self)
        notifier.enabled = settings.notifications_enabled

        pomodoro = PomodoroEngine(store)
        tracker = Tracker(store, settings, X11Display())
        limits = LimitsEngine()
        reminders = RemindersEngine()
        forfeit = ForfeitStore(store)

        ctx = AppContext(
            store=store,
            settings=settings,
            pomodoro=pomodoro,
            limits=limits,
            reminders=reminders,
            tracker=tracker,
            forfeit=forfeit,
            notifier=notifier,
        )
        self.ctx = ctx

        # 引擎回调接线
        pomodoro.on_notify = ctx.notify
        pomodoro.on_work_segment = self._on_work_segment
        pomodoro.on_break_start = self._on_break_start
        limits.on_notify = ctx.notify
        reminders.on_notify = ctx.notify
        reminders.cups_provider = ctx.cups
        tracker.on_segment_change = self._on_segment_change

        log.info(
            "启动完成 db=%s idle=%ss limits=%s tray=%s",
            store.path, settings.idle_threshold, settings.limits_enabled, settings.tray_enabled,
        )

    def _on_activate(self, _app) -> None:
        if self.ctx is None:  # pragma: no cover - 防御
            return
        if self.window is None:
            self.window = MainWindow(self, self.ctx)
            self.window.connect("close-request", self._on_window_close)
            self._setup_tray()
            self._start_timers()

        self.window.present()
        page = self.options.get("page")
        if page:
            self.window.show_page(page)
        self._run_headless_tasks()
        self._schedule_quit()

    def _setup_tray(self) -> None:
        if not self.ctx.settings.tray_enabled:
            return
        from .platform.tray import Tray

        self.tray = Tray(
            self.ctx,
            on_open=self._open_window,
            on_pause=lambda _p: self._refresh_all(force=True),
            on_quit=self.quit,
            on_cup=self._tray_add_cup,
            on_break=self._show_break_overlay,
        )
        self.tray.refresh(force=True)

    def _tray_add_cup(self) -> None:
        if self.ctx is not None:
            self.ctx.add_cup(1)
            self._refresh_all(force=True)

    @property
    def tracking_enabled(self) -> bool:
        return not self.options.get("no_track")

    def _on_shutdown(self, _app) -> None:
        for source in self._tick_sources:
            try:
                GLib.source_remove(source)
            except Exception:  # pragma: no cover
                pass
        self._tick_sources.clear()
        if self.ctx is not None and not self.options.get("no_track"):
            self.ctx.tracker.force_close()
            self.ctx.forfeit.save()
            self.ctx.store.close()
        if self.tray is not None:
            self.tray.destroy()
        log.info("已退出")

    # ------------------------------------------------------------------ #
    # 定时器
    # ------------------------------------------------------------------ #

    def _every(self, seconds: int, callback) -> None:
        def _wrapped() -> bool:
            try:
                callback()
            except Exception:  # pragma: no cover - 定时器不得崩
                log.exception("定时任务异常")
            return True

        self._tick_sources.append(GLib.timeout_add_seconds(seconds, _wrapped))

    def _start_timers(self) -> None:
        self._every(2, self._tick_tracker)
        self._every(1, self._tick_pomodoro)
        self._every(2, self._refresh_all)
        self._every(5, self._tick_reminders)
        self._every(60, self._tick_limits)
        # 启动后立即跑一次
        self._tick_tracker()
        self._tick_pomodoro()

    def _tick_tracker(self) -> None:
        if self.ctx is None or self.options.get("no_track"):
            return
        self.ctx.tracker.tick()

    def _tick_pomodoro(self) -> None:
        if self.ctx is None:
            return
        self.ctx.pomodoro.tick()

    def _tick_reminders(self) -> None:
        if self.ctx is None:
            return
        settings = self.ctx.settings
        engine = self.ctx.pomodoro
        in_break = engine.state.phase.is_break and not engine.state.paused
        snapshot = ReminderSettings(
            notifications_enabled=settings.notifications_enabled,
            break_enabled=settings.break_reminder_enabled,
            break_interval_minutes=settings.break_interval_minutes,
            water_enabled=settings.water_enabled,
            water_interval_minutes=settings.water_interval_minutes,
            water_start_hour=settings.water_start_hour,
            water_end_hour=settings.water_end_hour,
            water_goal_cups=settings.water_goal_cups,
        )
        self.ctx.reminders.tick(
            idle=self.ctx.tracker.is_idle or settings.paused,
            in_pomodoro_break=in_break,
            settings=snapshot,
            tick_interval=5,
        )

    def _tick_limits(self) -> None:
        if self.ctx is None:
            return
        settings = self.ctx.settings
        snapshot = LimitSettings(
            enabled=settings.limits_enabled,
            daily_minutes=settings.limits_daily_minutes,
            distract_enabled=settings.distract_nudge_enabled,
        )
        self.ctx.limits.minute(
            LimitCheckInputs(
                today_total=self.ctx.today_total(),
                daily_limit_minutes=settings.limits_daily_minutes,
                now=datetime.now(),
                current_host=self.ctx.tracker.current_host,
                current_segment_start=self.ctx.tracker.current_segment_start,
            ),
            snapshot,
        )

    def _refresh_all(self, force: bool = False) -> None:
        if self.ctx is None:
            return
        if self.window is not None and self.window.get_visible():
            self.window.refresh(force=force)
        if self.tray is not None:
            self.tray.refresh(force=force)
        self._write_snapshot()

    # ------------------------------------------------------------------ #
    # 引擎事件
    # ------------------------------------------------------------------ #

    def _on_work_segment(self, segment) -> None:
        if self.ctx is None:
            return
        self.ctx.store.record_focus(
            segment.start, segment.end, segment.completed, segment.preset_name
        )
        log.info(
            "番茄段落库 completed=%s %.0fs", segment.completed, segment.duration
        )

    def _on_break_start(self) -> None:
        if self.ctx is None:
            return
        self.ctx.reminders.reset_active_time()
        if self.ctx.settings.pomodoro_break_overlay:
            self._show_break_overlay()

    def _on_segment_change(self, app_id: str, host: str | None) -> None:
        if self.ctx is None:
            return
        if self.ctx.forfeit.observe(app_id, host):
            self.ctx.forfeit.save()

    # ------------------------------------------------------------------ #
    # 微休息遮罩
    # ------------------------------------------------------------------ #

    def _show_break_overlay(self) -> None:
        if self._break_overlay is not None:
            return
        from .ui.overlay import BreakOverlay

        overlay = BreakOverlay(self, on_done=self._close_overlay)
        self._break_overlay = overlay
        overlay.present()

    def _close_overlay(self) -> None:
        self._break_overlay = None

    # ------------------------------------------------------------------ #
    # 快照（对应 macOS 的 widget-snapshot.json）
    # ------------------------------------------------------------------ #

    def _write_snapshot(self) -> None:
        if self.ctx is None:
            return
        now = datetime.now()
        if (now.timestamp() - self._last_snapshot) < 55:
            return
        self._last_snapshot = now.timestamp()
        total = self.ctx.today_total()
        level = for_total(total)
        engine = self.ctx.pomodoro
        payload = {
            "todaySeconds": round(total, 1),
            "level": level.level,
            "levelName": level.name,
            "levelLabel": level.label_en,
            "pomoPhase": engine.state.phase.value,
            "pomoRemain": round(engine.remain, 1),
            "pomoRound": engine.state.round,
            "pomoTotal": round(engine.phase_total, 1),
            "topAppName": self.ctx.tracker.current_app_name,
            "generatedAt": now.isoformat(timespec="seconds"),
        }
        try:
            path = snapshot_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            log.debug("快照写入失败", exc_info=True)

    # ------------------------------------------------------------------ #
    # 其它
    # ------------------------------------------------------------------ #

    def _open_window(self) -> None:
        if self.window is not None:
            self.window.present()

    def _on_window_close(self, *_args) -> bool:
        # 关窗不退出：托盘常驻、采集继续（macOS 菜单栏应用的行为）
        if self.ctx is not None and self.ctx.settings.tray_enabled and self.tray is not None and self.tray.available:
            self.window.set_visible(False)
            return True
        self.quit()
        return True

    def _schedule_quit(self) -> None:
        """``--run-seconds``：跑够时间后优雅退出（会正常结账当前段）。"""
        seconds = self.options.get("run_seconds")
        if not seconds:
            return
        GLib.timeout_add(int(float(seconds) * 1000), lambda: (self.quit(), False)[1])

    def _run_headless_tasks(self) -> None:
        """``--screenshot`` / ``--dump`` 等无头校验入口。"""
        shot = self.options.get("screenshot")
        dump = self.options.get("dump")
        if not shot and not dump:
            return

        def _do() -> bool:
            if self.window is not None:
                self.window.refresh(force=True)
            if dump:
                self._dump_state(dump)
            if shot:
                self._capture(shot)
            if self.options.get("quit_after"):
                self.quit()
            return False

        # 等一帧渲染完成
        GLib.timeout_add(900, _do)

    def _capture(self, path: str) -> None:
        """把窗口渲染成 PNG（走 X11 XID + ImageMagick import，最保真）。"""
        if self.window is None:
            return
        try:
            surface = self.window.get_native().get_surface()
            xid = surface.get_xid() if hasattr(surface, "get_xid") else None
            if xid:
                import subprocess

                subprocess.run(
                    ["import", "-window", str(xid), path], check=False, timeout=20
                )
                log.info("截图已保存 %s (xid=%s)", path, xid)
                return
        except Exception:  # pragma: no cover
            log.exception("截图失败")
        # 退化：GdkTexture
        try:
            paintable = Gtk.WidgetPaintable.new(self.window)
            image = paintable.get_current_image()
            if image is not None and hasattr(image, "save_to_png"):
                image.save_to_png(path)
        except Exception:  # pragma: no cover
            log.exception("截图退化路径也失败")

    def _dump_state(self, path: str) -> None:
        """把关键 UI 状态导出成 JSON（自动化验证用）。"""
        if self.ctx is None or self.window is None:
            return
        ctx = self.ctx
        rows = ctx.store.today_rows()
        payload = {
            "page": self.window.current_page_key(),
            "today_seconds": round(ctx.today_total(), 1),
            "today_rows": len(rows),
            "total_label": models.fmt_duration(models.total(rows), compact=True),
            "by_app": [(s.name, round(s.seconds)) for s in models.by_app(rows, limit=8)],
            "by_host": [(s.host, round(s.seconds)) for s in models.by_host(rows, limit=8)],
            "by_category": [(s.name, round(s.seconds)) for s in models.by_category(rows, limit=9)],
            "pomodoro_phase": ctx.pomodoro.state.phase.value,
            "pomodoro_remain": round(ctx.pomodoro.remain),
            "pomodoro_round": ctx.pomodoro.state.round,
            "cups": ctx.cups(),
            "forfeit_lost_today": sorted(ctx.forfeit.ledger.lost_hours(ctx.forfeit.ledger.current_day_key)),
            "paused": ctx.settings.paused,
            "idle": ctx.tracker.is_idle,
            "current_app": ctx.tracker.current_app_name,
            "tray_available": bool(self.tray and self.tray.available),
            "pages": ["today", "focus", "stats", "timeline", "forfeit"],
            "layout_width": self.window.get_width(),
            "layout_height": self.window.get_height(),
            "widget_count": count_widgets(self.window),
            "widget_texts": widget_texts(self.window)[:120],
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_context(db_path: str | None = None) -> AppContext:
    """无 GUI 地构造上下文（测试/演示数据生成用）。"""
    store = Store(db_path)
    settings = Settings(store)
    set_language(settings.language)
    pomodoro = PomodoroEngine(store)
    tracker = Tracker(store, settings, X11Display())
    ctx = AppContext(
        store=store,
        settings=settings,
        pomodoro=pomodoro,
        limits=LimitsEngine(),
        reminders=RemindersEngine(),
        tracker=tracker,
        forfeit=ForfeitStore(store),
        notifier=Notifier(),
    )
    return ctx
