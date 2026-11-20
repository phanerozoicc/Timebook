import AppKit
import ApplicationServices
import CoreGraphics
import Foundation
import SwiftData

// MARK: - Browser tab URL via AppleScript (optional, gracefully degrades)

enum Browser {
    static let chromium: [String: String] = [
        "com.google.Chrome": "Google Chrome",
        "company.thebrowser.browser": "Arc",
        "company.thebrowser.Arc": "Arc",
        "com.microsoft.edgemac": "Microsoft Edge",
        "com.brave.Browser": "Brave Browser",
        "com.vivaldi.Vivaldi": "Vivaldi",
        "com.operasoftware.Opera": "Opera",
    ]

    static func isBrowser(_ bundleID: String) -> Bool {
        chromium[bundleID] != nil || bundleID == "com.apple.Safari"
    }

    /// 同步版本：必须在专用后台队列调用（NSAppleScript 可能阻塞数百毫秒到数秒，
    /// 绝不能上主线程）。denied 命中时直接返回 nil。
    static func activeTabURLSync(bundleID: String, appName: String, denied: Set<String>) -> (url: String?, deniedNow: Bool) {
        guard !denied.contains(bundleID) else { return (nil, false) }
        let script: String
        if bundleID == "com.apple.Safari" {
            script = "tell application \"Safari\" to get URL of front document"
        } else {
            let name = chromium[bundleID] ?? appName
            script = "tell application \"\(name)\" to get URL of active tab of front window"
        }
        var errorInfo: NSDictionary?
        let result = NSAppleScript(source: script)?.executeAndReturnError(&errorInfo)
        if let errorInfo {
            let declined = (errorInfo[NSAppleScript.errorNumber] as? Int) == -1743
            return (nil, declined)
        }
        return (result?.stringValue, false)
    }
}

// MARK: - Poller

@MainActor
final class Poller: ObservableObject {
    @Published private(set) var currentLine: String?
    @Published private(set) var todaySeconds: TimeInterval = 0
    @Published var paused = false {
        didSet {
            if paused { closeOpen(at: Date()) }
        }
    }

    private let store: Store
    private var open: (event: UsageEvent, identity: String)?
    private var lastTick = Date()
    private var gcdTimer: DispatchSourceTimer?
    private var deniedBrowsers = Set<String>()
    private var lastMenuMinute: (hour: Int, minute: Int) = (-1, -1)
    private var lastTitlePid: pid_t = -1
    private var cachedTitle: String?
    private var tickCount = 0
    private var sessionLockedNow = false   // 锁屏（会话级）
    private var screensAsleepNow = false   // 显示器休眠
    private var screenBlocked: Bool { sessionLockedNow || screensAsleepNow }
    private let urlQueue = DispatchQueue(label: "com.haozc.Timebook.url", qos: .userInitiated)
    private var urlInFlight = false
    private var cachedURL: (bundleID: String, url: String?, at: Date)?

    /// Called once per minute (menu refresh) — used for widget snapshots.
    var onMinuteTick: (() -> Void)?

    /// 当前是否处于键鼠空闲（供提醒引擎联动）。
    @Published private(set) var isIdleNow = false

    /// 当前分段信息（供限额引擎判断分心连续使用）。
    struct SegmentInfo {
        let appID: String
        let appName: String
        let host: String?
        let start: Date
    }

    var currentSegment: SegmentInfo? {
        guard let open else { return nil }
        return SegmentInfo(appID: open.event.appID, appName: open.event.appName,
                           host: open.event.host, start: open.event.start)
    }

    /// 分段变化回调（切换应用或浏览器 tab 网址变化时）：供丢小时做网址级判荒。
    var onSegmentChange: ((String, String?) -> Void)?

    init(store: Store) {
        self.store = store
        store.deleteOlderThan(days: AppSettings.retentionDays)
        startTimer()
        observeTermination()
        observeScreenState()
        // 启动时一次性同步锁屏态（处理"启动时已锁屏"）；之后解锁只信系统通知，
        // 会话字典有传播延迟，逐 tick 轮询会与通知竞态（实测 0.36s 内翻回解锁）
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self, let dict = CGSessionCopyCurrentDictionary() as? [String: Any],
                  (dict["CGSSessionScreenIsLocked"] as? String) == "1" else { return }
            self.setSessionLocked(true, reason: "启动时检测到已锁屏")
        }
    }

    func finish() {
        gcdTimer?.cancel()
        gcdTimer = nil
        closeOpen(at: Date())
    }

    private func startTimer() {
        // GCD 定时器：macOS 27 会回收 LSUIElement 应用 RunLoop common-mode 的
        // 重复 Timer（实测 fire 一次即停），DispatchSourceTimer 不经 RunLoop，不受影响
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now() + 2, repeating: 2)
        timer.setEventHandler { [weak self] in
            Task { @MainActor [weak self] in self?.tick() }
        }
        timer.resume()
        gcdTimer = timer
        AppLog.info("轮询定时器已启动（GCD 2s 间隔）")
    }

    /// 锁屏/显示器休眠 → 暂停计时（与键鼠空闲判定无关，即使空闲判定关闭也生效）
    private func observeScreenState() {
        let dnc = DistributedNotificationCenter.default()
        dnc.addObserver(forName: NSNotification.Name("com.apple.screenIsLocked"),
                        object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.setSessionLocked(true, reason: "锁屏通知") }
        }
        dnc.addObserver(forName: NSNotification.Name("com.apple.screenIsUnlocked"),
                        object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.setSessionLocked(false, reason: "解锁通知") }
        }
        let wnc = NSWorkspace.shared.notificationCenter
        wnc.addObserver(forName: NSWorkspace.screensDidSleepNotification,
                        object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.setScreensAsleep(true, reason: "显示器休眠") }
        }
        wnc.addObserver(forName: NSWorkspace.screensDidWakeNotification,
                        object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.setScreensAsleep(false, reason: "显示器唤醒") }
        }
    }

    private func setSessionLocked(_ locked: Bool, reason: String) {
        guard sessionLockedNow != locked else { return }
        sessionLockedNow = locked
        AppLog.info("屏幕状态: \(locked ? "锁屏（暂停计时）" : "解锁（恢复计时）") —— \(reason)")
        if locked { closeOpen(at: Date()) }
    }

    private func setScreensAsleep(_ asleep: Bool, reason: String) {
        guard screensAsleepNow != asleep else { return }
        screensAsleepNow = asleep
        AppLog.info("屏幕状态: \(asleep ? "显示器休眠（暂停计时）" : "显示器唤醒（恢复计时）") —— \(reason)")
        if asleep { closeOpen(at: Date()) }
    }

    /// 兜底轮询：CGSession 会话字典里的锁屏标记（防止通知漏收，如启动时已锁屏）
    private func sessionScreenLocked() -> Bool {
        guard let dict = CGSessionCopyCurrentDictionary() as? [String: Any] else { return false }
        return (dict["CGSSessionScreenIsLocked"] as? String) == "1"
    }

    private func observeTermination() {
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            // Terminate completes synchronously after this notification; an
            // async Task would never run, so seal the segment right here.
            MainActor.assumeIsolated {
                self?.finish()
            }
        }
    }

    private var lastTickCountdown = "" // 空闲/暂停等状态变化日志限频

    func tick() {
        let now = Date()
        defer { lastTick = now }
        tickCount += 1
        if tickCount % 150 == 1 { // ~每 5 分钟一次心跳
            AppLog.info("tick 心跳 #\(tickCount) elapsed=\(Int(now.timeIntervalSince(lastTick)))s threshold=\(AppSettings.idleThreshold)")
        }

        guard !paused else {
            if lastTickCountdown != "paused" {
                AppLog.info("tick: 暂停中（不计时）")
                lastTickCountdown = "paused"
            }
            currentLine = nil
            return
        }

        // 锁屏/黑屏：不计时（显示器休眠与锁屏是独立标志，互不覆盖）
        if screenBlocked {
            if lastTickCountdown != "screen" {
                AppLog.info("tick: 锁屏/黑屏，不计时")
                lastTickCountdown = "screen"
            }
            closeOpen(at: now)
            currentLine = T("锁屏中", "Locked")
            isIdleNow = true
            refreshMenu(now: now)
            return
        }
        if lastTickCountdown == "screen" { lastTickCountdown = "" }

        guard let front = NSWorkspace.shared.frontmostApplication,
              let bundleID = front.bundleIdentifier, !bundleID.isEmpty else {
            closeOpen(at: now)
            currentLine = nil
            return
        }

        // Machine slept: the wall-clock gap since our last tick is bigger than
        // any plausible poll delay, so seal the segment at sleep time.
        if now.timeIntervalSince(lastTick) > Double(max(AppSettings.idleThreshold, 300)) + 30 {
            AppLog.info("检测到睡眠，分段封口")
            closeOpen(at: lastTick)
            open = nil
            refreshMenu(now: now)
            return
        }

        // Idle (no keyboard/mouse for a while): stop counting.
        // 阈值 0 = 不启用空闲判定（看视频等被动使用也计时）
        let idleCutoff = Double(AppSettings.idleThreshold)
        if idleCutoff > 0, idleSeconds() >= idleCutoff {
            // Seal slightly back in time so the segment ends at the real last input.
            let idle = idleSeconds()
            closeOpen(at: now.addingTimeInterval(-max(0, idle - 5)))
            open = nil
            currentLine = T("空闲中", "Idle")
            isIdleNow = true
            refreshMenu(now: now)
            return
        }
        isIdleNow = false

        if AppSettings.excluded.contains(bundleID) {
            closeOpen(at: now)
            open = nil
            currentLine = nil
            return
        }

        let isBrowser = Browser.isBrowser(bundleID)
        var detail: String?
        if isBrowser {
            if let cached = cachedURL, cached.bundleID == bundleID,
               now.timeIntervalSince(cached.at) < 2.0 {
                detail = cached.url
            }
            if !urlInFlight {
                urlInFlight = true
                let deniedSnapshot = deniedBrowsers
                let appName = front.localizedName ?? bundleID
                urlQueue.async { [weak self] in
                    let result = Browser.activeTabURLSync(bundleID: bundleID, appName: appName, denied: deniedSnapshot)
                    DispatchQueue.main.async { [weak self] in
                        guard let self else { return }
                        if result.deniedNow {
                            AppLog.info("浏览器自动化被拒绝，本次会话不再查询: \(bundleID)")
                            self.deniedBrowsers.insert(bundleID)
                        }
                        self.cachedURL = (bundleID, result.url, Date())
                        self.urlInFlight = false
                    }
                }
            }
        }
        let title = AppSettings.captureTitles && !isBrowser
            ? windowTitle(pid: front.processIdentifier)
            : nil
        let identity = bundleID + "|" + (detail ?? "") + "|" + (title ?? "")

        if let openEvent = open, openEvent.identity == identity {
            openEvent.event.end = now
        } else {
            AppLog.info("切换应用: \(front.localizedName ?? bundleID) url=\(detail ?? "-") title=\(title ?? "-")")
            closeOpen(at: now)
            let event = UsageEvent(
                appID: bundleID,
                appName: front.localizedName ?? bundleID,
                detail: detail,
                host: detail?.urlHost,
                title: title,
                start: now, end: now
            )
            store.context.insert(event)
            open = (event, identity)
            onSegmentChange?(bundleID, detail?.urlHost)
        }

        currentLine = {
            let name = front.localizedName ?? bundleID
            if let host = detail?.urlHost { return "\(name) — \(host)" }
            return name
        }()

        try? store.context.save()
        refreshMenu(now: now)
    }

    private func closeOpen(at date: Date) {
        guard let openEvent = open else { return }
        openEvent.event.end = max(openEvent.event.start, date)
        open = nil
        try? store.context.save()
    }

    private func refreshMenu(now: Date) {
        let components = Calendar.current.dateComponents([.hour, .minute], from: now)
        let minuteKey = (hour: components.hour ?? -1, minute: components.minute ?? -1)
        guard minuteKey != lastMenuMinute else { return }
        lastMenuMinute = minuteKey
        let start = Calendar.current.startOfDay(for: now)
        let end = start.addingTimeInterval(86_400)
        todaySeconds = Agg.total(store.rows(from: start, to: end))
        onMinuteTick?()
    }

    /// 窗口标题（需要辅助功能权限；未授权/取不到时返回 nil）。
    private func windowTitle(pid: pid_t) -> String? {
        if pid != lastTitlePid {
            axApp = AXUIElementCreateApplication(pid)
            lastTitlePid = pid
            cachedTitle = nil
        }
        if let cached = cachedTitle { return cached }
        var window: CFTypeRef?
        guard AXUIElementCopyAttributeValue(axApp!, kAXFocusedWindowAttribute as CFString, &window) == .success,
              let windowElement = window else { return nil }
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(windowElement as! AXUIElement, kAXTitleAttribute as CFString, &value)
        guard result == .success, let title = value as? String, !title.isEmpty else { return nil }
        cachedTitle = title
        return title
    }

    private var axApp: AXUIElement?

    private func idleSeconds() -> Double {
        // 聚合查询（kCGAnyInputEventType = 0xFFFFFFFF）：单一权威值，
        // 避免逐类型查询在系统更新后出现语义漂移
        let aggregate = CGEventSource.secondsSinceLastEventType(
            .hidSystemState, eventType: CGEventType(rawValue: 0xFFFF_FFFF) ?? .keyDown
        )
        if aggregate.isFinite, aggregate >= 0, aggregate < 1_000_000 { return aggregate }
        let types: [CGEventType] = [
            .leftMouseDown, .rightMouseDown, .otherMouseDown,
            .mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged,
            .keyDown, .scrollWheel,
        ]
        let values = types.map {
            CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: $0)
        }
        let candidates = values.filter { $0.isFinite && $0 >= 0 }
        guard let idle = candidates.min(), idle < 1_000_000 else { return 0 }
        return idle
    }
}
