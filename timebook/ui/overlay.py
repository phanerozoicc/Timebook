"""20 秒全屏微休息遮罩。

对应 macOS 版 ``BreakOverlay.swift``（NSPanel · screenSaver 层）：深色渐变
背景 + 中央倒计时环 + 护眼引导文案 + 跳过。Linux 版用无边框全屏
``Gtk.Window``（``fullscreen``），不抢键盘焦点（``set_can_focus(False)``）。
"""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..core.l10n import T  # noqa: E402
from . import widgets as W  # noqa: E402
from .theme import GAP, WELL_GREEN  # noqa: E402

DURATION = 20


class BreakOverlay(Gtk.Window):
    def __init__(self, app, on_done=None, duration: int = DURATION) -> None:
        super().__init__(application=app)
        self._on_done = on_done
        self._remaining = duration
        self._duration = duration
        self._timer_id: int | None = None

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_can_focus(False)
        self.fullscreen()
        self.add_css_class("tb-overlay")
        self.set_title(T("微休息", "Micro break"))

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("tb-overlay")
        root.set_valign(Gtk.Align.CENTER)
        root.set_halign(Gtk.Align.CENTER)

        self.ring = W.RingProgress(240, 12)
        root.append(self.ring)

        title = W.label(
            T("让眼睛休息一下", "Give your eyes a break"),
            "tb-overlay-title",
            xalign=0.5,
        )
        title.set_halign(Gtk.Align.CENTER)
        title.set_margin_top(18)
        root.append(title)

        hints = T(
            "看向 6 米外 · 多眨眼 · 深呼吸 · 活动肩颈",
            "Look 6 m away · Blink · Breathe deep · Roll your shoulders",
        )
        body = W.label(hints, "tb-overlay-body", xalign=0.5)
        body.set_halign(Gtk.Align.CENTER)
        body.set_margin_top(6)
        body.set_wrap(True)
        root.append(body)

        skip = Gtk.Button(label=T("跳过", "Skip"))
        skip.add_css_class("tb-ghost")
        skip.set_halign(Gtk.Align.CENTER)
        skip.set_margin_top(26)
        skip.connect("clicked", lambda _b: self.close())
        root.append(skip)

        self.set_child(root)
        self.connect("close-request", self._on_close)
        self._timer_id = GLib.timeout_add(1000, self._tick)
        self._render()

    # ------------------------------------------------------------------ #

    def _render(self) -> None:
        fraction = 1.0 - (self._remaining / self._duration if self._duration else 0)
        self.ring.update(
            max(0.0, min(1.0, fraction)),
            WELL_GREEN,
            f"{self._remaining}",
            T("秒", "sec"),
        )

    def _tick(self) -> bool:
        self._remaining -= 1
        if self._remaining <= 0:
            self.close()
            return False
        self._render()
        return True

    def _on_close(self, *_args) -> bool:
        if self._timer_id is not None:
            try:
                GLib.source_remove(self._timer_id)
            except Exception:  # pragma: no cover
                pass
            self._timer_id = None
        if self._on_done:
            callback, self._on_done = self._on_done, None
            callback()
        self.destroy()
        return True
