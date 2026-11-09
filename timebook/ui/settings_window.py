"""设置窗口：记录 / 每日限额 / 提醒 / 排除应用 / 外观与数据。

对应 macOS 版 ``SettingsView``（Form grouped，五段）。Linux 版额外提供
「托盘」与「窗口标题采集」的说明文字，并把导出按钮做成行内反馈。
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..core import models  # noqa: E402
from ..core.l10n import T, set_language  # noqa: E402
from . import widgets as W  # noqa: E402
from .export_dialog import downloads_dir, extract_to_downloads  # noqa: E402


class SettingsWindow(Adw.Window):
    def __init__(self, parent, ctx) -> None:
        super().__init__(transient_for=parent, modal=False)
        self._ctx = ctx
        self._parent = parent
        self._syncing = False
        self.set_title("设置")
        self.set_default_size(600, 720)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        toolbar.add_top_bar(header)
        self.toast_overlay = Adw.ToastOverlay()
        toolbar.set_content(self.toast_overlay)
        setattr(parent, "_toast_overlay", self.toast_overlay)

        page = Adw.PreferencesPage()
        self.toast_overlay.set_child(page)

        # ---- 记录 ----
        group = Adw.PreferencesGroup(title="记录")
        group.set_description("只统计前台应用，不联网、不上报、不需要授权。")
        page.add(group)

        self.idle_combo = Adw.ComboRow(title="空闲判定")
        self.idle_combo.set_subtitle("键鼠停止多久后不再计时")
        self._idle_values = [0, 60, 120, 300, 600]
        self.idle_combo.set_model(
            Gtk.StringList.new(
                ["不启用（看视频也计时）", "1 分钟", "2 分钟", "5 分钟", "10 分钟"]
            )
        )
        self.idle_combo.connect("notify::selected", self._on_idle)
        group.add(self.idle_combo)

        self.title_switch = Adw.SwitchRow(
            title="采集窗口标题", subtitle="用于时间线回看；标题只存本机数据库"
        )
        self.title_switch.connect("notify::active", self._on_capture_titles)
        group.add(self.title_switch)

        self.browser_switch = Adw.SwitchRow(
            title="浏览器域名统计", subtitle="从窗口标题推断域名，失败则只记应用"
        )
        self.browser_switch.connect("notify::active", self._on_browser)
        group.add(self.browser_switch)

        self.pause_switch = Adw.SwitchRow(title="暂停记录", subtitle="暂停期间不产生任何数据")
        self.pause_switch.connect("notify::active", self._on_pause)
        group.add(self.pause_switch)

        self.tray_switch = Adw.SwitchRow(
            title="显示托盘图标", subtitle="需要 GNOME AppIndicator 扩展；关闭后仅保留窗口"
        )
        self.tray_switch.connect("notify::active", self._on_tray)
        group.add(self.tray_switch)

        # ---- 每日限额 ----
        limits = Adw.PreferencesGroup(title="每日限额")
        limits.set_description("系统级应用无法强制屏蔽其他应用或网站，这里只做温和提醒。")
        page.add(limits)

        self.limits_switch = Adw.SwitchRow(title="启用每日限额")
        self.limits_switch.connect("notify::active", self._on_limits)
        limits.add(self.limits_switch)

        self.limit_combo = Adw.ComboRow(title="每日上限")
        self._limit_values = [60, 120, 180, 240, 300, 360, 480]
        self.limit_combo.set_model(
            Gtk.StringList.new(["1 小时", "2 小时", "3 小时", "4 小时", "5 小时", "6 小时", "8 小时"])
        )
        self.limit_combo.connect("notify::selected", self._on_limit_value)
        limits.add(self.limit_combo)

        self.distract_switch = Adw.SwitchRow(
            title="分心网站提醒", subtitle="社交/视频/购物/娱乐连续 10 分钟提醒，30 分钟冷却"
        )
        self.distract_switch.connect("notify::active", self._on_distract)
        limits.add(self.distract_switch)

        # ---- 提醒 ----
        reminders = Adw.PreferencesGroup(title="提醒")
        page.add(reminders)

        self.notify_switch = Adw.SwitchRow(title="允许系统通知")
        self.notify_switch.connect("notify::active", self._on_notifications)
        reminders.add(self.notify_switch)

        self.break_switch = Adw.SwitchRow(title="休息提醒")
        self.break_switch.connect("notify::active", self._on_break_enabled)
        reminders.add(self.break_switch)

        self.break_combo = Adw.ComboRow(title="休息间隔")
        self._break_values = [20, 30, 45, 60]
        self.break_combo.set_model(Gtk.StringList.new(["20 分钟", "30 分钟", "45 分钟", "60 分钟"]))
        self.break_combo.connect("notify::selected", self._on_break_interval)
        reminders.add(self.break_combo)

        self.water_switch = Adw.SwitchRow(title="喝水提醒")
        self.water_switch.connect("notify::active", self._on_water_enabled)
        reminders.add(self.water_switch)

        self.water_combo = Adw.ComboRow(title="喝水间隔")
        self._water_values = [30, 45, 60, 90, 120]
        self.water_combo.set_model(
            Gtk.StringList.new(["30 分钟", "45 分钟", "60 分钟", "90 分钟", "120 分钟"])
        )
        self.water_combo.connect("notify::selected", self._on_water_interval)
        reminders.add(self.water_combo)

        self.overlay_switch = Adw.SwitchRow(
            title="番茄休息时弹微休息遮罩", subtitle="20 秒全屏护眼引导，可随时跳过"
        )
        self.overlay_switch.connect("notify::active", self._on_overlay)
        reminders.add(self.overlay_switch)

        # ---- 排除应用 ----
        exclude = Adw.PreferencesGroup(title="排除应用")
        exclude.set_description("名单里的应用完全不产生记录。")
        page.add(exclude)
        self.exclude_rows = []
        self.exclude_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        exclude.add(self.exclude_box)
        self.exclude_empty = W.label("还没有排除任何应用。", "tb-caption")
        self.exclude_box.append(self.exclude_empty)

        self.exclude_picker = Adw.ComboRow(title="添加应用")
        self.exclude_picker.connect("notify::selected", self._on_exclude_add)
        exclude.add(self.exclude_picker)

        # ---- 外观与数据 ----
        appearance = Adw.PreferencesGroup(title="外观与数据")
        page.add(appearance)

        self.lang_combo = Adw.ComboRow(title="语言")
        self._lang_values = ["auto", "zh", "en"]
        self.lang_combo.set_model(Gtk.StringList.new(["跟随系统", "中文", "English"]))
        self.lang_combo.connect("notify::selected", self._on_language)
        appearance.add(self.lang_combo)

        self.retention_combo = Adw.ComboRow(title="数据保留期")
        self._retention_values = [0, 90, 180, 365]
        self.retention_combo.set_model(
            Gtk.StringList.new(["永久保留", "90 天", "180 天", "365 天"])
        )
        self.retention_combo.connect("notify::selected", self._on_retention)
        appearance.add(self.retention_combo)

        export_row = Adw.ActionRow(
            title="导出数据", subtitle=f"CSV 明细 + Markdown 周报 → {downloads_dir().name}/"
        )
        export_button = Gtk.Button(label="导出")
        export_button.add_css_class("tb-ghost")
        export_button.set_valign(Gtk.Align.CENTER)
        export_button.connect("clicked", self._on_export)
        export_row.add_suffix(export_button)
        appearance.add(export_row)

        data_row = Adw.ActionRow(
            title="数据库",
            subtitle=f"{self._ctx.store.path} · {self._ctx.store.size_bytes() / 1024:.0f} KB",
        )
        appearance.add(data_row)

        appear_r = Adw.ActionRow(title="界面主题", subtitle="跟随系统深色/浅色")
        appearance.add(appear_r)

        toolbar_content = toolbar
        self.set_content(toolbar_content)
        self.reload()

    # ------------------------------------------------------------------ #

    def _idx(self, values: list, current: int) -> int:
        return values.index(current) if current in values else 0

    def reload(self) -> None:
        self._syncing = True
        try:
            settings = self._ctx.settings
            self.idle_combo.set_selected(self._idx(self._idle_values, settings.idle_threshold))
            self.title_switch.set_active(settings.capture_titles)
            self.browser_switch.set_active(settings.browser_title_parsing)
            self.pause_switch.set_active(settings.paused)
            self.tray_switch.set_active(settings.tray_enabled)
            self.limits_switch.set_active(settings.limits_enabled)
            self.limit_combo.set_selected(self._idx(self._limit_values, settings.limits_daily_minutes))
            self.distract_switch.set_active(settings.distract_nudge_enabled)
            self.notify_switch.set_active(settings.notifications_enabled)
            self.break_switch.set_active(settings.break_reminder_enabled)
            self.break_combo.set_selected(self._idx(self._break_values, settings.break_interval_minutes))
            self.water_switch.set_active(settings.water_enabled)
            self.water_combo.set_selected(self._idx(self._water_values, settings.water_interval_minutes))
            self.overlay_switch.set_active(settings.pomodoro_break_overlay)
            self.lang_combo.set_selected(self._idx(self._lang_values, settings.language))
            self.retention_combo.set_selected(self._idx(self._retention_values, settings.retention_days))
        finally:
            self._syncing = False
        self._rebuild_excludes()

    def _rebuild_excludes(self) -> None:
        child = self.exclude_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.exclude_box.remove(child)
            child = nxt
        excluded = sorted(self._ctx.settings.excluded)
        if not excluded:
            self.exclude_box.append(self.exclude_empty)
        names = dict(self._ctx.store.known_apps())
        for app_id in excluded:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("tb-row")
            row.append(W.label(names.get(app_id, app_id)))
            row.append(W.spacer())
            remove = Gtk.Button(label="移除")
            remove.add_css_class("tb-ghost")
            remove.connect("clicked", lambda _b, a=app_id: self._remove_exclude(a))
            row.append(remove)
            self.exclude_box.append(row)

        candidates = [
            (app_id, name)
            for app_id, name in self._ctx.store.known_apps()
            if app_id not in excluded
        ]
        self._exclude_ids = [app_id for app_id, _ in candidates]
        self.exclude_picker.set_model(
            Gtk.StringList.new([name for _, name in candidates] or ["（暂无）"])
        )

    def _remove_exclude(self, app_id: str) -> None:
        self._ctx.settings.excluded = self._ctx.settings.excluded - {app_id}
        self._rebuild_excludes()

    def _toast(self, text: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(text))

    # ---- 回调 ---------------------------------------------------------- #

    def _on_idle(self, row, _p) -> None:
        if self._syncing:
            return
        self._ctx.settings.idle_threshold = self._idle_values[row.get_selected()]

    def _on_capture_titles(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.capture_titles = row.get_active()

    def _on_browser(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.browser_title_parsing = row.get_active()

    def _on_pause(self, row, _p) -> None:
        if self._syncing:
            return
        self._ctx.settings.paused = row.get_active()
        self._ctx.tracker.force_close()

    def _on_tray(self, row, _p) -> None:
        if self._syncing:
            return
        self._ctx.settings.tray_enabled = row.get_active()
        self._toast("托盘设置已保存，重启应用后生效")

    def _on_limits(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.limits_enabled = row.get_active()

    def _on_limit_value(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.limits_daily_minutes = self._limit_values[row.get_selected()]

    def _on_distract(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.distract_nudge_enabled = row.get_active()

    def _on_notifications(self, row, _p) -> None:
        if self._syncing:
            return
        self._ctx.settings.notifications_enabled = row.get_active()
        if self._ctx.notifier is not None:
            self._ctx.notifier.enabled = row.get_active()

    def _on_break_enabled(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.break_reminder_enabled = row.get_active()

    def _on_break_interval(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.break_interval_minutes = self._break_values[row.get_selected()]

    def _on_water_enabled(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.water_enabled = row.get_active()

    def _on_water_interval(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.water_interval_minutes = self._water_values[row.get_selected()]

    def _on_overlay(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.pomodoro_break_overlay = row.get_active()

    def _on_language(self, row, _p) -> None:
        if self._syncing:
            return
        value = self._lang_values[row.get_selected()]
        self._ctx.settings.language = value
        set_language(value)
        self._toast("语言已切换，重新打开主窗口后全部生效")
        if self._ctx.on_language_changed:
            self._ctx.on_language_changed()

    def _on_retention(self, row, _p) -> None:
        if self._syncing:
            return
        self._ctx.settings.retention_days = self._retention_values[row.get_selected()]
        removed = self._ctx.tracker.prune_old_data()
        self._toast(f"已保存（清理 {removed} 条旧记录）")

    def _on_exclude_add(self, row, _p) -> None:
        if self._syncing:
            return
        index = row.get_selected()
        if 0 <= index < len(getattr(self, "_exclude_ids", [])):
            app_id = self._exclude_ids[index]
            self._ctx.settings.excluded = self._ctx.settings.excluded | {app_id}
            self._syncing = True
            try:
                row.set_selected(Gtk.INVALID_LIST_POSITION)
            finally:
                self._syncing = False
            self._rebuild_excludes()

    def _on_export(self, _button) -> None:
        csv_path, _md = extract_to_downloads(self._parent, self._ctx)
        self._toast(f"已导出到 {csv_path.parent.name}/")
