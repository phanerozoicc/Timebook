"""Real GTK controls, signals and rendering. Requires GTK4 and a display.

Run with TIMEBOOK_REQUIRE_UI=1 to fail (rather than skip) without a display.
All data is isolated in SQLite memory or a temporary export directory.
"""
import csv
import io
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from tests.test_regressions import context
from tests.test_platform import WindowStub
from timebook.core import models
from timebook.core.l10n import reset_for_tests, set_language
from timebook.core.pomodoro import PomodoroPhase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    GUI = Gtk.init_check()
except (ImportError, ValueError):
    GUI = False

if not GUI and os.environ.get("TIMEBOOK_REQUIRE_UI"):
    raise RuntimeError("Full UI verification requires GTK4/libadwaita and a working display")

if GUI:
    from timebook.ui.main_window import MainWindow, PAGES
    from timebook.ui.settings_window import SettingsWindow
    from timebook.ui.export_dialog import extract_to_downloads
    from timebook.ui.overlay import BreakOverlay
    from timebook.ui.introspect import widget_texts
    from timebook.ui.theme import CSS, install_css
    from timebook.ui import widgets as W


def drain(seconds=0.03):
    loop = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while loop.pending():
            loop.iteration(False)
        time.sleep(0.002)


@unittest.skipUnless(GUI, "GTK4 or display unavailable; use TIMEBOOK_REQUIRE_UI=1 in desktop CI")
class UIWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()
        cls.app = Adw.Application(application_id="io.github.timebook.UITests", flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)
        install_css()

    def setUp(self):
        set_language("zh")
        self.ctx, self.clock, self.source = context()
        self.window = MainWindow(self.app, self.ctx)
        self.errors = []
        self.original_hook = sys.excepthook
        sys.excepthook = lambda *args: self.errors.append(args)
        self.window.present()
        drain()

    def tearDown(self):
        if self.window._settings_window:
            self.window._settings_window.destroy()
        self.window.destroy()
        drain()
        self.ctx.store.close()
        reset_for_tests()
        sys.excepthook = self.original_hook
        if self.errors:
            self.fail(f"Exception from GTK signal: {self.errors}")

    def seed(self):
        now = datetime.now()
        for app_id, app_name, minutes, host in (("code", "Editor", 30, None),
                                                ("browser", "Browser", 10, "github.com"),
                                                ("chat", "Chat", 5, "x.com")):
            self.ctx.store.add_event(app_id, app_name, now - timedelta(minutes=minutes), now,
                                     host=host, title="A long title " * 20)
        self.window.refresh(force=True)

    def page(self, key):
        self.window.show_page(key)
        drain()
        return self.window.stack.get_child_by_name(key)

    def settings(self):
        self.window._open_settings()
        drain()
        return self.window._settings_window

    def test_empty_pages_render_and_navigation_shortcuts(self):
        for i, (key, title, _, _) in enumerate(PAGES):
            with self.subTest(page=key):
                self.assertTrue(self.window._on_key(None, Gdk.KEY_1 + i, 0, Gdk.ModifierType.CONTROL_MASK))
                drain()
                self.assertEqual(self.window.current_page_key(), key)
                self.assertEqual(self.window.page_title.get_text(), title)
                self.assertGreater(len(widget_texts(self.window)), 10)

    def test_render_populated_pages_light_dark_and_minimum_size(self):
        self.seed()
        manager = Adw.StyleManager.get_default()
        previous = manager.get_color_scheme()
        self.addCleanup(manager.set_color_scheme, previous)
        for theme in (Adw.ColorScheme.FORCE_LIGHT, Adw.ColorScheme.FORCE_DARK):
            manager.set_color_scheme(theme)
            self.window.set_default_size(860, 600)
            deadline = time.monotonic() + 2
            while self.window.get_width() != 860 and time.monotonic() < deadline:
                drain(0.02)
            for key, *_ in PAGES:
                with self.subTest(theme=theme, page=key):
                    page = self.page(key)
                    self.assertGreater(page.get_width(), 0)
                    self.assertLessEqual(page.body.measure(Gtk.Orientation.HORIZONTAL, -1)[0], page.get_width())
                    self.assertLessEqual(self.window.get_width(), 860)

    def test_large_system_font_and_reduced_motion(self):
        settings = Gtk.Settings.get_default()
        previous_font = settings.get_property("gtk-font-name")
        previous_motion = settings.get_property("gtk-enable-animations")
        self.addCleanup(settings.set_property, "gtk-font-name", previous_font)
        self.addCleanup(settings.set_property, "gtk-enable-animations", previous_motion)
        settings.set_property("gtk-font-name", "Sans 14")
        settings.set_property("gtk-enable-animations", False)
        self.window.set_default_size(1280, 800)
        self.seed()
        for key, *_ in PAGES:
            with self.subTest(page=key):
                page = self.page(key)
                self.assertLessEqual(page.body.measure(Gtk.Orientation.HORIZONTAL, -1)[0], page.get_width())

    def test_open_settings_does_not_exclude_any_app(self):
        self.seed()
        before = self.ctx.settings.excluded.copy()
        window = self.settings()
        self.assertEqual(self.ctx.settings.excluded, before)
        self.assertEqual(window.exclude_picker.get_selected(), 0)
        window.reload()
        self.assertEqual(self.ctx.settings.excluded, before)

    def test_exclusion_add_remove_only_on_explicit_selection(self):
        self.seed()
        window = self.settings()
        chosen = window._exclude_ids[1]
        window.exclude_picker.set_selected(1)
        drain()
        self.assertEqual(self.ctx.settings.excluded, {chosen})
        self.assertEqual(window.exclude_picker.get_selected(), 0)
        window._remove_exclude(chosen)
        self.assertEqual(self.ctx.settings.excluded, set())

    def test_settings_window_reused(self):
        first = self.settings()
        self.window._open_settings()
        self.assertIs(self.window._settings_window, first)

    def test_tracking_toggle_settings_and_header_sync(self):
        window = self.settings()
        window.pause_switch.set_active(True)
        self.window.refresh()
        self.assertTrue(self.window.pause_button.get_active())
        self.window.pause_button.set_active(False)
        window.reload()
        self.assertFalse(window.pause_switch.get_active())
        self.assertFalse(self.ctx.settings.paused)

    def test_settings_roundtrip_and_dependent_controls(self):
        window = self.settings()
        for combo, index, attr, value in ((window.idle_combo, 2, "idle_threshold", 120),
                                          (window.limit_combo, 3, "limits_daily_minutes", 240),
                                          (window.break_combo, 2, "break_interval_minutes", 45),
                                          (window.water_combo, 3, "water_interval_minutes", 90)):
            combo.set_selected(index)
            self.assertEqual(getattr(self.ctx.settings, attr), value)
        window.limits_switch.set_active(False)
        window.break_switch.set_active(False)
        window.water_switch.set_active(False)
        self.assertFalse(window.limit_combo.get_sensitive())
        self.assertFalse(window.break_combo.get_sensitive())
        self.assertFalse(window.water_combo.get_sensitive())
        window.reload()
        self.assertEqual(window.water_combo.get_selected(), 3)

    def test_language_navigation_refreshes_immediately(self):
        window = self.settings()
        window.lang_combo.set_selected(2)
        self.assertEqual(self.window.page_title.get_text(), "Today")
        self.assertEqual(self.window.pause_button.get_label(), "Pause tracking")
        window.lang_combo.set_selected(1)
        self.assertEqual(self.window.page_title.get_text(), "今日")

    def test_focus_start_pause_resume_skip_stop_buttons(self):
        page = self.page("focus")
        page.primary_button.emit("clicked")
        self.assertEqual(self.ctx.pomodoro.state.phase, PomodoroPhase.WORK)
        self.assertEqual(page.primary_button.get_label(), "暂停")
        self.assertTrue(all(not b.get_sensitive() for b in page.preset_buttons.values()))
        self.clock.advance(minutes=1)
        page.primary_button.emit("clicked")
        self.assertTrue(self.ctx.pomodoro.state.paused)
        self.assertEqual(page.primary_button.get_label(), "继续")
        self.clock.advance(minutes=3)
        page.primary_button.emit("clicked")
        self.assertEqual(self.ctx.pomodoro.remain, 39 * 60)
        page.skip_button.emit("clicked")
        self.assertTrue(self.ctx.pomodoro.state.phase.is_break)
        self.assertEqual(len(self.ctx.store.focus_for_day(self.clock.now.date())), 1)
        page.stop_button.emit("clicked")
        self.assertEqual(self.ctx.pomodoro.state.phase, PomodoroPhase.IDLE)
        self.assertFalse(page.skip_button.get_sensitive())
        self.assertTrue(all(b.get_sensitive() for b in page.preset_buttons.values()))

    def test_focus_preset_ready_auto_and_completion(self):
        page = self.page("focus")
        page.preset_buttons["sprint"].set_active(True)
        self.assertEqual(page.ring._value_label.get_text(), "15:00")
        page.auto_break.set_active(False)
        page.auto_work.set_active(False)
        page.primary_button.emit("clicked")
        self.clock.advance(minutes=15)
        self.ctx.pomodoro.tick()
        page.refresh()
        self.assertEqual(self.ctx.pomodoro.state.phase, PomodoroPhase.SHORT_READY)
        self.assertEqual(page.ring._value_label.get_text(), "03:00")
        self.assertEqual(page.card_done._value.get_text(), "1")
        page.primary_button.emit("clicked")
        self.clock.advance(minutes=3)
        self.ctx.pomodoro.tick()
        page.refresh()
        self.assertEqual(self.ctx.pomodoro.state.phase, PomodoroPhase.WORK_READY)
        page.primary_button.emit("clicked")
        self.assertEqual(self.ctx.pomodoro.state.phase, PomodoroPhase.WORK)

    def test_water_controls_boundaries(self):
        page = self.page("focus")
        self.assertFalse(page.water_buttons[-1].get_sensitive())
        page.water_buttons[1].emit("clicked")
        self.assertEqual(self.ctx.cups(), 1)
        self.assertTrue(page.water_buttons[-1].get_sensitive())
        page.water_buttons[-1].emit("clicked")
        self.assertEqual(self.ctx.cups(), 0)
        self.ctx.add_cup(12)
        page.refresh()
        self.assertEqual(page.water_run._fraction, 1)
        self.assertIn("12", page.water_label.get_text())

    def test_hour_toggle_and_future_disabled(self):
        page = self.page("forfeit")
        now = datetime.now()
        button = page.grid.buttons[now.hour]
        button.emit("clicked")
        self.assertIn(now.hour, self.ctx.forfeit.ledger.lost_hours(self.ctx.forfeit.ledger.current_day_key))
        self.assertTrue(button.get_active())
        button.emit("clicked")
        self.assertNotIn(now.hour, self.ctx.forfeit.ledger.lost_hours(self.ctx.forfeit.ledger.current_day_key))
        for future in page.grid.buttons[now.hour + 1:]:
            self.assertFalse(future.get_sensitive())
        self.assertTrue(button.get_focusable())

    def test_distractor_selection_survives_refresh(self):
        self.seed()
        page = self.page("forfeit")
        page.app_picker.set_selected(1)
        chosen = page._app_ids[1]
        page.refresh()
        page.refresh(force=True)
        self.assertEqual(page._app_ids[page.app_picker.get_selected()], chosen)
        page.add_app_button.emit("clicked")
        self.assertIn(chosen, self.ctx.forfeit.distractor_apps)
        page._remove_distractor(chosen)
        self.assertNotIn(chosen, self.ctx.forfeit.distractor_apps)

    def test_domain_validation_add_duplicate_remove(self):
        page = self.page("forfeit")
        page.dom_entry.set_text("invalid")
        page.dom_entry.emit("activate")
        self.assertTrue(page.dom_error.get_visible())
        self.assertEqual(page.dom_entry.get_text(), "invalid")
        page.dom_entry.set_text("https://example.com/path")
        page.dom_entry.emit("activate")
        self.assertEqual(page.dom_entry.get_text(), "")
        self.assertFalse(page.dom_error.get_visible())
        self.assertIn("example.com", self.ctx.forfeit.custom_domains)
        page.dom_entry.set_text("example.com")
        page.dom_entry.emit("activate")
        self.assertTrue(page.dom_error.get_visible())
        page._remove_domain("example.com")
        self.assertNotIn("example.com", self.ctx.forfeit.custom_domains)

    def test_category_switch_and_stats_denominator(self):
        self.seed()
        page = self.page("forfeit")
        category, switch = next(iter(page.cat_switches.items()))
        expected = not switch.get_active()
        switch.set_active(expected)
        self.assertEqual(category in self.ctx.forfeit.enabled_categories, expected)
        stats = self.page("stats")
        self.assertEqual(stats.donut._center, "15分")
        self.assertIn("67%", widget_texts(stats.legend))
        self.assertIn("33%", widget_texts(stats.legend))

    def test_live_data_consistent_across_today_timeline_stats(self):
        self.source.window = WindowStub()
        self.ctx.tracker.tick()
        self.clock.advance(seconds=30)
        # Freeze all UI reads at the same instant.
        with patch("timebook.ui.pages.today.datetime") as today_dt, patch("timebook.ui.pages.timeline.datetime") as timeline_dt, patch("timebook.ui.pages.stats.datetime") as stats_dt:
            for mocked in (today_dt, timeline_dt, stats_dt):
                mocked.now.return_value = self.clock.now
                mocked.side_effect = datetime
            today = self.page("today")
            self.assertEqual(today.hero_number.get_text(), "30秒")
            timeline = self.page("timeline")
            self.assertIn("1 段", timeline.summary.get_text())
            self.assertIn("VS Code", widget_texts(timeline))
            stats = self.page("stats")
            self.assertEqual(stats.card_total._value.get_text(), "30秒")
        self.assertEqual(self.ctx.store.count_events(), 0)

    def test_export_success_main_toast_and_live_rows(self):
        self.seed()
        self.ctx.settings.water_goal_cups = 12
        self.ctx.add_cup(2)
        overlay = Mock()
        self.window._toast_overlay = overlay
        with tempfile.TemporaryDirectory() as target, patch("timebook.ui.export_dialog.downloads_dir", return_value=Path(target)):
            csv_path, md_path = extract_to_downloads(self.window, self.ctx)
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(len(list(csv.reader(stream))), 4)
            self.assertIn("2/12", md_path.read_text())
            second = extract_to_downloads(self.window, self.ctx)
            self.assertNotEqual(csv_path, second[0])
        self.assertEqual(overlay.add_toast.call_count, 2)

    def test_export_failure_shows_feedback(self):
        overlay = Mock()
        self.window._toast_overlay = overlay
        with tempfile.TemporaryDirectory() as target:
            file = Path(target) / "file"
            file.write_text("not a directory")
            with patch("timebook.ui.export_dialog.downloads_dir", return_value=file / "Downloads"):
                self.assertIsNone(extract_to_downloads(self.window, self.ctx))
        self.assertIn("导出失败", overlay.add_toast.call_args.args[0].get_title())

    def test_settings_export_uses_own_feedback(self):
        window = self.settings()
        overlay = self.window._toast_overlay
        with tempfile.TemporaryDirectory() as target, patch("timebook.ui.export_dialog.downloads_dir", return_value=Path(target)):
            window._on_export(None)
            self.assertEqual(len(list(Path(target).iterdir())), 2)
        self.assertIs(self.window._toast_overlay, overlay)

    def test_microbreak_escape_cleans_timer(self):
        done = Mock()
        overlay = BreakOverlay(self.app, on_done=done)
        overlay.present()
        drain()
        self.assertTrue(overlay._on_key(None, Gdk.KEY_Escape, 0, 0))
        self.assertIsNone(overlay._timer_id)
        done.assert_called_once()

    def test_stats_range_changes_totals_and_point_count(self):
        now = datetime.now()
        self.ctx.store.add_event("old", "Old", now - timedelta(days=20, hours=1), now - timedelta(days=20))
        self.ctx.store.add_event("new", "New", now - timedelta(hours=1), now)
        page = self.page("stats")
        self.assertEqual(page.card_total._value.get_text(), "1时00分")
        self.assertEqual(len(page.chart._points), 7)
        page.month_button.set_active(True)
        self.assertEqual(page.card_total._value.get_text(), "2时00分")
        self.assertEqual(len(page.chart._points), 30)
        page.week_button.set_active(True)
        self.assertEqual(page.card_total._value.get_text(), "1时00分")

    def test_limit_progress_updates_and_hides_when_disabled(self):
        self.seed()
        self.ctx.settings.limits_enabled = True
        self.ctx.settings.limits_daily_minutes = 60
        page = self.page("today")
        self.assertAlmostEqual(page.hero_bar._fraction, 0.75, places=3)
        self.ctx.settings.limits_enabled = False
        page.refresh()
        self.assertFalse(page.hero_bar.get_visible())

    def test_title_capture_switch_closes_existing_segment(self):
        self.source.window = WindowStub()
        self.ctx.tracker.tick()
        self.clock.advance(seconds=15)
        window = self.settings()
        window.title_switch.set_active(True)
        self.ctx.tracker.tick()
        self.clock.advance(seconds=10)
        rows = self.ctx.today_rows(self.clock.now)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r.duration for r in rows), 25)
        self.assertEqual(sum(r.duration for r in rows if r.title), 10)

    @staticmethod
    def _window_manager_present() -> bool | None:
        """裸 Xvfb 没有窗口管理器，全屏协商不可能完成；xprop 可用时探测，失败返回 None（维持原断言）。"""
        try:
            out = subprocess.run(
                ["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.returncode == 0 and "no such property" not in out.stdout

    def test_microbreak_fills_monitor_and_centers_content(self):
        if self._window_manager_present() is False:
            self.skipTest("bare X server (e.g. xvfb) has no window manager to acknowledge fullscreen")
        overlay = BreakOverlay(self.app, duration=20)
        self.addCleanup(overlay.close)
        overlay.present()
        geometry = overlay._monitor.get_geometry()
        deadline = time.monotonic() + 3
        while (not overlay.is_fullscreen() or overlay.get_width() != geometry.width
               or overlay.get_height() != geometry.height) and time.monotonic() < deadline:
            drain(0.02)
        self.assertTrue(overlay.is_fullscreen(), "Window manager must acknowledge fullscreen")
        self.assertEqual(overlay.get_width(), geometry.width)
        self.assertEqual(overlay.get_height(), geometry.height)
        content = overlay.get_child()
        ok, bounds = content.compute_bounds(overlay)
        self.assertTrue(ok)
        self.assertAlmostEqual(bounds.get_x() + bounds.get_width() / 2, geometry.width / 2, delta=3)
        self.assertAlmostEqual(bounds.get_y() + bounds.get_height() / 2, geometry.height / 2, delta=3)

    def test_microbreak_completes_and_calls_done_once(self):
        done = Mock()
        overlay = BreakOverlay(self.app, on_done=done, duration=1)
        overlay.present()
        drain()
        self.assertFalse(overlay._tick())
        self.assertIsNone(overlay._timer_id)
        done.assert_called_once()

    def test_close_signal_quits_when_tray_unavailable(self):
        from timebook.app import TimebookApp
        from types import SimpleNamespace
        host = SimpleNamespace(ctx=self.ctx, window=self.window, tray=None, quit=Mock())
        self.window.connect("close-request", lambda *_: TimebookApp._on_window_close(host))
        self.window.close()
        host.quit.assert_called_once()

    def test_close_signal_hides_when_tray_available(self):
        from timebook.app import TimebookApp
        from types import SimpleNamespace
        self.ctx.settings.tray_enabled = True
        host = SimpleNamespace(ctx=self.ctx, window=self.window,
                               tray=SimpleNamespace(available=True), quit=Mock())
        self.window.connect("close-request", lambda *_: TimebookApp._on_window_close(host))
        self.window.close()
        self.assertFalse(self.window.get_visible())
        host.quit.assert_not_called()

    def test_no_track_shutdown_closes_database(self):
        from timebook.app import TimebookApp
        from types import SimpleNamespace
        store = Mock()
        host = SimpleNamespace(ctx=SimpleNamespace(store=store), options={"no_track": True},
                               _tick_sources=[], _break_overlay=None, tray=None)
        TimebookApp._on_shutdown(host, None)
        store.close.assert_called_once()

    def test_hidden_start_can_be_reopened(self):
        from timebook.app import TimebookApp
        from types import SimpleNamespace
        host = SimpleNamespace(ctx=self.ctx, window=self.window, options={"hidden": True},
                               _run_headless_tasks=Mock(), _schedule_quit=Mock())
        self.window.set_visible(False)
        TimebookApp._on_activate(host, None)
        self.assertTrue(self.window.get_visible())

    def test_introspection_retains_stack_siblings(self):
        from timebook.ui.introspect import count_widgets
        box = Gtk.Box()
        box.append(Gtk.Label(label="Before"))
        stack = Gtk.Stack()
        stack.add_named(Gtk.Label(label="Page"), "page")
        box.append(stack)
        box.append(Gtk.Label(label="After"))
        self.assertEqual(count_widgets(box), 5)

    def test_theme_css_has_no_parse_errors(self):
        errors = []
        provider = Gtk.CssProvider()
        provider.connect("parsing-error", lambda _p, _section, error: errors.append(error))
        provider.load_from_data(("@define-color tb_accent #AC3D22;\n" + CSS).encode())
        self.assertEqual(errors, [])

    def test_chart_foreground_tracks_theme(self):
        manager = Adw.StyleManager.get_default()
        previous = manager.get_color_scheme()
        self.addCleanup(manager.set_color_scheme, previous)
        chart = self.page("stats").chart
        manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        drain()
        light = W.foreground(chart)
        manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        drain()
        dark = W.foreground(chart)
        self.assertLess(sum(light[:3]), sum(dark[:3]))
