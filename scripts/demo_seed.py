"""生成演示数据：让界面在没有真实使用记录时也有内容可看。

用法::

    python3 scripts/demo_seed.py --db /tmp/demo.db --days 14
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timebook.core.store import Store  # noqa: E402

APPS = [
    ("google-chrome", "Google Chrome", ["github.com", "stackoverflow.com", "youtube.com", "news.ycombinator.com", "bilibili.com"]),
    ("code", "Visual Studio Code", [None]),
    ("firefox", "Firefox", ["reddit.com", "developer.mozilla.org", "x.com"]),
    ("org.gnome.Nautilus", "Files", [None]),
    ("slack", "Slack", [None]),
    ("org.gnome.Terminal", "Terminal", [None]),
    ("spotify", "Spotify", [None]),
    ("notion", "Notion", [None]),
]
TITLES = {
    "github.com": "Pull request #42 · GitHub",
    "stackoverflow.com": "How do I fix a segfault? - Stack Overflow",
    "youtube.com": "Lo-fi beats to relax to - YouTube",
    "news.ycombinator.com": "Hacker News",
    "bilibili.com": "【原创】Linux 桌面美化 - 哔哩哔哩",
    "reddit.com": "r/linux · Reddit",
    "developer.mozilla.org": "Array.prototype.map() - MDN",
    "x.com": "Home / X",
}


def seed(db_path: str, days: int = 14, seed_value: int = 7, reset: bool = True) -> None:
    rng = random.Random(seed_value)
    if reset:
        # 重新生成前先清空，避免旧数据（含真实采集）污染演示结果
        target = Path(db_path)
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(target) + suffix)
            if candidate.exists():
                candidate.unlink()
    store = Store(db_path)
    now = datetime.now()
    today = datetime(now.year, now.month, now.day)

    for day_offset in range(days - 1, -1, -1):
        day = today - timedelta(days=day_offset)
        if day.weekday() >= 5 and rng.random() < 0.35:
            continue  # 周末偶尔躺平
        cursor = day + timedelta(hours=8, minutes=rng.randint(0, 90))
        end_of_day = day + timedelta(hours=22)
        target = rng.uniform(2.0, 8.5) * 3600
        spent = 0.0
        while spent < target and cursor < end_of_day:
            app_id, app_name, hosts = rng.choice(APPS)
            host = rng.choice(hosts) if hosts else None
            duration = rng.uniform(180, 2400)
            if host and host in TITLES:
                title = TITLES[host]
            else:
                title = rng.choice([app_name, f"{app_name} — 项目", "未命名"])
            end = cursor + timedelta(seconds=duration)
            store.add_event(app_id, app_name, cursor, end, detail=host, host=host, title=title)
            spent += duration
            cursor = end + timedelta(minutes=rng.randint(1, 25))

        # 番茄记录
        for _ in range(rng.randint(0, 5)):
            start = day + timedelta(hours=rng.randint(9, 18), minutes=rng.randint(0, 50))
            store.record_focus(start, start + timedelta(minutes=40), rng.random() < 0.85, "classic")
        # 喝水（每天一行）
        cups = rng.randint(2, 8)
        store.add_cup(cups, now=day + timedelta(hours=20))

    # 丢小时：随机几个小时
    for day_offset in range(min(days, 14)):
        day = today - timedelta(days=day_offset)
        key = day.strftime("%Y-%m-%d")
        lost = set(rng.sample(range(9, 23), k=rng.randint(0, 3)))
        store.set_lost_hours(key, lost)

    # 番茄状态：留一个待机
    store.set("pomodoroPreset", "classic")
    store.set("pomodoroAutoBreaks", True)
    store.set("pomodoroAutoWork", False)

    # 默认设置：打开限额与分心提醒，便于展示
    store.set("limitsEnabled", True)
    store.set("limitsDailyMin", 240)
    store.set("distractNudge", True)

    print(f"演示数据已写入 {db_path}（{store.count_events()} 条使用记录，{days} 天）")
    store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Timebook 演示数据")
    parser.add_argument("--db", default=os.environ.get("TIMEBOOK_DB", "/tmp/timebook-demo.db"))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    seed(args.db, args.days, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
