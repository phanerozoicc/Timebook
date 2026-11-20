"""导出：CSV 明细 + Markdown 周报（写入 XDG 下载目录并用系统程序打开所在目录）。"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..core.exporter import export_csv, weekly_markdown
from ..core import models
from . import widgets as W
from datetime import timedelta  # noqa: E402


def downloads_dir() -> Path:
    """XDG 下载目录（``xdg-user-dir DOWNLOAD``，退化到 ``~/Downloads``）。"""
    try:
        out = subprocess.run(
            ["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2, check=False
        )
        candidate = out.stdout.strip()
        if candidate and candidate != str(Path.home()):
            return Path(candidate)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Downloads"


def open_folder(path: Path) -> None:
    try:
        subprocess.Popen(["xdg-open", str(path.parent)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        pass


def extract_to_downloads(window, ctx) -> tuple[Path, Path] | None:
    """Export a single live snapshot and show success or a recoverable error."""
    now = datetime.now()
    target_dir = downloads_dir()
    stamp = now.strftime("%Y%m%d-%H%M%S-%f")
    overlay = getattr(window, "_toast_overlay", None)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        rows = ctx.today_rows(now)
        csv_path = target_dir / f"timebook-detail-{stamp}.csv"
        count = export_csv(rows, csv_path)
        start = models.today_start(now) - timedelta(days=6)
        end = models.today_start(now) + timedelta(days=1)
        week = ctx.rows(start, end, now)
        focus = ctx.store.focus_events(start, end)
        report = weekly_markdown(
            now, models.per_day(week, now=now), models.by_app(week), models.by_host(week),
            models.by_category(week), pomodoros=sum(f.completed for f in focus),
            focus_seconds=sum(f.duration for f in focus if f.completed),
            cups=ctx.cups(), goal_cups=ctx.settings.water_goal_cups,
        )
        md_path = target_dir / f"timebook-weekly-{stamp}.md"
        md_path.write_text(report, encoding="utf-8")
    except OSError:
        if overlay is not None:
            W.add_translated_toast(overlay, W.translated(Adw.Toast.new(""), title=(
                "导出失败，请检查下载目录的写入权限或可用空间。",
                "Export failed. Check Downloads permissions and available space.",
            )))
        return None

    toast = W.translated(Adw.Toast.new(""),
                         title=(f"已导出 {count} 行明细与周报", f"Exported {count} rows and weekly report"),
                         button_label=("打开文件夹", "Open folder"))
    toast.connect("button-clicked", lambda _t: open_folder(csv_path))
    if overlay is not None:
        W.add_translated_toast(overlay, toast)
    return csv_path, md_path
