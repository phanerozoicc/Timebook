"""应用设置：对应 macOS 版 ``AppSettings``（UserDefaults → SQLite kv 表）。

所有读取都「每次实时读」——tracker 每个 tick 都会重新读空闲阈值，这样设置面板
改动立即生效，不需要重启。
"""

from __future__ import annotations

from typing import Any

from .l10n import T
from .models import fmt_minutes_hm
from .store import Store

# 设置键名与 macOS 版保持一致，便于将来从 macOS 备份迁移。
IDLE_KEY = "idleThreshold"
EXCLUDED_KEY = "excludedApps"
RETENTION_KEY = "retentionDays"
LANGUAGE_KEY = "language"
TITLES_KEY = "captureTitles"
LIMITS_ENABLED_KEY = "limitsEnabled"
LIMITS_DAILY_MIN_KEY = "limitsDailyMin"
DISTRACT_NUDGE_KEY = "distractNudge"
BREAK_REMINDER_KEY = "breakReminderEnabled"
BREAK_INTERVAL_KEY = "breakIntervalMin"
WATER_ENABLED_KEY = "waterEnabled"
WATER_INTERVAL_KEY = "waterIntervalMin"
WATER_START_HOUR_KEY = "waterStartHour"
WATER_END_HOUR_KEY = "waterEndHour"
WATER_GOAL_KEY = "waterGoalCups"
NOTIFICATIONS_KEY = "notificationsEnabled"
POMO_BREAK_OVERLAY_KEY = "pomodoroBreakOverlay"

# Linux 版新增
PAUSED_KEY = "trackingPaused"
TRAY_ENABLED_KEY = "trayEnabled"
BROWSER_TITLES_KEY = "browserTitleParsing"
FORFEIT_ENABLED_KEY = "forfeitEnabled"

_VALID_LANGUAGES = ("auto", "zh", "en")


class Settings:
    """``Store`` kv 之上的一层类型化设置访问器。"""

    def __init__(self, store: Store) -> None:
        self._store = store

    # -- 原始访问 -------------------------------------------------------- #

    def get_raw(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def set_raw(self, key: str, value: Any) -> None:
        self._store.set(key, value)

    # -- 记录 ------------------------------------------------------------ #

    @property
    def idle_threshold(self) -> int:
        """空闲判定阈值（秒）。0 = 不启用空闲判定；默认 120，最小值 30。"""
        raw = self._store.get(IDLE_KEY)
        if raw is None:
            return 120
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 120
        if value == 0:
            return 0
        return value if value >= 30 else 120

    @idle_threshold.setter
    def idle_threshold(self, value: int) -> None:
        # 与 Swift 版一致：原样存，读取时再按规则夹紧（0=不启用，<30 视为无效→120）
        self._store.set(IDLE_KEY, int(value))

    @property
    def excluded(self) -> set[str]:
        raw = self._store.get(EXCLUDED_KEY, [])
        if not isinstance(raw, list):
            return set()
        return {str(x) for x in raw}

    @excluded.setter
    def excluded(self, apps: set[str] | list[str]) -> None:
        self._store.set(EXCLUDED_KEY, sorted({str(a) for a in apps}))

    @property
    def retention_days(self) -> int:
        raw = self._store.get(RETENTION_KEY, 0)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 0
        return value if value in (90, 180, 365) else 0

    @retention_days.setter
    def retention_days(self, value: int) -> None:
        self._store.set(RETENTION_KEY, int(value) if int(value) in (90, 180, 365) else 0)

    @property
    def language(self) -> str:
        raw = self._store.get(LANGUAGE_KEY, "auto")
        return raw if raw in _VALID_LANGUAGES else "auto"

    @language.setter
    def language(self, value: str) -> None:
        self._store.set(LANGUAGE_KEY, value if value in _VALID_LANGUAGES else "auto")

    @property
    def capture_titles(self) -> bool:
        return bool(self._store.get(TITLES_KEY, False))

    @capture_titles.setter
    def capture_titles(self, value: bool) -> None:
        self._store.set(TITLES_KEY, bool(value))

    @property
    def browser_title_parsing(self) -> bool:
        """Linux 版：用窗口标题推断浏览器域名（对应 macOS 的 AppleScript 授权）。"""
        return bool(self._store.get(BROWSER_TITLES_KEY, True))

    @browser_title_parsing.setter
    def browser_title_parsing(self, value: bool) -> None:
        self._store.set(BROWSER_TITLES_KEY, bool(value))

    @property
    def paused(self) -> bool:
        return bool(self._store.get(PAUSED_KEY, False))

    @paused.setter
    def paused(self, value: bool) -> None:
        self._store.set(PAUSED_KEY, bool(value))

    @property
    def tray_enabled(self) -> bool:
        return bool(self._store.get(TRAY_ENABLED_KEY, True))

    @tray_enabled.setter
    def tray_enabled(self, value: bool) -> None:
        self._store.set(TRAY_ENABLED_KEY, bool(value))

    # -- 每日限额（warn 语义） ------------------------------------------- #

    @property
    def limits_enabled(self) -> bool:
        return bool(self._store.get(LIMITS_ENABLED_KEY, False))

    @limits_enabled.setter
    def limits_enabled(self, value: bool) -> None:
        self._store.set(LIMITS_ENABLED_KEY, bool(value))

    @property
    def limits_daily_minutes(self) -> int:
        raw = self._store.get(LIMITS_DAILY_MIN_KEY)
        try:
            value = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            value = 0
        return value if value > 0 else 240

    @limits_daily_minutes.setter
    def limits_daily_minutes(self, value: int) -> None:
        self._store.set(LIMITS_DAILY_MIN_KEY, int(value))

    @property
    def distract_nudge_enabled(self) -> bool:
        return bool(self._store.get(DISTRACT_NUDGE_KEY, False))

    @distract_nudge_enabled.setter
    def distract_nudge_enabled(self, value: bool) -> None:
        self._store.set(DISTRACT_NUDGE_KEY, bool(value))

    # -- 提醒 ------------------------------------------------------------ #

    @property
    def break_reminder_enabled(self) -> bool:
        return bool(self._store.get(BREAK_REMINDER_KEY, True))

    @break_reminder_enabled.setter
    def break_reminder_enabled(self, value: bool) -> None:
        self._store.set(BREAK_REMINDER_KEY, bool(value))

    @property
    def break_interval_minutes(self) -> int:
        value = self._int(BREAK_INTERVAL_KEY, 0)
        return value if value >= 10 else 30

    @break_interval_minutes.setter
    def break_interval_minutes(self, value: int) -> None:
        self._store.set(BREAK_INTERVAL_KEY, int(value))

    @property
    def water_enabled(self) -> bool:
        return bool(self._store.get(WATER_ENABLED_KEY, True))

    @water_enabled.setter
    def water_enabled(self, value: bool) -> None:
        self._store.set(WATER_ENABLED_KEY, bool(value))

    @property
    def water_interval_minutes(self) -> int:
        value = self._int(WATER_INTERVAL_KEY, 0)
        return value if value >= 15 else 60

    @water_interval_minutes.setter
    def water_interval_minutes(self, value: int) -> None:
        self._store.set(WATER_INTERVAL_KEY, int(value))

    @property
    def water_start_hour(self) -> int:
        value = self._int(WATER_START_HOUR_KEY, -1)
        return value if 0 <= value <= 23 else 9

    @water_start_hour.setter
    def water_start_hour(self, value: int) -> None:
        self._store.set(WATER_START_HOUR_KEY, int(value))

    @property
    def water_end_hour(self) -> int:
        value = self._int(WATER_END_HOUR_KEY, -1)
        return value if 0 <= value <= 24 else 22

    @water_end_hour.setter
    def water_end_hour(self, value: int) -> None:
        self._store.set(WATER_END_HOUR_KEY, int(value))

    @property
    def water_goal_cups(self) -> int:
        value = self._int(WATER_GOAL_KEY, 0)
        return value if value > 0 else 8

    @water_goal_cups.setter
    def water_goal_cups(self, value: int) -> None:
        self._store.set(WATER_GOAL_KEY, int(value))

    @property
    def notifications_enabled(self) -> bool:
        return bool(self._store.get(NOTIFICATIONS_KEY, True))

    @notifications_enabled.setter
    def notifications_enabled(self, value: bool) -> None:
        self._store.set(NOTIFICATIONS_KEY, bool(value))

    @property
    def pomodoro_break_overlay(self) -> bool:
        return bool(self._store.get(POMO_BREAK_OVERLAY_KEY, True))

    @pomodoro_break_overlay.setter
    def pomodoro_break_overlay(self, value: bool) -> None:
        self._store.set(POMO_BREAK_OVERLAY_KEY, bool(value))

    @property
    def forfeit_enabled(self) -> bool:
        return bool(self._store.get(FORFEIT_ENABLED_KEY, True))

    @forfeit_enabled.setter
    def forfeit_enabled(self, value: bool) -> None:
        self._store.set(FORFEIT_ENABLED_KEY, bool(value))

    # -- 展示 ------------------------------------------------------------ #

    @property
    def limits_daily_label(self) -> str:
        return fmt_minutes_hm(self.limits_daily_minutes)

    # -- 内部 ------------------------------------------------------------ #

    def _int(self, key: str, default: int) -> int:
        raw = self._store.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
