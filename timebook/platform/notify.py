"""桌面通知：优先走 ``notify-send``（libnotify），退化到 GApplication 通知。

macOS 版用 ``UNUserNotificationCenter``；Linux 桌面统一走 freedesktop 通知
守护进程，行为一致：不抢焦点、自动消失、可在通知中心回看。
"""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("timebook.notify")


class Notifier:
    """发通知的小封装。``enabled`` 由设置控制（App 层负责同步）。"""

    def __init__(self, app_name: str = "时账 Timebook", icon: str = "timebook", app=None) -> None:
        self.app_name = app_name
        self.icon = icon
        self.app = app
        self.enabled = True
        self._notify_send = shutil.which("notify-send")
        self._sent: list[tuple[str, str]] = []

    @property
    def history(self) -> list[tuple[str, str]]:
        """最近发出的通知（调试/测试用）。"""
        return list(self._sent)

    def send(self, title: str, body: str) -> None:
        if not self.enabled:
            return
        self._sent.append((title, body))
        if len(self._sent) > 50:
            self._sent = self._sent[-50:]

        if self._notify_send:
            try:
                subprocess.run(
                    [
                        self._notify_send,
                        "--app-name", self.app_name,
                        "--icon", self.icon,
                        "--expire-time", "8000",
                        title,
                        body,
                    ],
                    check=False,
                    timeout=5,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except (OSError, subprocess.SubprocessError):
                log.debug("notify-send 调用失败，尝试 GApplication 通知")

        if self.app is not None:
            try:
                from gi.repository import Gio, GLib

                notification = Gio.Notification.new(title)
                notification.set_body(body)
                self.app.send_notification(GLib.uuid_string_random(), notification)
            except Exception:  # pragma: no cover - 无桌面环境
                log.debug("GApplication 通知不可用")
