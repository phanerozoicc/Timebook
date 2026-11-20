"""托盘测试：图标渲染 + 菜单文案/动作分发（不依赖真实 D-Bus 会话）。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from timebook.core.l10n import set_language, reset_for_tests
from timebook.core.pomodoro import PomodoroEngine, PomodoroPhase
from timebook.core.settings import Settings
from timebook.core.store import Store
from timebook.platform.tray import MENU_LAYOUT, Tray, render_icon


class FakeTracker:
    def __init__(self) -> None:
        self.closed = 0
        self.is_idle = False
        self.current_app_name = "VS Code"
        self.current_host = None

    def force_close(self, *args) -> None:
        self.closed += 1


class FakeCtx:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.settings = Settings(store)
        self.pomodoro = PomodoroEngine(store)
        self.tracker = FakeTracker()

    def today_total(self) -> float:
        return 3661.0

    def add_cup(self, delta: int = 1) -> int:
        return self.store.add_cup(delta)


def make_tray(store: Store, **callbacks):
    """构造一个不连 D-Bus 的托盘实例（只测文案/动作逻辑）。"""
    tray = Tray.__new__(Tray)
    tray._ctx = FakeCtx(store)
    tray.available = False
    tray._label = ""
    tray._tooltip = ""
    tray._status_line = ""
    tray._pomodoro_text = ""
    tray._icon = b""
    tray._icon_size = 22
    tray._bus = None
    tray._bus_name = None
    tray._service_name = ""
    tray._dbus = None
    tray._item = None
    tray._menu = None
    tray._on_open = callbacks.get("on_open", lambda: None)
    tray._on_pause = callbacks.get("on_pause", lambda p: None)
    tray._on_quit = callbacks.get("on_quit", lambda: None)
    tray._on_cup = callbacks.get("on_cup", lambda: None)
    tray._on_break = callbacks.get("on_break", lambda: None)
    return tray


class IconTests(unittest.TestCase):
    def test_render_icon_size(self) -> None:
        for size in (16, 22, 32):
            data = render_icon(size)
            self.assertEqual(len(data), size * size * 4, "ARGB32 位图字节数应为 w*h*4")

    def test_render_icon_has_brand_color(self) -> None:
        data = render_icon(22)
        # 找出不透明像素里的品牌红（#F0663F → r=240,g=102,b=63）
        found = False
        for index in range(0, len(data), 4):
            a, r, g, b = data[index : index + 4]
            if a > 200 and abs(r - 240) < 24 and abs(g - 102) < 24 and abs(b - 63) < 24:
                found = True
                break
        self.assertTrue(found, "图标里应含品牌番茄橘像素")


class TrayLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        set_language("zh")
        self.addCleanup(reset_for_tests)
        self.store = Store(":memory:")
        self.events: list[str] = []
        self.tray = make_tray(
            self.store,
            on_open=lambda: self.events.append("open"),
            on_quit=lambda: self.events.append("quit"),
            on_cup=lambda: (self.events.append("cup"), self.store.add_cup(1)),
            on_break=lambda: self.events.append("break"),
            on_pause=lambda paused: self.events.append(f"pause:{paused}"),
        )

    def tearDown(self) -> None:
        self.store.close()

    def test_menu_has_expected_actions(self) -> None:
        keys = [entry[2] for entry in MENU_LAYOUT if entry[1] == "action"]
        self.assertEqual(keys, ["open", "pomodoro", "pause", "water", "break", "quit"])

    def test_activate_dispatches_each_action(self) -> None:
        ids = {entry[2]: entry[0] for entry in MENU_LAYOUT if entry[1] == "action"}
        self.tray._activate(ids["open"])
        self.tray._activate(ids["water"])
        self.tray._activate(ids["break"])
        self.tray._activate(ids["quit"])
        self.assertEqual(self.events, ["open", "cup", "break", "quit"])
        self.assertEqual(self.store.cups_today(), 1, "托盘 +1 杯水应写入数据库")

    def test_label_shows_today_duration_when_idle(self) -> None:
        self.tray.refresh(force=True)
        self.assertEqual(self.tray._label, "1时01分", "非番茄期间托盘标签显示今日时长")

    def test_label_shows_countdown_during_focus(self) -> None:
        self.tray._ctx.pomodoro.start()
        self.tray.refresh(force=True)
        self.assertTrue(self.tray._label.startswith("🍅"), f"专注时标签应为番茄倒计时，实际 {self.tray._label!r}")
        self.assertIn("40:00", self.tray._label)

    def test_pomodoro_action_starts_pauses_and_resumes(self) -> None:
        item_id = next(entry[0] for entry in MENU_LAYOUT if entry[2] == "pomodoro")
        engine = self.tray._ctx.pomodoro
        self.assertIn("40", self.tray._menu_text("pomodoro"))

        self.tray._activate(item_id)
        self.assertEqual(engine.state.phase, PomodoroPhase.WORK)
        self.assertIn("40:00", self.tray._label)
        self.assertEqual(self.tray._pomodoro_text, self.tray._menu_text("pomodoro"))

        self.tray._activate(item_id)
        self.assertTrue(engine.state.paused)
        self.assertIn("⏸", self.tray._label)

        self.tray._activate(item_id)
        self.assertFalse(engine.state.paused)
        self.assertFalse(self.tray._ctx.settings.paused)
        self.assertEqual(self.tray._ctx.tracker.closed, 0)

    def test_pomodoro_action_starts_ready_phases(self) -> None:
        item_id = next(entry[0] for entry in MENU_LAYOUT if entry[2] == "pomodoro")
        now = self.tray._ctx.pomodoro.now
        engine = PomodoroEngine(self.store, now_fn=lambda: now)
        self.tray._ctx.pomodoro = engine
        engine.auto_start_breaks = False
        self.tray._activate(item_id)
        now = engine.state.ends_at
        engine.tick()
        self.assertEqual(engine.state.phase, PomodoroPhase.SHORT_READY)
        self.tray._activate(item_id)
        self.assertEqual(engine.state.phase, PomodoroPhase.SHORT)
        now = engine.state.ends_at
        engine.tick()
        self.assertEqual(engine.state.phase, PomodoroPhase.WORK_READY)
        self.tray._activate(item_id)
        self.assertEqual(engine.state.phase, PomodoroPhase.WORK)
        self.assertEqual(engine.state.round, 2)

    def test_pomodoro_menu_refreshes_while_tracking_paused(self) -> None:
        self.tray._ctx.settings.paused = True
        self.tray.refresh()
        self.tray.available = True
        self.tray._item = Mock()
        self.tray._menu = Mock()
        self.tray._dbus = Mock()
        self.tray._ctx.pomodoro.start()
        self.tray.refresh()
        self.tray._menu.LayoutUpdated.assert_called_once()
        self.assertEqual(self.tray._label, "⏸")

    def test_label_shows_pause_marker(self) -> None:
        self.tray._ctx.pomodoro.start()
        self.tray._ctx.pomodoro.pause()
        self.tray.refresh(force=True)
        self.assertIn("⏸", self.tray._label)

    def test_label_when_tracking_paused(self) -> None:
        self.tray._ctx.settings.paused = True
        self.tray.refresh(force=True)
        self.assertEqual(self.tray._label, "⏸")

    def test_status_line_reflects_state(self) -> None:
        self.tray.refresh(force=True)
        self.assertIn("VS Code", self.tray._status_line)
        self.tray._ctx.tracker.is_idle = True
        self.tray.refresh(force=True)
        self.assertIn("空闲", self.tray._status_line)

    def test_toggle_pause_flips_setting_and_closes_segment(self) -> None:
        self.tray._toggle_pause()
        self.assertTrue(self.tray._ctx.settings.paused)
        self.assertEqual(self.tray._ctx.tracker.closed, 1, "暂停时应把当前段结账")
        self.assertIn("pause:True", self.events)
        self.tray._toggle_pause()
        self.assertFalse(self.tray._ctx.settings.paused)

    def test_refresh_is_noop_when_unavailable(self) -> None:
        self.tray.available = False
        self.tray.refresh(force=True)  # 不应抛异常

    def test_destroy_safe_without_dbus(self) -> None:
        self.tray.destroy()
        self.assertFalse(self.tray.available)

    def test_menu_text_switches_with_language(self) -> None:
        from timebook.core.l10n import reset_for_tests, set_language

        try:
            set_language("en")
            self.assertIn("Open", self.tray._menu_text("open"))
            self.assertEqual(self.tray._menu_text("pomodoro"), "Start pomodoro (40 min)")
            self.tray._ctx.pomodoro.start()
            self.assertEqual(self.tray._menu_text("pomodoro"), "Pause pomodoro")
            self.tray._ctx.pomodoro.pause()
            self.assertEqual(self.tray._menu_text("pomodoro"), "Resume pomodoro")
            set_language("zh")
            self.assertIn("打开", self.tray._menu_text("open"))
            self.assertEqual(self.tray._menu_text("pomodoro"), "继续番茄钟")
        finally:
            reset_for_tests()


if __name__ == "__main__":
    unittest.main()
