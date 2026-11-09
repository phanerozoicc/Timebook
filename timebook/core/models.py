"""领域值对象与聚合函数（纯函数，无 GTK / 无 IO，便于单测）。

移植自 macOS 版 ``Sources/Store.swift`` 中的 ``EventRow`` / ``Agg`` / ``Fmt``。
时间约定：全部使用**本地朴素 datetime**（naive local），与 Swift 的
``Date`` + ``Calendar.current`` 行为一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .categories import BY_ID, OTHER, SiteCategory, for_host
from .l10n import T

# --------------------------------------------------------------------------- #
# 值对象
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EventRow:
    """一段连续使用某个应用（可能附带浏览器域名）的记录。"""

    app_id: str
    app_name: str
    start: datetime
    end: datetime
    detail: str | None = None
    host: str | None = None
    title: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())

    @property
    def appID(self) -> str:  # Swift 命名对齐
        return self.app_id


@dataclass(frozen=True, slots=True)
class FocusRow:
    """一次完成（或跳过）的专注段。"""

    start: datetime
    end: datetime
    completed: bool
    preset_name: str

    @property
    def duration(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


@dataclass(frozen=True, slots=True)
class AppSlice:
    app_id: str
    name: str
    seconds: float

    @property
    def id(self) -> str:
        return self.app_id


@dataclass(frozen=True, slots=True)
class HostSlice:
    host: str
    seconds: float

    @property
    def id(self) -> str:
        return self.host


@dataclass(frozen=True, slots=True)
class DayPoint:
    day: date
    seconds: float

    @property
    def id(self) -> date:
        return self.day


@dataclass(frozen=True, slots=True)
class CategorySlice:
    category_id: str
    name: str
    hex_color: int
    seconds: float

    @property
    def id(self) -> str:
        return self.category_id


@dataclass(frozen=True, slots=True)
class StackedPoint:
    day: date
    app_name: str
    minutes: float


# --------------------------------------------------------------------------- #
# 时间辅助
# --------------------------------------------------------------------------- #


def today_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    return datetime(now.year, now.month, now.day)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)


def day_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"


# --------------------------------------------------------------------------- #
# 聚合（对应 Swift 的 enum Agg）
# --------------------------------------------------------------------------- #


def total(rows: list[EventRow] | tuple[EventRow, ...]) -> float:
    return float(sum(r.duration for r in rows))


def by_app(rows: list[EventRow] | tuple[EventRow, ...], limit: int = 8) -> list[AppSlice]:
    seconds: dict[str, float] = {}
    names: dict[str, str] = {}
    for row in rows:
        seconds[row.app_id] = seconds.get(row.app_id, 0.0) + row.duration
        names.setdefault(row.app_id, row.app_name)
    slices = [
        AppSlice(app_id=app_id, name=names.get(app_id, app_id), seconds=sec)
        for app_id, sec in seconds.items()
    ]
    slices.sort(key=lambda s: s.seconds, reverse=True)
    return slices[:limit]


def by_host(rows: list[EventRow] | tuple[EventRow, ...], limit: int = 8) -> list[HostSlice]:
    seconds: dict[str, float] = {}
    for row in rows:
        if row.duration <= 0:
            continue
        host = (row.host or "").strip()
        if not host:
            continue
        seconds[host] = seconds.get(host, 0.0) + row.duration
    slices = [HostSlice(host=h, seconds=s) for h, s in seconds.items()]
    slices.sort(key=lambda s: s.seconds, reverse=True)
    return slices[:limit]


def segments(rows: list[EventRow] | tuple[EventRow, ...]) -> list[EventRow]:
    return sorted(rows, key=lambda r: r.start, reverse=True)


def by_category(
    rows: list[EventRow] | tuple[EventRow, ...], limit: int = 8
) -> list[CategorySlice]:
    seconds: dict[str, float] = {}
    for row in rows:
        host = (row.host or "").strip()
        if not host or row.duration <= 0:
            continue
        category = for_host(host)
        seconds[category.id] = seconds.get(category.id, 0.0) + row.duration
    slices: list[CategorySlice] = []
    for cid, sec in seconds.items():
        category: SiteCategory = BY_ID.get(cid, OTHER)
        slices.append(
            CategorySlice(
                category_id=cid,
                name=category.name,
                hex_color=category.hex_color,
                seconds=sec,
            )
        )
    slices.sort(key=lambda s: s.seconds, reverse=True)
    return slices[:limit]


def per_day(
    rows: list[EventRow] | tuple[EventRow, ...],
    count: int = 7,
    now: datetime | None = None,
) -> list[DayPoint]:
    """以 ``now`` 所在日为最后一天的 trailing ``count`` 天每日合计。"""
    now = now or datetime.now()
    end_day = now.date()
    days = [end_day - timedelta(days=offset) for offset in range(count - 1, -1, -1)]
    buckets: dict[date, float] = {d: 0.0 for d in days}
    for row in rows:
        day = row.start.date()
        if day in buckets:
            buckets[day] += row.duration
    return [DayPoint(day=d, seconds=buckets[d]) for d in days]


def stacked(
    rows: list[EventRow] | tuple[EventRow, ...],
    count: int = 7,
    now: datetime | None = None,
    top: int = 5,
) -> list[StackedPoint]:
    """每日堆叠图：整体 Top-N 应用 + 「其他」。"""
    top_ids = {s.app_id for s in by_app(rows, limit=top)}
    now = now or datetime.now()
    end_day = now.date()
    days = [end_day - timedelta(days=offset) for offset in range(count - 1, -1, -1)]
    buckets: dict[date, dict[str, float]] = {d: {} for d in days}
    for row in rows:
        day = row.start.date()
        if day not in buckets:
            continue
        name = row.app_name if row.app_id in top_ids else T("其他", "Other")
        buckets[day][name] = buckets[day].get(name, 0.0) + row.duration / 60.0
    points: list[StackedPoint] = []
    for day in days:
        for name, minutes in buckets[day].items():
            points.append(StackedPoint(day=day, app_name=name, minutes=minutes))
    points.sort(key=lambda p: (p.day, -p.minutes))
    return points


def active_days(
    rows: list[EventRow] | tuple[EventRow, ...],
    count: int = 7,
    now: datetime | None = None,
) -> int:
    points = per_day(rows, count=count, now=now)
    return sum(1 for p in points if p.seconds > 0)


def average_active_day(
    rows: list[EventRow] | tuple[EventRow, ...],
    count: int = 7,
    now: datetime | None = None,
) -> float:
    points = per_day(rows, count=count, now=now)
    active = [p.seconds for p in points if p.seconds > 0]
    return float(sum(active) / len(active)) if active else 0.0


def day_total(rows: list[EventRow] | tuple[EventRow, ...], day: date) -> float:
    return float(sum(r.duration for r in rows if r.start.date() == day))


def top_app_name(rows: list[EventRow] | tuple[EventRow, ...]) -> str | None:
    slices = by_app(rows, limit=1)
    return slices[0].name if slices else None


def focus_completed(rows: list[FocusRow]) -> int:
    return sum(1 for r in rows if r.completed)


# --------------------------------------------------------------------------- #
# 格式化（对应 Swift 的 enum Fmt）
# --------------------------------------------------------------------------- #


def fmt_duration(seconds: float, compact: bool = False) -> str:
    """人类可读时长。compact: ``2h07m`` / ``34m`` / ``0s``；否则 ``2 小时 7 分``。"""
    total_seconds = int(max(0.0, round(seconds)))
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    if compact:
        if h > 0:
            return f"{h}h{m:02d}m"
        if m > 0:
            return f"{m}m"
        return f"{s}s"
    if h > 0:
        return T(f"{h} 小时 {m} 分", f"{h}h {m}m")
    if m > 0:
        return T(f"{m} 分", f"{m}m")
    return T(f"{s} 秒", f"{s}s")


def fmt_clock(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def fmt_clock_interval(seconds: float) -> str:
    total_seconds = int(round(max(0.0, seconds)))
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def fmt_minutes_hm(minutes: int) -> str:
    """限额文案：正确处理 1 小时以下的分钟数。"""
    if minutes < 60:
        return T(f"{minutes} 分钟", f"{minutes} min")
    if minutes % 60 == 0:
        return T(f"{minutes // 60} 小时", f"{minutes // 60} h")
    return T(f"{minutes // 60} 小时 {minutes % 60} 分", f"{minutes // 60}h {minutes % 60}m")
