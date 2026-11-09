"""文件日志：``~/.local/state/timebook/timebook.log``（INFO/DEBUG/ERROR）。

对应 macOS 版 ``AppLog``：覆盖启动、应用切换、番茄阶段转换、提醒触发、导出，
并挂上未捕获异常钩子，保证「无声退出」可追溯。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path


def log_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "timebook"


def setup_logging(level: int | None = None, console: bool = True) -> Path | None:
    """初始化日志，返回日志文件路径。"""
    directory = log_dir()
    path = directory / "timebook.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 目录不可写（只读家目录 / 沙箱）时退化为仅控制台日志，绝不因此崩溃
        path = None

    root = logging.getLogger()
    root.setLevel(level or (logging.DEBUG if os.environ.get("TIMEBOOK_DEBUG") else logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    if path is not None:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            path = None

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.setLevel(logging.WARNING)
        root.addHandler(stream)

    _install_excepthooks()
    logging.getLogger("timebook").info("日志初始化 %s", path)
    return path


def _install_excepthooks() -> None:
    log = logging.getLogger("timebook.crash")

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _hook
