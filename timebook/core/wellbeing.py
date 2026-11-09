"""每日限额 + 分心提醒 + 休息/喝水提醒。

移植自 ``Sources/Wellbeing.swift``。系统级应用无法强制屏蔽其他应用/网站，
所以限额统一是 **warn 语义**：阈值进度提醒 + 分心站点连续使用温和提醒。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .categories import for_host
from .l10n import T
from .models import fmt_duration


@dataclass
class LimitCheckInputs:
    today_total: float
    daily_limit_minutes: int
    now: datetime
    current_host: str | None = None
    current_segment_start: datetime | None = None


@dataclass
class LimitSettings:
    """限额相关的设置快照（避免引擎直接依赖 Settings，便于测试）。"""

    enabled: bool = False
    daily_minutes: int = 240
    distract_enabled: bool = False


class LimitsEngine:
    """80/90/100% 三档提醒（每天各一次）+ 分心站点提醒（10 分钟起步、30 分钟冷却）。"""

    def __init__(self) -> None:
        self.today_percent: int = 0
        self.limit_reached: bool = False
        self._warned: set[int] = set()
        self._last_warned_day: str = ""
        self._last_distract_nudge: datetime | None = None
        #: 通知落点
        self.on_notify: Callable[[str, str], None] | None = None

    def minute(
        self,
        inputs: LimitCheckInputs,
        settings: LimitSettings | Callable[[], LimitSettings] | None = None,
    ) -> str | None:
        """每分钟由主循环驱动；返回本次触发的提醒标识（``None`` = 无提醒）。"""
        if settings is None:
            settings = LimitSettings()
        if callable(settings):
            settings = settings()

        day_key = inputs.now.strftime("%Y-%m-%d")
        if day_key != self._last_warned_day:
            self._last_warned_day = day_key
            self._warned = set()

        if not settings.enabled or inputs.daily_limit_minutes <= 0:
            self.today_percent = 0
            self.limit_reached = False
            return None

        limit = float(inputs.daily_limit_minutes * 60)
        percent = int(round(inputs.today_total / limit * 100))
        self.today_percent = percent
        self.limit_reached = percent >= 100

        for threshold in (80, 90, 100):
            if percent >= threshold and threshold not in self._warned:
                self._warned.add(threshold)
                used = fmt_duration(inputs.today_total, compact=True)
                if threshold >= 100:
                    self._notify(
                        T("今日屏幕时间已到限额 ⚠️", "Daily screen-time limit reached ⚠️"),
                        T(
                            f"已用 {used}。差不多该离开了，明天见。",
                            f"Used {used}. Time to wrap up, see you tomorrow.",
                        ),
                    )
                else:
                    self._notify(
                        T("屏幕时间提醒", "Screen-time reminder"),
                        T(
                            f"今日已用 {used}，达到限额的 {threshold}%。",
                            f"Used {used} today — {threshold}% of your limit.",
                        ),
                    )
                return f"limit-{threshold}"

        # 分心站点连续使用温和提醒（10 分钟起步，30 分钟冷却）
        if (
            settings.distract_enabled
            and inputs.current_host
            and inputs.current_segment_start is not None
        ):
            category = for_host(inputs.current_host)
            if category.distracting:
                minutes = int((inputs.now - inputs.current_segment_start).total_seconds() / 60)
                if minutes >= 10:
                    if (
                        self._last_distract_nudge is not None
                        and (inputs.now - self._last_distract_nudge).total_seconds() < 30 * 60
                    ):
                        return None
                    self._last_distract_nudge = inputs.now
                    self._notify(
                        T("该收心了 🧘", "Time to refocus 🧘"),
                        T(
                            f"在 {inputs.current_host} 已经 {minutes} 分钟了（{category.name}）。",
                            f"{minutes} min on {inputs.current_host} ({category.name}).",
                        ),
                    )
                    return "distract"
        return None

    def reset_for_testing(self) -> None:
        self._warned = set()
        self._last_warned_day = ""
        self._last_distract_nudge = None
        self.today_percent = 0
        self.limit_reached = False

    def _notify(self, title: str, body: str) -> None:
        if self.on_notify:
            self.on_notify(title, body)


@dataclass
class ReminderSettings:
    """提醒相关设置快照。"""

    notifications_enabled: bool = True
    break_enabled: bool = True
    break_interval_minutes: int = 30
    water_enabled: bool = True
    water_interval_minutes: int = 60
    water_start_hour: int = 9
    water_end_hour: int = 22
    water_goal_cups: int = 8


class RemindersEngine:
    """连续活跃计时 + 休息提醒 + 喝水提醒（含每日时间窗与冷却）。"""

    def __init__(self) -> None:
        self.active_seconds: float = 0.0
        self.on_notify: Callable[[str, str], None] | None = None
        #: 今日杯数提供者（由 App 接线到 Store）。
        self.cups_provider: Callable[[], int] = lambda: 0

        self._last_water_nudge: datetime | None = None
        self._last_break_day: str = ""

    def tick(
        self,
        idle: bool,
        in_pomodoro_break: bool,
        now: datetime | None = None,
        tick_interval: float = 5.0,
        settings: ReminderSettings | Callable[[], ReminderSettings] | None = None,
    ) -> str | None:
        """由主循环按固定步长驱动（默认 5 秒）。返回触发的提醒标识。"""
        now = now or datetime.now()
        if settings is None:
            settings = ReminderSettings()
        if callable(settings):
            settings = settings()

        day_key = now.strftime("%Y-%m-%d")
        if day_key != self._last_break_day:
            self._last_break_day = day_key
            self.active_seconds = 0.0

        # 休息联动：空闲或番茄休息期都重置连续活跃计数
        if idle or in_pomodoro_break:
            self.active_seconds = 0.0
            return None
        self.active_seconds += tick_interval

        if (
            settings.notifications_enabled
            and settings.break_enabled
            and self.active_seconds >= settings.break_interval_minutes * 60
        ):
            self.active_seconds = 0.0
            self._notify(
                T("该休息一下了 👀", "Time for a break 👀"),
                T(
                    "连续用眼较久，远眺放松一下，顺便站起来活动活动。",
                    "Eyes have been busy — look far away and stretch a little.",
                ),
            )
            return "break"

        hour = now.hour
        in_window = settings.water_start_hour <= hour < settings.water_end_hour
        if settings.notifications_enabled and settings.water_enabled and in_window:
            since_last = (
                (now - self._last_water_nudge).total_seconds()
                if self._last_water_nudge is not None
                else float("inf")
            )
            if since_last >= settings.water_interval_minutes * 60:
                self._last_water_nudge = now
                cups = self.cups_provider()
                goal = settings.water_goal_cups
                self._notify(
                    T("喝口水 💧", "Drink some water 💧"),
                    T(
                        f"今天 {cups}/{goal} 杯。番茄休息时顺便补杯水。",
                        f"{cups}/{goal} cups today. Top up on your next pomodoro break.",
                    ),
                )
                return "water"
        return None

    def reset_active_time(self) -> None:
        """微休息 / 番茄休息后由 UI 调用，重置连续活跃计数。"""
        self.active_seconds = 0.0

    def reset_for_testing(self) -> None:
        self.active_seconds = 0.0
        self._last_water_nudge = None
        self._last_break_day = ""

    def _notify(self, title: str, body: str) -> None:
        if self.on_notify:
            self.on_notify(title, body)
