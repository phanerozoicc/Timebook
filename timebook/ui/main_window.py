"""主窗口：侧边栏导航 + 顶栏 + 页面栈。

对应 macOS 版 ``MainWindow.swift``：4 段导航换成侧边栏（品牌头部 + 图标导航 +
底部今日合计迷你卡），⌘1–5 快捷键切页。
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..core import models  # noqa: E402
from ..core.brain_level import for_total  # noqa: E402
from ..core.l10n import T  # noqa: E402
from . import widgets as W  # noqa: E402
from .pages.focus import FocusPage  # noqa: E402
from .pages.forfeit import ForfeitPage  # noqa: E402
from .pages.stats import StatsPage  # noqa: E402
from .pages.timeline import TimelinePage  # noqa: E402
from .pages.today import TodayPage  # noqa: E402
from .theme import BRAND, GAP, WELL_GREEN, css_rgba, css_hex  # noqa: E402

PAGES = [
    ("today", "今日", "Today", "x-office-calendar-symbolic"),
    ("focus", "专注", "Focus", "alarm-symbolic"),
    ("stats", "统计", "Stats", "org.gnome.Settings-applications-symbolic"),
    ("timeline", "时间线", "Timeline", "document-open-recent-symbolic"),
    ("forfeit", "丢小时", "Forfeit", "dialog-warning-symbolic"),
]


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, ctx) -> None:
        super().__init__(application=app)
        self._ctx = ctx
        self._lang = self._current_lang()
        W.translated(self, title=('时账 Timebook', 'Timebook'))
        self.set_default_size(1020, 720)
        self.set_size_request(860, 600)
        self.add_css_class("tb-window")

        self._settings_window = None
        self._nav_rows: dict[str, Gtk.ListBoxRow] = {}

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # ---- 顶栏 ----
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        self.page_title = W.translated(Gtk.Label(), label=('今日', 'Today'))
        self.page_title.add_css_class("tb-page-title")
        header.set_title_widget(self.page_title)

        self.pause_button = W.translated(Gtk.ToggleButton(), label=('暂停记录', 'Pause tracking'))
        self.pause_button.add_css_class("tb-ghost")
        self.pause_button.connect("toggled", self._on_pause_toggled)
        header.pack_end(self.pause_button)

        settings_button = Gtk.Button()
        settings_button.set_icon_name("emblem-system-symbolic")
        W.translated(settings_button, tooltip_text=("设置", "Settings"))
        settings_button.add_css_class("tb-icon-button")
        W.translated(settings_button, accessible=("设置", "Settings"))
        settings_button.connect("clicked", lambda _b: self._open_settings())
        header.pack_end(settings_button)

        export_button = Gtk.Button()
        export_button.set_icon_name("document-save-symbolic")
        W.translated(export_button, tooltip_text=("导出 CSV 与周报", "Export CSV and weekly report"))
        export_button.add_css_class("tb-icon-button")
        W.translated(export_button, accessible=("导出数据", "Export data"))
        export_button.connect("clicked", lambda _b: self._open_export())
        header.pack_end(export_button)
        root.append(header)

        # ---- 主体：侧边栏 + 内容 ----
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.set_vexpand(True)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar.add_css_class("tb-sidebar")
        sidebar.set_size_request(200, -1)
        sidebar.set_hexpand(False)
        body.append(sidebar)

        # 品牌头
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        brand.set_margin_top(16)
        brand.set_margin_bottom(10)
        brand.set_margin_start(16)
        brand.set_margin_end(16)
        logo = self._brand_logo()
        brand.append(logo)
        brand_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        brand_text.append(W.label(('时账', 'Timebook'), "tb-brand-name"))
        brand_text.append(W.label(('Timebook · 本地优先', 'Local first'), "tb-brand-sub"))
        brand.append(brand_text)
        sidebar.append(brand)

        # 导航
        self.nav = Gtk.ListBox()
        self.nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        self.nav.connect("row-selected", self._on_nav)
        for index, (key, zh, en, icon_name) in enumerate(PAGES):
            row = Gtk.ListBoxRow()
            row.add_css_class("tb-nav-row")
            row.set_name(key)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(7)
            box.set_margin_bottom(7)
            box.set_margin_start(8)
            box.set_margin_end(8)
            image = Gtk.Image.new_from_icon_name(icon_name)
            image.set_pixel_size(17)
            box.append(image)
            box.append(W.label((zh, en), "tb-nav-label"))
            row.set_child(box)
            W.translated(row, tooltip_text=(f"{zh} · Ctrl+{index + 1}", f"{en} · Ctrl+{index + 1}"))
            self.nav.append(row)
            self._nav_rows[key] = row
        sidebar.append(self.nav)

        sidebar.append(W.spacer(vertical=True))

        # 底部迷你卡
        mini = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        mini.add_css_class("tb-mini-card")
        mini.set_margin_start(12)
        mini.set_margin_end(12)
        mini.set_margin_bottom(12)
        mini.append(W.label(('今日合计', "Today's total"), "tb-caption"))
        self.mini_value = W.label(models.fmt_duration(0, compact=True), "tb-mini-value tb-mono")
        mini.append(self.mini_value)
        self.mini_level = W.label(('L1 清醒', 'L1 Fresh'), "tb-caption")
        mini.append(self.mini_level)
        sidebar.append(mini)

        # 内容区
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_hexpand(True)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(160)
        self.stack.set_vexpand(True)
        self.stack.set_hexpand(True)
        self.stack.add_named(TodayPage(ctx), "today")
        self.stack.add_named(FocusPage(ctx), "focus")
        self.stack.add_named(StatsPage(ctx), "stats")
        self.stack.add_named(TimelinePage(ctx), "timeline")
        self.stack.add_named(ForfeitPage(ctx), "forfeit")
        content.append(self.stack)
        body.append(content)
        root.append(body)
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(root)
        self.set_content(self._toast_overlay)

        # 快捷键 Ctrl+1..5
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key)
        self.add_controller(controller)

        # 默认选中今日
        self.nav.select_row(self._nav_rows["today"])

        self.refresh(force=True)

    # ------------------------------------------------------------------ #

    def _current_lang(self) -> str:
        from ..core.l10n import resolved_language

        return resolved_language()

    def _brand_logo(self) -> Gtk.Widget:
        """程序化品牌图标：番茄红圆环 + 琥珀指针。"""
        area = Gtk.DrawingArea()
        area.set_size_request(34, 34)
        area.set_valign(Gtk.Align.CENTER)

        def draw(_a, cr, w, h):
            import math

            cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 2
            cr.set_line_width(3.2)
            cr.set_line_cap(__import__("cairo").LINE_CAP_ROUND)
            cr.set_source_rgba(*W.rgba(BRAND, 0.22))
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            cr.set_source_rgba(*W.rgba(BRAND, 1.0))
            cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + math.pi * 1.35)
            cr.stroke()
            cr.set_source_rgba(0.95, 0.72, 0.35, 1.0)
            cr.set_line_width(2.2)
            cr.move_to(cx, cy)
            cr.line_to(cx + r * 0.45, cy - r * 0.32)
            cr.stroke()
            cr.set_source_rgba(*W.rgba(0xEA, 0.95))
            cr.arc(cx, cy, 2.6, 0, 2 * math.pi)
            cr.fill()

        area.set_draw_func(draw)
        return area

    def _on_nav(self, _listbox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        key = row.get_name()
        self.stack.set_visible_child_name(key)
        for page_key, zh, en, _icon in PAGES:
            if page_key == key:
                self.page_title.set_text(zh if self._lang == "zh" else en)
        page = self.stack.get_child_by_name(key)
        if hasattr(page, "refresh"):
            page.refresh(force=True)

    def _on_key(self, _controller, keyval, _keycode, state) -> bool:
        mask = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        if mask == Gdk.ModifierType.CONTROL_MASK and Gdk.KEY_1 <= keyval <= Gdk.KEY_5:
            index = keyval - Gdk.KEY_1
            if index < len(PAGES):
                self.nav.select_row(self._nav_rows[PAGES[index][0]])
                return True
        return False

    def _on_pause_toggled(self, button: Gtk.ToggleButton) -> None:
        paused = button.get_active()
        self._ctx.settings.paused = paused
        self._ctx.tracker.force_close()
        button.set_label(T("继续记录", "Resume tracking") if paused else T("暂停记录", "Pause tracking"))
        self.refresh(force=True)

    def _open_settings(self) -> None:
        from .settings_window import SettingsWindow

        if self._settings_window is None:
            self._settings_window = SettingsWindow(self, self._ctx)
            self._settings_window.set_hide_on_close(True)
        self._settings_window.reload()
        self._settings_window.present()

    def _open_export(self) -> None:
        from .export_dialog import extract_to_downloads

        extract_to_downloads(self, self._ctx)

    def refresh(self, force: bool = False) -> None:
        language = self._current_lang()
        if language != self._lang:
            self._lang = language
            W.refresh_translations(self)
            for key, *_ in PAGES:
                self.stack.get_child_by_name(key).refresh(force=True)
            self._on_nav(self.nav, self.nav.get_selected_row())
            if self._settings_window is not None:
                self._settings_window.refresh_language()
        paused = self._ctx.settings.paused
        self.pause_button.set_label(T("继续记录", "Resume tracking") if paused else T("暂停记录", "Pause tracking"))
        if self.pause_button.get_active() != paused:
            self.pause_button.handler_block_by_func(self._on_pause_toggled)
            self.pause_button.set_active(paused)
            self.pause_button.handler_unblock_by_func(self._on_pause_toggled)
            self.pause_button.set_label(T("继续记录", "Resume tracking") if paused else T("暂停记录", "Pause tracking"))

        total = self._ctx.today_total()
        self.mini_value.set_text(models.fmt_duration(total, compact=True))
        level = for_total(total)
        self.mini_level.set_text(f"L{level.level} {level.name}")

        page = self.stack.get_visible_child()
        if page is not None and hasattr(page, "refresh"):
            page.refresh(force=force)

    def current_page_key(self) -> str | None:
        child = self.stack.get_visible_child()
        if child is None:
            return None
        for key, *_ in PAGES:
            if self.stack.get_child_by_name(key) is child:
                return key
        return None

    def show_page(self, key: str) -> None:
        if key in self._nav_rows:
            self.nav.select_row(self._nav_rows[key])
            self.refresh(force=True)
            self.present()
