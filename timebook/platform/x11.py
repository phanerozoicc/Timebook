"""X11 原生调用：前台窗口、空闲秒数、屏保状态。

macOS 版用 ``NSWorkspace.frontmostApplication`` + ``CGEventSource``；Linux 上
等价能力由 X11 提供：

* ``_NET_ACTIVE_WINDOW`` / ``XGetInputFocus`` → 前台窗口
* ``_NET_WM_PID`` / ``WM_CLASS`` / ``_NET_WM_NAME`` → 进程、应用、标题
* ``XScreenSaverQueryInfo``（libXss）→ 空闲秒数 + 屏保/锁屏状态

全部用 ctypes 直连 libX11 / libXss（本机没有 python-xlib），任何失败都优雅
降级为 ``None`` / ``0.0``，绝不打断采集循环。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger("timebook.x11")

# --------------------------------------------------------------------------- #
# X11 常量
# --------------------------------------------------------------------------- #

XA_ATOM = 4
XA_CARDINAL = 6
XA_STRING = 31
XA_WINDOW = 33

ANY_PROPERTY_TYPE = 0
SUCCESS = 0

#: XScreenSaver 状态位
SCREEN_SAVER_OFF = 0
SCREEN_SAVER_ON = 1
SCREEN_SAVER_CYCLE = 2
SCREEN_SAVER_DISABLED = 3

#: 屏保状态里「显示器已休眠 / 已锁」的位
SCREEN_SAVER_STATE_BLANK = 1 << 0
SCREEN_SAVER_STATE_LOCKED = 1 << 1


class XScreenSaverInfo(ctypes.Structure):
    """``XScreenSaverInfo``（X11/extensions/scrnsaver.h）。"""

    _fields_ = [
        ("window", ctypes.c_ulong),
        ("state", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("til_or_since", ctypes.c_ulong),
        ("idle", ctypes.c_ulong),
        ("eventMask", ctypes.c_ulong),
    ]


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """前台窗口快照。"""

    window_id: int
    pid: int | None
    app_id: str
    app_name: str
    title: str

    @property
    def has_title(self) -> bool:
        return bool(self.title.strip())


def _class_to_ids(class_hint: str) -> tuple[str, str]:
    """把 ``WM_CLASS``（``"instance\\x00Class\\x00"``）解析成 (app_id, app_name)。

    规则：优先第二段（Class，如 ``Firefox`` / ``Google-chrome``），实例名兜底；
    app_id 取小写并把空格/下划线统一成「-」，便于与 ``BROWSER_IDS`` 对齐。
    """
    parts = [p for p in class_hint.replace("\x00", "\n").split("\n") if p.strip()]
    if not parts:
        return "", ""
    name = parts[-1].strip() if len(parts) > 1 else parts[0].strip()
    instance = parts[0].strip()
    app_id = (name or instance).lower().replace(" ", "-").replace("_", "-")
    return app_id, name


def parse_class_hint(raw: str) -> str:
    """把 ``xprop`` 输出的 ``WM_CLASS(STRING) = "a", "b"`` 转成 NUL 分隔形式。"""
    if "=" not in raw:
        return ""
    payload = raw.split("=", 1)[1].strip()
    parts = [p.strip().strip('"') for p in payload.split(",") if p.strip()]
    return "\x00".join(parts)


def parse_title_hint(raw: str) -> str:
    """把 ``_NET_WM_NAME(UTF8_STRING) = "标题"`` 形式的输出取值。"""
    if "=" not in raw:
        return ""
    value = raw.split("=", 1)[1].strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


class X11Display:
    """libX11 / libXss 的薄封装。连接是懒加载的，失败后不再反复重试。"""

    def __init__(self) -> None:
        self._x11 = None
        self._xss = None
        self._display = None
        self._root = None
        self._atoms: dict[str, int] = {}
        self._load_error: str | None = None
        self._failed = False

    # -- 连接 ------------------------------------------------------------ #

    def _load(self) -> bool:
        if self._display is not None:
            return True
        if self._failed:
            return False
        try:
            x11_name = ctypes.util.find_library("X11") or "libX11.so.6"
            self._x11 = ctypes.cdll.LoadLibrary(x11_name)
            xss_name = ctypes.util.find_library("Xss") or "libXss.so.1"
            self._xss = ctypes.cdll.LoadLibrary(xss_name)

            self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self._x11.XOpenDisplay.restype = ctypes.c_void_p
            self._x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self._x11.XDefaultRootWindow.restype = ctypes.c_ulong
            self._x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            self._x11.XInternAtom.restype = ctypes.c_ulong
            self._x11.XGetWindowProperty.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self._x11.XGetWindowProperty.restype = ctypes.c_int
            self._x11.XFree.argtypes = [ctypes.c_void_p]
            self._x11.XGetInputFocus.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)
            ]
            self._x11.XGetInputFocus.restype = ctypes.c_int
            self._x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            self._x11.XFlush.argtypes = [ctypes.c_void_p]

            self._xss.XScreenSaverAllocInfo.argtypes = []
            self._xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
            self._xss.XScreenSaverQueryInfo.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XScreenSaverInfo)
            ]
            self._xss.XScreenSaverQueryInfo.restype = ctypes.c_int

            display = self._x11.XOpenDisplay(os.environ.get("DISPLAY", "").encode() or None)
            if not display:
                self._failed = True
                self._load_error = "XOpenDisplay 失败"
                return False
            self._display = ctypes.c_void_p(display)
            self._root = self._x11.XDefaultRootWindow(self._display)
            return True
        except (OSError, AttributeError) as exc:  # pragma: no cover - 环境相关
            self._failed = True
            self._load_error = str(exc)
            log.warning("X11 初始化失败：%s", exc)
            return False

    @property
    def is_connected(self) -> bool:
        return self._display is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def close(self) -> None:
        if self._display is not None and self._x11 is not None:
            try:
                self._x11.XCloseDisplay(self._display)
            except Exception:  # pragma: no cover
                pass
        self._display = None
        self._root = None

    # -- 原子 ------------------------------------------------------------ #

    def _atom(self, name: str) -> int:
        if name not in self._atoms:
            assert self._x11 is not None
            self._atoms[name] = int(
                self._x11.XInternAtom(self._display, name.encode(), 0)
            )
        return self._atoms[name]

    # -- 属性读取 -------------------------------------------------------- #

    def _property(self, window: int, prop: str) -> tuple[int, bytes] | None:
        """读窗口属性，返回 (实际类型, 原始字节)。"""
        if not self._load():
            return None
        assert self._x11 is not None
        actual_type = ctypes.c_ulong(0)
        actual_format = ctypes.c_int(0)
        n_items = ctypes.c_ulong(0)
        bytes_after = ctypes.c_ulong(0)
        data = ctypes.c_void_p(0)
        status = self._x11.XGetWindowProperty(
            self._display,
            ctypes.c_ulong(window),
            ctypes.c_ulong(self._atom(prop)),
            0,
            4096,
            0,
            ANY_PROPERTY_TYPE,
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(n_items),
            ctypes.byref(bytes_after),
            ctypes.byref(data),
        )
        if status != SUCCESS or not data.value:
            if data.value:
                self._x11.XFree(data)
            return None
        try:
            size = n_items.value * (actual_format.value // 8 or 1)
            payload = ctypes.string_at(data, size) if size else b""
            return int(actual_type.value), payload
        finally:
            self._x11.XFree(data)

    def _string_property(self, window: int, prop: str) -> str:
        result = self._property(window, prop)
        if not result:
            return ""
        _type, payload = result
        if not payload:
            return ""
        try:
            return payload.rstrip(b"\x00").decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover
            return ""

    def _cardinal_property(self, window: int, prop: str) -> int | None:
        result = self._property(window, prop)
        if not result:
            return None
        _type, payload = result
        if len(payload) < 4:
            return None
        return int.from_bytes(payload[:4], "little")

    def _window_pid(self, window: int) -> int | None:
        pid = self._cardinal_property(window, "_NET_WM_PID")
        if pid:
            return pid
        # 退化：沿父链找带 _NET_WM_PID 的祖先（部分应用只在顶层窗口上设置）
        parent = window
        for _ in range(4):
            parent = self._parent_window(parent) or 0
            if not parent:
                break
            pid = self._cardinal_property(parent, "_NET_WM_PID")
            if pid:
                return pid
        return None

    def _parent_window(self, window: int) -> int | None:
        if not self._load():
            return None
        assert self._x11 is not None
        root = ctypes.c_ulong(0)
        parent = ctypes.c_ulong(0)
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint(0)
        try:
            self._x11.XQueryTree.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                ctypes.POINTER(ctypes.c_uint),
            ]
            self._x11.XQueryTree.restype = ctypes.c_int
            ok = self._x11.XQueryTree(
                self._display, ctypes.c_ulong(window), ctypes.byref(root),
                ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count),
            )
            if children:
                self._x11.XFree(children)
            return int(parent.value) if ok else None
        except (AttributeError, OSError):  # pragma: no cover
            return None

    # -- 公共 API -------------------------------------------------------- #

    def active_window(self) -> WindowInfo | None:
        """当前前台窗口；无窗口/失败返回 None。"""
        if not self._load():
            return None
        try:
            window = self._cardinal_property(self._root, "_NET_ACTIVE_WINDOW") or 0
            if not window:
                focus = ctypes.c_ulong(0)
                revert = ctypes.c_int(0)
                self._x11.XGetInputFocus(self._display, ctypes.byref(focus), ctypes.byref(revert))
                window = int(focus.value) if focus.value not in (0, 1) else 0
            if not window:
                return None

            class_hint = self._string_property(window, "WM_CLASS")
            app_id, app_name = _class_to_ids(class_hint)

            title = ""
            for prop in ("_NET_WM_NAME", "WM_NAME"):
                title = self._string_property(window, prop)
                if title:
                    break

            pid = self._window_pid(window)
            if not app_name and pid:
                app_name = _proc_name(pid)
                app_id = app_id or app_name.lower()

            if not app_id and not app_name and not title:
                return None
            return WindowInfo(
                window_id=window,
                pid=pid,
                app_id=app_id or "unknown",
                app_name=app_name or app_id or "unknown",
                title=title,
            )
        except Exception as exc:  # pragma: no cover - 环境相关
            log.debug("读取前台窗口失败：%s", exc)
            return None

    def _saver_info(self) -> XScreenSaverInfo | None:
        if not self._load() or self._xss is None:
            return None
        try:
            info = self._xss.XScreenSaverAllocInfo()
            if not info:
                return None
            ok = self._xss.XScreenSaverQueryInfo(self._display, ctypes.c_ulong(self._root), info)
            if not ok:
                return None
            return info.contents
        except Exception:  # pragma: no cover
            return None

    def idle_seconds(self) -> float:
        """键鼠空闲秒数（``XScreenSaverQueryInfo``；失败退化到 ``xprintidle``）。"""
        info = self._saver_info()
        if info is not None:
            return float(info.idle) / 1000.0  # 毫秒 → 秒
        exe = shutil.which("xprintidle")
        if exe:
            try:
                out = subprocess.run(
                    [exe], capture_output=True, text=True, timeout=2, check=False
                )
                return float(out.stdout.strip() or 0) / 1000.0
            except (ValueError, OSError, subprocess.SubprocessError):
                return 0.0
        return 0.0

    def screensaver_active(self) -> bool:
        """显示器休眠 / 已锁屏（此时不计时）。"""
        info = self._saver_info()
        if info is None:
            return False
        if info.state in (SCREEN_SAVER_ON, SCREEN_SAVER_CYCLE):
            return True
        return bool(getattr(info, "kind", 0) & (SCREEN_SAVER_STATE_BLANK | SCREEN_SAVER_STATE_LOCKED))


def _proc_name(pid: int) -> str:
    """从 /proc 读进程名（X11 属性缺失时兜底）。"""
    for candidate in (f"/proc/{pid}/comm", f"/proc/{pid}/cmdline"):
        try:
            with open(candidate, "rb") as handle:
                raw = handle.read()
            if not raw:
                continue
            text = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
            if text:
                return text.rsplit("/", 1)[-1]
        except OSError:
            continue
    return ""


def available() -> bool:
    """当前环境是否有可用的 X11 连接（供 UI 提示/测试用）。"""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
