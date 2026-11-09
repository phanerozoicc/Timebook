"""页面基类：统一滚动容器、间距与刷新协议。"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..theme import GAP  # noqa: E402


class Page(Gtk.ScrolledWindow):
    """所有主窗口页面的基类：一个可滚动的垂直内容区。"""

    def __init__(self, ctx, name: str) -> None:
        super().__init__()
        self._ctx = ctx
        self.name = name
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_hexpand(True)
        self.set_vexpand(True)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=GAP)
        self.body.set_margin_top(18)
        self.body.set_margin_bottom(24)
        self.body.set_margin_start(22)
        self.body.set_margin_end(22)
        self.set_child(self.body)

    def refresh(self, force: bool = False) -> None:  # pragma: no cover - 子类实现
        """由 App 定时驱动（约 2 秒一次）。``force`` 忽略增量缓存。"""
