"""核心领域逻辑单元测试（存储 / 聚合 / 设置 / 分类 / 等级 / 热力图 / 导出）。"""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from timebook.core import models
from timebook.core.brain_level import ALL as LEVELS
from timebook.core.brain_level import for_total, next_of, progress_to_next
from timebook.core.categories import ALL as CATEGORIES
from timebook.core.categories import for_host, is_distracting
from timebook.core.exporter import csv_text, export_csv, weekly_markdown
from timebook.core.heatmap import HeatGrid, PALETTE, color_for, level_for_seconds
from timebook.core.l10n import T, reset_for_tests, set_language, set_system_language
from timebook.core.settings import Settings
from timebook.core.store import Store


def make_row(app="code", name="VS Code", start=None, seconds=600, host=None, title=None):
    start = start or datetime(2026, 3, 2, 10, 0)
    return models.EventRow(
        app_id=app, app_name=name, start=start,
        end=start + timedelta(seconds=seconds), detail=host, host=host, title=title,
    )


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")

    def tearDown(self) -> None:
        self.store.close()

    def test_add_and_query_rows_in_range(self) -> None:
        base = datetime(2026, 3, 2, 9, 0)
        self.store.add_event("a", "A", base, base + timedelta(minutes=10))
        self.store.add_event("b", "B", base + timedelta(hours=2), base + timedelta(hours=3))
        rows = self.store.rows(base, base + timedelta(hours=1))
        self.assertEqual(len(rows), 1, "区间查询应只返回交集记录")
        self.assertEqual(rows[0].app_id, "a")

    def test_rows_sorted_desc(self) -> None:
        base = datetime(2026, 3, 2, 9, 0)
        self.store.add_event("a", "A", base, base + timedelta(minutes=1))
        self.store.add_event("b", "B", base + timedelta(hours=1), base + timedelta(hours=2))
        rows = self.store.rows(base, base + timedelta(days=1))
        self.assertGreater(rows[0].start, rows[1].start, "应按开始时间倒序")

    def test_today_rows_and_known_apps(self) -> None:
        now = datetime.now()
        start = datetime(now.year, now.month, now.day, 8, 0)
        self.store.add_event("code", "VS Code", start, start + timedelta(minutes=5))
        self.store.add_event("code", "VS Code", start + timedelta(minutes=6), start + timedelta(minutes=9))
        self.assertEqual(len(self.store.today_rows(now)), 2)
        self.assertEqual(len(self.store.known_apps()), 1, "known_apps 必须去重")

    def test_delete_older_than(self) -> None:
        old = datetime.now() - timedelta(days=400)
        self.store.add_event("a", "A", old, old + timedelta(minutes=5))
        self.assertEqual(self.store.delete_older_than(90), 1)
        self.assertEqual(self.store.count_events(), 0)
        self.assertEqual(self.store.delete_older_than(0), 0, "0 表示永久保留")

    def test_kv_json_roundtrip(self) -> None:
        self.store.set("num", 42)
        self.store.set("flag", True)
        self.store.set("lst", [1, 2, 3])
        self.store.set("obj", {"a": "中文"})
        self.assertEqual(self.store.get("num"), 42)
        self.assertIs(self.store.get("flag"), True)
        self.assertEqual(self.store.get("lst"), [1, 2, 3])
        self.assertEqual(self.store.get("obj"), {"a": "中文"})
        self.assertIsNone(self.store.get("missing"))

    def test_cups_never_negative(self) -> None:
        self.assertEqual(self.store.add_cup(2), 2)
        self.assertEqual(self.store.add_cup(-5), 0, "杯数不得为负")
        self.assertEqual(self.store.cups_today(), 0)

    def test_focus_events(self) -> None:
        now = datetime(2026, 3, 2, 10, 0)
        self.store.record_focus(now, now + timedelta(minutes=25), True, "classic")
        self.store.record_focus(now + timedelta(hours=1), now + timedelta(hours=1, minutes=3), False, "classic")
        events = self.store.focus_events(now, now + timedelta(days=1))
        self.assertEqual(len(events), 2)
        self.assertEqual(sum(1 for e in events if e.completed), 1)

    def test_lost_hours_roundtrip(self) -> None:
        self.store.set_lost_hours("2026-03-02", {1, 5, 23})
        self.assertEqual(self.store.lost_hours("2026-03-02"), {1, 5, 23})
        self.assertEqual(self.store.lost_hours("2026-03-03"), set())

    def test_forfeit_prune(self) -> None:
        self.store.set_lost_hours("2020-01-01", {3})
        removed = self.store.prune_forfeit_days(60, now=datetime(2026, 3, 2))
        self.assertEqual(removed, 1)


class AggregationTests(unittest.TestCase):
    def test_total_and_by_app_limit(self) -> None:
        rows = [make_row(app=f"app{i}", name=f"App {i}", seconds=60 * (i + 1)) for i in range(5)]
        self.assertEqual(models.total(rows), 60 * 15)
        top = models.by_app(rows, limit=2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0].name, "App 4", "最长的应用应排第一")

    def test_by_host_ignores_empty(self) -> None:
        rows = [
            make_row(host="github.com", seconds=100),
            make_row(host=None, seconds=999),
            make_row(host="", seconds=50),
        ]
        hosts = models.by_host(rows)
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].host, "github.com")

    def test_by_category_maps_domains(self) -> None:
        rows = [
            make_row(host="www.youtube.com", seconds=3600),
            make_row(host="github.com", seconds=1800),
            make_row(host="unknown.example.org", seconds=600),
        ]
        cats = {c.category_id: c.seconds for c in models.by_category(rows)}
        self.assertEqual(cats["video"], 3600)
        self.assertEqual(cats["work"], 1800)
        self.assertEqual(cats["other"], 600)

    def test_per_day_length_and_buckets(self) -> None:
        now = datetime(2026, 3, 9, 12, 0)
        rows = [
            make_row(start=datetime(2026, 3, 9, 9, 0), seconds=600),
            make_row(start=datetime(2026, 3, 8, 9, 0), seconds=300),
            make_row(start=datetime(2026, 2, 1, 9, 0), seconds=9999),  # 区间外
        ]
        points = models.per_day(rows, count=3, now=now)
        self.assertEqual(len(points), 3)
        self.assertEqual(points[-1].day, date(2026, 3, 9), "最后一天应是今天")
        self.assertEqual(points[-1].seconds, 600)
        self.assertEqual(points[-2].seconds, 300)

    def test_active_and_average(self) -> None:
        now = datetime(2026, 3, 9, 12, 0)
        rows = [make_row(start=datetime(2026, 3, 9, 9, 0), seconds=7200),
                make_row(start=datetime(2026, 3, 7, 9, 0), seconds=3600)]
        self.assertEqual(models.active_days(rows, count=3, now=now), 2)
        self.assertAlmostEqual(models.average_active_day(rows, count=3, now=now), 5400.0)

    def test_segments_sorted_desc(self) -> None:
        rows = [make_row(start=datetime(2026, 3, 2, 9)), make_row(start=datetime(2026, 3, 2, 11))]
        ordered = models.segments(rows)
        self.assertGreater(ordered[0].start, ordered[1].start)


class FormatTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_for_tests()

    def test_fmt_compact(self) -> None:
        set_language("en")
        self.addCleanup(reset_for_tests)
        self.assertEqual(models.fmt_duration(0, compact=True), "0s")
        self.assertEqual(models.fmt_duration(59, compact=True), "59s")
        self.assertEqual(models.fmt_duration(60, compact=True), "1m")
        self.assertEqual(models.fmt_duration(3600 + 7 * 60, compact=True), "1h07m")
        self.assertEqual(models.fmt_duration(3600 * 2 + 60, compact=True), "2h01m")

    def test_fmt_clock_interval(self) -> None:
        self.assertEqual(models.fmt_clock_interval(0), "00:00")
        self.assertEqual(models.fmt_clock_interval(1492), "24:52")

    def test_fmt_clock(self) -> None:
        self.assertEqual(models.fmt_clock(datetime(2026, 3, 2, 9, 5)), "09:05")


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")
        self.settings = Settings(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def test_idle_threshold_defaults_and_clamp(self) -> None:
        self.assertEqual(self.settings.idle_threshold, 120)
        self.settings.idle_threshold = 0
        self.assertEqual(self.settings.idle_threshold, 0, "0 表示不启用空闲判定")
        self.settings.idle_threshold = 5
        self.assertEqual(self.settings.idle_threshold, 120, "低于 30 秒应回落到默认")

    def test_excluded_set(self) -> None:
        self.settings.excluded = {"code", "slack"}
        self.assertEqual(self.settings.excluded, {"code", "slack"})
        self.assertNotIn("code", sorted(self.settings.excluded)[1:])

    def test_retention_only_valid(self) -> None:
        self.settings.retention_days = 180
        self.assertEqual(self.settings.retention_days, 180)
        self.settings.retention_days = 7
        self.assertEqual(self.settings.retention_days, 0, "非法保留期回落到永久")

    def test_limits_label(self) -> None:
        self.settings.limits_daily_minutes = 45
        set_language("zh")
        self.assertEqual(self.settings.limits_daily_label, "45 分钟")
        self.settings.limits_daily_minutes = 120
        self.assertEqual(self.settings.limits_daily_label, "2 小时")

    def test_language_fallback(self) -> None:
        self.settings.language = "fr"
        self.assertEqual(self.settings.language, "auto")


class CategoryTests(unittest.TestCase):
    def test_suffix_match(self) -> None:
        self.assertEqual(for_host("www.youtube.com").id, "video")
        self.assertEqual(for_host("news.bbc.co.uk").id, "news")
        self.assertEqual(for_host("sub.github.com").id, "work")

    def test_unknown_to_other(self) -> None:
        self.assertEqual(for_host("example.invalid").id, "other")
        self.assertEqual(for_host("").id, "other")

    def test_nine_categories(self) -> None:
        self.assertEqual(len(CATEGORIES), 9, "分类数量固定为 9")

    def test_distracting_flag(self) -> None:
        self.assertTrue(is_distracting("youtube.com"))
        self.assertFalse(is_distracting("github.com"))


class BrainLevelTests(unittest.TestCase):
    def test_thresholds(self) -> None:
        self.assertEqual(for_total(0).level, 1)
        self.assertEqual(for_total(3599).level, 1)
        self.assertEqual(for_total(3600).level, 2)
        self.assertEqual(for_total(3 * 3600).level, 4)
        self.assertEqual(for_total(12 * 3600).level, 10)

    def test_ten_levels(self) -> None:
        self.assertEqual(len(LEVELS), 10)

    def test_next_and_progress(self) -> None:
        self.assertIsNone(next_of(10), "最高级没有下一级")
        level, nxt, ratio = progress_to_next(1.5 * 3600)
        self.assertEqual(level.level, 2)
        self.assertEqual(nxt.level, 3)
        self.assertAlmostEqual(ratio, 0.5, places=2)


class HeatmapTests(unittest.TestCase):
    def test_level_boundaries(self) -> None:
        self.assertEqual(level_for_seconds(0), 0)
        self.assertEqual(level_for_seconds(0.25 * 3600), 1)
        self.assertEqual(level_for_seconds(0.5 * 3600), 2)
        self.assertEqual(level_for_seconds(1 * 3600), 3)
        self.assertEqual(level_for_seconds(2 * 3600), 4)
        self.assertEqual(level_for_seconds(6 * 3600), 6)
        self.assertEqual(level_for_seconds(99 * 3600), 6)

    def test_palette_seven(self) -> None:
        self.assertEqual(len(PALETTE), 7)
        self.assertEqual(color_for(0), "#262A35")

    def test_grid_shape_and_alignment(self) -> None:
        now = datetime(2026, 3, 4, 15, 0)  # 周三
        grid = HeatGrid.for_rows([], now)
        self.assertEqual(len(grid.columns), 12, "固定 12 列")
        self.assertTrue(all(len(c.cells) == 7 for c in grid.columns), "每列 7 天")
        self.assertEqual(grid.columns[0].cells[0].day.weekday(), 0, "首格必须是周一")
        self.assertEqual(grid.columns[-1].cells[-1].day, date(2026, 3, 8), "末格是本周日")

    def test_grid_buckets_rows(self) -> None:
        now = datetime(2026, 3, 4, 15, 0)
        rows = [make_row(start=datetime(2026, 3, 4, 9), seconds=7200)]
        grid = HeatGrid.for_rows(rows, now)
        today_cell = [c for c in grid.cells if c.day == date(2026, 3, 4)][0]
        self.assertEqual(today_cell.seconds, 7200)
        self.assertEqual(today_cell.level, 4)


class ExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        set_language("zh")
        self.addCleanup(reset_for_tests)

    def test_csv_header_and_bom(self) -> None:
        text = csv_text([make_row(host="github.com")])
        self.assertTrue(text.startswith("\ufeff"), "CSV 需带 BOM 以便 Excel 正确识别")
        parsed = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
        self.assertEqual(parsed[0], ["start", "end", "duration_seconds", "app", "host", "detail", "title"])
        self.assertEqual(len(parsed), 2)

    def test_csv_escapes_commas_and_quotes(self) -> None:
        row = make_row(title='带有,逗号 和 "引号"')
        parsed = list(csv.reader(io.StringIO(csv_text([row]).lstrip("\ufeff"))))
        self.assertEqual(parsed[1][6], '带有,逗号 和 "引号"')

    def test_export_csv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            count = export_csv([make_row(), make_row()], path)
            self.assertEqual(count, 2)
            self.assertTrue(path.exists())

    def test_weekly_markdown_contains_sections(self) -> None:
        now = datetime(2026, 3, 9, 12, 0)
        per_day = models.per_day([make_row()], count=7, now=now)
        md = weekly_markdown(
            now=now, per_day=per_day, top_apps=models.by_app([make_row()]),
            top_hosts=[], categories=[], pomodoros=3, focus_seconds=4500,
            cups=4, goal_cups=8,
        )
        self.assertIn("时账周报", md)
        self.assertIn("每日", md)
        self.assertIn("3 🍅", md)
        self.assertIn("4/8", md)

    def test_empty_markdown_does_not_crash(self) -> None:
        now = datetime(2026, 3, 9, 12, 0)
        md = weekly_markdown(now=now, per_day=[], top_apps=[], top_hosts=[], categories=[])
        self.assertIn("时账周报", md)


class L10nTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_for_tests()

    def test_explicit_language(self) -> None:
        set_language("en")
        self.assertEqual(T("中文", "English"), "English")
        set_language("zh")
        self.assertEqual(T("中文", "English"), "中文")

    def test_auto_follows_system(self) -> None:
        set_language("auto")
        set_system_language("zh_CN.UTF-8")
        self.assertEqual(T("中文", "English"), "中文")
        set_system_language("en_US.UTF-8")
        self.assertEqual(T("中文", "English"), "English")

    def test_invalid_pref_falls_back(self) -> None:
        set_language("klingon")
        set_system_language("en")
        self.assertEqual(T("中文", "English"), "English")


if __name__ == "__main__":
    unittest.main()
