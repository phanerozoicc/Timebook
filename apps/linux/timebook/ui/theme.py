"""设计系统：颜色 token、CSS、8pt 网格与字体阶。

移植 macOS 版 ``Sources/Theme.swift`` 的 v4 视觉规范（见 ``docs/ui-spec.md``
第 0 节）：品牌番茄橘 + 卡片三层质感 + 侧边栏导航 + 数字等宽。
Linux 版用 GTK CSS 表达同一套 token；语义色（等级/分类/热力）直接取自
``core`` 层，保证图表与文案一致。
"""

from __future__ import annotations

from ..core.brain_level import ALL as LEVELS
from ..core.categories import ALL as CATEGORIES
from ..core.heatmap import PALETTE as HEAT_PALETTE

# --------------------------------------------------------------------------- #
# 品牌 token（与 Theme.swift 一一对应）
# --------------------------------------------------------------------------- #

BRAND = 0xF0663F        # 番茄橘：选中态/主按钮/趋势柱/大数字
BRAND_SOFT = 0xFF9466   # 渐变亮端
BRAND_DEEP = 0xD14A28   # 渐变暗端
WELL_GREEN = 0x53B987   # 健康
CALM_BLUE = 0x5B8DEF    # 专注
WATER = 0x4CC3E0        # 喝水
ALERT_RED = 0xE5484D    # 限额超限
AMBER = 0xF5A524

PAD = 24
GAP = 16
GAP_SMALL = 10
RADIUS = 14

#: 分类 9 色（与 Categories.swift 一致）
CATEGORY_COLORS = {c.id: c.hex_color for c in CATEGORIES}
#: 疲劳等级 10 色
LEVEL_COLORS = {level.level: level.hex_color for level in LEVELS}
#: 热力图 7 档
HEAT = HEAT_PALETTE

#: 番茄环按阶段着色
PHASE_COLORS = {
    "work": BRAND,
    "work-ready": BRAND,
    "short": WELL_GREEN,
    "short-ready": WELL_GREEN,
    "long": CALM_BLUE,
    "long-ready": CALM_BLUE,
    "idle": 0x8A8F98,
}


def hex_to_rgb(value: int) -> tuple[float, float, float]:
    return (
        ((value >> 16) & 0xFF) / 255.0,
        ((value >> 8) & 0xFF) / 255.0,
        (value & 0xFF) / 255.0,
    )


def css_rgba(value: int, alpha: float = 1.0) -> str:
    r, g, b = hex_to_rgb(value)
    return f"rgba({int(r * 255)},{int(g * 255)},{int(b * 255)},{alpha:.3f})"


def css_hex(value: int) -> str:
    return f"#{value:06X}"


def mix(a: int, b: int, t: float) -> int:
    """两色线性插值（t=0 → a，t=1 → b）。"""
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    r = int(round((ar + (br - ar) * t) * 255))
    g = int(round((ag + (bg - ag) * t) * 255))
    bl = int(round((ab + (bb - ab) * t) * 255))
    return (r << 16) | (g << 8) | bl


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #

CSS = f"""
window.tb-window {{ background: @window_bg_color; }}
.tb-sidebar {{
    background: alpha(@window_fg_color, 0.025);
    border-right: 1px solid alpha(@window_fg_color, 0.08);
}}
.tb-brand-name {{ font-size: 19px; font-weight: 700; }}
.tb-brand-sub {{ font-size: 12px; color: alpha(@window_fg_color, 0.72); }}
.tb-nav-row {{ border-radius: 10px; padding: 4px 6px; margin: 2px 8px; }}
.tb-nav-row:hover {{ background: alpha(@window_fg_color, 0.05); }}
.tb-nav-row:selected {{ background: alpha(@tb_accent, 0.12); }}
.tb-nav-row:selected label, .tb-nav-row:selected image {{ color: @tb_accent; font-weight: 600; }}
.tb-nav-label {{ font-size: 14px; }}
.tb-mini-card {{
    background: @card_bg_color;
    border: 1px solid alpha(@window_fg_color, 0.08);
    border-radius: 12px; padding: 14px;
}}
.tb-mini-value {{ font-size: 24px; font-weight: 600; }}
.tb-card {{
    background: @card_bg_color;
    border: 1px solid alpha(@window_fg_color, 0.08);
    border-radius: {RADIUS}px; padding: 18px;
}}
.tb-stat-card {{ padding: 14px; }}
.tb-hero {{
    background: @card_bg_color;
    border: 1px solid alpha(@tb_accent, 0.22);
    border-radius: {RADIUS}px; padding: 24px;
}}
.tb-hero-number {{ font-size: 44px; font-weight: 600; letter-spacing: -1px; }}
.tb-card-value {{ font-size: 22px; font-weight: 600; }}
.tb-page-title {{ font-size: 16px; font-weight: 600; }}
.tb-section {{ font-size: 14px; font-weight: 600; }}
.tb-caption, .tb-muted {{ color: alpha(@window_fg_color, 0.72); }}
.tb-caption {{ font-size: 12px; }}
.tb-mono {{ font-feature-settings: "tnum" 1; }}
.tb-timer {{ font-size: 38px; font-weight: 600; }}
.tb-chart-total {{ font-size: 22px; font-weight: 600; }}
.tb-pill {{ border-radius: 8px; padding: 4px 10px; font-size: 12px; background: alpha(@window_fg_color, 0.06); }}
.tb-badge {{ border-radius: 8px; padding: 3px 9px; font-size: 12px; font-weight: 600; }}
.tb-primary {{
    background: #BC4325; color: #FFFFFF; border-radius: 10px;
    font-weight: 600; padding: 8px 20px; min-height: 28px; border: none;
}}
.tb-primary:hover {{ background: #A83C21; }}
.tb-primary:active {{ background: #92321B; }}
.tb-primary:disabled {{ background: alpha(@window_fg_color, 0.10); color: alpha(@window_fg_color, 0.4); }}
.tb-ghost {{
    background: alpha(@window_fg_color, 0.04);
    border: 1px solid alpha(@window_fg_color, 0.12);
    border-radius: 10px; padding: 7px 12px; min-height: 28px; font-weight: 500;
}}
.tb-ghost:hover {{ background: alpha(@window_fg_color, 0.08); }}
.tb-ghost:active {{ background: alpha(@window_fg_color, 0.12); }}
.tb-ghost:checked {{ background: alpha(@tb_accent, 0.12); color: @tb_accent; border-color: alpha(@tb_accent, 0.4); }}
.tb-ghost:disabled {{ color: alpha(@window_fg_color, 0.35); }}
.tb-icon-button {{ min-height: 40px; min-width: 40px; padding: 2px; }}
.tb-seg {{ background: alpha(@window_fg_color, 0.04); border-radius: 10px; padding: 3px; }}
.tb-seg > button {{ border-radius: 8px; padding: 7px 14px; min-height: 28px; background: transparent; border: none; }}
.tb-seg > button:checked {{ background: @card_bg_color; color: @tb_accent; font-weight: 600; }}
.tb-row {{ padding: 12px 4px; }}
.tb-row + .tb-row {{ border-top: 1px solid alpha(@window_fg_color, 0.07); }}
.tb-rows {{ min-height: 30px; }}
.tb-hour {{ border-radius: 8px; min-height: 44px; min-width: 44px; padding: 4px; background: alpha(@window_fg_color, 0.04); }}
.tb-hour:checked {{ background: alpha(@tb_accent, 0.15); color: @tb_accent; }}
.tb-hour.current {{ outline: 2px solid @tb_accent; outline-offset: -2px; }}
.tb-error {{ color: @error_color; font-size: 12px; }}
.tb-overlay {{ background: #18211E; color: #FFFFFF; }}
.tb-overlay .tb-timer {{ font-size: 64px; color: #FFFFFF; }}
.tb-overlay .tb-caption {{ color: alpha(#FFFFFF, 0.78); }}
.tb-overlay .tb-ghost {{ color: #FFFFFF; background: alpha(#FFFFFF, 0.1); border-color: alpha(#FFFFFF, 0.3); }}
.tb-overlay-title {{ font-size: 26px; font-weight: 600; color: #FFFFFF; }}
.tb-overlay-body {{ font-size: 15px; color: alpha(#FFFFFF, 0.78); }}
"""

_providers = {}


def install_css(display=None) -> None:
    """Install once per display; update semantic colors when the system theme changes."""
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    target = display or Gdk.Display.get_default()
    if target is None or target in _providers:
        return
    provider = Gtk.CssProvider()
    manager = Adw.StyleManager.get_for_display(target)

    def reload(*_args):
        accent = "#FF9D80" if manager.get_dark() else "#AC3D22"
        provider.load_from_data((f"@define-color tb_accent {accent};\n" + CSS).encode())

    reload()
    manager.connect("notify::dark", reload)
    Gtk.StyleContext.add_provider_for_display(target, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _providers[target] = provider


# 单色 SVG 图标（24×24，currentColor 由 GTK 着色）
ICONS: dict[str, str] = {
    "today": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 2a8 8 0 1 1 0 16 8 8 0 0 1 0-16Zm-.9 3.6h1.8v5.2l4 2.4-.9 1.5-4.9-2.9V7.6Z"/></svg>""",
    "focus": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 2a7 7 0 0 1 7 7h-2a5 5 0 0 0-5-5V5Zm0 4a3 3 0 1 1 0 6 3 3 0 0 1 0-6Z"/></svg>""",
    "stats": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M4 20V9h3v11H4Zm6.5 0V4h3v16h-3ZM17 20v-7h3v7h-3Z"/></svg>""",
    "timeline": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M7 3h2v2h6V3h2v2h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2V3Zm12 6H5v10h14V9Zm-9 3h2v5H9v-5h1Zm4 0h3v5h-3v-5Z"/></svg>""",
    "forfeit": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10A10 10 0 0 1 2 12h2a8 8 0 1 0 8-8V2Zm1 5v6l4.2 2.5-1 1.7L11 14V7h2Z"/></svg>""",
    "settings": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0 2a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm-1.2-8h2.4l.4 2.3c.7.2 1.3.6 1.9 1l2.2-.9 1.2 2.1-1.8 1.5c.1.7.1 1.3 0 2l1.8 1.5-1.2 2.1-2.2-.9c-.6.4-1.2.8-1.9 1l-.4 2.3h-2.4l-.4-2.3c-.7-.2-1.3-.6-1.9-1l-2.2.9-1.2-2.1 1.8-1.5a7 7 0 0 1 0-2L5.1 5.5l1.2-2.1 2.2.9c.6-.4 1.2-.8 1.9-1L10.8 2Z"/></svg>""",
    "tomato": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M12 6c4.4 0 8 3.1 8 7s-3.6 7-8 7-8-3.1-8-7 3.6-7 8-7Zm0-4 1.6 2.6L16 3.6l-.6 3 3 .4-2 2.2 1.4 1.3-2.8.2.3 2.6-2.2-1.2-1 2.3L12 13l-1.1 1.6-1-2.3-2.2 1.2.3-2.6-2.8-.2L6.6 9.4 4.6 7.2l3-.4-.6-3 2.4 1L11 2.2 12 2Z"/></svg>""",
    "water": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M12 2s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11Zm0 3.2C10.1 7.8 8 11 8 13a4 4 0 0 0 8 0c0-2-2.1-5.2-4-7.8Z"/></svg>""",
    "export": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
      <path fill="currentColor" d="M12 3 8 7h3v6h2V7h3l-4-4ZM5 13h2v5h10v-5h2v7H5v-7Z"/></svg>""",
}
