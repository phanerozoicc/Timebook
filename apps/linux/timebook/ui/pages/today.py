"""今日页：大数字合计 + 疲劳等级 + 分类/网站/应用条形。"""

from __future__ import annotations

from datetime import datetime, timedelta

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from ...core.l10n import T, date_label
from ...core import models  # noqa: E402
from ...core.brain_level import for_total, progress_to_next  # noqa: E402
from ...core.categories import for_host  # noqa: E402
from .. import widgets as W  # noqa: E402
from ..theme import BRAND, CATEGORY_COLORS, GAP, LEVEL_COLORS, WELL_GREEN  # noqa: E402
from .base import Page  # noqa: E402


class TodayPage(Page):
    def __init__(self, ctx) -> None:
        super().__init__(ctx, "today")
        self._last_rows_signature: tuple | None = None

        # ---- Hero：今日合计 ----
        self.hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.hero.add_css_class("tb-hero")
        head = W.hbox(8)
        self.hero_caption = W.label(('今日屏幕时间', "Today's screen time"), "tb-caption")
        head.append(self.hero_caption)
        head.append(W.spacer())
        self.hero_date = W.label("", "tb-caption tb-mono")
        head.append(self.hero_date)
        self.hero.append(head)

        self.hero_number = W.label(models.fmt_duration(0, compact=True), "tb-hero-number tb-mono")
        self.hero.append(self.hero_number)

        self.hero_sub = W.label("", "tb-caption")
        self.hero.append(self.hero_sub)

        self.hero_bar = W.CapsuleBar(0.0, BRAND, 8)
        self.hero.append(self.hero_bar)
        self.body.append(self.hero)

        # ---- 疲劳等级 ----
        level_card = W.card(10)
        top = W.hbox(12)
        self.level_badge = W.LevelBadge(for_total(0), 54)
        top.append(self.level_badge)
        text_box = W.vbox(2)
        self.level_title = W.label(('L1 清醒', 'L1 Fresh'), "tb-card-value")
        text_box.append(self.level_title)
        self.level_message = W.label("", "tb-caption", wrap=True)
        text_box.append(self.level_message)
        top.append(text_box)
        top.append(W.spacer())
        self.level_next = W.label("", "tb-caption", xalign=1.0)
        top.append(self.level_next)
        level_card.append(top)
        self.level_bar = W.CapsuleBar(0.0, LEVEL_COLORS[1], 8)
        level_card.append(self.level_bar)
        self.body.append(level_card)

        # ---- 三个条形区 ----
        self.category_card = W.card(8)
        self.category_card.append(W.SectionHeader("view-grid-symbolic", ('分类占比', 'Categories'), ""))
        self.category_rows = W.vbox(6)
        self.category_card.append(self.category_rows)
        self.category_empty = W.EmptyState("view-grid-symbolic", ('今天还没有浏览记录。', 'No browser activity today.'))
        self.category_card.append(self.category_empty)
        self.body.append(self.category_card)

        self.host_card = W.card(8)
        self.host_card.append(W.SectionHeader("network-server-symbolic", ('按网站', 'By website'), ('仅浏览器', 'Browser activity only')))
        self.host_rows = W.vbox(6)
        self.host_card.append(self.host_rows)
        self.host_empty = W.EmptyState("network-server-symbolic", ('还没有网站记录，去浏览器逛逛？', 'Website activity will appear here as you browse.'))
        self.host_card.append(self.host_empty)
        self.body.append(self.host_card)

        self.app_card = W.card(8)
        self.app_card.append(W.SectionHeader("applications-system-symbolic", ('按应用', 'By app'), ""))
        self.app_rows = W.vbox(6)
        self.app_card.append(self.app_rows)
        self.app_empty = W.EmptyState("applications-system-symbolic", ('还没有应用记录。', 'No app activity yet.'))
        self.app_card.append(self.app_empty)
        self.body.append(self.app_card)

    # ------------------------------------------------------------------ #

    def refresh(self, force: bool = False) -> None:
        force = self.refresh_language() or force
        now = datetime.now()
        rows = self._ctx.today_rows(now)
        total = float(sum(r.duration for r in rows))
        live = self._ctx.today_total()
        total = max(total, live)

        self.hero_date.set_text(date_label(now))
        self.hero_number.set_text(models.fmt_duration(total, compact=True))
        settings = self._ctx.settings
        self.hero_bar.set_visible(settings.limits_enabled)
        self.hero_bar.set_fraction(total / (settings.limits_daily_minutes * 60))
        self.hero_bar.set_tooltip_text(T(f"每日上限 · {models.fmt_duration(settings.limits_daily_minutes * 60)}", f"Daily limit · {models.fmt_duration(settings.limits_daily_minutes * 60)}"))

        yesterday = self._yesterday_total(now)
        if total <= 0:
            self.hero_sub.set_text(T('开始工作后这里会实时累加。', 'Your screen time updates here as you work.'))
        elif yesterday > 0:
            delta = total - yesterday
            pct = abs(delta) / yesterday * 100
            arrow = "↑" if delta > 0 else "↓"
            self.hero_sub.set_text(
                T(f"比昨天同期 {arrow} {models.fmt_duration(abs(delta), compact=True)}（{pct:.0f}%）", f"Since this time yesterday {arrow} {models.fmt_duration(abs(delta), compact=True)} ({pct:.0f}%)")
            )
        else:
            self.hero_sub.set_text(T('昨天没有记录，今天是个新开始。', 'No activity yesterday. Today is a fresh start.'))

        level, nxt, ratio = progress_to_next(total)
        self.level_badge.set_level(level)
        self.level_title.set_text(f"L{level.level} {level.name}")
        self.level_message.set_text(level.message)
        self.level_bar.set_fraction(ratio, LEVEL_COLORS.get(level.level, BRAND))
        if nxt is None:
            self.level_next.set_text(T('已到最高级', 'Highest level reached'))
        else:
            remain = max(0.0, nxt.min_hours * 3600 - total)
            self.level_next.set_text(T(f"距 L{nxt.level} 还有 {models.fmt_duration(remain, compact=True)}", f"{models.fmt_duration(remain, compact=True)} until L{nxt.level}"))

        signature = (total, len(rows))
        if not force and signature == self._last_rows_signature:
            return
        self._last_rows_signature = signature

        # 分类
        categories = models.by_category(rows, limit=9)
        self._rebuild(self.category_rows, self.category_empty, [
            (c.name, c.seconds, CATEGORY_COLORS.get(c.category_id, 0x6B7280)) for c in categories
        ], models.total(rows))

        # 网站
        hosts = models.by_host(rows, limit=8)
        self._rebuild(self.host_rows, self.host_empty, [
            (h.host, h.seconds, for_host(h.host).hex_color) for h in hosts
        ], models.total(rows))

        # 应用
        apps = models.by_app(rows, limit=8)
        self._rebuild(self.app_rows, self.app_empty, [
            (a.name, a.seconds, BRAND) for a in apps
        ], models.total(rows))

    # ------------------------------------------------------------------ #

    def _rebuild(self, container: Gtk.Box, empty: W.EmptyState, items, total: float) -> None:
        child = container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            container.remove(child)
            child = nxt
        peak = max((seconds for _, seconds, _ in items), default=0.0)
        for name, seconds, color in items:
            container.append(W.BarRow(name, seconds, peak, color=color))
        container.set_visible(bool(items))
        empty.set_visible(not items)

    def _yesterday_total(self, now: datetime) -> float:
        """昨天同一时刻之前（同期）的累计时长，用于「比昨天」对比。"""
        day = now.date() - timedelta(days=1)
        start = datetime(day.year, day.month, day.day)
        cutoff = now - timedelta(days=1)
        rows = self._ctx.rows(start, cutoff)
        return float(sum(r.duration for r in rows))

