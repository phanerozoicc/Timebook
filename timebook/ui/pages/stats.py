"""统计页：周/月切换 + 汇总卡 + 每日趋势 + 分类环形图 + 12 周热力图。"""

from __future__ import annotations

from datetime import datetime, timedelta

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from ...core import models  # noqa: E402
from ...core.categories import BY_ID  # noqa: E402
from ...core.heatmap import HeatGrid  # noqa: E402
from .. import widgets as W  # noqa: E402
from ..theme import BRAND, CATEGORY_COLORS, CALM_BLUE, GAP, WELL_GREEN  # noqa: E402
from .base import Page  # noqa: E402


class StatsPage(Page):
    def __init__(self, ctx) -> None:
        super().__init__(ctx, "stats")
        self._days = 7

        # 周/月切换
        switch_row = W.hbox(8)
        self.seg = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.seg.add_css_class("tb-seg")
        self.week_button = Gtk.ToggleButton(label="最近 7 天")
        self.month_button = Gtk.ToggleButton(label="最近 30 天")
        self.month_button.set_group(self.week_button)
        self.week_button.set_active(True)
        self.week_button.connect("toggled", self._on_range, 7)
        self.month_button.connect("toggled", self._on_range, 30)
        self.seg.append(self.week_button)
        self.seg.append(self.month_button)
        switch_row.append(self.seg)
        switch_row.append(W.spacer())
        self.range_caption = W.label("", "tb-caption")
        switch_row.append(self.range_caption)
        self.body.append(switch_row)

        # 三张汇总卡
        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cards.set_homogeneous(True)
        self.card_total = W.StatCard("alarm-symbolic", "区间合计", "0m", BRAND)
        self.card_avg = W.StatCard("view-refresh-symbolic", "活跃天日均", "0m", WELL_GREEN)
        self.card_active = W.StatCard("emblem-ok-symbolic", "活跃天数", "0 天", CALM_BLUE)
        for card in (self.card_total, self.card_avg, self.card_active):
            cards.append(card)
        self.body.append(cards)

        # 每日趋势
        trend_card = W.card(8)
        self.trend_header = W.SectionHeader("office-calendar-symbolic", "每日趋势", "")
        trend_card.append(self.trend_header)
        self.chart = W.BarChart(180)
        trend_card.append(self.chart)
        self.body.append(trend_card)

        # 分类环形图
        cat_card = W.card(10)
        cat_card.append(W.SectionHeader("view-grid-symbolic", "分类占比", "按域名归类"))
        cat_body = W.hbox(20)
        self.donut = W.DonutChart(176, 20)
        self.donut.set_halign(Gtk.Align.START)
        cat_body.append(self.donut)
        self.legend = W.vbox(7)
        self.legend.set_valign(Gtk.Align.CENTER)
        cat_body.append(self.legend)
        cat_card.append(cat_body)
        self.body.append(cat_card)

        # 热力图
        heat_card = W.card(8)
        heat_card.append(W.SectionHeader("office-calendar-symbolic", "最近 12 周", ""))
        self.heatmap = W.HeatmapWidget()
        heat_card.append(self.heatmap)
        self.heat_caption = W.label("", "tb-caption")
        heat_card.append(self.heat_caption)
        self.body.append(heat_card)

    # ------------------------------------------------------------------ #

    def _on_range(self, button: Gtk.ToggleButton, days: int) -> None:
        if not button.get_active():
            return
        self._days = days
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        now = datetime.now()
        start = datetime(now.year, now.month, now.day) - timedelta(days=self._days - 1)
        end = datetime(now.year, now.month, now.day) + timedelta(days=1)
        rows = self._ctx.store.rows(start, end)

        per_day = models.per_day(rows, count=self._days, now=now)
        total = float(sum(p.seconds for p in per_day))
        active = sum(1 for p in per_day if p.seconds > 0)
        avg = total / active if active else 0.0

        self.card_total.set_value(models.fmt_duration(total, compact=True))
        self.card_avg.set_value(models.fmt_duration(avg, compact=True))
        self.card_active.set_value(f"{active} 天")
        self.range_caption.set_text(f"{start.strftime('%m/%d')} – {now.strftime('%m/%d')}")

        points = []
        for point in per_day:
            label = point.day.strftime("%m/%d") if self._days > 14 else (
                "一二三四五六日"[point.day.weekday()]
            )
            points.append((label, point.seconds))
        peak_day = max(per_day, key=lambda p: p.seconds, default=None)
        self.trend_header.set_trailing(
            f"峰值 {peak_day.day.strftime('%m/%d')} · {models.fmt_duration(peak_day.seconds, compact=True)}"
            if peak_day and peak_day.seconds > 0
            else ""
        )
        self.chart.set_points(points, BRAND)

        # 分类环形图
        categories = models.by_category(rows, limit=9)
        self.donut.set_slices(
            [(c.name, c.seconds, CATEGORY_COLORS.get(c.category_id, 0x6B7280)) for c in categories],
            models.fmt_duration(total, compact=True),
        )
        self._rebuild_legend(categories, total)

        # 热力图（12 周需要更长的数据范围）
        heat_start = end - timedelta(days=12 * 7 + 7)
        heat_rows = self._ctx.store.rows(heat_start, end)
        grid = HeatGrid.for_rows(heat_rows, now)
        self.heatmap.set_grid(grid)
        self.heat_caption.set_text(
            f"共 {grid.active_days} 天有记录 · 合计 {models.fmt_duration(grid.total_seconds, compact=True)}"
        )

    def _rebuild_legend(self, categories, total: float) -> None:
        child = self.legend.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.legend.remove(child)
            child = nxt
        if not categories:
            self.legend.append(W.label("还没有足够的浏览数据。", "tb-caption"))
            return
        for slice_ in categories:
            row = W.hbox(8)
            row.append(W.color_dot(CATEGORY_COLORS.get(slice_.category_id, 0x6B7280), 9))
            name = W.label(slice_.name)
            name.set_size_request(84, -1)
            row.append(name)
            bar = W.CapsuleBar(slice_.seconds / total if total else 0.0,
                               CATEGORY_COLORS.get(slice_.category_id, 0x6B7280), 6)
            bar.set_size_request(90, 6)
            row.append(bar)
            pct = W.label(f"{slice_.seconds / total * 100:.0f}%" if total else "0%", "tb-caption tb-mono")
            pct.set_size_request(38, -1)
            pct.set_xalign(1.0)
            row.append(pct)
            self.legend.append(row)
