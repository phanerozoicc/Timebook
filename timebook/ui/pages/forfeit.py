"""丢小时页：一天 24 格，点格子可手动改判；分心应用与网站名单。

移植 macOS 版 ``ForfeitPane``：分心应用在当前小时被切到前台 → 该小时整格记
「荒」。24 格视图让你一眼看到今天「荒」了几个小时。
"""

from __future__ import annotations

import math
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from ...core.categories import ALL as CATEGORIES  # noqa: E402
from ...core.forfeit import ToggleOutcome  # noqa: E402
from .. import widgets as W  # noqa: E402
from ..theme import AMBER, BRAND, CALM_BLUE, GAP, WELL_GREEN  # noqa: E402
from .base import Page  # noqa: E402

LOST_COLOR = 0xE5484D
KEPT_COLOR = 0x2E3A45


class HourGrid(Gtk.Widget):
    """一天 24 格（2 行 × 12 列）；荒 = 红，守 = 深灰，未来 = 极暗。"""

    CELL_W = 34
    CELL_H = 30
    GAP = 5
    TOP = 14

    def __init__(self, on_toggle=None) -> None:
        super().__init__()
        self._lost: set[int] = set()
        self._current_hour = 0
        self._day = ""
        self._on_toggle = on_toggle
        self.set_size_request(12 * (self.CELL_W + self.GAP), 2 * (self.CELL_H + self.GAP) + self.TOP)
        self._area = Gtk.DrawingArea()
        self._area.set_draw_func(self._draw)
        self._container = Gtk.Box()
        self._container.append(self._area)
        self.set_layout_manager(Gtk.BinLayout())
        self._container.set_parent(self)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self._area.add_controller(click)

    def set_state(self, day: str, lost: set[int], current_hour: int) -> None:
        self._day, self._lost, self._current_hour = day, set(lost), current_hour
        self._area.queue_draw()

    def _cell_rect(self, hour: int) -> tuple[float, float, float, float]:
        row, col = divmod(hour, 12)
        x = col * (self.CELL_W + self.GAP)
        y = self.TOP + row * (self.CELL_H + self.GAP)
        return x, y, self.CELL_W, self.CELL_H

    def _draw(self, _area, cr, w, h):
        for hour in range(24):
            x, y, cw, ch = self._cell_rect(hour)
            lost = hour in self._lost
            future = hour > self._current_hour
            if lost:
                W.fill_rounded(cr, x, y, cw, ch, 8, LOST_COLOR, 0.9)
                text_color = (1, 1, 1, 0.95)
            elif future:
                W.fill_rounded(cr, x, y, cw, ch, 8, 0xFFFFFF, 0.04)
                text_color = (1, 1, 1, 0.22)
            else:
                W.fill_rounded(cr, x, y, cw, ch, 8, KEPT_COLOR, 0.55)
                text_color = (1, 1, 1, 0.5)
            W.draw_text(cr, f"{hour}", x + cw / 2, y + 7, size=11,
                        color=text_color, align="center", weight=Pango.Weight.BOLD)
            if hour == self._current_hour:
                cr.set_line_width(1.5)
                cr.set_source_rgba(*W.rgba(BRAND, 0.95))
                W.rounded_rect(cr, x + 0.75, y + 0.75, cw - 1.5, ch - 1.5, 8)
                cr.stroke()

    def _on_click(self, gesture, _n_press, x, y) -> None:
        col = int(x // (self.CELL_W + self.GAP))
        row = int((y - self.TOP) // (self.CELL_H + self.GAP))
        if not (0 <= col < 12 and 0 <= row < 2):
            return
        hour = row * 12 + col
        if self._on_toggle:
            self._on_toggle(self._day, hour)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)


class ForfeitPage(Page):
    def __init__(self, ctx) -> None:
        super().__init__(ctx, "forfeit")

        # 概览
        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cards.set_homogeneous(True)
        self.card_today = W.StatCard("media-record-symbolic", "今日荒废", "0 小时", LOST_COLOR)
        self.card_streak = W.StatCard("emblem-ok-symbolic", "连续干净天", "0 天", WELL_GREEN)
        self.card_month = W.StatCard("office-calendar-symbolic", "最近 30 天", "0 小时", AMBER)
        for card in (self.card_today, self.card_streak, self.card_month):
            cards.append(card)
        self.body.append(cards)

        # 24 格
        grid_card = W.card(10)
        head = W.hbox(8)
        head.append(W.label("一天 24 格", "tb-section"))
        head.append(W.spacer())
        self.grid_hint = W.label("点击格子可手动改判", "tb-caption")
        head.append(self.grid_hint)
        grid_card.append(head)
        self.grid = HourGrid(self._toggle_hour)
        grid_card.append(self.grid)
        legend = W.hbox(14)
        for color, text in ((LOST_COLOR, "荒：分心应用占用"), (KEPT_COLOR, "守：清醒使用"), (BRAND, "当前小时")):
            row = W.hbox(6)
            dot = W.color_dot(color, 9)
            row.append(dot)
            row.append(W.label(text, "tb-caption"))
            legend.append(row)
        grid_card.append(legend)
        self.body.append(grid_card)

        # 最近 14 天柱状
        bars_card = W.card(8)
        bars_card.append(W.SectionHeader("office-calendar-symbolic", "最近 14 天", "每天荒废小时数"))
        self.bars = W.BarChart(130)
        bars_card.append(self.bars)
        self.body.append(bars_card)

        # 分心应用名单
        apps_card = W.card(8)
        apps_card.append(W.SectionHeader("applications-system-symbolic", "分心应用", "被切到前台即判荒"))
        self.app_rows = W.vbox(2)
        apps_card.append(self.app_rows)
        self.app_empty = W.EmptyState("emblem-ok-symbolic", "还没有设置分心应用。从下面最近用过的应用里挑一个。")
        apps_card.append(self.app_empty)

        picker_row = W.hbox(8)
        self.app_picker = Gtk.DropDown.new_from_strings([])
        self.app_picker.set_hexpand(True)
        self._app_ids: list[str] = []
        picker_row.append(self.app_picker)
        add_app = Gtk.Button(label="加入名单")
        add_app.add_css_class("tb-ghost")
        add_app.connect("clicked", self._add_distractor)
        picker_row.append(add_app)
        apps_card.append(picker_row)
        self.body.append(apps_card)

        # 分心类目
        cat_card = W.card(8)
        cat_card.append(W.SectionHeader("view-grid-symbolic", "分心类目", "浏览器命中这些类目即判荒"))
        self.cat_flow = Gtk.FlowBox()
        self.cat_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.cat_flow.set_max_children_per_line(5)
        self.cat_flow.set_row_spacing(6)
        self.cat_flow.set_column_spacing(6)
        self.cat_switches: dict[str, Gtk.Switch] = {}
        for category in CATEGORIES:
            if category.id == "other":
                continue
            row = W.hbox(6)
            row.append(W.color_dot(category.hex_color, 8))
            row.append(W.label(category.name_zh if self._zh() else category.name_en, "tb-caption"))
            switch = Gtk.Switch()
            switch.connect("notify::active", self._toggle_category, category.id)
            self.cat_switches[category.id] = switch
            row.append(switch)
            self.cat_flow.append(row)
        cat_card.append(self.cat_flow)
        self.body.append(cat_card)

        # 自定义域名
        dom_card = W.card(8)
        dom_card.append(W.SectionHeader("network-server-symbolic", "自定义分心网站", "域名后缀匹配"))
        self.dom_rows = W.vbox(2)
        dom_card.append(self.dom_rows)
        entry_row = W.hbox(8)
        self.dom_entry = Gtk.Entry()
        self.dom_entry.set_placeholder_text("例如 douyin.com")
        self.dom_entry.set_hexpand(True)
        self.dom_entry.connect("activate", self._add_domain)
        entry_row.append(self.dom_entry)
        add_dom = Gtk.Button(label="添加")
        add_dom.add_css_class("tb-ghost")
        add_dom.connect("clicked", self._add_domain)
        entry_row.append(add_dom)
        dom_card.append(entry_row)
        self.body.append(dom_card)

        self._syncing = False

    # ------------------------------------------------------------------ #

    def _zh(self) -> bool:
        from ...core.l10n import resolved_language

        return resolved_language() == "zh"

    def _toggle_hour(self, day: str, hour: int) -> None:
        outcome = self._ctx.forfeit.ledger.toggle(day, hour)
        if outcome is not ToggleOutcome.REJECTED:
            self._ctx.forfeit.save()
            self.refresh(force=True)

    def _toggle_category(self, switch, _param, category_id: str) -> None:
        if self._syncing:
            return
        self._ctx.forfeit.toggle_category(category_id)
        self.refresh(force=True)

    def _add_domain(self, _widget) -> None:
        text = self.dom_entry.get_text().strip()
        if text and self._ctx.forfeit.add_custom_domain(text):
            self.dom_entry.set_text("")
            self.refresh(force=True)

    def _add_distractor(self, _widget) -> None:
        index = self.app_picker.get_selected()
        if 0 <= index < len(self._app_ids):
            self._ctx.forfeit.add_distractor(self._app_ids[index])
            self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        now = datetime.now()
        ledger = self._ctx.forfeit.ledger
        day = ledger.current_day_key
        lost = ledger.lost_hours(day)

        self.grid.set_state(day, lost, now.hour)
        self.card_today.set_value(f"{len(lost)} 小时")
        self.card_streak.set_value(f"{ledger.clean_streak()} 天")
        self.card_month.set_value(f"{ledger.total_lost(30)} 小时")

        bars = ledger.last_n_day_bars(14)
        self.bars.set_points(
            [(d.strftime("%m/%d"), hours * 3600) for d, hours in bars],
            LOST_COLOR,
        )

        # 分心应用列表
        self._sync_switches()
        child = self.app_rows.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.app_rows.remove(child)
            child = nxt
        apps = sorted(self._ctx.forfeit.distractor_apps)
        self.app_rows.set_visible(bool(apps))
        self.app_empty.set_visible(not apps)
        for app_id in apps:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("tb-row")
            row.append(W.label(app_id, ellipsize=Pango.EllipsizeMode.END))
            row.append(W.spacer())
            remove = Gtk.Button(label="移除")
            remove.add_css_class("tb-ghost")
            remove.connect("clicked", lambda _b, a=app_id: self._remove_distractor(a))
            row.append(remove)
            self.app_rows.append(row)

        # 应用候选
        known = [app for app in self._ctx.store.known_apps() if app[0] not in self._ctx.forfeit.distractor_apps]
        self._app_ids = [app_id for app_id, _name in known]
        names = [f"{name}" for _app_id, name in known]
        self.app_picker.set_model(Gtk.StringList.new(names or ["（暂无可用应用）"]))

        # 自定义域名
        child = self.dom_rows.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.dom_rows.remove(child)
            child = nxt
        for domain in sorted(self._ctx.forfeit.custom_domains):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("tb-row")
            row.append(W.label(domain, "tb-mono", ellipsize=Pango.EllipsizeMode.END))
            row.append(W.spacer())
            remove = Gtk.Button(label="移除")
            remove.add_css_class("tb-ghost")
            remove.connect("clicked", lambda _b, d=domain: self._remove_domain(d))
            row.append(remove)
            self.dom_rows.append(row)

    def _sync_switches(self) -> None:
        self._syncing = True
        try:
            for category_id, switch in self.cat_switches.items():
                switch.set_active(category_id in self._ctx.forfeit.enabled_categories)
        finally:
            self._syncing = False

    def _remove_distractor(self, app_id: str) -> None:
        self._ctx.forfeit.remove_distractor(app_id)
        self.refresh(force=True)

    def _remove_domain(self, domain: str) -> None:
        self._ctx.forfeit.remove_custom_domain(domain)
        self.refresh(force=True)
