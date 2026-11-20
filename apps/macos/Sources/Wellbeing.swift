import Foundation

// MARK: - 每日限额与分心提醒（limits 设计，warn 模式）
//
// 系统级应用无法强制屏蔽其他应用/网站（那是浏览器插件的能力），所以这里
// 做 warn：阈值进度提醒 + 分心站点连续使用温和提醒（带冷却时间）。

struct LimitCheckInputs {
    var todayTotal: TimeInterval
    var dailyLimitMinutes: Int
    var currentHost: String?
    var currentSegmentStart: Date?
    var now: Date
}

@MainActor
final class LimitsEngine: ObservableObject {
    @Published private(set) var todayPercent = 0
    @Published private(set) var limitReached = false

    private var warnedPercent: Set<Int> = []
    private var lastWarnedDay = ""
    private var lastDistractNudge: Date?

    var onNotify: ((String, String) -> Void)?

    /// 每分钟由主循环驱动；返回值仅供测试断言（nil = 本次无提醒）。
    @discardableResult
    func minute(_ input: LimitCheckInputs, settings: @autoclosure () -> (enabled: Bool, distractEnabled: Bool) = (AppSettings.limitsEnabled, AppSettings.distractNudgeEnabled)) -> String? {
        let dayKey = Store.dayKey(input.now)
        if dayKey != lastWarnedDay {
            lastWarnedDay = dayKey
            warnedPercent = []
        }
        guard settings().enabled, input.dailyLimitMinutes > 0 else {
            todayPercent = 0
            limitReached = false
            return nil
        }

        let limit = TimeInterval(input.dailyLimitMinutes * 60)
        let percent = Int((input.todayTotal / limit * 100).rounded())
        todayPercent = percent
        limitReached = percent >= 100

        for threshold in [80, 90, 100] where percent >= threshold && !warnedPercent.contains(threshold) {
            warnedPercent.insert(threshold)
            let used = Fmt.duration(input.todayTotal, compact: true)
            if threshold >= 100 {
                onNotify?(T("今日屏幕时间已到限额 ⚠️", "Daily screen-time limit reached ⚠️"),
                          T("已用 \(used)。差不多该离开了，明天见。", "Used \(used). Time to wrap up, see you tomorrow."))
            } else {
                onNotify?(T("屏幕时间提醒", "Screen-time reminder"),
                          T("今日已用 \(used)，达到限额的 \(threshold)%。", "Used \(used) today — \(threshold)% of your limit."))
            }
            return "limit-\(threshold)"
        }

        // 分心站点连续使用温和提醒（10 分钟起步，30 分钟冷却）
        if settings().distractEnabled,
           let host = input.currentHost,
           let start = input.currentSegmentStart {
            let category = SiteCategory.forHost(host)
            if category.distracting {
                let minutes = Int(input.now.timeIntervalSince(start) / 60)
                if minutes >= 10, let last = lastDistractNudge {
                    if input.now.timeIntervalSince(last) < 30 * 60 { return nil }
                }
                if minutes >= 10 {
                    lastDistractNudge = input.now
                    onNotify?(T("该收心了 🧘", "Time to refocus 🧘"),
                              T("在 \(host) 已经 \(minutes) 分钟了（\(category.name)）。", "\(minutes) min on \(host) (\(category.name))."))
                    return "distract"
                }
            }
        }
        return nil
    }

    /// 仅供测试：重置当日状态。
    func resetForTesting() {
        warnedPercent = []
        lastWarnedDay = ""
        lastDistractNudge = nil
        todayPercent = 0
        limitReached = false
    }
}

// MARK: - 休息提醒 + 喝水提醒（reminders/water 设计）

@MainActor
final class RemindersEngine: ObservableObject {
    /// 连续活跃（非空闲、非休息）秒数，菜单/主窗口可展示。
    @Published private(set) var activeSeconds: TimeInterval = 0

    var onNotify: ((String, String) -> Void)?
    var cupsProvider: () -> Int = { 0 }
    var goalProvider: () -> Int = { AppSettings.waterGoalCups }

    private var lastWaterNudge: Date?
    private var lastBreakDay = ""
    private var gcdTimer: DispatchSourceTimer?

    /// 输入源：空闲状态 + 是否处于番茄休息期（App 层接线）。
    var inputsProvider: (() -> (idle: Bool, inBreak: Bool))?

    init() {
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now() + 5, repeating: 5)
        timer.setEventHandler { [weak self] in
            Task { @MainActor [weak self] in
                guard let self, let inputs = self.inputsProvider?() else { return }
                self.tick(idle: inputs.idle, inPomodoroBreak: inputs.inBreak)
            }
        }
        timer.resume()
        gcdTimer = timer
    }

    func stop() {
        gcdTimer?.cancel()
        gcdTimer = nil
    }

    /// 由主循环按固定步长驱动（tickInterval 秒）。
    func tick(idle: Bool, inPomodoroBreak: Bool, now: Date = Date(), tickInterval: TimeInterval = 5) {
        if Store.dayKey(now) != lastBreakDay {
            lastBreakDay = Store.dayKey(now)
            activeSeconds = 0
        }

        // 休息联动：空闲或番茄休息期都重置连续活跃计数（与休息联动）
        if idle || inPomodoroBreak {
            activeSeconds = 0
            return
        }
        activeSeconds += tickInterval

        if AppSettings.notificationsEnabled, AppSettings.breakReminderEnabled,
           activeSeconds >= TimeInterval(AppSettings.breakIntervalMinutes * 60) {
            activeSeconds = 0
            onNotify?(T("该休息一下了 👀", "Time for a break 👀"),
                     T("连续用眼较久，远眺放松一下，顺便站起来活动活动。", "Eyes have been busy — look far away and stretch a little."))
        }

        let hour = Calendar.current.component(.hour, from: now)
        let inWindow = hour >= AppSettings.waterStartHour && hour < AppSettings.waterEndHour
        if AppSettings.notificationsEnabled, AppSettings.waterEnabled, inWindow {
            let sinceLast = lastWaterNudge.map { now.timeIntervalSince($0) } ?? TimeInterval.greatestFiniteMagnitude
            if sinceLast >= TimeInterval(AppSettings.waterIntervalMinutes * 60) {
                lastWaterNudge = now
                let cups = cupsProvider()
                let goal = goalProvider()
                onNotify?(T("喝口水 💧", "Drink some water 💧"),
                          T("今天 \(cups)/\(goal) 杯。番茄休息时顺便补杯水。", "\(cups)/\(goal) cups today. Top up on your next pomodoro break."))
            }
        }
    }

    /// 微休息 / 番茄休息后由 UI 调用，重置连续活跃计数。
    func resetActiveTime() {
        activeSeconds = 0
    }

    /// 仅供测试。
    func resetForTesting() {
        activeSeconds = 0
        lastWaterNudge = nil
        lastBreakDay = ""
    }
}
