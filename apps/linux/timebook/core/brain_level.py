"""大脑疲劳等级：按今日累计屏幕时间分 10 级。

移植自 ``Sources/Shared/BrainLevel.swift``，阈值/配色/文案一致。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrainLevel:
    level: int
    label_en: str
    name_zh: str
    min_hours: float
    hex_color: int
    message_zh: str
    message_en: str

    @property
    def name(self) -> str:
        from .l10n import T

        return T(self.name_zh, self.label_en)

    @property
    def message(self) -> str:
        from .l10n import T

        return T(self.message_zh, self.message_en)

    @property
    def color_hex(self) -> str:
        return f"#{self.hex_color:06X}"


ALL: tuple[BrainLevel, ...] = (
    BrainLevel(1, "Fresh", "清醒", 0.0, 0x6FAF8C, "状态极佳，保持这个节奏", "Feeling great — keep this pace"),
    BrainLevel(2, "Chill", "放松", 1.0, 0x8BB271, "轻松区，注意别刷太久", "Easy zone — don't drift too long"),
    BrainLevel(3, "Meh", "一般", 2.0, 0xC4A968, "有点麻木了，来次微休息吧", "Getting numb — take a micro-break"),
    BrainLevel(4, "Tired", "疲倦", 3.0, 0xC99A45, "大脑开始疲劳，效率在下降", "Fatigue setting in, focus is dropping"),
    BrainLevel(5, "Strained", "紧绷", 4.0, 0xC28053, "注意力涣散，该停一停了", "Attention drifting — time to stop"),
    BrainLevel(6, "Drained", "透支", 5.0, 0xBC6A55, "能量见底，继续刷只会更累", "Running on empty — scrolling adds fatigue"),
    BrainLevel(7, "Foggy", "迷糊", 6.0, 0xB06070, "脑雾状态，判断力已下降", "Brain fog — judgement is impaired"),
    BrainLevel(8, "Fried", "炸毛", 8.0, 0x9A6386, "严重过载，先照顾好自己", "Heavy overload — take care of yourself"),
    BrainLevel(9, "Melting", "融化", 10.0, 0x746BB0, "再刷下去明天会崩盘", "Keep going and tomorrow collapses"),
    BrainLevel(10, "Dead", "躺平", 12.0, 0x585E68, "大脑已离线…", "Brain offline…"),
)


def for_total(seconds: float) -> BrainLevel:
    """按今日累计秒数返回等级（向下取整到已越过的最高阈值）。"""
    hours = max(0.0, seconds) / 3600.0
    current = ALL[0]
    for candidate in ALL:
        if hours >= candidate.min_hours:
            current = candidate
    return current


def next_of(level: int) -> BrainLevel | None:
    for candidate in ALL:
        if candidate.level == level + 1:
            return candidate
    return None


def progress_to_next(seconds: float) -> tuple[BrainLevel, BrainLevel | None, float]:
    """返回 (当前等级, 下一等级, 到下一等级的进度 0..1)。"""
    current = for_total(seconds)
    nxt = next_of(current.level)
    if nxt is None:
        return current, None, 1.0
    hours = max(0.0, seconds) / 3600.0
    span = nxt.min_hours - current.min_hours
    if span <= 0:
        return current, nxt, 1.0
    ratio = (hours - current.min_hours) / span
    return current, nxt, min(1.0, max(0.0, ratio))


LEVEL_COLORS: dict[int, int] = {b.level: b.hex_color for b in ALL}
