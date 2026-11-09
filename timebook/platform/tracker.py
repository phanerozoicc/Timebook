"""前台应用采集循环。

移植自 ``Sources/Poller.swift``：2 秒轮询前台应用，切应用/切标签/空闲/锁屏时
把当前段「结账」落库；排除应用、暂停、空闲、熄屏一律不产生数据，所以「没有
记录 == 不在用电脑」。

与 Swift 版的差异：定时器由 GTK 主循环驱动（``tick`` 由 ``App`` 每 2 秒调用），
不自己开线程；X11 交互全部收敛到 ``X11Display``，便于测试注入假实现。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from ..core.models import EventRow
from ..core.settings import Settings
from ..core.store import Store
from .browsers import is_browser
from .browsers import host_from_title

log = logging.getLogger("timebook.tracker")


class WindowSource(Protocol):
    """``X11Display`` 的最小子集，便于测试注入假实现。"""

    def active_window(self): ...
    def idle_seconds(self) -> float: ...
    def screensaver_active(self) -> bool: ...


@dataclass
class OpenSegment:
    """正在进行的段（只在关闭时写库）。"""

    app_id: str
    app_name: str
    host: str | None
    title: str | None
    start: datetime

    def to_row(self, end: datetime) -> EventRow:
        return EventRow(
            app_id=self.app_id,
            app_name=self.app_name,
            start=self.start,
            end=end,
            detail=self.host,
            host=self.host,
            title=self.title,
        )


class Tracker:
    """轮询前台窗口 → 分段落库。线程安全（UI 线程 + 后台均可调用）。"""

    def __init__(
        self,
        store: Store,
        settings: Settings,
        window_source: WindowSource,
        now_fn: Callable[[], datetime] = datetime.now,
        idle_grace_seconds: float = 5.0,
    ) -> None:
        self._store = store
        self._settings = settings
        self._x11 = window_source
        self._now = now_fn
        self._idle_grace = idle_grace_seconds
        self._lock = threading.RLock()

        self._open: OpenSegment | None = None
        self._current: OpenSegment | None = None  # 只读快照，供 UI 显示
        self._idle = False
        self._last_tick: datetime | None = None
        self._last_prune_day: str = ""
        #: 段变化回调（供「丢小时」判定与 UI 刷新）。
        self.on_segment_change: Callable[[str, str | None], None] | None = None

        self.prune_old_data()

    # -- 主循环 ---------------------------------------------------------- #

    def tick(self, now: datetime | None = None) -> None:
        now = now or self._now()
        with self._lock:
            try:
                self._tick_locked(now)
            except Exception:  # pragma: no cover - 采集必须永不崩
                log.exception("采集 tick 异常（已忽略）")
            finally:
                self._last_tick = now
                self.prune_if_needed(now)

    def _tick_locked(self, now: datetime) -> None:
        # 1) 暂停：关段且不记
        if self._settings.paused:
            self._close_open(now, record=False)
            self._idle = False
            return

        # 2) 熄屏/锁屏：不记
        try:
            if self._x11.screensaver_active():
                self._close_open(now, record=False)
                self._idle = False
                return
        except Exception:  # pragma: no cover
            pass

        # 3) 空闲：把结束时间回退到「开始空闲之前」，避免把发呆时间算进去
        threshold = self._settings.idle_threshold
        idle_seconds = 0.0
        try:
            idle_seconds = float(self._x11.idle_seconds() or 0.0)
        except Exception:  # pragma: no cover
            idle_seconds = 0.0
        if threshold > 0 and idle_seconds >= threshold:
            back = max(0.0, idle_seconds - self._idle_grace)
            self._close_open(now - timedelta(seconds=back), record=True)
            if not self._idle:
                log.debug("进入空闲（%.0fs ≥ 阈值 %ss）", idle_seconds, threshold)
            self._idle = True
            return
        self._idle = False

        # 4) 前台窗口
        try:
            window = self._x11.active_window()
        except Exception:  # pragma: no cover
            window = None
        if window is None:
            return

        app_id = (window.app_id or "").strip() or "unknown"
        app_name = (window.app_name or app_id).strip()

        # 排除应用：完全不落库
        if app_id in self._settings.excluded or app_name in self._settings.excluded:
            if self._open is not None:
                self._close_open(now, record=False)
            return

        host = None
        title = None
        if self._settings.browser_title_parsing and is_browser(app_id, app_name):
            host = host_from_title(window.title or "")
        if self._settings.capture_titles and (window.title or "").strip():
            title = window.title.strip()

        last_tick_gap = (
            (now - self._last_tick).total_seconds() if self._last_tick is not None else 0.0
        )

        if self._open is None:
            self._begin(OpenSegment(app_id, app_name, host, title, now))
            return

        # 应用切换，或浏览器换了标签页（host 变化）→ 断段
        if self._open.app_id != app_id or self._open.host != host:
            self._close_open(now, record=True)
            self._begin(OpenSegment(app_id, app_name, host, title, now))
            return

        # 同一应用内标题变化 / 名字变化：刷新展示信息
        self._open.app_name = app_name
        if title:
            self._open.title = title
        self._current = self._open

        # 5) 休眠/挂起恢复后的大跳跃：丢弃这一段，避免一次记上几小时
        if last_tick_gap > max(threshold, 300) + 30:
            self._close_open(now, record=False)
            self._begin(OpenSegment(app_id, app_name, host, title, now))

    # -- 段管理 ---------------------------------------------------------- #

    def _begin(self, segment: OpenSegment) -> None:
        self._open = segment
        self._current = segment
        if self.on_segment_change:
            try:
                self.on_segment_change(segment.app_id, segment.host)
            except Exception:  # pragma: no cover
                log.exception("段变化回调异常")

    def _close_open(self, end: datetime, record: bool) -> None:
        segment = self._open
        self._open = None
        if segment is None:
            return
        if record and end > segment.start:
            try:
                self._store.add_event(
                    app_id=segment.app_id,
                    app_name=segment.app_name,
                    start=segment.start,
                    end=end,
                    detail=segment.host,
                    host=segment.host,
                    title=segment.title,
                )
            except Exception:  # pragma: no cover
                log.exception("写入使用记录失败")

    def force_close(self, now: datetime | None = None) -> None:
        """退出前调用：把当前段结账。"""
        with self._lock:
            self._close_open(now or self._now(), record=True)

    # -- 查询 ------------------------------------------------------------ #

    @property
    def current_app_name(self) -> str | None:
        segment = self._open or self._current
        return segment.app_name if segment else None

    @property
    def current_host(self) -> str | None:
        segment = self._open or self._current
        return segment.host if segment else None

    @property
    def current_segment_start(self) -> datetime | None:
        segment = self._open or self._current
        return segment.start if segment else None

    @property
    def is_idle(self) -> bool:
        return self._idle

    @property
    def is_paused(self) -> bool:
        return self._settings.paused

    def today_seconds(self, now: datetime | None = None) -> float:
        now = now or self._now()
        rows = self._store.today_rows(now)
        total = float(sum(r.duration for r in rows))
        # 加上尚未结账的当前段，让菜单栏数字实时跳动
        segment = self._open
        if segment is not None and not self._settings.paused and not self._idle:
            total += max(0.0, (now - segment.start).total_seconds())
        return total

    def snapshot(self, now: datetime | None = None) -> dict:
        now = now or self._now()
        return {
            "paused": self._settings.paused,
            "idle": self._idle,
            "current_app": self.current_app_name,
            "current_host": self.current_host,
            "today_seconds": self.today_seconds(now),
        }

    # -- 维护 ------------------------------------------------------------ #

    def prune_old_data(self, now: datetime | None = None) -> int:
        days = self._settings.retention_days
        if days <= 0:
            return 0
        try:
            removed = self._store.delete_older_than(days, now or self._now())
            if removed:
                log.info("保留期清理：删除 %d 条旧记录（保留 %d 天）", removed, days)
            return removed
        except Exception:  # pragma: no cover
            log.exception("保留期清理失败")
            return 0

    def prune_if_needed(self, now: datetime | None = None) -> None:
        now = now or self._now()
        day = now.strftime("%Y-%m-%d")
        if day != self._last_prune_day:
            self._last_prune_day = day
            self.prune_old_data(now)
