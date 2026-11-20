"""系统托盘：直接实现 freedesktop StatusNotifierItem（D-Bus）。

为什么不用 ``AyatanaAppIndicator3``：那个库依赖 GTK **3**，而本应用是 GTK4，
Python 的 GObject 内省不允许同一进程里同时加载 Gtk 3.0 和 4.0。所以这里直接
实现标准协议，效果等价且无版本冲突：

* ``org.kde.StatusNotifierItem`` —— 图标 + 提示 + 标签（``XAyatanaLabel``，
  Ubuntu/GNOME AppIndicator 扩展会读它显示文字，也就还原了 macOS 版菜单栏
  的「今日时长 / 番茄倒计时」）。
* ``com.canonical.dbusmenu`` —— 下拉菜单（打开窗口 / 番茄钟 / 暂停 / +1 杯水 /
  微休息 / 退出）。
* 图标用 cairo 现场绘制成 ARGB32 位图（``IconPixmap``），不依赖主题里是否
  装了 timebook 图标。

找不到 StatusNotifierWatcher（没装扩展/非支持桌面）时 ``available`` 为 False，
应用照常以窗口形式工作。
"""

from __future__ import annotations

import logging

from ..core.l10n import T, resolved_language
import os

log = logging.getLogger("timebook.tray")

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"

CATEGORY = "System Services"
STATUS_ACTIVE = "Active"
STATUS_PASSIVE = "Passive"

#: 菜单 id → 动作。0 是根节点。
MENU_LAYOUT = [
    (1, "label", "today", False),
    (2, "label", "status", False),
    (3, "separator", None, True),
    (4, "action", "open", True),
    (10, "action", "pomodoro", True),
    (5, "action", "pause", True),
    (6, "action", "water", True),
    (7, "action", "break", True),
    (8, "separator", None, True),
    (9, "action", "quit", True),
]


def render_icon(size: int = 22) -> bytes:
    """画品牌图标（深色圆环 + 番茄红进度弧 + 琥珀指针），返回 ARGB32 大端字节。"""
    try:
        import cairo

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        ctx = cairo.Context(surface)
        ctx.set_antialias(cairo.ANTIALIAS_BEST)
        ctx.scale(size / 24.0, size / 24.0)
        cx = cy = 12.0
        radius = 8.4
        ctx.set_line_width(3.0)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_source_rgba(1, 1, 1, 0.28)
        ctx.arc(cx, cy, radius, 0, 6.28318)
        ctx.stroke()
        ctx.set_source_rgb(0.941, 0.400, 0.247)  # #F0663F
        ctx.arc(cx, cy, radius, -1.5708, -1.5708 + 4.24)
        ctx.stroke()
        ctx.set_source_rgb(0.953, 0.722, 0.353)
        ctx.set_line_width(2.0)
        ctx.move_to(cx, cy)
        ctx.line_to(cx + radius * 0.5, cy - radius * 0.35)
        ctx.stroke()
        ctx.set_source_rgba(1, 1, 1, 0.95)
        ctx.arc(cx, cy, 1.4, 0, 6.28318)
        ctx.fill()

        surface.flush()
        stride = surface.get_stride()
        data = bytes(surface.get_data())
        out = bytearray(size * size * 4)
        for y in range(size):
            for x in range(size):
                offset = y * stride + x * 4
                b, g, r, a = data[offset : offset + 4]  # cairo ARGB32 是原生小端 BGRA
                target = (y * size + x) * 4
                out[target : target + 4] = bytes((a, r, g, b))
        return bytes(out)
    except Exception:  # pragma: no cover - cairo 缺失时退化为纯红方块
        log.debug("图标绘制失败，使用纯色兜底", exc_info=True)
        return bytes([0x3F, 0x66, 0xF0, 0xFF]) * (size * size)


class Tray:
    """StatusNotifierItem 托盘。接口与之前的实现保持一致。"""

    def __init__(
        self,
        ctx,
        on_open=None,
        on_pause=None,
        on_quit=None,
        on_quiet=None,
        on_cup=None,
        on_break=None,
    ) -> None:
        self._ctx = ctx
        self.available = False
        self._label = ""
        self._tooltip = ""
        self._status_line = ""
        self._pomodoro_text = ""
        self._bus = None
        self._bus_name = None
        self._service_name = ""
        self._dbus = None
        self._item = None
        self._menu = None
        self._icon = b""
        self._icon_size = 22

        self._on_open = on_open or (lambda: None)
        self._on_pause = on_pause or (lambda paused: None)
        self._on_quit = on_quit or (lambda: None)
        self._on_cup = on_cup or (lambda: None)
        self._on_break = on_break or (lambda: None)

        try:
            self._start()
        except Exception as exc:  # pragma: no cover - 桌面环境相关
            log.info("托盘初始化失败（%s），降级为纯窗口模式", exc)
            self.available = False

    # ------------------------------------------------------------------ #

    def _start(self) -> None:
        import dbus
        import dbus.mainloop.glib
        import dbus.service

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        if not bus.name_has_owner(WATCHER_NAME):
            log.info("未找到 StatusNotifierWatcher，托盘不可用（GNOME 需装 AppIndicator 扩展）")
            return

        self._bus = bus
        self._dbus = dbus
        service_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._bus_name = dbus.service.BusName(service_name, bus=bus, do_not_queue=True)
        self._service_name = service_name
        self._icon = render_icon(self._icon_size)

        tray = self

        class StatusNotifierItem(dbus.service.Object):
            @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
            def Activate(self, x, y):  # noqa: N802 - D-Bus 方法名
                tray._on_open()

            @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
            def SecondaryActivate(self, x, y):  # noqa: N802
                tray._toggle_pause()

            @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
            def ContextMenu(self, x, y):  # noqa: N802
                pass

            @dbus.service.method("org.kde.StatusNotifierItem", in_signature="is", out_signature="")
            def Scroll(self, delta, orientation):  # noqa: N802
                pass

            @dbus.service.signal("org.kde.StatusNotifierItem", signature="s")
            def NewLabel(self, label):  # noqa: N802
                pass

            @dbus.service.signal("org.kde.StatusNotifierItem", signature="")
            def NewToolTip(self):  # noqa: N802
                pass

            @dbus.service.signal("org.kde.StatusNotifierItem", signature="")
            def NewIcon(self):  # noqa: N802
                pass

            @dbus.service.signal("org.kde.StatusNotifierItem", signature="")
            def NewStatus(self, status=""):  # noqa: N802
                pass

            @dbus.service.signal("org.freedesktop.DBus.Properties", signature="sa{sv}as")
            def PropertiesChanged(self, interface, changed, invalidated):  # noqa: N802
                pass

            @dbus.service.method("org.freedesktop.DBus.Properties",
                                 in_signature="ss", out_signature="v")
            def Get(self, interface, prop):  # noqa: N802
                return tray._property(prop)

            @dbus.service.method("org.freedesktop.DBus.Properties",
                                 in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):  # noqa: N802
                return {
                    "Category": tray._property("Category"),
                    "Id": tray._property("Id"),
                    "Title": tray._property("Title"),
                    "Status": tray._property("Status"),
                    "IconName": tray._property("IconName"),
                    "IconPixmap": tray._property("IconPixmap"),
                    "ToolTip": tray._property("ToolTip"),
                    "Menu": tray._property("Menu"),
                    "XAyatanaLabel": tray._property("XAyatanaLabel"),
                }

            @dbus.service.method("org.freedesktop.DBus.Properties",
                                 in_signature="ssv", out_signature="")
            def Set(self, interface, prop, value):  # noqa: N802
                pass

        class MenuBar(dbus.service.Object):
            @dbus.service.method("com.canonical.dbusmenu", in_signature="iias",
                                 out_signature="u(ia{sv}av)")
            def GetLayout(self, parent_id, depth, props):  # noqa: N802
                return dbus.UInt32(1), tray._layout(int(parent_id))

            @dbus.service.method("com.canonical.dbusmenu", in_signature="aias",
                                 out_signature="a(ia{sv})")
            def GetGroupProperties(self, ids, props):  # noqa: N802
                out = dbus.Array([], signature="(ia{sv})")
                for item_id in tray._all_ids():
                    ident, properties = tray._item_properties(item_id)
                    out.append(dbus.Struct((ident, properties), signature="(ia{sv})"))
                return out

            @dbus.service.method("com.canonical.dbusmenu", in_signature="",
                                 out_signature="u")
            def GetRevision(self):  # noqa: N802
                return dbus.UInt32(1)

            @dbus.service.method("com.canonical.dbusmenu", in_signature="i", out_signature="b")
            def AboutToShow(self, item_id):  # noqa: N802
                return False

            @dbus.service.method("com.canonical.dbusmenu", in_signature="isvu",
                                 out_signature="")
            def Event(self, item_id, event_id, data, timestamp):  # noqa: N802
                if event_id == "clicked" or event_id == int(0):
                    tray._activate(int(item_id))

            @dbus.service.signal("com.canonical.dbusmenu", signature="u")
            def LayoutUpdated(self, revision):  # noqa: N802
                pass

        self._item = StatusNotifierItem(bus, ITEM_PATH)
        self._menu = MenuBar(bus, MENU_PATH)

        watcher = bus.get_object(WATCHER_NAME, WATCHER_PATH)
        iface = dbus.Interface(watcher, "org.kde.StatusNotifierWatcher")
        iface.RegisterStatusNotifierItem(dbus.String(self._service_name))
        self.available = True
        log.info("托盘已启用（StatusNotifierItem %s）", self._service_name)

    # ------------------------------------------------------------------ #

    def _all_ids(self) -> list[int]:
        return [0] + [item[0] for item in MENU_LAYOUT]

    def _menu_text(self, key: str) -> str:
        from ..core.l10n import T, resolved_language

        if key == "pomodoro":
            engine = self._ctx.pomodoro
            state = engine.state
            ready_phase = state.phase.ready_base
            if ready_phase is not None:
                return T(
                    f"番茄钟：开始{ready_phase.label}",
                    f"Pomodoro: start {ready_phase.label.lower()}",
                )
            if not state.phase.is_running:
                return T(
                    f"开始番茄钟（{engine.preset.work_min} 分钟）",
                    f"Start pomodoro ({engine.preset.work_min} min)",
                )
            if state.paused:
                return T("继续番茄钟", "Resume pomodoro")
            return T("暂停番茄钟", "Pause pomodoro")

        texts = {
            "open": T("打开时账", "Open Timebook"),
            "pause": T("暂停记录", "Pause tracking")
            if not self._ctx.settings.paused
            else T("继续记录", "Resume tracking"),
            "water": T("+1 杯水", "+1 cup of water"),
            "break": T("微休息 20 秒", "Micro break (20s)"),
            "quit": T("退出", "Quit"),
        }
        paused = self._ctx.settings.paused
        if key == "pause":
            return texts["pause"]
        return texts.get(key, key)

    def _props(self, **values):
        """构造显式签名的 ``a{sv}``：嵌在 variant 里时必须显式，否则无法推断签名。"""
        return self._dbus.Dictionary(
            {key: value for key, value in values.items() if value is not None},
            signature="sv",
        )

    def _item_properties(self, item_id: int):
        dbus = self._dbus
        if item_id == 0:
            return dbus.Int32(0), self._props()
        for ident, kind, key, _enabled in MENU_LAYOUT:
            if ident != item_id:
                continue
            if kind == "separator":
                return dbus.Int32(item_id), self._props(
                    type=dbus.String("separator"), visible=dbus.Boolean(True)
                )
            if kind == "label":
                text = self._label if key == "today" else self._status_line
                return dbus.Int32(item_id), self._props(
                    type=dbus.String("standard"),
                    label=dbus.String(text),
                    enabled=dbus.Boolean(False),
                    visible=dbus.Boolean(True),
                )
            return dbus.Int32(item_id), self._props(
                type=dbus.String("standard"),
                label=dbus.String(self._menu_text(key or "")),
                enabled=dbus.Boolean(True),
                visible=dbus.Boolean(True),
            )
        return dbus.Int32(item_id), self._props()

    def _layout(self, parent_id: int):
        """返回 dbusmenu 布局节点 ``(id, properties, children)``。

        注意：``children`` 的签名是 ``av``（数组里每个元素必须是 **variant**），
        所以每个子节点都要显式包一层 ``Variant(signature="(ia{sv}av)")``。
        """
        dbus = self._dbus
        if parent_id not in (0, -1):
            return dbus.Struct(
                (dbus.Int32(parent_id), self._props(), dbus.Array([], signature="v")),
                signature="(ia{sv}av)",
            )
        children = dbus.Array([], signature="v")
        for ident, _kind, _key, _enabled in MENU_LAYOUT:
            item_id, props = self._item_properties(ident)
            children.append((item_id, props, dbus.Array([], signature="v")))
        root_props = self._props(**{"children-display": dbus.String("submenu")})
        return dbus.Struct(
            (dbus.Int32(0), root_props, children), signature="(ia{sv}av)"
        )

    def _property(self, name: str):
        dbus = self._dbus
        if name == "Category":
            return dbus.String(CATEGORY)
        if name == "Id":
            return dbus.String("timebook")
        if name == "Title":
            return dbus.String(self._label or "Timebook")
        if name == "Status":
            return dbus.String(STATUS_ACTIVE)
        if name == "IconName":
            return dbus.String("")
        if name == "IconPixmap":
            return dbus.Array(
                [dbus.Struct((dbus.Int32(self._icon_size), dbus.Int32(self._icon_size),
                              dbus.ByteArray(self._icon)), signature=None)],
                signature="(iiay)",
            )
        if name == "ToolTip":
            return dbus.Struct(
                (
                    dbus.String(""),
                    dbus.Array([], signature="(iiay)"),
                    dbus.String(self._tooltip or "Timebook"),
                    dbus.String(self._status_line),
                ),
                signature=None,
            )
        if name == "Menu":
            return dbus.ObjectPath(MENU_PATH)
        if name == "XAyatanaLabel":
            return dbus.String(self._label)
        return dbus.String("")

    # ------------------------------------------------------------------ #

    def _activate(self, item_id: int) -> None:
        for ident, kind, key, _enabled in MENU_LAYOUT:
            if ident != item_id or kind != "action":
                continue
            if key == "open":
                self._on_open()
            elif key == "pomodoro":
                self._ctx.pomodoro.toggle()
                self.refresh(force=True)
            elif key == "pause":
                self._toggle_pause()
            elif key == "water":
                self._on_cup()
            elif key == "break":
                self._on_break()
            elif key == "quit":
                self._on_quit()

    def _toggle_pause(self) -> None:
        paused = not self._ctx.settings.paused
        self._ctx.settings.paused = paused
        self._ctx.tracker.force_close()
        self._on_pause(paused)
        self.refresh(force=True)

    # ------------------------------------------------------------------ #

    def refresh(self, force: bool = False) -> None:
        # 先无条件算好标签/状态：即使当前没有 StatusNotifier 宿主（GNOME 未装
        # 扩展），内部状态也保持正确，便于测试与 tooltip 复用。
        paused = self._ctx.settings.paused
        engine = self._ctx.pomodoro
        if paused:
            label = "⏸"
        elif engine.state.phase.is_running:
            marker = "⏸ " if engine.state.paused else ""
            label = f"🍅 {marker}{engine.remain_clock}"
        else:
            from ..core.models import fmt_duration

            label = fmt_duration(self._ctx.today_total(), compact=True)

        from ..core.models import fmt_duration

        total = self._ctx.today_total()
        if paused:
            status = T("记录已暂停", "Tracking paused")
        elif self._ctx.tracker.is_idle:
            status = T("空闲中", "Idle")
        else:
            current = self._ctx.tracker.current_app_name
            status = T(f"当前：{current or '—'}", f"Current: {current or '—'}")

        changed_status = status != self._status_line
        language = resolved_language()
        changed_language = language != getattr(self, "_language", None)
        self._language = language
        changed_label = label != self._label
        pomodoro_text = self._menu_text("pomodoro")
        changed_pomodoro = pomodoro_text != self._pomodoro_text
        self._pomodoro_text = pomodoro_text
        self._label = label
        self._status_line = status
        self._tooltip = T(f"今日 {fmt_duration(total)}", f"Today {fmt_duration(total)}")
        if not self.available or self._item is None:
            return
        if not (changed_label or changed_pomodoro or changed_status or changed_language or force):
            return
        try:
            self._item.NewLabel(label)
            self._item.NewToolTip()
            self._item.PropertiesChanged(
                "org.kde.StatusNotifierItem",
                {
                    "XAyatanaLabel": self._dbus.String(label),
                    "Title": self._dbus.String(label),
                    "ToolTip": self._property("ToolTip"),
                },
                [],
            )
            self._menu.LayoutUpdated(1)
        except Exception:  # pragma: no cover - 总线偶发错误
            log.debug("托盘刷新失败", exc_info=True)

    def destroy(self) -> None:
        if getattr(self, "_item", None) is not None:
            try:
                self._item.remove_from_connection()
            except Exception:  # pragma: no cover
                pass
            self._item = None
        if getattr(self, "_menu", None) is not None:
            try:
                self._menu.remove_from_connection()
            except Exception:  # pragma: no cover
                pass
            self._menu = None
        if getattr(self, "_bus_name", None) is not None:
            try:
                self._bus_name.get_bus().release_name(self._bus_name.get_name())
            except Exception:  # pragma: no cover
                pass
            self._bus_name = None
        self.available = False
