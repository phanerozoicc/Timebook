"""Language coverage through real GTK widgets, canvas text and user workflows."""
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from tests.test_regressions import context
from tests.test_tray import make_tray
from tests.test_ui import GUI, drain
from timebook.core import models
from timebook.core.l10n import count_label, date_label, reset_for_tests, set_language, set_system_language
from timebook.core.exporter import build_weekly_markdown
from timebook.core.pomodoro import PomodoroPhase

if GUI:
    import cairo
    from gi.repository import Adw, Gio, Gtk
    from timebook.ui import widgets as W
    from timebook.ui.main_window import MainWindow, PAGES
    from timebook.ui.overlay import BreakOverlay
    from timebook.ui.introspect import widget_texts
    from timebook.ui.theme import install_css

CJK = re.compile(r"[\u3400-\u9fff]")


def all_texts(root):
    """Inspect visible and hidden controls, tooltips and dropdown choices."""
    out = []
    stack = [root]
    while stack:
        widget = stack.pop()
        for name in ("get_text", "get_label", "get_title", "get_subtitle", "get_description",
                     "get_tooltip_text", "get_placeholder_text"):
            getter = getattr(widget, name, None)
            if getter:
                text = getter()
                if isinstance(text, str) and text:
                    out.append(text)
        if isinstance(widget, (Adw.ComboRow, Gtk.DropDown)):
            model = widget.get_model()
            if isinstance(model, Gtk.StringList):
                out.extend(model.get_string(i) for i in range(model.get_n_items()))
        child = widget.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


@unittest.skipUnless(GUI, "Requires GTK display")
class LocalizationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()
        cls.app = Adw.Application(application_id="io.github.timebook.LocaleTests", flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)
        install_css()

    def setUp(self):
        import sys
        self.ctx, self.clock, self.source = context()
        self.ctx.settings.language = "en"
        set_language("en")
        self.window = MainWindow(self.app, self.ctx)
        self.window.present()
        self.errors = []
        self.hook = sys.excepthook
        sys.excepthook = lambda *args: self.errors.append(args)
        drain()

    def tearDown(self):
        import sys
        if self.window._settings_window:
            self.window._settings_window.destroy()
        self.window.destroy()
        drain()
        self.ctx.store.close()
        reset_for_tests()
        sys.excepthook = self.hook
        self.assertEqual(self.errors, [], "GTK signal callback failed")

    def assert_english(self, widget):
        self.assertEqual([s for s in all_texts(widget) if CJK.search(s)], [])

    def switch(self, language):
        self.window._open_settings()
        settings = self.window._settings_window
        settings.lang_combo.set_selected(settings._lang_values.index(language))
        drain(0.1)
        return settings

    def seed(self):
        now = datetime.now()
        for app, host in (("Browser", "github.com"), ("Editor", None)):
            self.ctx.store.add_event(app.lower(), app, now - timedelta(minutes=5), now, host=host)

    def test_english_cold_start_all_pages_and_settings(self):
        for page, *_ in PAGES:
            with self.subTest(page=page):
                self.window.show_page(page)
                self.assert_english(self.window)
        self.window._open_settings()
        self.assert_english(self.window._settings_window)
        self.assertEqual(self.window.get_title(), "Timebook")

    def test_language_round_trip_preserves_session_inputs_and_settings(self):
        self.seed()
        self.window.show_page("stats")
        stats = self.window.stack.get_child_by_name("stats")
        stats.month_button.set_active(True)
        forfeit = self.window.stack.get_child_by_name("forfeit")
        forfeit.refresh(force=True)
        forfeit.dom_entry.set_text("draft.example.com")
        forfeit.app_picker.set_selected(1)
        self.ctx.pomodoro.start()
        session = self.ctx.pomodoro.state.to_dict()
        before = [(row[0], row[1]) for row in self.ctx.store._conn.execute("SELECT key, value FROM kv WHERE key != 'language'")]
        for lang in ("zh", "en", "zh", "en"):
            settings = self.switch(lang)
            self.assertEqual(self.window.current_page_key(), "stats")
            self.assertIs(self.window.stack.get_child_by_name("stats"), stats)
            self.assertEqual(stats._days, 30)
            self.assertEqual(forfeit.dom_entry.get_text(), "draft.example.com")
            self.assertEqual(forfeit.app_picker.get_selected(), 1)
            self.assertEqual(self.ctx.pomodoro.state.to_dict(), session)
            if lang == "en":
                self.assert_english(self.window)
                self.assert_english(settings)
            else:
                self.assertEqual(settings.get_title(), "设置")
                self.assertEqual(stats.month_button.get_label(), "最近 30 天")
                self.assertEqual(settings.idle_combo.get_title(), "空闲判定")
        after = [(row[0], row[1]) for row in self.ctx.store._conn.execute("SELECT key, value FROM kv WHERE key != 'language'")]
        self.assertEqual(before, after, "Changing language must not change other settings")

    def test_auto_language_updates_entire_existing_window(self):
        set_system_language("zh")
        self.switch("auto")
        self.assertEqual(self.window.get_title(), "时账 Timebook")
        self.window.show_page("focus")
        self.assertIn("经典 40/5", widget_texts(self.window))
        self.switch("en")
        set_system_language("en")
        self.switch("auto")
        self.assert_english(self.window)
        self.assert_english(self.window._settings_window)

    def test_populated_pages_and_dynamic_states_remain_english(self):
        self.seed()
        now = datetime.now()
        self.ctx.store.add_event("browser", "Browser", now-timedelta(days=1, minutes=30), now-timedelta(days=1), host="x.com")
        self.ctx.forfeit.add_custom_domain("example.com")
        self.ctx.forfeit.add_distractor("browser")
        for phase in PomodoroPhase:
            with self.subTest(phase=phase):
                self.ctx.pomodoro.state.phase = phase
                self.ctx.pomodoro.state.ends_at = self.clock.now + timedelta(minutes=5)
                self.window.show_page("focus")
                self.assert_english(self.window)
        self.ctx.settings.capture_titles = True
        self.ctx.settings.limits_enabled = True
        for page, *_ in PAGES:
            self.window.show_page(page)
            self.assert_english(self.window)
        page = self.window.stack.get_child_by_name("forfeit")
        page.dom_entry.set_text("invalid")
        page._add_domain(None)
        self.assertTrue(page.dom_error.get_visible())
        self.assert_english(page)
        self.switch("zh")
        self.assertIn("请输入", page.dom_error.get_text())
        self.switch("en")
        self.assert_english(page)

    def test_user_app_names_and_draft_text_are_never_translated(self):
        now = datetime.now()
        self.ctx.store.add_event("userapp", "今日", now-timedelta(minutes=1), now)
        page = self.window.stack.get_child_by_name("forfeit")
        page.dom_entry.set_text("中文草稿")
        self.switch("zh")
        self.switch("en")
        self.window.show_page("today")
        self.assertIn("今日", widget_texts(self.window))
        self.assertEqual(page.dom_entry.get_text(), "中文草稿")

    def test_excluded_app_placeholder_and_remove_button_retranslate(self):
        self.seed()
        self.ctx.settings.excluded = {"editor"}
        settings = self.switch("zh")
        self.switch("en")
        self.assert_english(settings)
        settings._remove_exclude("editor")
        self.assertIn("No apps excluded yet.", widget_texts(settings))
        self.assert_english(settings)

    def test_canvas_weekdays_months_units_and_legends(self):
        stats = self.window.stack.get_child_by_name("stats")
        stats.refresh(force=True)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 500, 250)
        cr = cairo.Context(surface)
        with patch.object(W, "draw_text", wraps=W.draw_text) as draw:
            stats.heatmap._draw(stats.heatmap._area, cr, 500, 250)
        texts = [call.args[1] for call in draw.call_args_list]
        self.assertIn("Less", texts)
        self.assertIn("More", texts)
        self.assertIn("Mon", texts)
        self.assertFalse(any(CJK.search(text) for text in texts))
        self.assert_english(stats)
        self.switch("zh")
        with patch.object(W, "draw_text", wraps=W.draw_text) as draw:
            stats.heatmap._draw(stats.heatmap._area, cr, 500, 250)
        self.assertIn("少", [call.args[1] for call in draw.call_args_list])
        self.assertIn("多", [call.args[1] for call in draw.call_args_list])

    def test_live_overlay_retranslates_without_resetting_countdown(self):
        overlay = BreakOverlay(self.app, duration=20)
        try:
            overlay.present()
            drain()
            overlay._remaining = 12
            self.assert_english(overlay)
            set_language("zh")
            overlay.refresh_language()
            self.assertIn("让眼睛休息一下", widget_texts(overlay))
            set_language("en")
            overlay.refresh_language()
            self.assertEqual(overlay._remaining, 12)
            self.assert_english(overlay)
        finally:
            overlay.close()

    def test_tray_language_change_emits_update_even_with_unchanged_timer(self):
        tray = make_tray(self.ctx.store)
        tray._ctx.settings.paused = True
        tray.refresh()
        tray.available = True
        tray._item = Mock()
        tray._menu = Mock()
        tray._dbus = Mock()
        set_language("zh")
        tray.refresh()
        self.assertEqual(tray._status_line, "记录已暂停")
        tray._menu.LayoutUpdated.assert_called_once()
        set_language("en")
        tray.refresh()
        self.assertEqual(tray._status_line, "Tracking paused")
        self.assertFalse(CJK.search(tray._tooltip))
        tray._ctx.settings.paused = False
        tray._ctx.tracker.is_idle = True
        tray.refresh()
        self.assertEqual(tray._status_line, "Idle")

    def test_units_dates_report_follow_app_language(self):
        self.assertEqual(date_label(datetime(2026, 11, 20)), "Nov 20, 2026")
        self.assertEqual(count_label(1, "day"), "1 day")
        self.assertEqual(count_label(2, "day"), "2 days")
        self.assertEqual(models.fmt_duration(3660, compact=True), "1h01m")
        self.assertFalse(CJK.search(build_weekly_markdown(self.ctx.store, datetime.now())))
        set_language("zh")
        self.assertEqual(date_label(datetime(2026, 11, 20)), "2026年11月20日")
        self.assertEqual(models.fmt_duration(3660, compact=True), "1时01分")
        self.assertEqual(models.fmt_duration(45, compact=True), "45秒")
        self.assertNotIn("Fresh", build_weekly_markdown(self.ctx.store, datetime.now()))

    def test_existing_export_toast_retranslates(self):
        import tempfile
        from pathlib import Path
        from timebook.ui.export_dialog import extract_to_downloads
        set_language("zh")
        self.window.refresh(force=True)
        with tempfile.TemporaryDirectory() as root, patch("timebook.ui.export_dialog.downloads_dir", return_value=Path(root)):
            extract_to_downloads(self.window, self.ctx)
        toast = self.window._toast_overlay._translated_toasts[0]
        self.assertIn("已导出", toast.get_title())
        set_language("en")
        self.window.refresh(force=True)
        self.assertIn("Exported", toast.get_title())
        self.assertEqual(toast.get_button_label(), "Open folder")

    def test_notification_sender_follows_app_language(self):
        from timebook.platform.notify import Notifier
        notifier = Notifier()
        notifier._notify_send = "notify-send"
        with patch("timebook.platform.notify.subprocess.run") as send:
            notifier.send("Break", "Rest your eyes")
            self.assertEqual(send.call_args.args[0][2], "Timebook")
            set_language("zh")
            notifier.send("休息", "休息一下")
            self.assertEqual(send.call_args.args[0][2], "时账")

    def test_english_compact_page_layouts(self):
        # set_default_size 对已显示窗口无效：隐藏后重设再显示，才真正进入 860×600。
        self.window.set_visible(False)
        self.window.set_default_size(860, 600)
        self.window.present()
        drain()
        for key, *_ in PAGES:
            self.window.show_page(key)
            drain()
            page = self.window.stack.get_child_by_name(key)
            self.assertLessEqual(page.body.get_width(), page.get_width())
            # 不同系统的字体（DejaVu vs Noto）自然宽度有几十像素差异；
            # 本条防的是英文文案把窗口撑回 1020 默认宽，而非精确 860。
            self.assertLessEqual(self.window.get_width(), 920)
