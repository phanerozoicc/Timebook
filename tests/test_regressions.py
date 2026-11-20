"""Behavioral regressions for data boundaries and multi-step user workflows."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timebook.context import AppContext
from timebook.core import models
from timebook.core.exporter import build_weekly_markdown, export_csv
from timebook.core.forfeit import ForfeitStore
from timebook.core.heatmap import HeatGrid
from timebook.core.l10n import reset_for_tests, set_language
from timebook.core.pomodoro import PomodoroEngine
from timebook.core.settings import Settings
from timebook.core.store import Store
from timebook.core.wellbeing import LimitsEngine, RemindersEngine
from timebook.platform.tracker import Tracker
from tests.test_platform import FakeClock, FakeX11, WindowStub


def context(now=None):
    store = Store(":memory:")
    settings = Settings(store)
    settings.retention_days = 0
    clock = FakeClock(now or datetime.now())
    source = FakeX11()
    engine = PomodoroEngine(store, clock)
    engine.on_work_segment = lambda s: store.record_focus(s.start, s.end, s.completed, s.preset_name)
    ctx = AppContext(store, settings, engine, LimitsEngine(), RemindersEngine(),
                     Tracker(store, settings, source, clock), ForfeitStore(store, clock))
    return ctx, clock, source


class TimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.clock, self.source = context(datetime(2026, 11, 19, 0, 10))
        self.addCleanup(self.ctx.store.close)
        self.start = datetime(2026, 11, 18, 23, 50)
        self.end = datetime(2026, 11, 19, 0, 10)
        self.row = models.EventRow("code", "Editor", self.start, self.end)
        self.ctx.store.add_event("code", "Editor", self.start, self.end)

    def test_store_clips_at_both_edges(self):
        rows = self.ctx.store.rows(self.start + timedelta(minutes=5), self.end - timedelta(minutes=5))
        self.assertEqual(models.total(rows), 600)
        self.assertEqual(rows[0].start, self.start + timedelta(minutes=5))

    def test_half_open_interval_does_not_repeat_ending_event(self):
        self.assertEqual(self.ctx.store.rows(self.end, self.end + timedelta(hours=1)), [])
        self.assertEqual(self.ctx.store.rows(self.start, self.start), [])

    def test_daily_totals_split_midnight(self):
        points = models.per_day([self.row], 2, self.end)
        self.assertEqual([p.seconds for p in points], [600, 600])
        self.assertEqual(models.day_total([self.row], self.end.date()), 600)
        self.assertEqual(models.active_days([self.row], 2, self.end), 2)

    def test_stacked_totals_split_midnight(self):
        self.assertEqual([p.minutes for p in models.stacked([self.row], 2, self.end)], [10, 10])

    def test_heatmap_agrees_with_daily_totals(self):
        grid = HeatGrid.for_rows([self.row], self.end)
        self.assertEqual(grid.active_days, 2)
        self.assertEqual(grid.total_seconds, 1200)

    def test_multiday_event_is_partitioned_without_loss(self):
        row = models.EventRow("a", "A", self.start, self.end + timedelta(days=2))
        parts = list(models.daily_parts([row]))
        self.assertEqual(len(parts), 4)
        self.assertEqual(models.total(parts), row.duration)

    def test_today_total_includes_only_today_portion(self):
        self.assertEqual(self.ctx.today_total(), 600)

    def test_previous_same_time_comparison_clips_long_event(self):
        start = datetime(2026, 11, 18, 9)
        self.ctx.store.add_event("web", "Browser", start, start + timedelta(hours=4))
        rows = self.ctx.store.rows(start, start + timedelta(hours=1))
        self.assertEqual(models.total(rows), 3600)

    def test_focus_completion_counted_once_across_midnight(self):
        self.ctx.store.record_focus(self.start, self.end, True)
        self.assertEqual(self.ctx.store.focus_for_day(self.start.date()), [])
        self.assertEqual(len(self.ctx.store.focus_for_day(self.end.date())), 1)


class TrackingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.clock, self.source = context(datetime(2026, 11, 18, 23, 59))
        self.addCleanup(self.ctx.store.close)
        self.source.window = WindowStub()
        self.ctx.tracker.tick()

    def test_live_rows_and_totals_agree_after_midnight(self):
        self.clock.advance(minutes=2)
        self.assertEqual(self.ctx.today_total(), 60)
        self.assertEqual(models.total(self.ctx.today_rows(self.clock.now)), 60)
        self.assertEqual(self.ctx.store.count_events(), 0)

    def test_settling_live_event_does_not_double_count(self):
        self.clock.advance(seconds=30)
        before = self.ctx.today_total()
        self.ctx.tracker.force_close()
        self.assertEqual(self.ctx.today_total(), before)
        self.assertEqual(self.ctx.store.count_events(), 1)

    def test_switch_to_excluded_app_retains_previous_work(self):
        self.clock.advance(seconds=30)
        self.ctx.settings.excluded = {"private"}
        self.source.window = WindowStub("private", "Private")
        self.ctx.tracker.tick()
        self.assertEqual(self.ctx.today_total(), 30)
        self.assertIsNone(self.ctx.tracker.current_app_name)

    def test_lock_preserves_only_observed_work(self):
        self.clock.advance(seconds=30)
        self.ctx.tracker.tick()
        self.clock.advance(seconds=2)
        self.source.screensaver = True
        self.ctx.tracker.tick()
        self.assertEqual(self.ctx.today_total(), 30)
        self.assertIsNone(self.ctx.tracker.current_host)

    def test_suspend_and_app_switch_does_not_add_sleep_time(self):
        self.clock.advance(seconds=30)
        self.ctx.tracker.tick()
        self.clock.advance(hours=3)
        self.source.window = WindowStub("terminal", "Terminal")
        self.ctx.tracker.tick()
        rows = self.ctx.store.rows(datetime(2026, 11, 18), self.clock.now)
        self.assertEqual(models.total(rows), 30)
        self.assertEqual(self.ctx.today_total(), 0)

    def test_missing_foreground_closes_live_segment(self):
        self.clock.advance(seconds=10)
        self.source.window = None
        self.ctx.tracker.tick()
        self.clock.advance(seconds=30)
        self.assertEqual(self.ctx.today_total(), 10)
        self.assertIsNone(self.ctx.tracker.current_segment_start)

    def test_paused_tracking_hides_live_segment(self):
        self.clock.advance(seconds=15)
        self.ctx.tracker.force_close()
        self.ctx.settings.paused = True
        self.clock.advance(seconds=45)
        self.ctx.tracker.tick()
        self.assertEqual(self.ctx.today_total(), 0)  # now the next day
        self.assertEqual(models.total(self.ctx.store.rows(datetime(2026, 11, 18), self.clock.now)), 15)


class ExportWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.clock, _ = context(datetime(2026, 11, 19, 12))
        self.addCleanup(self.ctx.store.close)
        self.addCleanup(reset_for_tests)

    def test_csv_multiline_title_counts_records_not_lines(self):
        row = models.EventRow("editor", "Editor", self.clock.now - timedelta(minutes=1), self.clock.now,
                              title='first line\nsecond, "quoted" line')
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.csv"
            self.assertEqual(export_csv(iter([row]), path), 1)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_report_obeys_language_and_custom_water_goal(self):
        self.ctx.settings.water_goal_cups = 12
        self.ctx.store.add_cup(3, self.clock.now)
        for language, heading in (("zh", "时账周报"), ("en", "Timebook Weekly")):
            with self.subTest(language=language):
                set_language(language)
                report = build_weekly_markdown(self.ctx.store, self.clock.now)
                self.assertIn(heading, report)
                self.assertIn("3/12", report)

    def test_report_week_boundary_clips_previous_week(self):
        self.ctx.store.add_event("a", "A", datetime(2026, 11, 12, 23, 30), datetime(2026, 11, 13, 0, 30))
        set_language("en")
        report = build_weekly_markdown(self.ctx.store, self.clock.now)
        self.assertIn("Week total：30m", report)


class PomodoroWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.clock, _ = context(datetime(2026, 11, 19, 9))
        self.addCleanup(self.ctx.store.close)

    def test_resume_remaining_correct_before_next_tick(self):
        e = self.ctx.pomodoro
        e.start()
        self.clock.advance(minutes=3)
        e.pause()
        self.clock.advance(minutes=7)
        e.resume()
        self.assertEqual(e.remain, 37 * 60)

    def test_skip_paused_work_excludes_pause_time(self):
        e = self.ctx.pomodoro
        e.start()
        self.clock.advance(minutes=3)
        e.pause()
        self.clock.advance(minutes=20)
        e.skip()
        rows = self.ctx.store.focus_for_day(self.clock.now.date())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].duration, 180)
        self.assertFalse(rows[0].completed)
