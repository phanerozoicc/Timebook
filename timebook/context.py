"""应用上下文：把存储、设置、各引擎和采集器装在一起。

界面层只依赖这个对象，不直接创建引擎，便于测试时替换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .core.forfeit import ForfeitStore
from .core.pomodoro import PomodoroEngine
from .core.settings import Settings
from .core.store import Store
from .core.wellbeing import LimitsEngine, RemindersEngine
from .platform.tracker import Tracker


@dataclass
class AppContext:
    store: Store
    settings: Settings
    pomodoro: PomodoroEngine
    limits: LimitsEngine
    reminders: RemindersEngine
    tracker: Tracker
    forfeit: ForfeitStore
    notifier: object | None = None
    #: 语言变化时通知界面重建
    on_language_changed: Callable[[], None] | None = None
    started_at: datetime = field(default_factory=datetime.now)

    def notify(self, title: str, body: str) -> None:
        if self.notifier is not None and hasattr(self.notifier, "send"):
            self.notifier.send(title, body)

    def rows(self, start, end, now=None):
        return self.tracker.rows(start, end, now)

    def today_rows(self, now=None):
        from .core.models import today_start

        now = now or datetime.now()
        return self.rows(today_start(now), today_start(now) + timedelta(days=1), now)

    def today_total(self) -> float:
        return self.tracker.today_seconds()

    def cups(self) -> int:
        return self.store.cups_today()

    def add_cup(self, delta: int = 1) -> int:
        return self.store.add_cup(delta)
