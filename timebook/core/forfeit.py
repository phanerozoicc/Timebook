"""丢小时（Forfeit）：一天 24 格，分心应用在某小时被切到前台，该小时整格记「荒」。

移植自 ``Sources/Forfeit.swift`` 的纯逻辑部分（``HourLedger`` +
``ForfeitRules``）。macOS 版里锁屏/休眠监听属于 AppKit，这里只保留可注入的
抑制态开关（``suppress`` / ``resume_from_suppression``），由 platform 层驱动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

from .categories import ALL as ALL_CATEGORIES
from .categories import for_host

KEEP_DAYS = 60


class ToggleOutcome(str, Enum):
    NOW_LOST = "now-lost"
    NOW_KEPT = "now-kept"
    REJECTED = "rejected"


@dataclass
class DayRecord:
    lost: set[int] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"lost": sorted(self.lost)}

    @classmethod
    def from_dict(cls, data: dict) -> "DayRecord":
        hours = data.get("lost", []) if isinstance(data, dict) else []
        return cls(lost={int(h) for h in hours if 0 <= int(h) <= 23})


class HourLedger:
    """纯逻辑小时账本：不依赖 GUI；时钟与「日历」都可注入。"""

    keep_days = KEEP_DAYS

    def __init__(
        self,
        days: dict[str, DayRecord] | None = None,
        now_fn=datetime.now,
    ) -> None:
        self.days: dict[str, DayRecord] = dict(days or {})
        self._now = now_fn
        self.prune_if_needed()

    # -- 基础 ------------------------------------------------------------ #

    def day_key(self, dt: datetime | None = None) -> str:
        dt = dt or self._now()
        return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"

    @property
    def current_day_key(self) -> str:
        return self.day_key()

    def current_hour(self, dt: datetime | None = None) -> int:
        return (dt or self._now()).hour

    # -- 写入 ------------------------------------------------------------ #

    def mark_lost(self, dt: datetime | None = None) -> bool:
        """分心应用此刻激活：把所在小时记为荒。幂等，返回是否新标记。"""
        dt = dt or self._now()
        key = self.day_key(dt)
        hour = dt.hour
        record = self.days.setdefault(key, DayRecord())
        if hour in record.lost:
            return False
        record.lost.add(hour)
        self.prune_if_needed()
        return True

    def toggle(self, day: str, hour: int) -> ToggleOutcome:
        """手动改判（点击格子）：未来小时拒绝；荒↔守互换。"""
        if not 0 <= hour <= 23:
            return ToggleOutcome.REJECTED
        if day == self.current_day_key and hour > self.current_hour():
            return ToggleOutcome.REJECTED
        record = self.days.setdefault(day, DayRecord())
        if hour in record.lost:
            record.lost.discard(hour)
            return ToggleOutcome.NOW_KEPT
        record.lost.add(hour)
        return ToggleOutcome.NOW_LOST

    # -- 查询 ------------------------------------------------------------ #

    def lost_hours(self, day: str) -> set[int]:
        record = self.days.get(day)
        return set(record.lost) if record else set()

    @property
    def today_lost_count(self) -> int:
        return len(self.lost_hours(self.current_day_key))

    def last_n_days(self, n: int) -> list[tuple[str, set[int]]]:
        """最近 n 天（含今天，旧→新）。"""
        today = self._now().date()
        result: list[tuple[str, set[int]]] = []
        for offset in range(n - 1, -1, -1):
            day = today - timedelta(days=offset)
            key = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
            result.append((key, self.lost_hours(key)))
        return result

    def total_lost(self, days: int) -> int:
        return sum(len(hours) for _, hours in self.last_n_days(days))

    def last_n_day_bars(self, n: int) -> list[tuple[date, float]]:
        today = self._now().date()
        bars: list[tuple[date, float]] = []
        for offset in range(n - 1, -1, -1):
            day = today - timedelta(days=offset)
            key = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
            bars.append((day, float(len(self.lost_hours(key)))))
        return bars

    def clean_streak(self) -> int:
        """连续干净天：今天干净则含今天，否则从昨天往前数。"""
        today = self._now().date()
        offset = 0 if not self.lost_hours(self.day_key()) else 1
        streak = 0
        while offset < self.keep_days:
            day = today - timedelta(days=offset)
            key = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
            if self.lost_hours(key):
                break
            streak += 1
            offset += 1
        return streak

    # -- 维护 ------------------------------------------------------------ #

    def prune_if_needed(self, max_days: int | None = None) -> int:
        """只保留最近 ``max_days`` 天（按日期键排序）。"""
        max_days = self.keep_days if max_days is None else max_days
        keys = sorted(self.days)
        if len(keys) <= max_days:
            return 0
        drop = keys[: len(keys) - max_days]
        for key in drop:
            self.days.pop(key, None)
        return len(drop)

    def to_dict(self) -> dict:
        return {"days": {k: v.to_dict() for k, v in self.days.items()}}

    @classmethod
    def from_dict(cls, data: dict | None, now_fn=datetime.now) -> "HourLedger":
        days: dict[str, DayRecord] = {}
        if isinstance(data, dict):
            for key, value in (data.get("days") or {}).items():
                days[key] = DayRecord.from_dict(value)
        return cls(days=days, now_fn=now_fn)


# --------------------------------------------------------------------------- #
# 判定规则（纯函数，可测）
# --------------------------------------------------------------------------- #


DEFAULT_CATEGORIES: set[str] = {c.id for c in ALL_CATEGORIES if c.distracting}


@dataclass(frozen=True, slots=True)
class Verdict:
    kind: str  # "app" | "site"
    name: str = ""
    host: str = ""


def verdict(
    app_id: str,
    host: str | None,
    *,
    is_browser,
    distractor_apps: set[str],
    custom_domains: list[str],
    enabled_categories: set[str],
) -> Verdict | None:
    """应用名单优先全时判；浏览器按「自定义网站 → 网址类目」判，「其他」永不判。"""
    if app_id in distractor_apps:
        return Verdict("app", name=app_id)
    if not host or not is_browser(app_id):
        return None
    lowered = host.lower()
    for domain in custom_domains:
        if lowered == domain or lowered.endswith("." + domain):
            return Verdict("site", name="自定义", host=host)
    category = for_host(host)
    if category.id == "other" or category.id not in enabled_categories:
        return None
    return Verdict("site", name=category.name, host=host)


def normalize_domain(raw: str) -> str | None:
    """规整用户输入的域名：去 scheme/路径/空白/结尾点，小写。无效返回 None。"""
    import re

    value = (raw or "").strip().lower()
    value = re.sub(r"^[a-z]+://", "", value)
    value = value.split("/", 1)[0]
    value = value.rstrip(".")
    if not value or " " in value or "." not in value:
        return None
    return value


class ForfeitStore:
    """账本 + 分心名单的持久化包装（数据落在 ``Store`` 的 kv / forfeit_days 表）。"""

    def __init__(self, store, now_fn=datetime.now) -> None:
        self._store = store
        self._now = now_fn
        raw = store.get("forfeitState")
        self.ledger = self._load_ledger(store, now_fn)
        state = raw if isinstance(raw, dict) else {}
        self.distractor_apps: set[str] = set(state.get("distractors", []) or [])
        cats = state.get("categories")
        self.enabled_categories: set[str] = set(cats) if cats is not None else set(DEFAULT_CATEGORIES)
        self.custom_domains: list[str] = list(state.get("customDomains", []) or [])
        self.suppressed = False
        self._awaiting_input = True

    # -- 抑制态（锁屏/休眠/唤醒后防躺枪） -------------------------------- #

    def suppress(self) -> None:
        self.suppressed = True
        self._awaiting_input = True

    def resume_from_suppression(self) -> None:
        self.suppressed = False
        self._awaiting_input = False

    def note_real_input(self) -> None:
        """一次真实键鼠输入后解除抑制。"""
        self._awaiting_input = False

    @property
    def can_judge(self) -> bool:
        return not self.suppressed and not self._awaiting_input

    # -- 判定 ------------------------------------------------------------ #

    def evaluate(self, app_id: str, host: str | None) -> Verdict | None:
        if not self.can_judge:
            return None
        from ..platform.browsers import is_browser

        return verdict(
            app_id,
            host,
            is_browser=is_browser,
            distractor_apps=self.distractor_apps,
            custom_domains=self.custom_domains,
            enabled_categories=self.enabled_categories,
        )

    def observe(self, app_id: str, host: str | None, now: datetime | None = None) -> bool:
        """采集循环每次分段变化时调用；命中则把当前小时记荒。"""
        hit = self.evaluate(app_id, host)
        if hit is None:
            return False
        return self.ledger.mark_lost(now or self._now())

    # -- 名单编辑 -------------------------------------------------------- #

    def toggle_category(self, category_id: str) -> bool:
        if category_id == "other" or not any(c.id == category_id for c in ALL_CATEGORIES):
            return category_id in self.enabled_categories
        if category_id in self.enabled_categories:
            self.enabled_categories.discard(category_id)
        else:
            self.enabled_categories.add(category_id)
        self.save()
        return category_id in self.enabled_categories

    def add_custom_domain(self, raw: str) -> bool:
        domain = normalize_domain(raw)
        if not domain or domain in self.custom_domains:
            return False
        self.custom_domains.append(domain)
        self.save()
        return True

    def remove_custom_domain(self, domain: str) -> None:
        self.custom_domains = [d for d in self.custom_domains if d != domain]
        self.save()

    def add_distractor(self, app_id: str) -> None:
        self.distractor_apps.add(app_id)
        self.save()

    def remove_distractor(self, app_id: str) -> None:
        self.distractor_apps.discard(app_id)
        self.save()

    # -- 持久化 ---------------------------------------------------------- #

    @staticmethod
    def _load_ledger(store, now_fn) -> HourLedger:
        """从 ``forfeit_days`` 表恢复账本（每天一行，JSON 小时数组）。"""
        days: dict[str, DayRecord] = {}
        try:
            with store._lock:  # noqa: SLF001 - 同包内部访问
                cur = store._conn.execute("SELECT day_key, lost_hours FROM forfeit_days")  # noqa: SLF001
                for row in cur.fetchall():
                    hours = set()
                    try:
                        import json

                        hours = {int(h) for h in json.loads(row["lost_hours"]) if 0 <= int(h) < 24}
                    except (ValueError, TypeError):
                        hours = set()
                    days[row["day_key"]] = DayRecord(lost=hours)
        except Exception:  # pragma: no cover - 老库/损坏时退回空账本
            days = {}
        return HourLedger(days=days, now_fn=now_fn)

    def save(self) -> None:
        # 账本落到 forfeit_days 表；名单配置落到 kv
        for key, record in self.ledger.days.items():
            self._store.set_lost_hours(key, record.lost)
        self._store.set(
            "forfeitState",
            {
                "distractors": sorted(self.distractor_apps),
                "categories": sorted(self.enabled_categories),
                "customDomains": sorted(self.custom_domains),
            },
        )
