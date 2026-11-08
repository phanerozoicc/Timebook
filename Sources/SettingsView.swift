import ServiceManagement
import SwiftUI
import UserNotifications

struct SettingsView: View {
    let store: Store
    @ObservedObject var poller: Poller
    @ObservedObject var forfeit: ForfeitController

    @State private var newCustomDomain = ""
    @State private var showAppPicker = false
    @State private var appQuery = ""

    @State private var idleThreshold: Int
    @State private var retention: Int
    @State private var excluded: Set<String>
    @State private var knownApps: [(appID: String, appName: String)] = []
    @State private var launchAtLogin: Bool
    @State private var language: String
    @State private var captureTitles: Bool
    @State private var limitsEnabled: Bool
    @State private var limitsDailyMinutes: Int
    @State private var distractNudge: Bool
    @State private var breakReminderEnabled: Bool
    @State private var breakIntervalMinutes: Int
    @State private var waterEnabled: Bool
    @State private var waterIntervalMinutes: Int
    @State private var waterStartHour: Int
    @State private var waterEndHour: Int
    @State private var waterGoalCups: Int
    @State private var notificationsEnabled: Bool
    @State private var exportStatus: String?
    @State private var notifDenied = false

    init(store: Store, poller: Poller, forfeit: ForfeitController) {
        self.store = store
        self.poller = poller
        self.forfeit = forfeit
        _idleThreshold = State(initialValue: AppSettings.idleThreshold)
        _retention = State(initialValue: AppSettings.retentionDays)
        _excluded = State(initialValue: AppSettings.excluded)
        _launchAtLogin = State(initialValue: SMAppService.mainApp.status == .enabled)
        _language = State(initialValue: AppSettings.language)
        _captureTitles = State(initialValue: AppSettings.captureTitles)
        _limitsEnabled = State(initialValue: AppSettings.limitsEnabled)
        _limitsDailyMinutes = State(initialValue: AppSettings.limitsDailyMinutes)
        _distractNudge = State(initialValue: AppSettings.distractNudgeEnabled)
        _breakReminderEnabled = State(initialValue: AppSettings.breakReminderEnabled)
        _breakIntervalMinutes = State(initialValue: AppSettings.breakIntervalMinutes)
        _waterEnabled = State(initialValue: AppSettings.waterEnabled)
        _waterIntervalMinutes = State(initialValue: AppSettings.waterIntervalMinutes)
        _waterStartHour = State(initialValue: AppSettings.waterStartHour)
        _waterEndHour = State(initialValue: AppSettings.waterEndHour)
        _waterGoalCups = State(initialValue: AppSettings.waterGoalCups)
        _notificationsEnabled = State(initialValue: AppSettings.notificationsEnabled)
    }

    var body: some View {
        Form {
            Section(header: Label(T("记录", "Tracking"), systemImage: "record.circle")) {
                Toggle(T("暂停记录", "Pause tracking"), isOn: $poller.paused)
                Picker(T("空闲判定", "Idle cutoff"), selection: $idleThreshold) {
                    Text(T("不启用（看视频等也计时）", "Off (count passive watching too)")).tag(0)
                    ForEach([60, 120, 180, 300, 600], id: \.self) { seconds in
                        Text(T("无输入 \(Fmt.duration(TimeInterval(seconds))) 后断开", "Cut after \(Fmt.duration(TimeInterval(seconds))) of no input")).tag(seconds)
                    }
                }
                Toggle(T("采集窗口标题", "Capture window titles"), isOn: $captureTitles)
                if captureTitles && !Accessibility.available {
                    Text(T("需要辅助功能权限：打开 系统设置 → 隐私与安全性 → 辅助功能，勾选 Timebook。", "Needs Accessibility: System Settings → Privacy & Security → Accessibility, enable Timebook."))
                        .font(.caption).foregroundStyle(.orange)
                }
                Text(T("键盘鼠标停止输入超过该时长后不计入统计（如离开座位）。窗口标题用于时间线回看，需要辅助功能权限，默认关。", "Stops counting after no input for this long. Window titles need Accessibility permission and stay off by default."))
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section(header: Label(T("每日限额", "Daily limit"), systemImage: "gauge.with.needle")) {
                Toggle(T("启用每日屏幕时间限额", "Enable daily screen-time limit"), isOn: $limitsEnabled)
                if limitsEnabled {
                    Picker(T("总限额", "Total limit"), selection: $limitsDailyMinutes) {
                        Text("2h").tag(120)
                        Text("4h").tag(240)
                        Text("6h").tag(360)
                        Text("8h").tag(480)
                    }
                    Toggle(T("分心网站连续使用提醒", "Nudge on distracting sites"), isOn: $distractNudge)
                    Text(T("达到限额 80% / 90% / 100% 时提醒。系统级应用无法强制屏蔽其他应用，故为提醒式限额。", "Notifies at 80% / 90% / 100% of the limit. A system-wide app cannot block other apps, so warnings are reminder-style."))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }

            Section(header: Label(T("提醒", "Reminders"), systemImage: "bell.badge.fill")) {
                Toggle(T("通知", "Notifications"), isOn: $notificationsEnabled)
                Toggle(T("休息提醒", "Break reminder"), isOn: $breakReminderEnabled)
                if breakReminderEnabled {
                    Picker(T("连续活跃", "After active"), selection: $breakIntervalMinutes) {
                        ForEach([20, 30, 45, 60], id: \.self) { minutes in
                            Text(T("每 \(minutes) 分钟", "every \(minutes) min")).tag(minutes)
                        }
                    }
                }
                Toggle(T("喝水提醒", "Water reminder"), isOn: $waterEnabled)
                if waterEnabled {
                    Picker(T("间隔", "Interval"), selection: $waterIntervalMinutes) {
                        ForEach([30, 45, 60, 90], id: \.self) { minutes in
                            Text(T("每 \(minutes) 分钟", "every \(minutes) min")).tag(minutes)
                        }
                    }
                    HStack {
                        Picker(T("时间窗", "Window"), selection: $waterStartHour) {
                            ForEach(0..<24, id: \.self) { hour in Text("\(hour):00").tag(hour) }
                        }
                        Text("→")
                        Picker(T("到", "to"), selection: $waterEndHour) {
                            ForEach(1...24, id: \.self) { hour in Text("\(hour):00").tag(hour) }
                        }
                    }
                    Stepper(value: $waterGoalCups, in: 1...16) {
                        Text(T("每日目标 \(waterGoalCups) 杯", "Daily goal: \(waterGoalCups) cups"))
                    }
                }
            }

            Section(header: Label(T("排除应用（完全不记录）", "Excluded apps (never recorded)"), systemImage: "eye.slash.fill")) {
                if knownApps.isEmpty {
                    Text(T("还没有记录过应用。", "No apps recorded yet.")).foregroundStyle(.secondary)
                } else {
                    ForEach(knownApps, id: \.appID) { app in
                        Toggle(app.appName, isOn: Binding(
                            get: { excluded.contains(app.appID) },
                            set: { on in
                                if on { excluded.insert(app.appID) } else { excluded.remove(app.appID) }
                                AppSettings.set(Array(excluded).sorted(), forKey: AppSettings.excludedKey)
                            }
                        ))
                    }
                }
                Text(T("已排除的 App 不会写入任何数据。", "Excluded apps never touch the database."))
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section(header: Label(T("丢小时 · 分心网站", "Forfeit · Distracting sites"), systemImage: "hourglass")) {
                ForEach(forfeit.siteCategories, id: \.id) { category in
                    HStack(spacing: 8) {
                        Circle().fill(category.color).frame(width: 9, height: 9)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(category.name)
                            Text(category.domains.joined(separator: " · "))
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                                .lineLimit(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                        Button {
                            forfeit.toggleCategory(id: category.id)
                        } label: {
                            Text(forfeit.isCategoryEnabled(category.id)
                                 ? T("已开启", "On") : T("已关闭", "Off"))
                                .font(.callout.weight(.semibold))
                                .foregroundStyle(forfeit.isCategoryEnabled(category.id) ? Color.forfeitLost : .secondary)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                Divider()
                Text(T("自定义网站（打开即记荒，优先于类目）", "Custom sites (opening one forfeits the hour; overrides categories)"))
                    .font(.callout.weight(.semibold))
                ForEach(forfeit.customDomains, id: \.self) { domain in
                    HStack(spacing: 8) {
                        Text(domain).font(.callout.monospaced())
                        Spacer()
                        Button(T("删除", "Remove")) {
                            forfeit.removeCustomDomain(domain)
                        }
                        .buttonStyle(.link)
                        .font(.caption)
                    }
                }
                HStack {
                    TextField(T("example.com", "example.com"), text: $newCustomDomain)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { addCustomDomain() }
                    Button(T("添加", "Add"), action: addCustomDomain)
                }
                Text(T("支持子域：填 douyin.com 会连 www.douyin.com 一起判。类目表没有的站加在这里。",
                       "Subdomains included: adding douyin.com also covers www.douyin.com. Add sites missing from the built-in categories here."))
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section(header: Label(T("丢小时 · 分心应用", "Forfeit · Distracting apps"), systemImage: "app.badge.fill")) {
                if forfeit.distractors.isEmpty {
                    Text(T("还没有分心应用——被切到前台就记荒的应用加在这里。", "No distracting apps yet — apps that forfeit the hour when activated."))
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(forfeit.distractors) { app in
                        HStack(spacing: 8) {
                            Image(nsImage: NSWorkspace.shared.icon(forFile: app.path))
                                .resizable()
                                .frame(width: 18, height: 18)
                            VStack(alignment: .leading, spacing: 0) {
                                Text(app.name)
                                Text(app.id)
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                            }
                            Spacer()
                            Button(T("移除", "Remove")) {
                                forfeit.removeDistractor(id: app.id)
                            }
                            .buttonStyle(.link)
                            .font(.caption)
                        }
                    }
                }
                DisclosureGroup(isExpanded: Binding(
                    get: { showAppPicker },
                    set: { on in
                        showAppPicker = on
                        if on { forfeit.ensureCatalogLoaded() }
                    }
                )) {
                    TextField(T("搜索应用名", "Search apps"), text: $appQuery)
                        .textFieldStyle(.roundedBorder)
                        .controlSize(.small)
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 2) {
                            ForEach(appPickerChoices) { app in
                                Button {
                                    forfeit.addDistractor(app)
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(nsImage: NSWorkspace.shared.icon(forFile: app.path))
                                            .resizable()
                                            .frame(width: 18, height: 18)
                                        Text(app.name)
                                            .foregroundStyle(appPickerAdded.contains(app.id) ? .secondary : .primary)
                                        Spacer()
                                        if appPickerAdded.contains(app.id) {
                                            Image(systemName: "checkmark")
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .disabled(appPickerAdded.contains(app.id))
                            }
                        }
                    }
                    .frame(height: 200)
                } label: {
                    Text(T("添加应用…", "Add apps…"))
                }
            }

            Section(header: Label(T("外观与数据", "Appearance & data"), systemImage: "paintpalette.fill")) {
                Picker(T("语言", "Language"), selection: $language) {
                    Text(T("跟随系统", "System")).tag("auto")
                    Text("中文").tag("zh")
                    Text("English").tag("en")
                }
                Picker(T("保留时长", "Retention"), selection: $retention) {
                    Text(T("90 天", "90 days")).tag(90)
                    Text(T("180 天", "180 days")).tag(180)
                    Text(T("365 天", "365 days")).tag(365)
                    Text(T("永久保留", "Keep forever")).tag(0)
                }
                Text(T("超期的旧数据在启动时自动删除。文件位置：~/Library/Application Support/Timebook/", "Old data is pruned at launch. Files live in ~/Library/Application Support/Timebook/"))
                    .font(.caption).foregroundStyle(.secondary)
                Toggle(T("登录时启动", "Launch at login"), isOn: $launchAtLogin)
                HStack {
                    Button(T("导出明细 CSV…", "Export CSV…")) { exportCSV() }
                    Button(T("导出周报 Markdown…", "Export weekly report…")) { exportReport() }
                    if let exportStatus {
                        Text(exportStatus).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 520, height: 620)
        .onAppear {
            knownApps = store.knownApps()
            UNUserNotificationCenter.current().getNotificationSettings { settings in
                DispatchQueue.main.async {
                    notifDenied = settings.authorizationStatus == .denied
                }
            }
        }
        .onChange(of: idleThreshold) { AppSettings.set($0, forKey: AppSettings.idleKey) }
        .onChange(of: retention) { AppSettings.set($0, forKey: AppSettings.retentionKey) }
        .onChange(of: language) { AppSettings.set($0, forKey: AppSettings.languageKey) }
        .onChange(of: captureTitles) { on in
            AppSettings.set(on, forKey: AppSettings.titlesKey)
            if on { _ = Accessibility.ensurePermission() }
        }
        .onChange(of: limitsEnabled) { AppSettings.set($0, forKey: AppSettings.limitsEnabledKey) }
        .onChange(of: limitsDailyMinutes) { AppSettings.set($0, forKey: AppSettings.limitsDailyMinKey) }
        .onChange(of: distractNudge) { AppSettings.set($0, forKey: AppSettings.distractNudgeKey) }
        .onChange(of: breakReminderEnabled) { on in
            AppSettings.set(on, forKey: AppSettings.breakReminderKey)
            if on { Self.requestNotifications() }
        }
        .onChange(of: breakIntervalMinutes) { AppSettings.set($0, forKey: AppSettings.breakIntervalKey) }
        .onChange(of: waterEnabled) { on in
            AppSettings.set(on, forKey: AppSettings.waterEnabledKey)
            if on { Self.requestNotifications() }
        }
        .onChange(of: waterIntervalMinutes) { AppSettings.set($0, forKey: AppSettings.waterIntervalKey) }
        .onChange(of: waterStartHour) { AppSettings.set($0, forKey: AppSettings.waterStartHourKey) }
        .onChange(of: waterEndHour) { AppSettings.set($0, forKey: AppSettings.waterEndHourKey) }
        .onChange(of: waterGoalCups) { AppSettings.set($0, forKey: AppSettings.waterGoalKey) }
        .onChange(of: notificationsEnabled) { AppSettings.set($0, forKey: AppSettings.notificationsKey) }
        .onChange(of: launchAtLogin) { on in
            do {
                if on { try SMAppService.mainApp.register() }
                else { try SMAppService.mainApp.unregister() }
            } catch {
                launchAtLogin = SMAppService.mainApp.status == .enabled
            }
        }
    }

    private var appPickerAdded: Set<String> {
        Set(forfeit.distractors.map(\.id))
    }

    private var appPickerChoices: [CatalogApp] {
        forfeit.catalogApps.filter {
            appQuery.isEmpty || $0.name.localizedCaseInsensitiveContains(appQuery)
                || $0.id.localizedCaseInsensitiveContains(appQuery)
        }
    }

    private func addCustomDomain() {
        let added = forfeit.addCustomDomain(newCustomDomain)
        if added { newCustomDomain = "" }
        exportStatus = added ? T("已添加", "Added") : T("无效或已存在的域名", "Invalid or duplicate domain")
    }

    private func exportCSV() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "timebook-export.csv"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let now = Date()
        let rows = store.rows(from: Date.distantPast, to: now.addingTimeInterval(60))
        do {
            try Exporter.csv(rows).write(to: url, atomically: true, encoding: .utf8)
            exportStatus = T("已导出 \(rows.count) 行 ✓", "Exported \(rows.count) rows ✓")
        } catch {
            exportStatus = T("导出失败", "Export failed")
        }
    }

    private func exportReport() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.plainText]
        panel.nameFieldStringValue = "timebook-weekly.md"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let calendar = Calendar.current
        let now = Date()
        let start = calendar.date(byAdding: .day, value: -6, to: calendar.startOfDay(for: now))!
        let rows = store.rows(from: start, to: now.addingTimeInterval(60))
        let focus = store.focusEvents(from: start, to: now.addingTimeInterval(60)).filter(\.completed)
        do {
            let markdown = Exporter.weeklyMarkdown(
                now: now,
                perDay: Agg.perDay(rows),
                topApps: Agg.byApp(rows),
                topHosts: Agg.byHost(rows),
                categories: Agg.byCategory(rows),
                pomodoros: focus.count,
                focusSeconds: focus.reduce(0) { $0 + $1.end.timeIntervalSince($1.start) },
                cups: store.cupsToday(now: now),
                goalCups: AppSettings.waterGoalCups
            )
            try markdown.write(to: url, atomically: true, encoding: .utf8)
            exportStatus = T("周报已导出 ✓", "Report exported ✓")
        } catch {
            exportStatus = T("导出失败", "Export failed")
        }
    }

    static func requestNotifications() {
        AppContext.requestNotifications()
    }
}

import UniformTypeIdentifiers

// MARK: - 辅助功能权限（窗口标题采集，默认关）

enum Accessibility {
    static var available: Bool { AXIsProcessTrusted() }

    /// 首次开启时引导到系统设置；返回是否已授权。
    @discardableResult
    static func ensurePermission() -> Bool {
        let trusted = AXIsProcessTrusted()
        if !trusted {
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as NSDictionary
            _ = AXIsProcessTrustedWithOptions(options)
        }
        return trusted
    }
}
