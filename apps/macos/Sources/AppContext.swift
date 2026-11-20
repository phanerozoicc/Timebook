import Foundation
import UserNotifications

// 全局模型上下文：AppKit 状态栏控制器与 SwiftUI 场景共用同一组引擎实例。
@MainActor
final class AppContext: ObservableObject {
    static let shared = AppContext()

    let store: Store
    let poller: Poller
    let pomodoro: PomodoroEngine
    let limits: LimitsEngine
    let reminders: RemindersEngine
    let breakController: BreakController
    let forfeit: ForfeitController

    /// 主窗口深链：弹窗「丢小时」等入口预设置目标页，MainWindow onAppear 消费。
    var pendingMainTab: Int?

    /// 状态栏弹窗需要关闭时由 SwiftUI 侧回调（AppDelegate 注入）。
    var closePopover: (() -> Void)?
    /// 主窗口唤起（由 MainWindow onAppear 注入 openWindow）。
    var openMain: (() -> Void)?

    /// 防 App Nap：菜单栏应用无窗口且无交互时，系统会暂停全部定时器，
    /// 导致追踪停止、提醒不触发。以 userInitiated 声明常驻活动。
    private var napActivity: NSObjectProtocol?

    private init() {
        napActivity = ProcessInfo.processInfo.beginActivity(
            options: [.userInitiated, .idleSystemSleepDisabled],
            reason: "Timebook 屏幕时间追踪与提醒（防 App Nap 冻结定时器）"
        )
        AppLog.installCrashHandlers()
        AppLog.info("AppContext 初始化开始")
        Self.logNotificationAuthorization()
        do {
            store = try Store()
        } catch {
            fatalError("Timebook: \(T("无法创建本地存储", "Cannot create local store"))：\(error)")
        }
        poller = Poller(store: store)
        pomodoro = PomodoroEngine()
        limits = LimitsEngine()
        reminders = RemindersEngine()
        breakController = BreakController()
        forfeit = ForfeitController()
        // 网址级判荒：host 取自轮询的当前分段；分段变化（含浏览器 tab 变化）即时回调
        forfeit.bind { [weak poller] in poller?.currentSegment?.host }
        poller.onSegmentChange = { [weak forfeit] bundleId, host in
            forfeit?.forwardSegmentChange(bundleId: bundleId, host: host)
        }
        wire()
    }

    private func wire() {
        pomodoro.onWorkSegment = { [store, pomodoro] start, end, completed in
            store.recordFocus(start: start, end: end, completed: completed,
                              presetName: pomodoro.activePresetName)
        }
        pomodoro.onNotify = Self.notify

        limits.onNotify = Self.notify

        reminders.onNotify = Self.notify
        reminders.cupsProvider = { [store] in store.cupsToday() }
        reminders.inputsProvider = { [poller, pomodoro] in
            (poller.isIdleNow, pomodoro.state.phase.isBreak)
        }
        breakController.onFinished = { [reminders] in
            AppLog.info("微休息结束，重置连续活跃")
            reminders.resetActiveTime()
        }
        AppLog.info("引擎接线完成")

        let snapshot: () -> Void = { [self] in
            let now = Date()
            let start = Calendar.current.startOfDay(for: now)
            let rows = store.rows(from: start, to: now.addingTimeInterval(60))
            let level = BrainLevel.forTotal(Agg.total(rows))
            WidgetSnapshot(
                todaySeconds: Agg.total(rows),
                level: level.level,
                levelName: level.name,
                levelLabel: level.label,
                pomoPhase: pomodoro.state.phase.rawValue,
                pomoRemain: pomodoro.remain,
                pomoRound: pomodoro.state.round,
                pomoTotal: pomodoro.phaseTotal,
                topAppName: Agg.byApp(rows).first?.name,
                generatedAt: now
            ).write()

            let segment = poller.currentSegment
            limits.minute(LimitCheckInputs(
                todayTotal: Agg.total(rows),
                dailyLimitMinutes: AppSettings.limitsDailyMinutes,
                currentHost: segment?.host,
                currentSegmentStart: segment?.start,
                now: now
            ))
        }
        pomodoro.onStateChange = snapshot
        poller.onMinuteTick = snapshot
    }

    static func notify(_ title: String, _ body: String) {
        AppLog.info("通知: \(title)")
        guard AppSettings.notificationsEnabled else {
            AppLog.info("通知已关闭（设置中「通知」开关），跳过投递")
            return
        }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        // 时限敏感：穿透专注模式，避免屏幕时间警告被静默归类
        content.interruptionLevel = .timeSensitive
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request) { error in
            if let error {
                AppLog.error("通知投递失败: \(error.localizedDescription)")
            } else {
                AppLog.debug("通知已投递: \(title)")
            }
        }
    }

    /// 启动时记录通知授权状态，便于排查「没有提醒」。
    static func logNotificationAuthorization() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            let status: String
            switch settings.authorizationStatus {
            case .notDetermined: status = "未决定(notDetermined)"
            case .denied: status = "已拒绝(denied)"
            case .authorized: status = "已允许(authorized)"
            case .provisional: status = "临时(provisional)"
            case .ephemeral: status = "受限(ephemeral)"
            @unknown default: status = "未知(\(settings.authorizationStatus.rawValue))"
            }
            AppLog.info("通知授权状态: \(status)")
        }
    }

    static func requestNotifications() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, error in
            AppLog.info("通知授权结果: granted=\(granted) error=\(error.map { $0.localizedDescription } ?? "无")")
        }
    }
}
