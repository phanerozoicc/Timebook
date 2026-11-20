import Foundation

// MARK: - Settings (UserDefaults-backed, read fresh each tick)

enum AppSettings {
    static let idleKey = "idleThreshold"
    static let excludedKey = "excludedApps"
    static let retentionKey = "retentionDays"
    static let languageKey = "language"
    static let titlesKey = "captureTitles"
    static let limitsEnabledKey = "limitsEnabled"
    static let limitsDailyMinKey = "limitsDailyMin"
    static let distractNudgeKey = "distractNudge"
    static let breakReminderKey = "breakReminderEnabled"
    static let breakIntervalKey = "breakIntervalMin"
    static let waterEnabledKey = "waterEnabled"
    static let waterIntervalKey = "waterIntervalMin"
    static let waterStartHourKey = "waterStartHour"
    static let waterEndHourKey = "waterEndHour"
    static let waterGoalKey = "waterGoalCups"
    static let notificationsKey = "notificationsEnabled"
    static let pomoBreakOverlayKey = "pomodoroBreakOverlay"

    /// 0 = 不启用空闲判定（看视频等被动使用也计时）。
    static var idleThreshold: Int {
        let value = UserDefaults.standard.integer(forKey: idleKey)
        return value >= 30 ? value : (value == 0 ? 0 : 120)
    }

    static var excluded: Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: excludedKey) ?? [])
    }

    /// 0 means keep forever.
    static var retentionDays: Int {
        let value = UserDefaults.standard.integer(forKey: retentionKey)
        return [90, 180, 365].contains(value) ? value : 0
    }

    /// "auto" | "zh" | "en"
    static var language: String {
        UserDefaults.standard.string(forKey: languageKey) ?? "auto"
    }

    /// 窗口标题采集需要辅助功能权限，默认关。
    static var captureTitles: Bool {
        UserDefaults.standard.bool(forKey: titlesKey)
    }

    // 每日限额（limits 设计，warn 模式；系统级应用无法强制屏蔽其他应用）

    static var limitsEnabled: Bool { UserDefaults.standard.bool(forKey: limitsEnabledKey) }
    static var limitsDailyMinutes: Int {
        let value = UserDefaults.standard.integer(forKey: limitsDailyMinKey)
        return value > 0 ? value : 240
    }
    static var distractNudgeEnabled: Bool { UserDefaults.standard.bool(forKey: distractNudgeKey) }

    // 提醒（休息 + 喝水，reminders/water 设计）

    static var breakReminderEnabled: Bool { UserDefaults.standard.object(forKey: breakReminderKey) as? Bool ?? true }
    static var breakIntervalMinutes: Int {
        let value = UserDefaults.standard.integer(forKey: breakIntervalKey)
        return value >= 10 ? value : 30
    }
    static var waterEnabled: Bool { UserDefaults.standard.object(forKey: waterEnabledKey) as? Bool ?? true }
    static var waterIntervalMinutes: Int {
        let value = UserDefaults.standard.integer(forKey: waterIntervalKey)
        return value >= 15 ? value : 60
    }
    static var waterStartHour: Int {
        let value = UserDefaults.standard.integer(forKey: waterStartHourKey)
        return (0...23).contains(value) ? value : 9
    }
    static var waterEndHour: Int {
        let value = UserDefaults.standard.integer(forKey: waterEndHourKey)
        return (0...24).contains(value) ? value : 22
    }
    static var waterGoalCups: Int {
        let value = UserDefaults.standard.integer(forKey: waterGoalKey)
        return value > 0 ? value : 8
    }
    static var notificationsEnabled: Bool {
        UserDefaults.standard.object(forKey: notificationsKey) as? Bool ?? true
    }

    /// 番茄进入休息阶段时自动弹 20 秒微休息遮罩。
    static var pomodoroBreakOverlay: Bool {
        UserDefaults.standard.object(forKey: pomoBreakOverlayKey) as? Bool ?? true
    }

    static func set(_ value: Any?, forKey key: String) {
        UserDefaults.standard.set(value, forKey: key)
    }

    /// 限额时长的人类可读标签（正确处理 1 小时以下的分钟数）。
    static var limitsDailyLabel: String {
        let minutes = limitsDailyMinutes
        if minutes < 60 { return T("\(minutes) 分钟", "\(minutes) min") }
        if minutes % 60 == 0 { return T("\(minutes / 60) 小时", "\(minutes / 60) h") }
        return T("\(minutes / 60) 小时 \(minutes % 60) 分", "\(minutes / 60)h \(minutes % 60)m")
    }
}
