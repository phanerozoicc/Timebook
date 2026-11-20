"""引擎测试：番茄钟状态机 / 限额与提醒 / 丢小时账本。"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from timebook.core.forfeit import (
    DEFAULT_CATEGORIES,
    HourLedger,
    ToggleOutcome,
    normalize_domain,
    verdict,
)
from timebook.core.pomodoro import (
    PRESETS,
    PomodoroEngine,
    PomodoroPhase,
    PomodoroState,
)
from timebook.core.store import Store
from timebook.core.wellbeing import (
    LimitCheckInputs,
    LimitsEngine,
    LimitSettings,
    ReminderSettings,
    RemindersEngine,
)


class FakeClock:
    """可手动推进的假时钟。"""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 3, 2, 9, 0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


class PomodoroEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")
        self.clock = FakeClock()
        self.engine = PomodoroEngine(self.store, now_fn=self.clock)
        self.segments: list = []
        self.notifications: list[tuple[str, str]] = []
        self.engine.on_work_segment = self.segments.append
        self.engine.on_notify = lambda t, b: self.notifications.append((t, b))

    def tearDown(self) -> None:
        self.store.close()

    def test_starts_in_idle(self) -> None:
        self.assertEqual(self.engine.state.phase, PomodoroPhase.IDLE)
        self.assertEqual(self.engine.remain, 0.0)

    def test_preset_durations(self) -> None:
        self.assertEqual(PRESETS["classic"].work_min, 40)
        self.assertEqual(PRESETS["sprint"].short_break_min, 3)
        self.assertEqual(PRESETS["deep"].long_break_min, 20)
        self.assertEqual(PRESETS["deep"].rounds, 3)

    def test_work_to_short_break(self) -> None:
        self.engine.start()
        self.assertEqual(self.engine.state.phase, PomodoroPhase.WORK)
        self.assertAlmostEqual(self.engine.remain, 40 * 60, delta=1)
        self.clock.advance(minutes=25)
        self.engine.tick()
        self.assertEqual(self.engine.state.phase, PomodoroPhase.WORK)
        self.clock.advance(minutes=15)
        self.engine.tick()
        self.assertEqual(self.engine.state.phase, PomodoroPhase.SHORT, "工作结束后应进短休")
        self.assertEqual(len(self.segments), 1)
        self.assertTrue(self.segments[0].completed, "自然结束应记为已完成")
        self.assertEqual(self.segments[0].duration, 40 * 60)

    def test_four_rounds_then_long_break_and_round_reset(self) -> None:
        preset = self.engine.preset
        self.engine.start()
        for index in range(4):
            self.clock.advance(minutes=preset.work_min)
            self.engine.tick()  # work → 休息
            if index < 3:
                self.clock.advance(minutes=preset.short_break_min)
                self.engine.tick()  # 短休结束（默认不自动开始下一轮）
                self.assertEqual(self.engine.state.phase, PomodoroPhase.WORK_READY)
                self.engine.begin_ready()  # 手动开始下一轮
        # 第 4 轮工作结束后应进长休，且 round 回 1
        self.assertEqual(self.engine.state.phase, PomodoroPhase.LONG)
        self.assertEqual(self.engine.state.round, 1, "长休后轮次应回到 1")
        self.assertEqual(len(self.segments), 4)

    def test_skip_records_incomplete_segment(self) -> None:
        self.engine.start()
        self.clock.advance(minutes=5)
        self.engine.skip()
        self.assertEqual(len(self.segments), 1)
        self.assertFalse(self.segments[0].completed, "跳过应记为未完成")
        self.assertEqual(self.segments[0].duration, 5 * 60, "跳过只记实际已专注的 5 分钟")
        self.assertEqual(self.engine.state.phase, PomodoroPhase.SHORT)

    def test_pause_resume_preserves_remaining(self) -> None:
        self.engine.start()
        self.clock.advance(minutes=5)
        self.engine.pause()
        paused_remain = self.engine.remain
        self.assertTrue(self.engine.state.paused)
        self.clock.advance(minutes=30)
        self.engine.tick()
        self.assertEqual(self.engine.state.phase, PomodoroPhase.WORK, "暂停期间不应推进阶段")
        self.assertAlmostEqual(self.engine.remain, paused_remain, delta=1)
        self.engine.resume()
        self.assertFalse(self.engine.state.paused)
        self.assertAlmostEqual(self.engine.remain, paused_remain, delta=1)

    def test_auto_start_breaks_off_goes_to_ready(self) -> None:
        self.engine.auto_start_breaks = False
        self.engine.start()
        self.clock.advance(minutes=40)
        self.engine.tick()
        self.assertEqual(self.engine.state.phase, PomodoroPhase.SHORT_READY)
        self.assertIsNone(self.engine.state.ends_at, "ready 阶段没有截止时间")
        self.engine.begin_ready()
        self.assertEqual(self.engine.state.phase, PomodoroPhase.SHORT)

    def test_reset(self) -> None:
        self.engine.start()
        self.engine.reset()
        self.assertEqual(self.engine.state.phase, PomodoroPhase.IDLE)
        self.assertEqual(self.engine.state.round, 1)

    def test_state_persisted(self) -> None:
        self.engine.start()
        self.clock.advance(minutes=3)
        self.engine.pause()
        revived = PomodoroEngine(self.store, now_fn=self.clock)
        self.assertEqual(revived.state.phase, PomodoroPhase.WORK, "重启后番茄状态不应丢")
        self.assertTrue(revived.state.paused)

    def test_preset_switch_changes_duration(self) -> None:
        self.engine.active_preset_name = "sprint"
        self.engine.start()
        self.assertAlmostEqual(self.engine.phase_total, 15 * 60)

    def test_progress_bounds(self) -> None:
        self.engine.start()
        self.assertAlmostEqual(self.engine.progress, 0.0, places=2)
        self.clock.advance(minutes=20)
        self.engine.tick()
        self.assertGreater(self.engine.progress, 0.4)
        self.assertLessEqual(self.engine.progress, 1.0)

    def test_toggle_primary_action(self) -> None:
        self.engine.toggle()
        self.assertEqual(self.engine.state.phase, PomodoroPhase.WORK)
        self.engine.toggle()
        self.assertTrue(self.engine.state.paused)
        self.engine.toggle()
        self.assertFalse(self.engine.state.paused)

    def test_remain_clock_format(self) -> None:
        self.engine.start()
        self.assertEqual(self.engine.remain_clock, "40:00")

    def test_state_serialization_roundtrip(self) -> None:
        state = PomodoroState(phase=PomodoroPhase.LONG, round=3, paused=True, paused_remaining=42.0)
        restored = PomodoroState.from_dict(state.to_dict())
        self.assertEqual(restored.phase, PomodoroPhase.LONG)
        self.assertEqual(restored.round, 3)
        self.assertTrue(restored.paused)


class LimitsEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = LimitsEngine()
        self.notifications: list[tuple[str, str]] = []
        self.engine.on_notify = lambda t, b: self.notifications.append((t, b))
        self.now = datetime(2026, 3, 2, 10, 0)

    def _input(self, used_minutes: float, limit: int = 100, **kwargs) -> LimitCheckInputs:
        return LimitCheckInputs(
            today_total=used_minutes * 60,
            daily_limit_minutes=limit,
            now=self.now,
            **kwargs,
        )

    def test_disabled_does_nothing(self) -> None:
        result = self.engine.minute(self._input(500), LimitSettings(enabled=False))
        self.assertIsNone(result)
        self.assertEqual(self.engine.today_percent, 0)

    def test_thresholds_fire_once_each(self) -> None:
        settings = LimitSettings(enabled=True, daily_minutes=100)
        self.assertIsNone(self.engine.minute(self._input(50), settings))
        self.assertEqual(self.engine.minute(self._input(80), settings), "limit-80")
        self.assertIsNone(self.engine.minute(self._input(85), settings), "80% 不应重复提醒")
        self.assertEqual(self.engine.minute(self._input(90), settings), "limit-90")
        self.assertEqual(self.engine.minute(self._input(100), settings), "limit-100")
        self.assertTrue(self.engine.limit_reached)

    def test_resets_on_new_day(self) -> None:
        settings = LimitSettings(enabled=True, daily_minutes=100)
        self.assertEqual(self.engine.minute(self._input(80), settings), "limit-80")
        self.now = datetime(2026, 3, 3, 9, 0)
        self.assertEqual(self.engine.minute(self._input(80), settings), "limit-80", "跨天应重新提醒")

    def test_distraction_nudge_with_cooldown(self) -> None:
        settings = LimitSettings(enabled=True, daily_minutes=1000, distract_enabled=True)
        segment_start = self.now - timedelta(minutes=11)
        inputs = self._input(50, current_host="youtube.com", current_segment_start=segment_start)
        self.assertEqual(self.engine.minute(inputs, settings), "distract")

        # 冷却 30 分钟内不重复
        self.now += timedelta(minutes=5)
        inputs = LimitCheckInputs(
            today_total=3000, daily_limit_minutes=0, now=self.now,
            current_host="youtube.com",
            current_segment_start=self.now - timedelta(minutes=16),
        )
        self.assertIsNone(self.engine.minute(inputs, settings))

    def test_non_distracting_site_no_nudge(self) -> None:
        settings = LimitSettings(enabled=True, daily_minutes=1000, distract_enabled=True)
        inputs = self._input(
            50, current_host="github.com", current_segment_start=self.now - timedelta(minutes=20)
        )
        self.assertIsNone(self.engine.minute(inputs, settings))


class RemindersEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RemindersEngine()
        self.notifications: list[tuple[str, str]] = []
        self.engine.on_notify = lambda t, b: self.notifications.append((t, b))
        self.engine.cups_provider = lambda: 3
        self.now = datetime(2026, 3, 2, 10, 0)

    def test_idle_resets_active_time(self) -> None:
        settings = ReminderSettings(water_enabled=False)
        for _ in range(3):
            self.engine.tick(False, False, now=self.now, settings=settings)
        self.assertAlmostEqual(self.engine.active_seconds, 15.0)
        self.engine.tick(True, False, now=self.now, settings=settings)
        self.assertEqual(self.engine.active_seconds, 0.0, "空闲应清零连续活跃")

    def test_pomodoro_break_resets_active_time(self) -> None:
        settings = ReminderSettings(water_enabled=False)
        self.engine.tick(False, False, now=self.now, settings=settings)
        self.engine.tick(False, True, now=self.now, settings=settings)
        self.assertEqual(self.engine.active_seconds, 0.0)

    def test_break_reminder_fires(self) -> None:
        settings = ReminderSettings(water_enabled=False, break_interval_minutes=10)
        result = None
        for _ in range(200):
            result = self.engine.tick(False, False, now=self.now, settings=settings)
            if result == "break":
                break
        self.assertEqual(result, "break")
        self.assertEqual(self.engine.active_seconds, 0.0, "提醒后应重置计数")

    def test_water_reminder_in_window(self) -> None:
        settings = ReminderSettings(water_interval_minutes=30, water_start_hour=9, water_end_hour=22)
        self.now = datetime(2026, 3, 2, 10, 0)
        first = self.engine.tick(False, False, now=self.now, settings=settings)
        self.assertEqual(first, "water")
        second = self.engine.tick(False, False, now=self.now, settings=settings)
        self.assertIsNone(second, "冷却中不应重复提醒")

    def test_water_reminder_outside_window(self) -> None:
        settings = ReminderSettings(water_interval_minutes=30, water_start_hour=9, water_end_hour=22)
        self.now = datetime(2026, 3, 2, 23, 30)
        self.assertIsNone(self.engine.tick(False, False, now=self.now, settings=settings))

    def test_notifications_disabled_blocks_all(self) -> None:
        settings = ReminderSettings(notifications_enabled=False, water_interval_minutes=15)
        self.assertIsNone(self.engine.tick(False, False, now=self.now, settings=settings))


class ForfeitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 3, 2, 15, 30)
        self.ledger = HourLedger(now_fn=lambda: self.now)

    def test_mark_lost_idempotent(self) -> None:
        self.assertTrue(self.ledger.mark_lost())
        self.assertFalse(self.ledger.mark_lost(), "同一小时重复标记应返回 False")
        self.assertEqual(self.ledger.today_lost_count, 1)

    def test_toggle_future_rejected(self) -> None:
        day = self.ledger.current_day_key
        self.assertEqual(self.ledger.toggle(day, 18), ToggleOutcome.REJECTED)
        self.assertEqual(self.ledger.toggle(day, 25), ToggleOutcome.REJECTED)
        self.assertEqual(self.ledger.toggle(day, 12), ToggleOutcome.NOW_LOST)
        self.assertEqual(self.ledger.toggle(day, 12), ToggleOutcome.NOW_KEPT)

    def test_clean_streak(self) -> None:
        self.assertEqual(self.ledger.clean_streak(), 60, "没有任何荒时，连续干净天数应到保留上限")
        self.ledger.mark_lost()
        # 与 Swift 一致：今天有荒则从昨天起往前数（今天是 1 天，所以是 59）
        self.assertEqual(self.ledger.clean_streak(), 59, "今天有荒时从昨天起算连续干净天")

    def test_last_n_days(self) -> None:
        days = self.ledger.last_n_days(7)
        self.assertEqual(len(days), 7)
        self.assertEqual(days[-1][0], "2026-03-02", "最后一项应是今天")

    def test_prune_keeps_limit(self) -> None:
        ledger = HourLedger(now_fn=lambda: self.now)
        for index in range(80):
            key = f"2020-01-{index + 1:02d}"
            ledger.days[key] = ledger.days.get(key) or __import__(
                "timebook.core.forfeit", fromlist=["DayRecord"]
            ).DayRecord()
        self.assertEqual(ledger.prune_if_needed(60), 20)

    def test_normalize_domain(self) -> None:
        self.assertEqual(normalize_domain("https://WWW.Example.com/path"), "www.example.com")
        self.assertEqual(normalize_domain("  douyin.com.  "), "douyin.com")
        self.assertIsNone(normalize_domain("not a domain"))
        self.assertIsNone(normalize_domain(""))

    def test_verdict_rules(self) -> None:
        common = dict(
            is_browser=lambda app: app in ("google-chrome", "firefox"),
            distractor_apps={"steam"},
            custom_domains={"douyin.com"},
            enabled_categories=DEFAULT_CATEGORIES,
        )
        self.assertEqual(verdict("steam", None, **common).kind, "app", "分心应用优先判荒")
        self.assertEqual(verdict("google-chrome", "youtube.com", **common).kind, "site")
        self.assertEqual(verdict("google-chrome", "douyin.com", **common).name, "自定义")
        self.assertIsNone(verdict("google-chrome", "github.com", **common), "工作类目永不判荒")
        self.assertIsNone(verdict("code", "youtube.com", **common), "非浏览器不看域名")

    def test_default_categories_are_distracting_ones(self) -> None:
        self.assertEqual(DEFAULT_CATEGORIES, {"social", "video", "shopping", "entertainment"})


if __name__ == "__main__":
    unittest.main()
