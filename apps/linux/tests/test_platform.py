"""平台层测试：浏览器域名推断 + 采集循环（用假 X11 源，无需显示器）。"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from timebook.core.settings import Settings
from timebook.core.store import Store
from timebook.platform.browsers import detail_from_title, host_from_title, is_browser
from timebook.platform.tracker import Tracker
from timebook.platform.x11 import WindowInfo, _class_to_ids


class WindowStub:
    """可编排的假前台窗口。"""

    def __init__(self, app_id="code", app_name="VS Code", title="main.py — VS Code", pid=1234):
        self.app_id = app_id
        self.app_name = app_name
        self.title = title
        self.pid = pid
        self.window_id = 42


class FakeX11:
    """实现 ``WindowSource`` 协议，供 Tracker 注入。"""

    def __init__(self) -> None:
        self.window: WindowInfo | None = None
        self.idle = 0.0
        self.screensaver = False

    def active_window(self):
        return self.window

    def idle_seconds(self) -> float:
        return self.idle

    def screensaver_active(self) -> bool:
        return self.screensaver


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 3, 2, 9, 0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


class BrowserTests(unittest.TestCase):
    def test_is_browser(self) -> None:
        self.assertTrue(is_browser("google-chrome", "Google Chrome"))
        self.assertTrue(is_browser("firefox", "Firefox"))
        self.assertTrue(is_browser("chromium-browser", "Chromium"))
        self.assertFalse(is_browser("code", "Visual Studio Code"))
        self.assertFalse(is_browser("org.gnome.Nautilus", "Files"))

    def test_known_brand_titles(self) -> None:
        cases = {
            "Some Video - YouTube - Google Chrome": "youtube.com",
            "GitHub · Where software is built": "github.com",
            "测试标题_哔哩哔哩_bilibili": "bilibili.com",
            "Home / X": "x.com",
            "小红书 - 标记我的生活": "xiaohongshu.com",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(host_from_title(title), expected)

    def test_generic_domain_fallback(self) -> None:
        self.assertEqual(host_from_title("新闻 - news.sina.com.cn"), "news.sina.com.cn")
        self.assertEqual(host_from_title("Docs — developer.mozilla.org"), "developer.mozilla.org")
        self.assertEqual(host_from_title("www.example.co.uk/path"), "example.co.uk")

    def test_unknown_titles(self) -> None:
        # 只有品牌中文名、没有域名时，靠别名表识别（这是 Linux 版的增强点）
        self.assertEqual(host_from_title("知乎 - 有问题就会有答案"), "zhihu.com")
        self.assertIsNone(host_from_title("未命名文档"))
        self.assertIsNone(host_from_title(""))
        self.assertIsNone(host_from_title("main.py — VS Code"))

    def test_file_extensions_not_treated_as_domains(self) -> None:
        self.assertIsNone(host_from_title("app.js - code editor"))
        self.assertIsNone(host_from_title("notes.md"))

    def test_detail_from_title(self) -> None:
        host, title = detail_from_title("Video - YouTube - Google Chrome", "google-chrome")
        self.assertEqual(host, "youtube.com")
        self.assertEqual(title, "Video - YouTube - Google Chrome")
        host, _ = detail_from_title("main.py", "code")
        self.assertIsNone(host, "非浏览器不推断域名")

    def test_class_to_ids(self) -> None:
        self.assertEqual(_class_to_ids("firefox\x00Firefox\x00"), ("firefox", "Firefox"))
        app_id, name = _class_to_ids("Navigator\x00firefox\x00")
        self.assertEqual(app_id, "firefox")
        self.assertEqual(_class_to_ids(""), ("", ""))


class TrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")
        self.settings = Settings(self.store)
        self.settings.browser_title_parsing = True
        self.settings.capture_titles = False
        self.x11 = FakeX11()
        self.clock = FakeClock()
        self.tracker = Tracker(
            self.store, self.settings, self.x11, now_fn=self.clock, idle_grace_seconds=0.0
        )

    def tearDown(self) -> None:
        self.store.close()

    def _window(self, app_id, name=None, title="", pid=1):
        return WindowInfo(
            window_id=1, pid=pid, app_id=app_id, app_name=name or app_id, title=title
        )

    def test_records_segment_on_app_switch(self) -> None:
        self.x11.window = self._window("code", "VS Code")
        self.tracker.tick()
        self.clock.advance(minutes=5)
        self.x11.window = self._window("slack", "Slack")
        self.tracker.tick()
        self.clock.advance(minutes=2)
        self.tracker.force_close()

        rows = self.store.today_rows(self.clock.now)
        self.assertEqual(len(rows), 2, "切应用应把上一段落库")
        self.assertEqual(rows[-1].app_id, "code")
        self.assertAlmostEqual(rows[-1].duration, 300, delta=1)

    def test_excluded_app_not_recorded(self) -> None:
        self.settings.excluded = {"code"}
        self.x11.window = self._window("code", "VS Code")
        self.tracker.tick()
        self.clock.advance(minutes=5)
        self.tracker.force_close()
        self.assertEqual(len(self.store.today_rows(self.clock.now)), 0, "排除应用不应落库")

    def test_paused_not_recorded(self) -> None:
        self.x11.window = self._window("code", "VS Code")
        self.tracker.tick()
        self.clock.advance(minutes=2)
        self.settings.paused = True
        self.tracker.tick()
        self.clock.advance(minutes=3)
        self.tracker.force_close()
        self.assertEqual(len(self.store.today_rows(self.clock.now)), 0, "暂停期间不产生数据")

    def test_idle_truncates_segment(self) -> None:
        self.settings.idle_threshold = 120
        self.x11.window = self._window("code", "VS Code")
        self.tracker.tick()
        self.clock.advance(minutes=10)
        self.x11.idle = 300.0  # 已空闲 5 分钟
        self.tracker.tick()
        self.tracker.force_close()

        rows = self.store.today_rows(self.clock.now)
        self.assertEqual(len(rows), 1)
        # 结束时间应回退到「开始空闲之前」（约 10 - 5 = 5 分钟处）
        self.assertLess(rows[0].duration, 10 * 60)
        self.assertAlmostEqual(rows[0].duration, 5 * 60, delta=10)

    def test_screensaver_not_recorded(self) -> None:
        self.x11.window = self._window("code", "VS Code")
        self.tracker.tick()
        self.clock.advance(minutes=2)
        self.x11.screensaver = True
        self.tracker.tick()
        self.clock.advance(minutes=2)
        self.tracker.force_close()
        self.assertEqual(len(self.store.today_rows(self.clock.now)), 0, "熄屏/锁屏不应记时")

    def test_browser_host_change_splits_segment(self) -> None:
        self.x11.window = self._window(
            "google-chrome", "Google Chrome", "Video - YouTube - Google Chrome"
        )
        self.tracker.tick()
        self.clock.advance(minutes=3)
        self.x11.window = self._window(
            "google-chrome", "Google Chrome", "Repo · GitHub - Google Chrome"
        )
        self.tracker.tick()
        self.clock.advance(minutes=2)
        self.tracker.force_close()

        rows = self.store.today_rows(self.clock.now)
        hosts = sorted((r.host or "") for r in rows)
        self.assertEqual(hosts, ["github.com", "youtube.com"], "浏览器切标签应断成两段")

    def test_capture_titles_off_by_default(self) -> None:
        self.x11.window = self._window("code", "VS Code", "secret.txt — VS Code")
        self.tracker.tick()
        self.clock.advance(minutes=1)
        self.tracker.force_close()
        rows = self.store.today_rows(self.clock.now)
        self.assertIsNone(rows[0].title, "未开启采集时不应保存窗口标题")

    def test_capture_titles_when_enabled(self) -> None:
        self.settings.capture_titles = True
        self.x11.window = self._window("code", "VS Code", "secret.txt — VS Code")
        self.tracker.tick()
        self.clock.advance(minutes=1)
        self.tracker.force_close()
        rows = self.store.today_rows(self.clock.now)
        self.assertEqual(rows[0].title, "secret.txt — VS Code")

    def test_today_seconds_includes_open_segment(self) -> None:
        self.x11.window = self._window("code", "VS Code")
        self.tracker.tick()
        self.clock.advance(seconds=90)
        self.assertAlmostEqual(self.tracker.today_seconds(), 90, delta=2)

    def test_snapshot_fields(self) -> None:
        self.x11.window = self._window("code", "VS Code")
        self.tracker.tick()
        snap = self.tracker.snapshot()
        self.assertEqual(snap["current_app"], "VS Code")
        self.assertFalse(snap["paused"])
        self.assertIn("today_seconds", snap)


class X11SmokeTests(unittest.TestCase):
    """真实 X11 冒烟测试（无显示器时自动跳过）。"""

    def setUp(self) -> None:
        import os

        if not os.environ.get("DISPLAY"):
            self.skipTest("无 DISPLAY，跳过真实 X11 冒烟")

    def test_active_window_or_graceful_none(self) -> None:
        from timebook.platform.x11 import X11Display

        display = X11Display()
        try:
            window = display.active_window()
            if window is not None:
                self.assertTrue(window.app_id, "前台窗口应有 app_id")
            self.assertGreaterEqual(display.idle_seconds(), 0.0)
        finally:
            display.close()


if __name__ == "__main__":
    unittest.main()
