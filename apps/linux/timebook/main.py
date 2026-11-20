"""命令行入口。

用法::

    timebook                       # 启动（有托盘时关窗不退出）
    timebook --page stats          # 直接打开某个页面
    timebook --db /tmp/x.db        # 指定数据库（演示/测试用）
    timebook --screenshot out.png  # 渲染窗口截图后退出
    timebook --dump state.json     # 导出 UI 状态 JSON 后退出
    timebook --version
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .core.applog import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timebook",
        description="时账 Timebook —— 纯本地屏幕时间统计 + 专注工具",
    )
    parser.add_argument("--page", choices=["today", "focus", "stats", "timeline", "forfeit"],
                        help="启动后直接打开指定页面")
    parser.add_argument("--db", dest="db_path", help="指定数据库文件路径")
    parser.add_argument("--screenshot", metavar="PNG", help="渲染窗口截图后退出")
    parser.add_argument("--dump", metavar="JSON", help="导出界面状态 JSON 后退出")
    parser.add_argument("--quit-after", action="store_true",
                        help="配合 --screenshot/--dump，完成后退出")
    parser.add_argument("--hidden", action="store_true", help="启动时不显示主窗口（只驻留托盘）")
    parser.add_argument("--no-track", action="store_true",
                        help="本次运行不采集前台应用（截图/演示用，保持数据库不变")
    parser.add_argument("--version", action="version", version=f"Timebook {__version__}")
    parser.add_argument("--run-seconds", type=float, metavar="N",
                        help="运行 N 秒后优雅退出（集成测试/演示用）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()

    if args.db_path:
        os.environ["TIMEBOOK_DB"] = args.db_path

    # GTK 在无 GPU 的容器/远程会话里需要软件渲染兜底
    os.environ.setdefault("GSK_RENDERER", "gl")
    if os.environ.get("TIMEBOOK_SOFTWARE_RENDER"):
        os.environ["GSK_RENDERER"] = "cairo"

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    # WM_CLASS 由程序名决定：必须与 .desktop 的 StartupWMClass / 文件名一致，
    # 否则 GNOME 无法把窗口关联到应用图标（会显示成「main.py」）。
    GLib.set_prgname("timebook")
    GLib.set_application_name("Timebook")

    from .app import TimebookApp

    Adw.init()
    app = TimebookApp(
        {
            "page": args.page,
            "db_path": args.db_path,
            "screenshot": args.screenshot,
            "dump": args.dump,
            "quit_after": args.quit_after or bool(args.screenshot or args.dump),
            "hidden": args.hidden,
            "no_track": args.no_track,
            "run_seconds": args.run_seconds,
        }
    )
    return app.run([sys.argv[0]])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
