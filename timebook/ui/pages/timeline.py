"""时间线页：当日分段列表（起止 / 时长 / 应用 / 域名 / 窗口标题）。"""

from __future__ import annotations

from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from ...core import models  # noqa: E402
from ...core.categories import for_host  # noqa: E402
from .. import widgets as W  # noqa: E402
from ..theme import BRAND, GAP  # noqa: E402
from .base import Page  # noqa: E402


class TimelinePage(Page):
    def __init__(self, ctx) -> None:
        super().__init__(ctx, "timeline")

        head = W.hbox(10)
        self.summary = W.label("", "tb-section")
        head.append(self.summary)
        head.append(W.spacer())
        self.capture_note = W.label("", "tb-caption")
        head.append(self.capture_note)
        self.body.append(head)

        self.list_card = W.card(2)
        self.rows_box = W.vbox(0)
        self.list_card.append(self.rows_box)
        self.empty = W.EmptyState("document-open-recent-symbolic", "今天还没有记录。")
        self.list_card.append(self.empty)
        self.body.append(self.list_card)

        self._signature: tuple | None = None

    def refresh(self, force: bool = False) -> None:
        now = datetime.now()
        rows = self._ctx.store.today_rows(now)
        rows = models.segments(rows)
        total = float(sum(r.duration for r in rows))
        self.summary.set_text(f"今日 {len(rows)} 段 · 合计 {models.fmt_duration(total)}")
        self.capture_note.set_text(
            "已开启窗口标题采集" if self._ctx.settings.capture_titles else "窗口标题采集已关闭（设置 → 记录）"
        )

        signature = (len(rows), rows[0].start if rows else None, total)
        if signature == self._signature and not force:
            return
        self._signature = signature

        child = self.rows_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.rows_box.remove(child)
            child = nxt

        self.rows_box.set_visible(bool(rows))
        self.empty.set_visible(not rows)
        for row in rows[:400]:
            self.rows_box.append(self._build_row(row))

    def _build_row(self, row) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("tb-row")

        time_label = W.label(
            f"{models.fmt_clock(row.start)} – {models.fmt_clock(row.end)}",
            "tb-mono tb-caption",
        )
        time_label.set_size_request(112, -1)
        box.append(time_label)

        duration = W.label(models.fmt_duration(row.duration, compact=True), "tb-mono")
        duration.set_size_request(64, -1)
        duration.set_xalign(1.0)
        box.append(duration)

        name_box = W.vbox(1)
        name_box.set_hexpand(True)
        app_label = W.label(row.app_name, ellipsize=Pango.EllipsizeMode.END)
        name_box.append(app_label)
        if row.title and row.title.strip() != row.app_name.strip():
            name_box.append(W.label(row.title, "tb-caption", ellipsize=Pango.EllipsizeMode.END))
        box.append(name_box)

        if row.host:
            category = for_host(row.host)
            pill = W.Pill(f"{row.host}", category.hex_color)
            box.append(pill)

        return box
