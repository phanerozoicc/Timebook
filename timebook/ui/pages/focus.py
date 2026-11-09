"""专注页：环形进度 + 轮次圆点 + 控制 + 预设 + 自动开始 + 统计卡 + 分心记录。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from ...core import models  # noqa: E402
from ...core.pomodoro import PRESET_NAMES, PRESETS, PomodoroPhase  # noqa: E402
from .. import widgets as W  # noqa: E402
from ..theme import BRAND, CALM_BLUE, GAP, PHASE_COLORS, WATER, WELL_GREEN  # noqa: E402
from .base import Page  # noqa: E402


class RoundsDots(Gtk.Widget):
    """轮次圆点：已完成的轮次实心，当前轮次描边。"""

    def __init__(self) -> None:
        super().__init__()
        self._total = 4
        self._round = 1
        self._color = BRAND
        self.set_size_request(-1, 18)
        self._area = Gtk.DrawingArea()
        self._area.set_draw_func(self._draw)
        self._container = Gtk.Box()
        self._container.append(self._area)
        self.set_layout_manager(Gtk.BinLayout())
        self._container.set_parent(self)

    def set_state(self, total: int, current: int, color: int) -> None:
        self._total, self._round, self._color = max(1, total), current, color
        self._area.queue_draw()

    def _draw(self, _area, cr, w, h):
        gap = 9.0
        radius = 5.0
        total_w = self._total * radius * 2 + (self._total - 1) * gap
        x = (w - total_w) / 2 + radius
        for index in range(self._total):
            done = index < self._round - 1
            current = index == self._round - 1
            cr.set_line_width(1.6)
            if done:
                cr.set_source_rgba(*W.rgba(self._color, 0.95))
                cr.arc(x, h / 2, radius, 0, 2 * math.pi)
                cr.fill()
            elif current:
                cr.set_source_rgba(*W.rgba(self._color, 0.95))
                cr.arc(x, h / 2, radius, 0, 2 * math.pi)
                cr.stroke()
                cr.arc(x, h / 2, radius - 3, 0, 2 * math.pi)
                cr.fill()
            else:
                cr.set_source_rgba(1, 1, 1, 0.18)
                cr.arc(x, h / 2, radius, 0, 2 * math.pi)
                cr.stroke()
            x += radius * 2 + gap


class FocusPage(Page):
    def __init__(self, ctx) -> None:
        super().__init__(ctx, "focus")

        # ---- 主卡：环 + 阶段 + 控制 ----
        main_card = W.card(12)
        self.ring = W.RingProgress(196, 11)
        main_card.append(self.ring)

        self.phase_label = W.label("待机", "tb-section", xalign=0.5)
        self.phase_label.set_halign(Gtk.Align.CENTER)
        main_card.append(self.phase_label)

        self.dots = RoundsDots()
        main_card.append(self.dots)

        controls = W.hbox(8)
        controls.set_halign(Gtk.Align.CENTER)
        self.primary_button = Gtk.Button(label="开始专注")
        self.primary_button.add_css_class("tb-primary")
        self.primary_button.connect("clicked", self._on_primary)
        controls.append(self.primary_button)

        self.skip_button = Gtk.Button(label="跳过")
        self.skip_button.add_css_class("tb-ghost")
        self.skip_button.connect("clicked", self._on_skip)
        controls.append(self.skip_button)

        self.stop_button = Gtk.Button(label="结束")
        self.stop_button.add_css_class("tb-ghost")
        self.stop_button.connect("clicked", self._on_stop)
        controls.append(self.stop_button)
        main_card.append(controls)

        # 预设
        preset_row = W.hbox(8)
        preset_row.set_halign(Gtk.Align.CENTER)
        preset_row.append(W.label("预设", "tb-caption"))
        self.preset_buttons: dict[str, Gtk.ToggleButton] = {}
        group = None
        for preset_id, preset_label in PRESET_NAMES:
            button = Gtk.ToggleButton(label=preset_label)
            button.add_css_class("tb-ghost")
            if group is not None:
                button.set_group(group)
            group = button
            button.connect("toggled", self._on_preset, preset_id)
            self.preset_buttons[preset_id] = button
            preset_row.append(button)
        main_card.append(preset_row)

        # 自动开始
        auto_row = W.hbox(14)
        auto_row.set_halign(Gtk.Align.CENTER)
        self.auto_break = Gtk.Switch()
        self.auto_break.connect("notify::active", self._on_auto_break)
        auto_row.append(W.label("自动开始休息", "tb-caption"))
        auto_row.append(self.auto_break)
        self.auto_work = Gtk.Switch()
        self.auto_work.connect("notify::active", self._on_auto_work)
        auto_row.append(W.label("自动开始下一轮", "tb-caption"))
        auto_row.append(self.auto_work)
        main_card.append(auto_row)
        self.body.append(main_card)

        # ---- 四张统计卡 ----
        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        stats.set_homogeneous(True)
        self.card_done = W.StatCard("emblem-ok-symbolic", "今日完成", "0 🍅", BRAND)
        self.card_focus = W.StatCard("alarm-symbolic", "专注时长", "0m", WELL_GREEN)
        self.card_water = W.StatCard("water", "喝水", "0/8", WATER)
        self.card_active = W.StatCard("preferences-system-time-symbolic", "连续活跃", "0m", CALM_BLUE)
        for card in (self.card_done, self.card_focus, self.card_water, self.card_active):
            stats.append(card)
        self.body.append(stats)

        # ---- 喝水快捷 ----
        water_card = W.card(8)
        water_head = W.hbox(8)
        water_head.append(W.label("💧 喝水", "tb-section"))
        water_head.append(W.spacer())
        self.water_label = W.label("0 / 8 杯", "tb-caption")
        water_head.append(self.water_label)
        water_card.append(water_head)
        water_buttons = W.hbox(8)
        for delta, text in ((1, "+1 杯"), (-1, "−1 杯")):
            button = Gtk.Button(label=text)
            button.add_css_class("tb-ghost")
            button.connect("clicked", lambda _b, d=delta: self._on_water(d))
            water_buttons.append(button)
        self.water_run = W.CapsuleBar(0.0, WATER, 8)
        water_buttons.append(self.water_run)
        water_card.append(water_buttons)
        self.body.append(water_card)

        # ---- 分心记录 ----
        self.distract_card = W.card(8)
        self.distract_card.append(W.SectionHeader("dialog-warning-symbolic", "分心记录", "本次专注期间"))
        self.distract_rows = W.vbox(4)
        self.distract_card.append(self.distract_rows)
        self.distract_empty = W.EmptyState("emblem-ok-symbolic", "本次专注很干净，没有切到别的应用。")
        self.distract_card.append(self.distract_empty)
        self.body.append(self.distract_card)

        self._syncing = False

    # ------------------------------------------------------------------ #

    def _on_primary(self, _button) -> None:
        self._ctx.pomodoro.toggle()
        self.refresh(force=True)

    def _on_skip(self, _button) -> None:
        self._ctx.pomodoro.skip()
        self.refresh(force=True)

    def _on_stop(self, _button) -> None:
        self._ctx.pomodoro.reset()
        self.refresh(force=True)

    def _on_preset(self, button: Gtk.ToggleButton, preset_id: str) -> None:
        if self._syncing or not button.get_active():
            return
        self._ctx.pomodoro.active_preset_name = preset_id
        self.refresh(force=True)

    def _on_auto_break(self, switch, _param) -> None:
        if not self._syncing:
            self._ctx.pomodoro.auto_start_breaks = switch.get_active()

    def _on_auto_work(self, switch, _param) -> None:
        if not self._syncing:
            self._ctx.pomodoro.auto_start_work = switch.get_active()

    def _on_water(self, delta: int) -> None:
        self._ctx.add_cup(delta)
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        engine = self._ctx.pomodoro
        state = engine.state
        phase = state.phase
        phase_color = PHASE_COLORS.get(phase.value, BRAND)

        # 环：运行中显示剩余倒计时；ready/idle 显示阶段时长
        if phase.is_running:
            big = engine.remain_clock
        elif phase.ready_base is not None:
            total_min = int(engine.phase_total // 60)
            big = f"{total_min:02d}:00"
        else:
            big = f"{int(engine.phase_total // 60):02d}:00"
        self.ring.update(engine.progress, phase_color, big, phase.label)

        self.phase_label.set_text(
            f"{phase.label} · 第 {state.round}/{engine.preset.rounds} 轮"
            if phase is not PomodoroPhase.IDLE
            else "待机 · 准备好就开始第一个番茄"
        )
        self.dots.set_state(engine.preset.rounds, state.round if phase is not PomodoroPhase.IDLE else 0, phase_color)

        # 主按钮文案
        if phase is PomodoroPhase.IDLE:
            text = "开始专注"
        elif phase.ready_base is not None:
            text = f"开始{phase.label.replace('准备', '')}"
        elif state.paused:
            text = "继续"
        else:
            text = "暂停"
        self.primary_button.set_label(text)
        self.skip_button.set_sensitive(phase.is_running)
        self.stop_button.set_sensitive(phase is not PomodoroPhase.IDLE)

        # 预设/开关同步（不触发回调）
        self._syncing = True
        try:
            active = engine.active_preset_name
            for preset_id, button in self.preset_buttons.items():
                button.set_active(preset_id == active)
            self.auto_break.set_active(engine.auto_start_breaks)
            self.auto_work.set_active(engine.auto_start_work)
        finally:
            self._syncing = False

        # 统计卡
        now = datetime.now()
        focus_rows = self._ctx.store.focus_for_day(now.date())
        completed = sum(1 for f in focus_rows if f.completed)
        focus_seconds = sum(f.duration for f in focus_rows if f.completed)
        self.card_done.set_value(f"{completed} 🍅")
        self.card_focus.set_value(models.fmt_duration(focus_seconds, compact=True))

        cups = self._ctx.cups()
        goal = self._ctx.settings.water_goal_cups
        self.card_water.set_value(f"{cups}/{goal}")
        self.water_label.set_text(f"{cups} / {goal} 杯")
        self.water_run.set_fraction(cups / goal if goal else 0.0)

        active_seconds = self._ctx.reminders.active_seconds
        self.card_active.set_value(models.fmt_duration(active_seconds, compact=True))

        # 分心记录：本次专注期间用过的应用（从使用记录反查）
        self._refresh_distractions()

    def _refresh_distractions(self) -> None:
        child = self.distract_rows.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.distract_rows.remove(child)
            child = nxt

        state = self._ctx.pomodoro.state
        if not state.phase.is_running or state.ends_at is None:
            self.distract_rows.set_visible(False)
            self.distract_empty.set_visible(True)
            self.distract_empty.set_text("专注开始后，这里会列出你切到过的应用。")
            return

        total = self._ctx.pomodoro.phase_total
        start = state.ends_at - timedelta(seconds=total)
        rows = self._ctx.store.rows_overlapping(start, datetime.now())
        apps = models.by_app(rows, limit=6)
        apps = [a for a in apps if a.seconds > 20]
        if not apps:
            self.distract_rows.set_visible(False)
            self.distract_empty.set_visible(True)
            self.distract_empty.set_text("本次专注很干净，没有切到别的应用。")
            return

        self.distract_empty.set_visible(False)
        self.distract_rows.set_visible(True)
        peak = max(a.seconds for a in apps)
        for app in apps:
            self.distract_rows.append(W.BarRow(app.name, app.seconds, peak, color=BRAND, label_width=150))
