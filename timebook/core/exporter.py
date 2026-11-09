"""导出：CSV 明细 + Markdown 周报（纯函数，便于单测）。

移植自 ``Sources/Exporter.swift``，列顺序与周报结构保持一致；CSV 额外写
UTF-8 BOM，让 Excel 直接双击不乱码（Linux 版新增）。
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from pathlib import Path

from . import models
from .brain_level import for_total
from .l10n import T

CSV_HEADER = ["start", "end", "duration_seconds", "app", "host", "detail", "title"]


def csv_text(rows) -> str:
    """明细 CSV（按开始时间升序）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for row in sorted(rows, key=lambda r: r.start):
        writer.writerow(
            [
                row.start.isoformat(timespec="seconds"),
                row.end.isoformat(timespec="seconds"),
                int(row.duration),
                row.app_name,
                row.host or "",
                row.detail or "",
                row.title or "",
            ]
        )
    return "\ufeff" + buffer.getvalue()


def export_csv(rows, path: str | Path) -> int:
    """写入 CSV，返回数据行数（不含表头）。"""
    text = csv_text(rows)
    Path(path).write_text(text, encoding="utf-8")
    return max(0, text.count("\n") - 1)


def weekly_markdown(
    now: datetime,
    per_day,
    top_apps,
    top_hosts,
    categories,
    pomodoros: int = 0,
    focus_seconds: float = 0.0,
    cups: int = 0,
    goal_cups: int = 8,
) -> str:
    """Markdown 周报：合计、疲劳等级、每日表、Top 应用/网站/分类、番茄与喝水。"""
    today = now.strftime("%Y-%m-%d")
    week_start = per_day[0].day.strftime("%Y-%m-%d") if per_day else today
    total = float(sum(p.seconds for p in per_day))
    today_total = 0.0
    for point in per_day:
        if point.day == now.date():
            today_total = point.seconds
            break
    level = for_total(today_total)

    md = f"# {T('时账周报', 'Timebook Weekly')} ({week_start} ~ {today})\n\n"
    md += f"- {T('本周合计', 'Week total')}：{models.fmt_duration(total)}\n"
    brain_line = T("今日疲劳等级", "Today's brain level")
    md += f"- {brain_line}：L{level.level} {level.name}（{level.label_en}）\n"
    md += (
        f"- {T('本周番茄', 'Pomodoros this week')}：{pomodoros} 🍅"
        f"（{models.fmt_duration(focus_seconds)}）\n"
    )
    md += f"- {T('本周喝水', 'Water today')}：{cups}/{goal_cups} 💧\n\n"

    md += f"## {T('每日', 'Daily')}\n\n"
    md += f"| {T('日期', 'Date')} | {T('时长', 'Time')} |\n|---|---|\n"
    for point in per_day:
        md += f"| {point.day.strftime('%Y-%m-%d')} | {models.fmt_duration(point.seconds)} |\n"

    if top_apps:
        md += f"\n## {T('Top 应用', 'Top apps')}\n\n"
        for app in list(top_apps)[:8]:
            md += f"- {app.name}：{models.fmt_duration(app.seconds)}\n"
    if top_hosts:
        md += f"\n## {T('Top 网站', 'Top sites')}\n\n"
        for host in list(top_hosts)[:8]:
            md += f"- {host.host}：{models.fmt_duration(host.seconds)}\n"
    if categories:
        md += f"\n## {T('分类', 'Categories')}\n\n"
        for slice_ in list(categories)[:9]:
            md += f"- {slice_.name}：{models.fmt_duration(slice_.seconds)}\n"

    md += (
        f"\n---\n\n{T('由 Timebook 本地生成，数据未离开这台电脑。', 'Generated locally by Timebook. Data never left this machine.')}\n"
    )
    return md


def build_weekly_markdown(store, now: datetime | None = None, days: int = 7) -> str:
    """从 ``Store`` 直接生成周报（今日 + 前 ``days-1`` 天）。"""
    now = now or datetime.now()
    start = datetime(now.year, now.month, now.day) - timedelta(days=days - 1)
    end = datetime(now.year, now.month, now.day) + timedelta(days=1)
    rows = store.rows(start, end)
    focus = store.focus_events(start, end)

    per_day = models.per_day(rows, count=days, now=now)
    top_apps = models.by_app(rows, limit=8)
    top_hosts = models.by_host(rows, limit=8)
    categories = models.by_category(rows, limit=9)
    pomodoros = sum(1 for f in focus if f.completed)
    focus_seconds = float(sum(f.duration for f in focus if f.completed))
    cups = store.cups_today(now)
    return weekly_markdown(
        now=now,
        per_day=per_day,
        top_apps=top_apps,
        top_hosts=top_hosts,
        categories=categories,
        pomodoros=pomodoros,
        focus_seconds=focus_seconds,
        cups=cups,
        goal_cups=8,
    )


def export_markdown(store, path: str | Path, now: datetime | None = None, days: int = 7) -> Path:
    target = Path(path)
    target.write_text(build_weekly_markdown(store, now, days), encoding="utf-8")
    return target
