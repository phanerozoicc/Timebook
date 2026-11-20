"""本地存储：SQLite 单文件（对应 macOS 版的 SwiftData store）。

设计要点
--------
* 一个文件即全部数据，拷走即备份（``~/.local/share/timebook/timebook.db``）。
* 线程安全：tracker 轮询可能在后台线程跑，故连接用 ``check_same_thread=False``
  + ``RLock`` 串行化。
* 时间戳存 Unix epoch（REAL），对外用本地朴素 datetime，与 ``models.EventRow``
  约定一致。
* WAL 模式：崩溃后不丢已提交数据。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .models import EventRow, FocusRow, clipped_rows

SCHEMA_VERSION = 1
APP_DIR_NAME = "timebook"
DB_NAME = "timebook.db"


def default_data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def default_db_path() -> Path:
    override = os.environ.get("TIMEBOOK_DB")
    if override:
        return Path(override)
    return default_data_dir() / DB_NAME


_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id   TEXT NOT NULL,
    app_name TEXT NOT NULL,
    detail   TEXT,
    host     TEXT,
    title    TEXT,
    start_ts REAL NOT NULL,
    end_ts   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_start ON usage_events(start_ts);
CREATE INDEX IF NOT EXISTS idx_usage_end   ON usage_events(end_ts);
CREATE INDEX IF NOT EXISTS idx_usage_app   ON usage_events(app_id);

CREATE TABLE IF NOT EXISTS focus_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts    REAL NOT NULL,
    end_ts      REAL NOT NULL,
    completed   INTEGER NOT NULL DEFAULT 0,
    preset_name TEXT NOT NULL DEFAULT 'classic'
);
CREATE INDEX IF NOT EXISTS idx_focus_start ON focus_events(start_ts);

CREATE TABLE IF NOT EXISTS water_logs (
    day_key TEXT PRIMARY KEY,
    cups    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS forfeit_days (
    day_key    TEXT PRIMARY KEY,
    lost_hours TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _ts(dt: datetime) -> float:
    return dt.timestamp()


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts)


class Store:
    """SQLite 存储。``path`` 传 ``":memory:"`` 可得到纯内存库（测试用）。"""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = default_db_path()
        if str(path) == ":memory:":
            self.path: Path | None = None
            target = ":memory:"
        else:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self.path = p
            target = str(p)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(target, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        if target != ":memory:":
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.DatabaseError:
                pass
        self._migrate()

    # -- 生命周期 -------------------------------------------------------- #

    def _migrate(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            current = self.get("schema_version")
            if current is None:
                self.set("schema_version", SCHEMA_VERSION)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def size_bytes(self) -> int:
        if self.path is None or not self.path.exists():
            return 0
        return self.path.stat().st_size

    def vacuum(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.execute("VACUUM")

    # -- 写入：使用记录 -------------------------------------------------- #

    def add_event(
        self,
        app_id: str,
        app_name: str,
        start: datetime,
        end: datetime,
        detail: str | None = None,
        host: str | None = None,
        title: str | None = None,
    ) -> int:
        if end < start:
            end = start
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO usage_events(app_id, app_name, detail, host, title, start_ts, end_ts)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (app_id, app_name, detail, host, title, _ts(start), _ts(end)),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    # -- 读取：使用记录 -------------------------------------------------- #

    def rows(self, start: datetime, end: datetime) -> list[EventRow]:
        """与 [start, end) 有交集的行，按开始时间倒序（对齐 Swift ``Store.rows``）。"""
        with self._lock:
            cur = self._conn.execute(
                "SELECT app_id, app_name, detail, host, title, start_ts, end_ts"
                " FROM usage_events WHERE end_ts > ? AND start_ts < ?"
                " ORDER BY start_ts DESC",
                (_ts(start), _ts(end)),
            )
            return clipped_rows([self._row(r) for r in cur.fetchall()], start, end)

    def rows_overlapping(self, start: datetime, end: datetime) -> list[EventRow]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT app_id, app_name, detail, host, title, start_ts, end_ts"
                " FROM usage_events WHERE end_ts > ? AND start_ts < ?"
                " ORDER BY start_ts DESC",
                (_ts(start), _ts(end)),
            )
            return clipped_rows([self._row(r) for r in cur.fetchall()], start, end)

    def rows_for_day(self, day: date) -> list[EventRow]:
        start = datetime(day.year, day.month, day.day)
        return self.rows(start, start + timedelta(days=1))

    def today_rows(self, now: datetime | None = None) -> list[EventRow]:
        now = now or datetime.now()
        return self.rows_for_day(now.date())

    def known_apps(self) -> list[tuple[str, str]]:
        """历史出现过的应用（用于排除列表），按最近使用排序。"""
        with self._lock:
            cur = self._conn.execute(
                "SELECT app_id, app_name, MAX(start_ts) AS last_ts FROM usage_events"
                " GROUP BY app_id ORDER BY last_ts DESC"
            )
            return [(r["app_id"], r["app_name"]) for r in cur.fetchall()]

    def delete_older_than(self, days: int, now: datetime | None = None) -> int:
        """数据保留期清理。``days <= 0`` 表示永久保留。返回删除行数。"""
        if days <= 0:
            return 0
        now = now or datetime.now()
        cutoff = now - timedelta(days=days)
        with self._lock:
            cur = self._conn.execute("DELETE FROM usage_events WHERE end_ts < ?", (_ts(cutoff),))
            self._conn.execute("DELETE FROM focus_events WHERE end_ts < ?", (_ts(cutoff),))
            self._conn.commit()
            return int(cur.rowcount or 0)

    def count_events(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) AS n FROM usage_events")
            return int(cur.fetchone()["n"])

    # -- 专注段 ---------------------------------------------------------- #

    def record_focus(
        self, start: datetime, end: datetime, completed: bool, preset_name: str = "classic"
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO focus_events(start_ts, end_ts, completed, preset_name)"
                " VALUES (?, ?, ?, ?)",
                (_ts(start), _ts(end), 1 if completed else 0, preset_name),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def focus_events(self, start: datetime, end: datetime) -> list[FocusRow]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT start_ts, end_ts, completed, preset_name FROM focus_events"
                " WHERE end_ts >= ? AND end_ts < ? ORDER BY start_ts DESC",
                (_ts(start), _ts(end)),
            )
            return [
                FocusRow(
                    start=_dt(r["start_ts"]),
                    end=_dt(r["end_ts"]),
                    completed=bool(r["completed"]),
                    preset_name=r["preset_name"],
                )
                for r in cur.fetchall()
            ]

    def focus_for_day(self, day: date) -> list[FocusRow]:
        start = datetime(day.year, day.month, day.day)
        return self.focus_events(start, start + timedelta(days=1))

    # -- 喝水 ------------------------------------------------------------ #

    @staticmethod
    def day_key(dt: datetime | None = None) -> str:
        dt = dt or datetime.now()
        return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"

    def cups_on(self, day_key: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT cups FROM water_logs WHERE day_key = ?", (day_key,)
            )
            row = cur.fetchone()
            return int(row["cups"]) if row else 0

    def cups_today(self, now: datetime | None = None) -> int:
        return self.cups_on(self.day_key(now))

    def add_cup(self, delta: int = 1, now: datetime | None = None) -> int:
        key = self.day_key(now)
        with self._lock:
            cur = self._conn.execute("SELECT cups FROM water_logs WHERE day_key = ?", (key,))
            row = cur.fetchone()
            cups = max(0, (int(row["cups"]) if row else 0) + delta)
            self._conn.execute(
                "INSERT INTO water_logs(day_key, cups) VALUES (?, ?)"
                " ON CONFLICT(day_key) DO UPDATE SET cups = excluded.cups",
                (key, cups),
            )
            self._conn.commit()
            return cups

    # -- 丢小时（Forfeit） ----------------------------------------------- #

    def lost_hours(self, day_key: str) -> set[int]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT lost_hours FROM forfeit_days WHERE day_key = ?", (day_key,)
            )
            row = cur.fetchone()
        if not row:
            return set()
        try:
            return {int(h) for h in json.loads(row["lost_hours"]) if 0 <= int(h) < 24}
        except (ValueError, TypeError):
            return set()

    def set_lost_hours(self, day_key: str, hours: Iterable[int]) -> None:
        payload = json.dumps(sorted({int(h) for h in hours if 0 <= int(h) < 24}))
        with self._lock:
            self._conn.execute(
                "INSERT INTO forfeit_days(day_key, lost_hours) VALUES (?, ?)"
                " ON CONFLICT(day_key) DO UPDATE SET lost_hours = excluded.lost_hours",
                (day_key, payload),
            )
            self._conn.commit()

    def prune_forfeit_days(self, keep_days: int = 60, now: datetime | None = None) -> int:
        if keep_days <= 0:
            return 0
        now = now or datetime.now()
        cutoff = (now.date() - timedelta(days=keep_days)).isoformat()
        with self._lock:
            cur = self._conn.execute("DELETE FROM forfeit_days WHERE day_key < ?", (cutoff,))
            self._conn.commit()
            return int(cur.rowcount or 0)

    # -- 键值（设置） ---------------------------------------------------- #

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            cur = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,))
            row = cur.fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv(key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, payload),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._conn.commit()

    # -- 内部 ------------------------------------------------------------ #

    @staticmethod
    def _row(r: sqlite3.Row) -> EventRow:
        return EventRow(
            app_id=r["app_id"],
            app_name=r["app_name"],
            start=_dt(r["start_ts"]),
            end=_dt(r["end_ts"]),
            detail=r["detail"],
            host=r["host"],
            title=r["title"],
        )
