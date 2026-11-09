"""12 周热力图分桶（GitHub 贡献格样式，暖色 7 档）。

移植自 ``Sources/Heatmap.swift``：``Heat.palette`` 与 ``Heat.bucket`` 的分档
边界保持一致，格子按周成列（每列 7 天，周一在上），末列允许不足 7 天。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .l10n import T

WEEKS = 12
DAYS = WEEKS * 7

#: 暖色 7 档：0h → ≥6h（与 Swift ``Heat.palette`` 完全一致）。
PALETTE: tuple[int, ...] = (0x262A35, 0x3A4A52, 0x4A5A50, 0x6B6A4C, 0x8A7A4E, 0xB08D4C, 0xE2B15C)

WEEKDAY_LABELS_ZH = ("一", "二", "三", "四", "五", "六", "日")
WEEKDAY_LABELS_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def level_for_seconds(seconds: float) -> int:
    """按小时分 0–6 档（与 ``Heat.bucket`` 一致）。"""
    hours = max(0.0, seconds) / 3600.0
    if hours < 0.25:
        return 0
    if hours < 0.5:
        return 1
    if hours < 1:
        return 2
    if hours < 2:
        return 3
    if hours < 4:
        return 4
    if hours < 6:
        return 5
    return 6


def color_for(level: int) -> str:
    return f"#{PALETTE[min(max(0, level), len(PALETTE) - 1)]:06X}"


def level_hint(level: int) -> str:
    return (
        "0–15m", "15–30m", "30–60m", "1–2h", "2–4h", "4–6h", "≥6h"
    )[min(max(0, level), 6)]


@dataclass(frozen=True, slots=True)
class HeatCell:
    day: date
    seconds: float
    level: int

    @property
    def color(self) -> str:
        return color_for(self.level)

    @property
    def in_future(self) -> bool:
        return False

    @property
    def label(self) -> str:
        return f"{self.day.strftime('%m/%d')} · {int(self.seconds // 60)}m"


@dataclass(frozen=True, slots=True)
class HeatColumn:
    cells: tuple[HeatCell, ...]


class HeatGrid:
    """最近 12 周（84 天）的热力网格，首列对齐到周一。"""

    def __init__(self, columns: list[HeatColumn]) -> None:
        self.columns = columns

    @property
    def cells(self) -> list[HeatCell]:
        return [cell for column in self.columns for cell in column.cells]

    @property
    def total_seconds(self) -> float:
        return float(sum(c.seconds for c in self.cells))

    @property
    def active_days(self) -> int:
        return sum(1 for c in self.cells if c.seconds > 0)

    @staticmethod
    def week_start(day: date) -> date:
        """该日所在周的周一。"""
        return day - timedelta(days=day.weekday())

    @classmethod
    def for_rows(
        cls, rows, now: datetime | None = None, weeks: int = WEEKS
    ) -> "HeatGrid":
        """用使用记录构造网格。``rows`` 只需有 ``start`` / ``duration``。"""
        now = now or datetime.now()
        today = now.date()
        end = cls.week_start(today) + timedelta(days=6)  # 本周日
        days = max(1, weeks) * 7
        start = end - timedelta(days=days - 1)

        buckets: dict[date, float] = {}
        for row in rows:
            day = row.start.date()
            if start <= day <= end:
                buckets[day] = buckets.get(day, 0.0) + row.duration

        columns: list[HeatColumn] = []
        cursor = start
        while cursor <= end:
            cells: list[HeatCell] = []
            for offset in range(7):
                day = cursor + timedelta(days=offset)
                seconds = buckets.get(day, 0.0)
                cells.append(HeatCell(day=day, seconds=seconds, level=level_for_seconds(seconds)))
            columns.append(HeatColumn(cells=tuple(cells)))
            cursor += timedelta(days=7)
        return cls(columns)

    @classmethod
    def empty(cls, now: datetime | None = None, weeks: int = WEEKS) -> "HeatGrid":
        return cls.for_rows([], now, weeks)


def weekday_label(index: int) -> str:
    """0=周一。"""
    return T(WEEKDAY_LABELS_ZH[index % 7], WEEKDAY_LABELS_EN[index % 7])
