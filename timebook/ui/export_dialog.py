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

from ..core.exporter import export_csv, export_markdown  # noqa: E402


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


def extract_to_downloads(window, ctx) -> tuple[Path, Path]:
    """写出两份文件，返回 (csv, md)。用 Toast 反馈结果。"""
    now = datetime.now()
    target_dir = downloads_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M")

    rows = ctx.store.today_rows(now)
    csv_path = target_dir / f"timebook-detail-{stamp}.csv"
    count = export_csv(rows, csv_path)
    md_path = target_dir / f"timebook-weekly-{stamp}.md"
    export_markdown(ctx.store, md_path, now)

    toast = Adw.Toast.new(f"已导出 {count} 行明细 + 周报 → {target_dir.name}/")
    toast.set_button_label("打开文件夹")
    toast.connect("button-clicked", lambda _t: open_folder(csv_path))
    overlay = getattr(window, "_toast_overlay", None)
    if overlay is not None:
        overlay.add_toast(toast)
    return csv_path, md_path
