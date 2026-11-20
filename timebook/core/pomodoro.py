"""番茄钟：work → short/long break 循环。

移植自 macOS 版 ``Sources/Pomodoro.swift``（状态机语义 1:1 保留）：
``idle`` → ``work`` → ``short``/``long`` → ``work``…，并支持 ``*-ready``
「待开始」阶段（不自动开始时的暂停点）。

与 Swift 版的差异只在宿主细节：``DispatchSourceTimer`` 换成由 GTK 主循环驱动
的 ``tick()``；``UserDefaults`` 换成 ``Store`` 的 kv 表。时钟通过 ``now_fn``
注入，因此状态机可以在测试里瞬间推进。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable

from .l10n import T

KV_STATE = "pomodoroState"
KV_PRESET = "pomodoroPreset"
KV_AUTO_BREAKS = "pomodoroAutoBreaks"
KV_AUTO_WORK = "pomodoroAutoWork"


class PomodoroPhase(str, Enum):
    """阶段（raw value 与 macOS 版、快照 JSON 对齐）。"""

    IDLE = "idle"
    WORK = "work"
    SHORT = "short"
    LONG = "long"
    WORK_READY = "work-ready"
    SHORT_READY = "short-ready"
    LONG_READY = "long-ready"

    @property
    def is_running(self) -> bool:
        return self in (PomodoroPhase.WORK, PomodoroPhase.SHORT, PomodoroPhase.LONG)

    @property
    def is_break(self) -> bool:
        return self in (PomodoroPhase.SHORT, PomodoroPhase.LONG)

    @property
    def ready_base(self) -> "PomodoroPhase | None":
        """``work-ready`` → ``work``（手动开始待开始的下一阶段）。"""
        return {
            PomodoroPhase.WORK_READY: PomodoroPhase.WORK,
            PomodoroPhase.SHORT_READY: PomodoroPhase.SHORT,
            PomodoroPhase.LONG_READY: PomodoroPhase.LONG,
        }.get(self)

    @property
    def label(self) -> str:
        return {
            PomodoroPhase.IDLE: T("待机", "Idle"),
            PomodoroPhase.WORK: T("专注", "Focus"),
            PomodoroPhase.SHORT: T("短休", "Short break"),
            PomodoroPhase.LONG: T("长休", "Long break"),
            PomodoroPhase.WORK_READY: T("准备专注", "Focus ready"),
            PomodoroPhase.SHORT_READY: T("准备短休", "Short-break ready"),
            PomodoroPhase.LONG_READY: T("准备长休", "Long-break ready"),
        }[self]


@dataclass(frozen=True, slots=True)
class PomodoroPreset:
    work_min: int = 40
    short_break_min: int = 5
    long_break_min: int = 15
    rounds: int = 4

    @property
    def work_seconds(self) -> int:
        return self.work_min * 60


PRESETS: dict[str, PomodoroPreset] = {
    "classic": PomodoroPreset(40, 5, 15, 4),
    "sprint": PomodoroPreset(15, 3, 10, 4),
    "deep": PomodoroPreset(50, 10, 20, 3),
    "custom": PomodoroPreset(30, 5, 15, 4),
}

#: 预设选择器顺序（中文为源语言）。
PRESET_NAMES: list[tuple[str, tuple[str, str]]] = [
    ("classic", ("经典 40/5", "Classic 40/5")),
    ("sprint", ("冲刺 15/3", "Sprint 15/3")),
    ("deep", ("深度 50/10", "Deep 50/10")),
    ("custom", ("自定义 30/5", "Custom 30/5")),
]


@dataclass
class PomodoroState:
    phase: PomodoroPhase = PomodoroPhase.IDLE
    round: int = 1
    ends_at: datetime | None = None
    paused: bool = False
    paused_remaining: float = 0.0

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "round": self.round,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "paused": self.paused,
            "paused_remaining": self.paused_remaining,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PomodoroState":
        phase_raw = data.get("phase", "idle")
        try:
            phase = PomodoroPhase(phase_raw)
        except ValueError:
            phase = PomodoroPhase.IDLE
        ends_raw = data.get("ends_at")
        ends_at: datetime | None = None
        if ends_raw:
            try:
                ends_at = datetime.fromisoformat(ends_raw)
            except (TypeError, ValueError):
                ends_at = None
        return cls(
            phase=phase,
            round=int(data.get("round", 1) or 1),
            ends_at=ends_at,
            paused=bool(data.get("paused", False)),
            paused_remaining=float(data.get("paused_remaining", 0.0) or 0.0),
        )


@dataclass
class WorkSegment:
    """一次落到统计里的专注段（含手动跳过的）。"""

    start: datetime
    end: datetime
    completed: bool
    preset_name: str = "classic"

    @property
    def duration(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


class PomodoroEngine:
    """番茄钟状态机。

    Parameters
    ----------
    store:
        ``timebook.core.store.Store``，用于状态/预设持久化（kv）。
    now_fn:
        时钟注入，默认 ``datetime.now``。
    """

    def __init__(self, store, now_fn: Callable[[], datetime] = datetime.now) -> None:
        self._store = store
        self._now = now_fn
        self.now: datetime = now_fn()

        #: 统计落点：专注段开始/结束/是否完整完成。
        self.on_work_segment: Callable[[WorkSegment], None] | None = None
        #: 通知落点：标题 / 内容。
        self.on_notify: Callable[[str, str], None] | None = None
        #: 状态变化（供快照/菜单刷新）。
        self.on_state_change: Callable[[], None] | None = None
        #: 进入休息阶段（短休/长休开始，含手动）——供联动（微休息/重置活跃计时）。
        self.on_break_start: Callable[[], None] | None = None

        self.state = self._load_state()

    # -- 持久化 ---------------------------------------------------------- #

    def _load_state(self) -> PomodoroState:
        raw = self._store.get(KV_STATE)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = None
        if isinstance(raw, dict):
            return PomodoroState.from_dict(raw)
        return PomodoroState()

    def _persist(self) -> None:
        self._store.set(KV_STATE, json.dumps(self.state.to_dict(), ensure_ascii=False))
        if self.on_state_change:
            self.on_state_change()

    # -- 配置 ------------------------------------------------------------ #

    @property
    def active_preset_name(self) -> str:
        value = self._store.get(KV_PRESET, "classic")
        return value if value in PRESETS else "classic"

    @active_preset_name.setter
    def active_preset_name(self, value: str) -> None:
        self._store.set(KV_PRESET, value if value in PRESETS else "classic")
        if self.on_state_change:
            self.on_state_change()

    @property
    def preset(self) -> PomodoroPreset:
        return PRESETS.get(self.active_preset_name, PRESETS["classic"])

    @property
    def auto_start_breaks(self) -> bool:
        value = self._store.get(KV_AUTO_BREAKS)
        return True if value is None else bool(value)

    @auto_start_breaks.setter
    def auto_start_breaks(self, value: bool) -> None:
        self._store.set(KV_AUTO_BREAKS, bool(value))
        if self.on_state_change:
            self.on_state_change()

    @property
    def auto_start_work(self) -> bool:
        value = self._store.get(KV_AUTO_WORK)
        return False if value is None else bool(value)

    @auto_start_work.setter
    def auto_start_work(self, value: bool) -> None:
        self._store.set(KV_AUTO_WORK, bool(value))
        if self.on_state_change:
            self.on_state_change()

    # -- 命令 ------------------------------------------------------------ #

    def start(self, now: datetime | None = None) -> None:
        now = now or self._now()
        self.state.round = 1
        self._begin_phase(PomodoroPhase.WORK, now)

    def pause(self, now: datetime | None = None) -> None:
        now = now or self._now()
        if not self.state.phase.is_running or self.state.paused:
            return
        self.state.paused = True
        self.state.paused_remaining = max(
            0.0, ((self.state.ends_at or now) - now).total_seconds()
        )
        self._persist()

    def resume(self, now: datetime | None = None) -> None:
        now = now or self._now()
        if not self.state.paused:
            return
        self.now = now
        self.state.paused = False
        self.state.ends_at = now + timedelta(seconds=self.state.paused_remaining)
        self._persist()

    def reset(self) -> None:
        self.state = PomodoroState()
        self._persist()

    def skip(self, now: datetime | None = None) -> None:
        now = now or self._now()
        if not self.state.phase.is_running:
            return
        self._complete(skipped=True, now=now)

    def begin_ready(self, now: datetime | None = None) -> None:
        """手动开始「待开始」的下一阶段。"""
        now = now or self._now()
        base = self.state.phase.ready_base
        if base is None:
            return
        self._begin_phase(base, now)

    def toggle(self, now: datetime | None = None) -> None:
        """一个按钮搞定开始/暂停/继续/开始下一阶段。"""
        now = now or self._now()
        if self.state.phase is PomodoroPhase.IDLE:
            self.start(now)
        elif self.state.phase.ready_base is not None:
            self.begin_ready(now)
        elif self.state.paused:
            self.resume(now)
        else:
            self.pause(now)

    # -- 引擎 ------------------------------------------------------------ #

    def tick(self, now: datetime | None = None) -> None:
        now = now or self._now()
        self.now = now
        if (
            self.state.phase.is_running
            and not self.state.paused
            and self.state.ends_at is not None
            and now >= self.state.ends_at
        ):
            self._complete(skipped=False, now=now)

    @property
    def remain(self) -> float:
        if not self.state.phase.is_running:
            return 0.0
        if self.state.paused:
            return self.state.paused_remaining
        if self.state.ends_at is None:
            return 0.0
        return max(0.0, (self.state.ends_at - self.now).total_seconds())

    @property
    def phase_total(self) -> float:
        """当前阶段总时长（画进度环用；ready/idle 阶段按工作时长展示）。"""
        preset = self.preset
        if self.state.phase in (PomodoroPhase.WORK, PomodoroPhase.WORK_READY, PomodoroPhase.IDLE):
            minutes = preset.work_min
        elif self.state.phase in (PomodoroPhase.SHORT, PomodoroPhase.SHORT_READY):
            minutes = preset.short_break_min
        else:
            minutes = preset.long_break_min
        return float(minutes * 60)

    @property
    def progress(self) -> float:
        """已完成的阶段比例 0..1（环形进度用）。"""
        total = self.phase_total
        if total <= 0:
            return 0.0
        if not self.state.phase.is_running or self.state.phase.ready_base is not None:
            return 0.0
        return min(1.0, max(0.0, 1.0 - self.remain / total))

    @property
    def remain_clock(self) -> str:
        total = int(round(self.remain))
        return f"{total // 60:02d}:{total % 60:02d}"

    def _begin_phase(self, phase: PomodoroPhase, now: datetime) -> None:
        self.now = now
        preset = self.preset
        if phase is PomodoroPhase.WORK:
            minutes = preset.work_min
        elif phase is PomodoroPhase.SHORT:
            minutes = preset.short_break_min
        elif phase is PomodoroPhase.LONG:
            minutes = preset.long_break_min
        else:
            minutes = preset.work_min
        self.state.phase = phase
        self.state.paused = False
        self.state.paused_remaining = 0.0
        self.state.ends_at = now + timedelta(minutes=minutes)
        self._persist()
        if phase.is_break and self.on_break_start:
            self.on_break_start()

    def _complete(self, skipped: bool, now: datetime) -> None:
        if self.state.phase is PomodoroPhase.WORK:
            preset = self.preset
            planned = self.state.ends_at or now
            started_at = planned - timedelta(minutes=preset.work_min)
            ended_at = (planned - timedelta(seconds=self.state.paused_remaining)
                        if skipped and self.state.paused else now if skipped else planned)
            worked = max(0.0, min((ended_at - started_at).total_seconds(), preset.work_seconds))
            segment = WorkSegment(
                start=started_at,
                end=started_at + timedelta(seconds=worked),
                completed=not skipped,
                preset_name=self.active_preset_name,
            )
            if self.on_work_segment:
                self.on_work_segment(segment)

            is_long = self.state.round >= preset.rounds
            self.state.round = 1 if is_long else self.state.round + 1
            nxt = PomodoroPhase.LONG if is_long else PomodoroPhase.SHORT
            if is_long:
                self._notify(
                    T("该长休啦 ☕️", "Long break time ☕️"),
                    T(
                        f"完成 {preset.rounds} 轮专注，休息 {preset.long_break_min} 分钟",
                        f"{preset.rounds} rounds done — rest {preset.long_break_min} min",
                    ),
                )
            else:
                self._notify(
                    T("番茄完成 🍅", "Pomodoro done 🍅"),
                    T(
                        f"休息 {preset.short_break_min} 分钟，顺便喝口水",
                        f"Rest {preset.short_break_min} min — grab some water",
                    ),
                )
            if skipped or self.auto_start_breaks:
                self._begin_phase(nxt, now)
            else:
                self.state.phase = self._ready_variant(nxt)
                self.state.ends_at = None
                self._persist()
        elif self.state.phase.is_break:
            self._notify(
                T("休息结束 🙌", "Break over 🙌"),
                T("准备好开始下一个番茄了吗？", "Ready for the next pomodoro?"),
            )
            if self.auto_start_work:
                self._begin_phase(PomodoroPhase.WORK, now)
            else:
                self.state.phase = PomodoroPhase.WORK_READY
                self.state.ends_at = None
                self._persist()

    def _notify(self, title: str, body: str) -> None:
        if self.on_notify:
            self.on_notify(title, body)

    @staticmethod
    def _ready_variant(phase: PomodoroPhase) -> PomodoroPhase:
        if phase is PomodoroPhase.SHORT:
            return PomodoroPhase.SHORT_READY
        if phase is PomodoroPhase.LONG:
            return PomodoroPhase.LONG_READY
        return PomodoroPhase.WORK_READY
