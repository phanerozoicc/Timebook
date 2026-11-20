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
from ...core.forfeit import ToggleOutcome
from ...core.l10n import T, count_label  # noqa: E402
from .. import widgets as W  # noqa: E402
from ..theme import AMBER, BRAND, CALM_BLUE, GAP, WELL_GREEN  # noqa: E402
from .base import Page  # noqa: E402

LOST_COLOR = 0xE5484D
KEPT_COLOR = 0x2E3A45


class HourGrid(Gtk.Grid):
    """24 native toggle buttons: keyboard access and a label beyond color."""

    def __init__(self, on_toggle=None) -> None:
        super().__init__(column_spacing=6, row_spacing=6)
        self.set_column_homogeneous(True)
        self._day = ""
        self._on_toggle = on_toggle
        self.buttons = []
        for hour in range(24):
            button = Gtk.ToggleButton()
            button.add_css_class("tb-hour")
            button.set_hexpand(True)
            button.connect("clicked", self._clicked, hour)
            self.attach(button, hour % 8, hour // 8, 1, 1)
            self.buttons.append(button)

    def set_state(self, day: str, lost: set[int], current_hour: int) -> None:
        self._day = day
        for hour, button in enumerate(self.buttons):
            status = T("荒", "Lost") if hour in lost else T("守", "Kept")
            future = hour > current_hour
            if future:
                status = "—"
            button.set_label(f"{hour:02d}  {status}")
            button.set_active(hour in lost)
            button.set_sensitive(not future)
            if hour == current_hour:
                button.add_css_class("current")
            else:
                button.remove_css_class("current")
            text = T(f"{hour:02d}:00 · {status}", f"{hour:02d}:00 · {status}")
            button.set_tooltip_text(text)
            W.accessible(button, text)

    def _clicked(self, _button, hour) -> None:
        if self._on_toggle:
            self._on_toggle(self._day, hour)


class ForfeitPage(Page):
    def __init__(self, ctx) -> None:
        super().__init__(ctx, "forfeit")
        self._rules_signature = None
        self._known_apps = None

        # 概览
        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cards.set_homogeneous(True)
        self.card_today = W.StatCard("media-record-symbolic", ('今日荒废', 'Hours lost today'), ('0 小时', '0 hours'), LOST_COLOR)
        self.card_streak = W.StatCard("emblem-ok-symbolic", ('连续干净天', 'Clean streak'), ('0 天', '0 days'), WELL_GREEN)
        self.card_month = W.StatCard("office-calendar-symbolic", ('最近 30 天', 'Last 30 days'), ('0 小时', '0 hours'), AMBER)
        for card in (self.card_today, self.card_streak, self.card_month):
            cards.append(card)
        self.body.append(cards)

        # 24 格
        grid_card = W.card(10)
        head = W.hbox(8)
        head.append(W.label(('一天 24 格', '24 hours at a glance'), "tb-section"))
        head.append(W.spacer())
        self.grid_hint = W.label(('点击格子可手动改判', 'Click an hour to change its status'), "tb-caption")
        head.append(self.grid_hint)
        grid_card.append(head)
        self.grid = HourGrid(self._toggle_hour)
        grid_card.append(self.grid)
        legend = W.hbox(14)
        for color, text in ((LOST_COLOR, ("荒：分心应用占用", "Lost: distracting activity")), (KEPT_COLOR, ("守：清醒使用", "Kept: mindful activity")), (BRAND, ("当前小时", "Current hour"))):
            row = W.hbox(6)
            dot = W.color_dot(color, 9)
            row.append(dot)
            row.append(W.label(text, "tb-caption"))
            legend.append(row)
        grid_card.append(legend)
        self.body.append(grid_card)

        # 最近 14 天柱状
        bars_card = W.card(8)
        bars_card.append(W.SectionHeader("office-calendar-symbolic", ('最近 14 天', 'Last 14 days'), ('每天荒废小时数', 'Hours lost each day')))
        self.bars = W.BarChart(130)
        bars_card.append(self.bars)
        self.body.append(bars_card)

        # 分心应用名单
        apps_card = W.card(8)
        apps_card.append(W.SectionHeader("applications-system-symbolic", ('分心应用', 'Distracting apps'), ('被切到前台即判荒', 'Using one marks the hour as lost')))
        self.app_rows = W.vbox(2)
        apps_card.append(self.app_rows)
        self.app_empty = W.EmptyState("emblem-ok-symbolic", ('还没有设置分心应用。从下面最近用过的应用里挑一个。', 'Choose a recently used app below to mark it as distracting.'))
        apps_card.append(self.app_empty)

        picker_row = W.hbox(8)
        self.app_picker = Gtk.DropDown.new_from_strings([])
        self.app_picker.set_hexpand(True)
        self._app_ids: list[str] = []
        picker_row.append(self.app_picker)
        add_app = W.translated(Gtk.Button(), label=('加入名单', 'Add to list'))
        self.add_app_button = add_app
        W.translated(self.app_picker, accessible=("选择分心应用", "Choose a distracting app"))
        add_app.add_css_class("tb-ghost")
        add_app.connect("clicked", self._add_distractor)
        picker_row.append(add_app)
        apps_card.append(picker_row)
        self.body.append(apps_card)

        # 分心类目
        cat_card = W.card(8)
        cat_card.append(W.SectionHeader("view-grid-symbolic", ('分心类目', 'Distracting categories'), ('浏览器命中这些类目即判荒', 'Browsing these categories marks the hour as lost')))
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
            row.append(W.label((category.name_zh, category.name_en), "tb-caption"))
            switch = Gtk.Switch()
            switch.set_valign(Gtk.Align.CENTER)
            W.translated(switch, accessible=(category.name_zh, category.name_en))
            switch.connect("notify::active", self._toggle_category, category.id)
            self.cat_switches[category.id] = switch
            row.append(switch)
            self.cat_flow.append(row)
        cat_card.append(self.cat_flow)
        self.body.append(cat_card)

        # 自定义域名
        dom_card = W.card(8)
        dom_card.append(W.SectionHeader("network-server-symbolic", ('自定义分心网站', 'Custom distracting sites'), ('域名后缀匹配', 'Includes matching subdomains')))
        self.dom_rows = W.vbox(2)
        dom_card.append(self.dom_rows)
        entry_row = W.hbox(8)
        self.dom_entry = Gtk.Entry()
        W.translated(self.dom_entry, placeholder_text=('例如 douyin.com', 'e.g. douyin.com'))
        W.translated(self.dom_entry, accessible=("自定义分心网站域名", "Distracting site domain"))
        self.dom_entry.set_hexpand(True)
        self.dom_entry.connect("activate", self._add_domain)
        entry_row.append(self.dom_entry)
        add_dom = W.translated(Gtk.Button(), label=('添加', 'Add'))
        add_dom.add_css_class("tb-ghost")
        add_dom.connect("clicked", self._add_domain)
        entry_row.append(add_dom)
        dom_card.append(entry_row)
        self.dom_error = W.label("", "tb-error", wrap=True)
        self.dom_error.set_visible(False)
        dom_card.append(self.dom_error)
        self.body.append(dom_card)

        self._syncing = False

    # ------------------------------------------------------------------ #


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
            self.dom_entry.remove_css_class("error")
            self.dom_error.set_visible(False)
            self.refresh(force=True)
        else:
            self.dom_entry.add_css_class("error")
            self.dom_error.set_text(T("请输入有效域名，并检查是否已在名单中。", "Enter a valid domain that is not already listed."))
            self.dom_error.set_visible(True)

    def _add_distractor(self, _widget) -> None:
        index = self.app_picker.get_selected()
        if 0 <= index < len(self._app_ids):
            self._ctx.forfeit.add_distractor(self._app_ids[index])
            self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        force = self.refresh_language() or force
        if self.dom_error.get_visible():
            self.dom_error.set_text(T("请输入有效域名，并检查是否已在名单中。", "Enter a valid domain that is not already listed."))
        now = datetime.now()
        ledger = self._ctx.forfeit.ledger
        day = ledger.current_day_key
        lost = ledger.lost_hours(day)

        self.grid.set_state(day, lost, now.hour)
        self.card_today.set_value(count_label(len(lost), "hour"))
        self.card_streak.set_value(count_label(ledger.clean_streak(), "day"))
        self.card_month.set_value(count_label(ledger.total_lost(30), "hour"))

        bars = ledger.last_n_day_bars(14)
        self.bars.set_points(
            [(d.strftime("%m/%d"), hours * 3600) for d, hours in bars],
            LOST_COLOR,
        )

        known = [app for app in self._ctx.store.known_apps() if app[0] not in self._ctx.forfeit.distractor_apps]
        signature = (tuple(sorted(self._ctx.forfeit.distractor_apps)),
                     tuple(sorted(self._ctx.forfeit.enabled_categories)),
                     tuple(sorted(self._ctx.forfeit.custom_domains)), tuple(known))
        if signature == self._rules_signature and not force:
            return
        self._rules_signature = signature
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
            remove = W.translated(Gtk.Button(), label=('移除', 'Remove'))
            remove.add_css_class("tb-ghost")
            remove.connect("clicked", lambda _b, a=app_id: self._remove_distractor(a))
            row.append(remove)
            self.app_rows.append(row)

        # 应用候选
        if known != self._known_apps or force:
            index = self.app_picker.get_selected()
            selected = self._app_ids[index] if 0 <= index < len(self._app_ids) else None
            self._known_apps = known
            self._app_ids = [app_id for app_id, _name in known]
            self.app_picker.set_model(Gtk.StringList.new([name for _, name in known] or [T("（暂无可用应用）", "No apps available")]))
            if selected in self._app_ids:
                self.app_picker.set_selected(self._app_ids.index(selected))
            self.app_picker.set_sensitive(bool(known))
            self.add_app_button.set_sensitive(bool(known))

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
            remove = W.translated(Gtk.Button(), label=('移除', 'Remove'))
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
