"""20 秒全屏微休息遮罩。

对应 macOS 版 ``BreakOverlay.swift``（NSPanel · screenSaver 层）：深色渐变
背景 + 中央倒计时环 + 护眼引导文案 + 跳过。使用所在显示器的逻辑尺寸，
窗口映射后再次请求全屏；支持键盘跳过与 Escape 关闭。
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
        self._fullscreen_source: int | None = None

        self.set_decorated(False)
        self.set_resizable(True)
        self.set_can_focus(True)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key)
        self.add_controller(controller)
        # Gtk.Window otherwise starts at its content's natural size; some
        # window managers ignore fullscreen requests made before mapping.
        display = self.get_display()
        active = app.get_active_window()
        surface = active.get_surface() if active and active is not self else None
        self._monitor = display.get_monitor_at_surface(surface) if surface else None
        if self._monitor is None:
            self._monitor = display.get_monitors().get_item(0)
        if self._monitor is not None:
            geometry = self._monitor.get_geometry()
            self.set_default_size(geometry.width, geometry.height)
        self.connect("map", self._on_map)
        self.add_css_class("tb-overlay")
        W.translated(self, title=("微休息", "Micro break"))

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("tb-overlay")
        root.set_valign(Gtk.Align.CENTER)
        root.set_halign(Gtk.Align.CENTER)

        self.ring = W.RingProgress(240, 12)
        root.append(self.ring)

        title = W.label(
            ("让眼睛休息一下", "Give your eyes a break"),
            "tb-overlay-title",
            xalign=0.5,
        )
        title.set_halign(Gtk.Align.CENTER)
        title.set_margin_top(18)
        root.append(title)

        hints = (
            "看向 6 米外 · 多眨眼 · 深呼吸 · 活动肩颈",
            "Look 6 m away · Blink · Breathe deep · Roll your shoulders",
        )
        body = W.label(hints, "tb-overlay-body", xalign=0.5)
        body.set_halign(Gtk.Align.CENTER)
        body.set_margin_top(6)
        body.set_wrap(True)
        root.append(body)

        skip = W.translated(Gtk.Button(), label=("跳过", "Skip"))
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

    def _on_map(self, *_args) -> None:
        if self._fullscreen_source is None:
            self._fullscreen_source = GLib.idle_add(self._enter_fullscreen)

    def _enter_fullscreen(self) -> bool:
        self._fullscreen_source = None
        if self._monitor is not None:
            self.fullscreen_on_monitor(self._monitor)
        else:
            self.fullscreen()
        return False

    def _on_key(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def refresh_language(self) -> None:
        W.refresh_translations(self)
        self._render()

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
        if self._fullscreen_source is not None:
            GLib.source_remove(self._fullscreen_source)
            self._fullscreen_source = None
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
