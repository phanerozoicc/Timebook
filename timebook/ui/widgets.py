"""可复用界面组件：卡片、统计卡、胶囊条、环形进度、柱状图、环形图、热力图。

对应 macOS 版的 ``StatCard`` / ``BarRow`` / ``RingProgress`` / ``SectionHeader``
/ ``LevelBadge`` / ``EmptyState``。图表全部用 cairo 直接绘制（GTK4 DrawingArea），
文字走 Pango，保证中文有正确的字体回退。
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gtk, Pango, PangoCairo  # noqa: E402

from ..core.l10n import T, month_label
from ..core import models  # noqa: E402
from ..core.brain_level import BrainLevel  # noqa: E402
from ..core.heatmap import HeatGrid, color_for, level_hint, weekday_label  # noqa: E402
from .theme import (  # noqa: E402
    BRAND,
    GAP,
    GAP_SMALL,
    LEVEL_COLORS,
    RADIUS,
    css_hex,
    css_rgba,
    hex_to_rgb,
    mix,
)


# --------------------------------------------------------------------------- #
# Pango 文本绘制
# --------------------------------------------------------------------------- #


def draw_text(
    cr,
    text: str,
    x: float,
    y: float,
    size: float = 12,
    color: tuple[float, float, float, float] = (1, 1, 1, 0.9),
    weight: Pango.Weight = Pango.Weight.NORMAL,
    align: str = "left",
    width: float | None = None,
    desc: str | None = None,
) -> tuple[int, int]:
    """在 cairo 上画一段文字（用 Pango，中文有字体回退）。返回像素宽高。"""
    layout = PangoCairo.create_layout(cr)
    font = Pango.FontDescription()
    font.set_family("Sans")
    font.set_absolute_size(int(round(size * Pango.SCALE)))
    font.set_weight(weight)
    layout.set_font_description(font)
    if desc:
        layout.set_text(desc, -1)
    else:
        layout.set_text(text, -1)
    layout.set_ellipsize(Pango.EllipsizeMode.END)
    if width:
        layout.set_width(int(width * Pango.SCALE))
    w, h = layout.get_pixel_size()
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    cr.set_source_rgba(*color)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)
    return w, h


def rgba(color: int, alpha: float = 1.0) -> tuple[float, float, float, float]:
    r, g, b = hex_to_rgb(color)
    return (r, g, b, alpha)


def foreground(widget, alpha: float = 1.0):
    color = widget.get_style_context().get_color()
    return (color.red, color.green, color.blue, color.alpha * alpha)


def accessible(widget, text: str) -> None:
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text])


def rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def fill_rounded(cr, x, y, w, h, r, color: int, alpha: float = 1.0) -> None:
    rounded_rect(cr, x, y, w, h, r)
    cr.set_source_rgba(*rgba(color, alpha))
    cr.fill()


def gradient_rounded(cr, x, y, w, h, r, color_a: int, color_b: int, alpha=1.0) -> None:
    rounded_rect(cr, x, y, w, h, r)
    grad = __import__("cairo").LinearGradient(x, y, x + w, y + h)
    ra = rgba(color_a, alpha)
    rb = rgba(color_b, alpha)
    grad.add_color_stop_rgba(0.0, *ra)
    grad.add_color_stop_rgba(1.0, *rb)
    cr.set_source(grad)
    cr.fill()


# --------------------------------------------------------------------------- #
# 容器
# --------------------------------------------------------------------------- #


def card(spacing: int = GAP_SMALL, padding: int | None = None) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.add_css_class("tb-card")
    if padding is not None:
        box.set_margin_top(0)
    return box


def translated(widget, **messages):
    """Bind explicitly translated properties without recreating controls or state."""
    bindings = getattr(widget, "_translations", {})
    bindings.update(messages)
    widget._translations = bindings
    for prop, message in messages.items():
        value = T(*message)
        if prop == "accessible":
            accessible(widget, value)
        else:
            getattr(widget, "set_" + prop)(value)
    return widget


def translated_model(widget, messages):
    widget._translated_model = messages
    widget.set_model(Gtk.StringList.new([T(*message) for message in messages]))


# GTK 内置控件文案（DropDown 弹层搜索框、空态占位、Entry 清除按钮提示）
# 由 GTK 按进程 locale 翻译、不走 W.translated；语言切换后按精确文本重翻，
# 进程 locale 的同步见 core/l10n.py 的 _apply_process_locale。
_STOCK_TEXTS = {
    "搜索": "Search",
    "搜索…": "Search…",
    "（无）": "(None)",
    "清除条目": "Clear Entry",
}


def _stock_translation(text: str) -> str | None:
    for zh, en in _STOCK_TEXTS.items():
        if text == zh or text == en:
            return T(zh, en)
    return None


def _retranslate_stock(widget) -> None:
    target = _stock_translation(widget.get_tooltip_text() or "")
    if target is not None:
        widget.set_tooltip_text(target)
    placeholder = getattr(widget, "get_placeholder_text", None)
    if placeholder is not None:
        current = placeholder()
        if current:
            target = _stock_translation(current)
            if target is not None:
                widget.set_placeholder_text(target)
    if isinstance(widget, Gtk.Label):
        target = _stock_translation(widget.get_label())
        if target is not None:
            widget.set_label(target)


def refresh_translations(widget):
    """Update explicit bindings, including hidden pages; never translate user data."""
    if getattr(widget, "_translations", None):
        translated(widget, **widget._translations)
    if getattr(widget, "_translated_model", None):
        selected = widget.get_selected()
        translated_model(widget, widget._translated_model)
        widget.set_selected(selected)
    for toast in getattr(widget, "_translated_toasts", []):
        translated(toast, **toast._translations)
    _retranslate_stock(widget)
    child = widget.get_first_child()
    while child is not None:
        refresh_translations(child)
        child = child.get_next_sibling()


def add_translated_toast(overlay, toast):
    active = getattr(overlay, "_translated_toasts", [])
    overlay._translated_toasts = active
    active.append(toast)
    toast.connect("dismissed", lambda item: active.remove(item) if item in active else None)
    overlay.add_toast(toast)


def label(
    text: str = "",
    css: str | None = None,
    xalign: float = 0.0,
    wrap: bool = False,
    ellipsize: Pango.EllipsizeMode | None = None,
) -> Gtk.Label:
    widget = Gtk.Label()
    if isinstance(text, tuple):
        translated(widget, label=text)
    else:
        widget.set_label(text)
    widget.set_xalign(xalign)
    if wrap:
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize is not None:
        widget.set_ellipsize(ellipsize)
        widget.set_max_width_chars(12)
    if css:
        for name in css.split():
            widget.add_css_class(name)
    return widget


def icon(name: str, size: int = 16, css: str | None = None) -> Gtk.Image:
    widget = Gtk.Image.new_from_icon_name(name)
    widget.set_pixel_size(size)
    if css:
        widget.add_css_class(css)
    return widget


def color_dot(value: int, size: int = 9) -> Gtk.Widget:
    """彩色小圆点（图例用）。"""

    def _draw(_area, cr, w, h):
        cr.set_source_rgba(*rgba(value, 1.0))
        cr.arc(w / 2, h / 2, min(w, h) / 2 - 0.5, 0, 2 * math.pi)
        cr.fill()

    area = Gtk.DrawingArea()
    area.set_size_request(size, size)
    area.set_valign(Gtk.Align.CENTER)
    area.set_draw_func(_draw)
    return area


def hbox(spacing: int = GAP_SMALL) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def vbox(spacing: int = GAP_SMALL) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def spacer(vertical: bool = False) -> Gtk.Widget:
    box = Gtk.Box()
    box.set_vexpand(vertical)
    box.set_hexpand(not vertical)
    return box


def separator() -> Gtk.Widget:
    line = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    line.add_css_class("tb-sep")
    return line


# --------------------------------------------------------------------------- #
# 组件
# --------------------------------------------------------------------------- #


class SectionHeader(Gtk.Box):
    """符号 + 标题 + 尾注（对应 Swift ``SectionHeader``）。"""

    def __init__(self, icon_name: str | None = None, title: str = "", trailing: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if icon_name:
            self.append(icon(icon_name, 14, "tb-muted"))
        self._title = label(title, "tb-section")
        self.append(self._title)
        self.append(spacer())
        self._trailing = label(trailing, "tb-caption")
        self.append(self._trailing)

    def set_title(self, text: str) -> None:
        self._title.set_text(text)

    def set_trailing(self, text: str) -> None:
        self._trailing.set_text(text)


class StatCard(Gtk.Box):
    """图标 + 标题 + 彩色数值 + 可选副标题（对应 Swift ``StatCard``）。"""

    def __init__(
        self,
        icon_name: str,
        title: str,
        value: str = "—",
        color: int = BRAND,
        subtitle: str = "",
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("tb-card")
        self.add_css_class("tb-stat-card")
        self.set_size_request(90, -1)
        head = hbox(6)
        head.append(icon(icon_name, 13, "tb-muted"))
        self._title = label(title, "tb-caption", ellipsize=Pango.EllipsizeMode.END)
        head.append(self._title)
        self.append(head)

        self._color = color
        self._value = label(value, "tb-card-value tb-mono")
        self._value.set_ellipsize(Pango.EllipsizeMode.END)
        self.append(self._value)
        self._subtitle = label(subtitle, "tb-caption")
        if subtitle:
            self.append(self._subtitle)
        # Neutral values keep semantic colors in the charts, where they carry meaning.

    def _apply_color(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            f"label {{ color: {css_hex(self._color)}; }}".encode()
        )
        self._value.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def set_value(self, text: str) -> None:
        self._value.set_text(text)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.set_text(text)


class LevelBadge(Gtk.Box):
    """等级圆形徽章（L 级别数字，等级色渐变）。"""

    def __init__(self, level: BrainLevel | None = None, size: int = 52) -> None:
        super().__init__()
        self._level = level
        self._size = size
        self.set_size_request(size, size)
        self.set_hexpand(False)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.CENTER)
        self._area = Gtk.DrawingArea()
        self._area.set_content_width(size)
        self._area.set_content_height(size)
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self.append(self._area)

        def _draw(_area, cr, w, h):
            if self._level is None:
                return
            base = LEVEL_COLORS.get(self._level.level, BRAND)
            fill_rounded(cr, 0, 0, w, h, min(w, h) / 2, base, 0.18)
            draw_text(
                cr, str(self._level.level), w / 2, h / 2 - 11, size=18,
                color=foreground(self), weight=Pango.Weight.BOLD, align="center",
            )

        self._area.set_draw_func(_draw)

    def set_level(self, level: BrainLevel) -> None:
        self._level = level
        accessible(self, f"L{level.level} {level.name}")
        self._area.queue_draw()


class CapsuleBar(Gtk.Box):
    """胶囊进度条：轨道 + 进度 + 可选品牌渐变。"""

    def __init__(self, fraction: float = 0.0, color: int = BRAND, height: int = 10) -> None:
        super().__init__()
        self._fraction = max(0.0, min(1.0, fraction))
        self._color = color
        self._height = height
        self.set_size_request(-1, height)
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.CENTER)
        self._area = Gtk.DrawingArea()
        self._area.set_content_height(height)
        self._area.set_hexpand(True)
        self._area.set_draw_func(self._draw)
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self.append(self._area)

    def _draw(self, _area, cr, w, h):
        r = h / 2
        fill_rounded(cr, 0, 0, w, h, r, 0x808080, 0.16)
        if self._fraction > 0:
            fw = max(h, w * self._fraction)
            fill_rounded(cr, 0, 0, min(w, fw), h, r, self._color)

    def set_fraction(self, fraction: float, color: int | None = None) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        if color is not None:
            self._color = color
        self._area.queue_draw()


class BarRow(Gtk.Box):
    """点/标签/胶囊条/紧凑时长（对应 Swift ``BarRow``，标签列宽 170）。"""

    def __init__(
        self,
        name: str,
        seconds: float,
        max_seconds: float,
        label_width: int = 170,
        color: int = BRAND,
        leading: Gtk.Widget | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.add_css_class("tb-rows")
        name_box = hbox(7)
        name_box.set_size_request(label_width, -1)
        if leading is not None:
            name_box.append(leading)
        self._name = label(name, ellipsize=Pango.EllipsizeMode.END)
        self._name.set_hexpand(True)
        name_box.append(self._name)
        self.append(name_box)

        fraction = (seconds / max_seconds) if max_seconds > 0 else 0.0
        self._bar = CapsuleBar(fraction, color)
        self.append(self._bar)

        self._value = label(models.fmt_duration(seconds, compact=True), "tb-mono tb-caption")
        self._value.set_xalign(1.0)
        self._value.set_size_request(74, -1)
        self.append(self._value)

    def update(self, name: str, seconds: float, max_seconds: float) -> None:
        self._name.set_text(name)
        self._bar.set_fraction(seconds / max_seconds if max_seconds > 0 else 0.0)
        self._value.set_text(models.fmt_duration(seconds, compact=True))


class RingProgress(Gtk.Box):
    """渐变环 + 中心文字（对应 Swift ``RingProgress``）。"""

    def __init__(self, size: int = 190, line_width: int = 10) -> None:
        super().__init__()
        self._fraction = 0.0
        self._color = BRAND
        self._big = "00:00"
        self._small = ""
        self._size = size
        self._line = line_width
        self.set_size_request(size, size)
        self.set_hexpand(False)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self._area = Gtk.DrawingArea()
        self._area.set_content_width(size)
        self._area.set_content_height(size)
        self._area.set_draw_func(self._draw)
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        overlay = Gtk.Overlay()
        overlay.set_child(self._area)
        self._text_box = vbox(4)
        self._text_box.set_valign(Gtk.Align.CENTER)
        self._text_box.set_halign(Gtk.Align.CENTER)
        self._value_label = label("", "tb-timer tb-mono", xalign=0.5)
        self._detail_label = label("", "tb-caption", xalign=0.5)
        self._text_box.append(self._value_label)
        self._text_box.append(self._detail_label)
        overlay.add_overlay(self._text_box)
        self.append(overlay)

    def _draw(self, _area, cr, w, h):
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - self._line / 2 - 6
        track = 0.14
        cr.set_line_width(self._line)
        cr.set_line_cap(__import__("cairo").LINE_CAP_ROUND)
        cr.set_source_rgba(0.6, 0.6, 0.65, track * 0.6)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()

        if self._fraction > 0.001:
            start = -math.pi / 2
            end = start + 2 * math.pi * self._fraction
            grad = __import__("cairo").LinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
            grad.add_color_stop_rgba(0.0, *rgba(mix(self._color, 0xFFFFFF, 0.12), 1.0))
            grad.add_color_stop_rgba(1.0, *rgba(mix(self._color, 0x000000, 0.12), 1.0))
            cr.set_source(grad)
            cr.arc(cx, cy, radius, start, end)
            cr.stroke()


    def update(self, fraction: float, color: int, big: str, small: str = "") -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._color = color
        self._big = big
        self._small = small
        self._value_label.set_text(big)
        self._detail_label.set_text(small)
        self._area.queue_draw()


class BarChart(Gtk.Box):
    """每日趋势柱状图（右上角数值 + 底部日期标签）。"""

    def __init__(self, height: int = 170) -> None:
        super().__init__()
        self._points: list[tuple[str, float]] = []
        self._color = BRAND
        self.set_size_request(-1, height)
        self.set_hexpand(True)
        self._area = Gtk.DrawingArea()
        self._area.set_content_height(height)
        self._area.set_hexpand(True)
        self._area.set_draw_func(self._draw)
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self.append(self._area)

    def set_points(self, points: Sequence[tuple[str, float]], color: int | None = None) -> None:
        self._points = list(points)
        self.set_tooltip_text("\n".join(f"{name}: {models.fmt_duration(value)}" for name, value in self._points))
        accessible(self, self.get_tooltip_text() or "—")
        if color is not None:
            self._color = color
        self._area.queue_draw()

    def _draw(self, _area, cr, w, h):
        if not self._points:
            draw_text(cr, "—", w / 2, h / 2 - 8, size=13, color=foreground(self, 0.75), align="center")
            return
        pad_bottom, pad_top = 20, 18
        plot_h = h - pad_bottom - pad_top
        peak = max((v for _, v in self._points), default=0.0)
        peak = max(peak, 60.0)
        n = len(self._points)
        inset = 20
        slot = max(1, w - inset * 2) / n
        bar_w = min(30.0, slot * 0.52)

        # 基线
        cr.set_source_rgba(*foreground(self, 0.12))
        cr.set_line_width(1)
        cr.move_to(0, pad_top + plot_h + 0.5)
        cr.line_to(w, pad_top + plot_h + 0.5)
        cr.stroke()

        for index, (name, value) in enumerate(self._points):
            cx = inset + slot * index + slot / 2
            bh = max(2.0, plot_h * (value / peak)) if value > 0 else 2.0
            x = cx - bar_w / 2
            y = pad_top + plot_h - bh
            if value > 0:
                gradient_rounded(
                    cr, x, y, bar_w, bh, min(6, bar_w / 2),
                    self._color, mix(self._color, 0xFFFFFF, 0.22),
                )
                if n <= 14 or value == peak:
                    draw_text(
                        cr, models.fmt_duration(value, compact=True), cx, y - 16,
                        size=11, color=foreground(self, 0.75), align="center",
                    )
            else:
                fill_rounded(cr, x, y, bar_w, bh, 2, 0x808080, 0.18)
            if n <= 14 or index % 5 == 0 or index == n - 1:
                draw_text(
                    cr, name, cx, pad_top + plot_h + 5, size=11,
                    color=foreground(self, 0.75), align="center",
                )


class DonutChart(Gtk.Box):
    """分类环形图 + 中心合计。"""

    def __init__(self, size: int = 172, line_width: int = 18) -> None:
        super().__init__()
        self._slices: list[tuple[str, float, int]] = []
        self._center = ""
        self._size = size
        self._line = line_width
        self.set_size_request(size, size)
        self.set_hexpand(False)
        self.set_valign(Gtk.Align.CENTER)
        self._area = Gtk.DrawingArea()
        self._area.set_content_width(size)
        self._area.set_content_height(size)
        self._area.set_draw_func(self._draw)
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        overlay = Gtk.Overlay()
        overlay.set_child(self._area)
        self._text_box = vbox(4)
        self._text_box.set_valign(Gtk.Align.CENTER)
        self._text_box.set_halign(Gtk.Align.CENTER)
        self._value_label = label("", "tb-chart-total tb-mono", xalign=0.5)
        self._detail_label = label("", "tb-caption", xalign=0.5)
        self._text_box.append(self._value_label)
        self._text_box.append(self._detail_label)
        overlay.add_overlay(self._text_box)
        self.append(overlay)

    def set_slices(self, slices: Iterable[tuple[str, float, int]], center: str = "") -> None:
        self._slices = [s for s in slices if s[1] > 0]
        self._center = center
        self._value_label.set_text(center)
        self._area.queue_draw()

    def _draw(self, _area, cr, w, h):
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - self._line / 2 - 2
        cr.set_line_width(self._line)
        total = sum(v for _, v, _ in self._slices)
        if total <= 0:
            cr.set_source_rgba(*foreground(self, 0.12))
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.stroke()
        else:
            start = -math.pi / 2
            for _name, value, color in self._slices:
                span = 2 * math.pi * (value / total)
                gap = 0.02 if span > 0.05 else 0.0
                cr.set_source_rgba(*rgba(color, 0.95))
                cr.arc(cx, cy, radius, start + gap / 2, start + span - gap / 2)
                cr.stroke()
                start += span


class HeatmapWidget(Gtk.Box):
    """12 周热力图（GitHub 贡献格样式，暖色 7 档）。"""

    CELL = 13
    GAP = 3
    LEFT = 34
    TOP = 16

    def __init__(self) -> None:
        super().__init__()
        self._grid = HeatGrid.empty()
        cols = 12
        self.set_size_request(
            self.LEFT + cols * (self.CELL + self.GAP),
            self.TOP + 7 * (self.CELL + self.GAP) + 22,
        )
        self._area = Gtk.DrawingArea()
        self._area.set_draw_func(self._draw)
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self.append(self._area)

    def set_grid(self, grid: HeatGrid) -> None:
        self._grid = grid
        self._area.queue_draw()
        self.set_tooltip_text(
            T(f"{len(grid.columns)} 周 · 活跃 {grid.active_days} 天 · 合计 {models.fmt_duration(grid.total_seconds)}",
              f"{len(grid.columns)} weeks · {grid.active_days} active days · Total {models.fmt_duration(grid.total_seconds)}")
        )

    def _draw(self, _area, cr, w, h):
        cell, gap = self.CELL, self.GAP
        # 星期标签（隔行显示，避免拥挤）
        for row in range(7):
            if row in (0, 2, 4, 6):
                draw_text(
                    cr, weekday_label(row), 0, self.TOP + row * (cell + gap) + 2,
                    size=8.5, color=foreground(self, 0.75),
                )
        # 月份标签：每列第一天是 1 号时标出
        last_month = None
        for index, column in enumerate(self._grid.columns):
            first = column.cells[0].day
            if first.month != last_month and first.day <= 7:
                last_month = first.month
                draw_text(
                    cr, month_label(first.month), self.LEFT + index * (cell + gap), 0,
                    size=8.5, color=foreground(self, 0.75),
                )
        # 格子
        for c_index, column in enumerate(self._grid.columns):
            for r_index, day_cell in enumerate(column.cells):
                x = self.LEFT + c_index * (cell + gap)
                y = self.TOP + r_index * (cell + gap)
                level = day_cell.level
                if day_cell.seconds <= 0:
                    fill_rounded(cr, x, y, cell, cell, 3, 0x808080, 0.15)
                else:
                    fill_rounded(cr, x, y, cell, cell, 3, color_value(level), 1.0)

        # 图例
        legend_y = self.TOP + 7 * (cell + gap) + 8
        draw_text(cr, T("少", "Less"), 0, legend_y, size=8.5, color=foreground(self, 0.75))
        for level in range(7):
            x = 34 + level * 14
            fill_rounded(cr, x, legend_y - 1, 10, 10, 2, color_value(level), 1.0)
        draw_text(cr, T("多", "More"), 34 + 7 * 14 + 4, legend_y, size=8.5, color=foreground(self, 0.75))


def color_value(level: int) -> int:
    from .theme import HEAT

    return HEAT[min(max(0, level), len(HEAT) - 1)]


class EmptyState(Gtk.Box):
    """空数据占位（对应 Swift ``EmptyState``）。"""

    def __init__(self, icon_name: str = "dialog-information-symbolic", text: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.set_margin_top(18)
        self.set_margin_bottom(18)
        image = icon(icon_name, 28, "tb-muted")
        image.set_opacity(0.5)
        self.append(image)
        self._label = label(text, "tb-caption", xalign=0.5, wrap=True)
        self._label.set_justify(Gtk.Justification.CENTER)
        self.append(self._label)

    def set_text(self, text: str) -> None:
        self._label.set_text(text)


class Pill(Gtk.Label):
    def __init__(self, text: str = "", color: int | None = None) -> None:
        super().__init__(label=text)
        self.add_css_class("tb-pill")
        self.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.set_max_width_chars(24)
        self.set_tooltip_text(text)
        if color is not None:
            provider = Gtk.CssProvider()
            provider.load_from_data(
                f"label {{ background: {css_rgba(color, 0.12)}; }}".encode()
            )
            self.get_style_context().add_provider(
                provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )


def set_label_color(widget: Gtk.Label, color: int, alpha: float = 1.0) -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(f"label {{ color: {css_rgba(color, alpha)}; }}".encode())
    widget.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
