"""设置窗口：记录 / 每日限额 / 提醒 / 排除应用 / 外观与数据。

对应 macOS 版 ``SettingsView``（Form grouped，五段）。Linux 版额外提供
「托盘」与「窗口标题采集」的说明文字，并把导出按钮做成行内反馈。
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..core import models  # noqa: E402
from ..core.l10n import T, set_language, resolved_language  # noqa: E402
from . import widgets as W  # noqa: E402
from .export_dialog import downloads_dir, extract_to_downloads  # noqa: E402


class SettingsWindow(Adw.Window):
    def __init__(self, parent, ctx) -> None:
        super().__init__(transient_for=parent, modal=False)
        self._ctx = ctx
        self._parent = parent
        self._syncing = False
        self._language = resolved_language()
        self._language_source = None
        self._last_toast = None
        W.translated(self, title=('设置', 'Settings'))
        self.set_default_size(600, 720)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        toolbar.add_top_bar(header)
        self.toast_overlay = Adw.ToastOverlay()
        self._toast_overlay = self.toast_overlay
        toolbar.set_content(self.toast_overlay)

        page = Adw.PreferencesPage()
        self.toast_overlay.set_child(page)

        # ---- 记录 ----
        group = W.translated(Adw.PreferencesGroup(), title=('记录', 'Tracking'))
        W.translated(group, description=('只统计前台应用，不联网、不上报、不需要授权。', 'Only tracks the foreground app. All data stays on this device.'))
        page.add(group)

        self.idle_combo = W.translated(Adw.ComboRow(), title=('空闲判定', 'Idle detection'))
        W.translated(self.idle_combo, subtitle=('键鼠停止多久后不再计时', 'Stop counting after this period without keyboard or mouse input'))
        self._idle_values = [0, 60, 120, 300, 600]
        W.translated_model(self.idle_combo, [('不启用（看视频也计时）', 'Off (includes time watching videos)'), ('1 分钟', '1 minute'), ('2 分钟', '2 minutes'), ('5 分钟', '5 minutes'), ('10 分钟', '10 minutes')])
        self.idle_combo.connect("notify::selected", self._on_idle)
        group.add(self.idle_combo)

        self.title_switch = W.translated(Adw.SwitchRow(), title=('采集窗口标题', 'Record window titles'), subtitle=('用于时间线回看；标题只存本机数据库', 'Show titles in the timeline; stored only on this device'))
        self.title_switch.connect("notify::active", self._on_capture_titles)
        group.add(self.title_switch)

        self.browser_switch = W.translated(Adw.SwitchRow(), title=('浏览器域名统计', 'Track browser domains'), subtitle=('从窗口标题推断域名，失败则只记应用', 'Infer domains from window titles; otherwise track only the app'))
        self.browser_switch.connect("notify::active", self._on_browser)
        group.add(self.browser_switch)

        self.pause_switch = W.translated(Adw.SwitchRow(), title=('暂停记录', 'Pause tracking'), subtitle=('暂停期间不产生任何数据', 'No activity is recorded while paused'))
        self.pause_switch.connect("notify::active", self._on_pause)
        group.add(self.pause_switch)

        self.tray_switch = W.translated(Adw.SwitchRow(), title=('显示托盘图标', 'Show tray icon'), subtitle=('需要 GNOME AppIndicator 扩展；关闭后仅保留窗口', 'Requires a tray host (AppIndicator on GNOME); disable for window-only use'))
        self.tray_switch.connect("notify::active", self._on_tray)
        group.add(self.tray_switch)

        # ---- 每日限额 ----
        limits = W.translated(Adw.PreferencesGroup(), title=('每日限额', 'Daily limit'))
        W.translated(limits, description=('系统级应用无法强制屏蔽其他应用或网站，这里只做温和提醒。', 'Reminders only; apps and websites are never blocked.'))
        page.add(limits)

        self.limits_switch = W.translated(Adw.SwitchRow(), title=('启用每日限额', 'Enable daily limit'))
        self.limits_switch.connect("notify::active", self._on_limits)
        limits.add(self.limits_switch)

        self.limit_combo = W.translated(Adw.ComboRow(), title=('每日上限', 'Daily allowance'))
        self._limit_values = [60, 120, 180, 240, 300, 360, 480]
        W.translated_model(self.limit_combo, [('1 小时', '1 hour'), ('2 小时', '2 hours'), ('3 小时', '3 hours'), ('4 小时', '4 hours'), ('5 小时', '5 hours'), ('6 小时', '6 hours'), ('8 小时', '8 hours')])
        self.limit_combo.connect("notify::selected", self._on_limit_value)
        limits.add(self.limit_combo)

        self.distract_switch = W.translated(Adw.SwitchRow(), title=('分心网站提醒', 'Distracting site reminders'), subtitle=('社交/视频/购物/娱乐连续 10 分钟提醒，30 分钟冷却', 'Remind after 10 minutes on distracting sites; wait 30 minutes between reminders'))
        self.distract_switch.connect("notify::active", self._on_distract)
        limits.add(self.distract_switch)

        # ---- 提醒 ----
        reminders = W.translated(Adw.PreferencesGroup(), title=('提醒', 'Reminders'))
        page.add(reminders)

        self.notify_switch = W.translated(Adw.SwitchRow(), title=('允许系统通知', 'Allow desktop notifications'))
        self.notify_switch.connect("notify::active", self._on_notifications)
        reminders.add(self.notify_switch)

        self.break_switch = W.translated(Adw.SwitchRow(), title=('休息提醒', 'Break reminders'))
        self.break_switch.connect("notify::active", self._on_break_enabled)
        reminders.add(self.break_switch)

        self.break_combo = W.translated(Adw.ComboRow(), title=('休息间隔', 'Break interval'))
        self._break_values = [20, 30, 45, 60]
        W.translated_model(self.break_combo, [('20 分钟', '20 minutes'), ('30 分钟', '30 minutes'), ('45 分钟', '45 minutes'), ('60 分钟', '60 minutes')])
        self.break_combo.connect("notify::selected", self._on_break_interval)
        reminders.add(self.break_combo)

        self.water_switch = W.translated(Adw.SwitchRow(), title=('喝水提醒', 'Water reminders'))
        self.water_switch.connect("notify::active", self._on_water_enabled)
        reminders.add(self.water_switch)

        self.water_combo = W.translated(Adw.ComboRow(), title=('喝水间隔', 'Water interval'))
        self._water_values = [30, 45, 60, 90, 120]
        W.translated_model(self.water_combo, [('30 分钟', '30 minutes'), ('45 分钟', '45 minutes'), ('60 分钟', '60 minutes'), ('90 分钟', '90 minutes'), ('120 分钟', '120 minutes')])
        self.water_combo.connect("notify::selected", self._on_water_interval)
        reminders.add(self.water_combo)

        self.overlay_switch = W.translated(Adw.SwitchRow(), title=('番茄休息时弹微休息遮罩', 'Show a full-screen pomodoro break'), subtitle=('20 秒全屏护眼引导，可随时跳过', 'A 20-second eye break; skip at any time'))
        self.overlay_switch.connect("notify::active", self._on_overlay)
        reminders.add(self.overlay_switch)

        # ---- 排除应用 ----
        exclude = W.translated(Adw.PreferencesGroup(), title=('排除应用', 'Excluded apps'))
        W.translated(exclude, description=('名单里的应用完全不产生记录。', 'Apps on this list are never tracked.'))
        page.add(exclude)
        self.exclude_rows = []
        self.exclude_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        exclude.add(self.exclude_box)
        self.exclude_empty = W.label(('还没有排除任何应用。', 'No apps excluded yet.'), "tb-caption")
        self.exclude_box.append(self.exclude_empty)

        self.exclude_picker = W.translated(Adw.ComboRow(), title=('添加应用', 'Add an app'))
        self.exclude_picker.connect("notify::selected", self._on_exclude_add)
        exclude.add(self.exclude_picker)

        # ---- 外观与数据 ----
        appearance = W.translated(Adw.PreferencesGroup(), title=('外观与数据', 'Appearance and data'))
        page.add(appearance)

        self.lang_combo = W.translated(Adw.ComboRow(), title=('语言', 'Language'))
        self._lang_values = ["auto", "zh", "en"]
        W.translated_model(self.lang_combo, [('跟随系统', 'System default'), ('中文', 'Chinese'), ('英语', 'English')])
        self.lang_combo.connect("notify::selected", self._on_language)
        appearance.add(self.lang_combo)

        self.retention_combo = W.translated(Adw.ComboRow(), title=('数据保留期', 'Data retention'))
        self._retention_values = [0, 90, 180, 365]
        W.translated_model(self.retention_combo, [('永久保留', 'Keep forever'), ('90 天', '90 days'), ('180 天', '180 days'), ('365 天', '365 days')])
        self.retention_combo.connect("notify::selected", self._on_retention)
        appearance.add(self.retention_combo)

        export_row = W.translated(Adw.ActionRow(), title=("导出数据", "Export data"), subtitle=(f"CSV 明细 + Markdown 周报 → {downloads_dir().name}/", f"CSV activity + Markdown weekly report → {downloads_dir().name}/"))
        export_button = W.translated(Gtk.Button(), label=('导出', 'Export'))
        export_button.add_css_class("tb-ghost")
        export_button.set_valign(Gtk.Align.CENTER)
        export_button.connect("clicked", self._on_export)
        export_row.add_suffix(export_button)
        appearance.add(export_row)

        data_row = W.translated(Adw.ActionRow(subtitle=f"{self._ctx.store.path} · {self._ctx.store.size_bytes() / 1024:.0f} KB"), title=('数据库', 'Database'))
        appearance.add(data_row)

        appear_r = W.translated(Adw.ActionRow(), title=('界面主题', 'Appearance'), subtitle=('跟随系统深色/浅色', 'Follow the system light or dark theme'))
        appearance.add(appear_r)

        toolbar_content = toolbar
        self.set_content(toolbar_content)
        self.reload()

    # ------------------------------------------------------------------ #

    def _idx(self, values: list, current: int) -> int:
        return values.index(current) if current in values else 0

    def refresh_language(self) -> None:
        # Adw.ComboRow must finish its selection signal before its model changes.
        if self._language != resolved_language() and self._language_source is None:
            self._language_source = GLib.idle_add(self._apply_language)

    def _apply_language(self) -> bool:
        self._language_source = None
        self._language = resolved_language()
        self._syncing = True
        try:
            W.refresh_translations(self)
        finally:
            self._syncing = False
        self.reload()
        return False

    def reload(self) -> None:
        self.refresh_language()
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
        self._sync_sensitivity()

    def _sync_sensitivity(self) -> None:
        self.limit_combo.set_sensitive(self.limits_switch.get_active())
        self.break_combo.set_sensitive(self.break_switch.get_active())
        self.water_combo.set_sensitive(self.water_switch.get_active())

    def _rebuild_excludes(self) -> None:
        W.refresh_translations(self.exclude_empty)
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
            remove = W.translated(Gtk.Button(), label=('移除', 'Remove'))
            remove.add_css_class("tb-ghost")
            remove.connect("clicked", lambda _b, a=app_id: self._remove_exclude(a))
            row.append(remove)
            self.exclude_box.append(row)

        candidates = [
            (app_id, name)
            for app_id, name in self._ctx.store.known_apps()
            if app_id not in excluded
        ]
        self._exclude_ids = [None] + [app_id for app_id, _ in candidates]
        syncing = self._syncing
        self._syncing = True
        try:
            self.exclude_picker.set_model(Gtk.StringList.new(
                [T("选择要排除的应用…", "Choose an app to exclude…")] + [name for _, name in candidates]
            ))
            self.exclude_picker.set_selected(0)
            self.exclude_picker.set_sensitive(bool(candidates))
        finally:
            self._syncing = syncing

    def _remove_exclude(self, app_id: str) -> None:
        self._ctx.settings.excluded = self._ctx.settings.excluded - {app_id}
        self._rebuild_excludes()

    def _toast(self, text: str) -> None:
        if self._last_toast is not None:
            self._last_toast.set_title(text)
            return
        self._last_toast = Adw.Toast.new(text)
        self._last_toast.connect("dismissed", self._on_toast_dismissed)
        self.toast_overlay.add_toast(self._last_toast)

    def _on_toast_dismissed(self, toast) -> None:
        if self._last_toast is toast:
            self._last_toast = None

    # ---- 回调 ---------------------------------------------------------- #

    def _on_idle(self, row, _p) -> None:
        if self._syncing:
            return
        self._ctx.settings.idle_threshold = self._idle_values[row.get_selected()]

    def _on_capture_titles(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.tracker.force_close()
            self._ctx.settings.capture_titles = row.get_active()

    def _on_browser(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.tracker.force_close()
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
        self._toast(T('托盘设置已保存，重启应用后生效', 'Tray preference saved. Restart the app to apply it.'))

    def _on_limits(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.limits_enabled = row.get_active()
            self._sync_sensitivity()

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
            self._sync_sensitivity()

    def _on_break_interval(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.break_interval_minutes = self._break_values[row.get_selected()]

    def _on_water_enabled(self, row, _p) -> None:
        if not self._syncing:
            self._ctx.settings.water_enabled = row.get_active()
            self._sync_sensitivity()

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
        self.refresh_language()
        self._parent.refresh(force=True)
        self._toast(T("语言偏好已保存", "Language preference saved"))
        if self._ctx.on_language_changed:
            self._ctx.on_language_changed()

    def _on_retention(self, row, _p) -> None:
        if self._syncing:
            return
        self._ctx.settings.retention_days = self._retention_values[row.get_selected()]
        removed = self._ctx.tracker.prune_old_data()
        self._toast(T(f"已保存（清理 {removed} 条旧记录）", f"Saved ({removed} old records removed)"))

    def _on_exclude_add(self, row, _p) -> None:
        if self._syncing:
            return
        index = row.get_selected()
        if 0 < index < len(getattr(self, "_exclude_ids", [])):
            app_id = self._exclude_ids[index]
            self._ctx.tracker.force_close()
            self._ctx.settings.excluded = self._ctx.settings.excluded | {app_id}
            # Finish the selection signal before replacing Adw's model.
            GLib.idle_add(self._finish_exclude_add)

    def _finish_exclude_add(self) -> bool:
        self._rebuild_excludes()
        return False

    def _on_export(self, _button) -> None:
        extract_to_downloads(self, self._ctx)
