import AppKit
import CoreGraphics
import Foundation
import SwiftUI

// MARK: - Forfeit（丢小时）
//
// 自 prod1/Forfeit 独立应用并入：一天 24 格，分心应用在某一小时被切到前台，
// 该小时整格记为「荒」。锁屏/显示器休眠不判；唤醒/解锁后进入抑制态，
// 直到一次真实键鼠输入才恢复（防唤醒躺枪）；启动时已在锁屏同样挂起。

struct DayRecord: Codable, Equatable {
    var lost: Set<Int> = []
}

enum ForfeitToggleOutcome: Equatable {
    case nowLost
    case nowKept
    case rejected
}

// 纯逻辑小时账本：不依赖 AppKit；时钟与日历可注入。
final class HourLedger {
    private(set) var days: [String: DayRecord]
    let calendar: Calendar
    private let now: () -> Date
    static let keepDays = 60

    init(days: [String: DayRecord] = [:], calendar: Calendar = .current, now: @escaping () -> Date = Date.init) {
        self.days = days
        self.calendar = calendar
        self.now = now
        pruneIfNeeded()
    }

    func dayKey(for date: Date) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04ld-%02ld-%02ld", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    func hour(of date: Date) -> Int {
        calendar.component(.hour, from: date)
    }

    var currentDayKey: String { dayKey(for: now()) }
    func currentHour(at date: Date? = nil) -> Int { hour(of: date ?? now()) }

    /// 分心应用此刻激活：把所在小时记为荒。幂等，返回是否新标记。
    @discardableResult
    func markLost(at date: Date? = nil) -> Bool {
        let d = date ?? now()
        let key = dayKey(for: d)
        let h = hour(of: d)
        var record = days[key] ?? DayRecord()
        guard record.lost.insert(h).inserted else { return false }
        days[key] = record
        pruneIfNeeded()
        return true
    }

    /// 手动改判（点击格子）：未来小时拒绝；荒↔守互换。
    func toggle(day: String, hour: Int) -> ForfeitToggleOutcome {
        guard (0...23).contains(hour) else { return .rejected }
        if day == currentDayKey {
            guard hour <= currentHour() else { return .rejected }
        }
        var record = days[day] ?? DayRecord()
        if record.lost.contains(hour) {
            record.lost.remove(hour)
            days[day] = record
            return .nowKept
        }
        record.lost.insert(hour)
        days[day] = record
        return .nowLost
    }

    func lostHours(day: String) -> Set<Int> {
        days[day]?.lost ?? []
    }

    var todayLostCount: Int {
        lostHours(day: currentDayKey).count
    }

    /// 最近 n 天（含今天，旧→新）。
    func lastNDays(_ n: Int) -> [(key: String, lost: Set<Int>)] {
        guard let start = calendar.date(byAdding: .day, value: -(n - 1), to: now()) else { return [] }
        return (0..<n).compactMap { offset in
            guard let d = calendar.date(byAdding: .day, value: offset, to: start) else { return nil }
            let key = dayKey(for: d)
            return (key, lostHours(day: key))
        }
    }

    func totalLost(inLastDays n: Int) -> Int {
        lastNDays(n).reduce(0) { $0 + $1.lost.count }
    }

    /// 最近 n 天的荒废小时柱状数据（含今天，旧→新）。
    func lastNDayBars(_ n: Int) -> [(date: Date, hours: Double)] {
        guard let start = calendar.date(byAdding: .day, value: -(n - 1), to: now()) else { return [] }
        return (0..<n).compactMap { offset in
            guard let d = calendar.date(byAdding: .day, value: offset, to: start) else { return nil }
            return (d, Double(lostHours(day: dayKey(for: d)).count))
        }
    }

    /// 连续干净天：今天干净则含今天，否则从昨天起往前数，连续无荒的天数。
    func cleanStreak() -> Int {
        var offset = lostHours(day: dayKey(for: now())).isEmpty ? 0 : 1
        var streak = 0
        while offset < HourLedger.keepDays {
            guard let d = calendar.date(byAdding: .day, value: -offset, to: now()),
                  lostHours(day: dayKey(for: d)).isEmpty
            else { break }
            streak += 1
            offset += 1
        }
        return streak
    }

    /// 只保留最近 keepDays 天。
    @discardableResult
    func pruneIfNeeded(maxDays: Int = HourLedger.keepDays) -> Int {
        let keys = days.keys.sorted().reversed()
        guard keys.count > maxDays else { return 0 }
        let drop = Set(keys.dropFirst(maxDays))
        for key in drop { days.removeValue(forKey: key) }
        return drop.count
    }
}

// MARK: - 存储

struct DistractorApp: Codable, Equatable, Identifiable {
    let id: String   // bundle identifier
    let name: String
    let path: String
}

private struct ForfeitPersistedState: Codable {
    var days: [String: DayRecord] = [:]
    var distractors: [DistractorApp] = []
    /// nil = 未配置（用内建默认：类目表自带 distracting 标记的那几类）
    var distractCategories: [String]? = nil
    /// 自定义分心网站（域名后缀匹配，优先于类目）
    var customDistractDomains: [String]? = nil
}

// 判定规则（纯函数，可测）：应用名单优先全时判；浏览器按「自定义网站 → 网址类目」判，「其他」永不判。
enum ForfeitRules {
    enum Verdict: Equatable {
        case app
        case site(name: String, host: String)
    }

    static func verdict(bundleId: String, host: String?,
                        isBrowser: (String) -> Bool,
                        isDistractorApp: (String) -> Bool,
                        isCustomDomain: (String) -> Bool,
                        isCategoryEnabled: (String) -> Bool) -> Verdict? {
        if isDistractorApp(bundleId) { return .app }
        guard isBrowser(bundleId), let host, !host.isEmpty else { return nil }
        if isCustomDomain(host) { return .site(name: T("自定义", "Custom"), host: host) }
        let category = SiteCategory.forHost(host)
        guard category.id != "other", isCategoryEnabled(category.id) else { return nil }
        return .site(name: category.localName, host: host)
    }
}

final class ForfeitStore {
    let directory: URL
    private let fileURL: URL
    let ledger: HourLedger
    private(set) var distractors: [DistractorApp]
    private(set) var distractCategories: Set<String>
    private(set) var customDomains: [String]

    /// 内建默认：类目表自带 distracting 标记的类目（社交/视频/购物/娱乐）。
    static let defaultCategories: Set<String> = Set(SiteCategory.all.filter(\.distracting).map(\.id))

    init(directory: URL? = nil, now: @escaping () -> Date = Date.init) throws {
        let base = directory ?? FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Timebook", isDirectory: true)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        self.directory = base
        fileURL = base.appendingPathComponent("forfeit.json")

        var loaded = ForfeitPersistedState()
        if let data = try? Data(contentsOf: fileURL),
           let decoded = try? JSONDecoder().decode(ForfeitPersistedState.self, from: data) {
            loaded = decoded
        }
        ledger = HourLedger(days: loaded.days, now: now)
        distractors = loaded.distractors
        distractCategories = loaded.distractCategories.map(Set.init) ?? Self.defaultCategories
        customDomains = loaded.customDistractDomains ?? []
    }

    func isDistractor(_ bundleId: String) -> Bool {
        distractors.contains { $0.id == bundleId }
    }

    func isCategoryEnabled(_ id: String) -> Bool {
        distractCategories.contains(id)
    }

    @discardableResult
    func toggleCategory(id: String) -> Bool {
        guard id != "other", SiteCategory.all.contains(where: { $0.id == id }) else {
            return isCategoryEnabled(id)
        }
        if distractCategories.contains(id) {
            distractCategories.remove(id)
        } else {
            distractCategories.insert(id)
        }
        try? save()
        return isCategoryEnabled(id)
    }

    /// 规整用户输入的域名：去 scheme/路径/空白/结尾点，小写。无效返回 nil。
    static func normalizeDomain(_ raw: String) -> String? {
        var d = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if let range = d.range(of: #"^[a-z]+://"#, options: .regularExpression) {
            d.removeSubrange(range)
        }
        if let slash = d.firstIndex(of: "/") { d = String(d[..<slash]) }
        while d.hasSuffix(".") { d.removeLast() }
        guard d.contains("."), !d.contains(" "), !d.isEmpty else { return nil }
        return d
    }

    /// host 是否命中自定义网站（精确或子域后缀）。
    func isCustomDomain(_ host: String) -> Bool {
        let lowered = host.lowercased()
        return customDomains.contains { lowered == $0 || lowered.hasSuffix("." + $0) }
    }

    @discardableResult
    func addCustomDomain(_ raw: String) -> Bool {
        guard let domain = Self.normalizeDomain(raw),
              !customDomains.contains(domain)
        else { return false }
        customDomains.append(domain)
        try? save()
        return true
    }

    func removeCustomDomain(_ domain: String) {
        customDomains.removeAll { $0 == domain }
        try? save()
    }

    func addDistractor(_ app: DistractorApp) {
        guard !isDistractor(app.id) else { return }
        distractors.append(app)
        try? save()
    }

    func removeDistractor(id: String) {
        distractors.removeAll { $0.id == id }
        try? save()
    }

    func save() throws {
        let state = ForfeitPersistedState(days: ledger.days, distractors: distractors,
                                          distractCategories: distractCategories.sorted(),
                                          customDistractDomains: customDomains.sorted())
        let data = try JSONEncoder().encode(state)
        try data.write(to: fileURL, options: .atomic)
    }
}

// MARK: - 应用目录

struct CatalogApp: Identifiable, Equatable {
    let id: String
    let name: String
    let path: String
}

enum AppCatalog {
    static let selfBundleId = "com.haozc.Timebook"
    static let defaultSearchPaths = [
        "/Applications",
        "/System/Applications",
        NSHomeDirectory() + "/Applications",
    ]

    static func scan(searchPaths: [String] = defaultSearchPaths) -> [CatalogApp] {
        var byId: [String: CatalogApp] = [:]
        let fm = FileManager.default
        for root in searchPaths {
            guard let entries = try? fm.contentsOfDirectory(atPath: root) else { continue }
            for entry in entries.sorted() where entry.hasSuffix(".app") {
                let path = (root as NSString).appendingPathComponent(entry)
                guard let bundle = Bundle(url: URL(fileURLWithPath: path)),
                      let id = bundle.bundleIdentifier,
                      id != selfBundleId
                else { continue }
                let name = (bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
                    ?? (bundle.object(forInfoDictionaryKey: "CFBundleName") as? String)
                    ?? (entry as NSString).deletingPathExtension
                if byId[id] == nil {
                    byId[id] = CatalogApp(id: id, name: name, path: path)
                }
            }
        }
        return byId.values.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }
}

// MARK: - 分心监听

// NSWorkspace 激活事件 + Poller 分段变化（网址级）为主，30s 轮询兜底。
// 判荒语义：判定规则由控制器注入（应用名单 + 网站类目）；锁屏/显示器休眠不判；
// 唤醒/解锁后进入抑制态，直到一次真实键鼠输入（防唤醒躺枪）。
final class ForfeitMonitor {
    private let ledger: HourLedger
    /// 完整判定规则：返回命中原因则记荒
    var evaluate: (String, String?) -> ForfeitRules.Verdict? = { _, _ in nil }
    /// 当前浏览器网址 host（激活事件路径；分段变化路径的 host 直传）
    var hostProvider: () -> String? = { nil }
    var onChange: () -> Void = {}

    private var locked = false
    private var awaitingInput = true   // 启动即抑制，等一次输入或激活
    private var timer: Timer?
    private var lastDayKey: String

    init(ledger: HourLedger) {
        self.ledger = ledger
        lastDayKey = ledger.currentDayKey
    }

    func start() {
        // 应用可能在锁屏期间启动（收不到锁屏通知）：loginwindow 持前台即视为锁屏。
        if NSWorkspace.shared.frontmostApplication?.bundleIdentifier == "com.apple.loginwindow" {
            locked = true
            AppLog.info("Forfeit：启动时检测到锁屏（loginwindow 前台），挂起判荒直至解锁")
        }
        let nc = NSWorkspace.shared.notificationCenter
        nc.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
        ) { [weak self] note in
            MainActor.assumeIsolated { self?.handleActivation(note) }
        }
        nc.addObserver(
            forName: NSWorkspace.screensDidSleepNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.sleepAgain() }
        }
        nc.addObserver(
            forName: NSWorkspace.screensDidWakeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.sleepAgain() }
        }

        let dnc = DistributedNotificationCenter.default()
        dnc.addObserver(
            forName: NSNotification.Name("com.apple.screenIsLocked"), object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.locked = true }
        }
        dnc.addObserver(
            forName: NSNotification.Name("com.apple.screenIsUnlocked"), object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.locked = false
                self?.sleepAgain()
            }
        }

        let t = Timer(timeInterval: 30, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        t.tolerance = 5
        RunLoop.main.add(t, forMode: .common)
        timer = t
        AppLog.info("Forfeit：监听已启动，lastDay=\(lastDayKey)")
    }

    private func handleActivation(_ note: Notification) {
        guard !locked,
              let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
              let bundleId = app.bundleIdentifier
        else { return }
        // 用户主动切到该应用本身就是输入
        awaitingInput = false
        markIfActive(bundleId: bundleId, host: hostProvider())
    }

    /// Poller 分段变化入口（切应用或浏览器 tab 网址变化，含网址解析完成的那次 tick）。
    func segmentChanged(bundleId: String, host: String?) {
        if awaitingInput, Self.hasRecentInput() { awaitingInput = false }
        markIfActive(bundleId: bundleId, host: host)
    }

    private func tick() {
        rollDayIfNeeded()
        if locked {
            // 自愈：解锁通知偶发丢失时，loginwindow 让出前台即解锁
            if NSWorkspace.shared.frontmostApplication?.bundleIdentifier != "com.apple.loginwindow" {
                locked = false
                sleepAgain()
                AppLog.info("Forfeit：轮询发现已解锁（通知缺失，已自愈）")
            }
        }
        if awaitingInput, Self.hasRecentInput() { awaitingInput = false }
        guard !locked, !awaitingInput else { return }
        if let bundleId = NSWorkspace.shared.frontmostApplication?.bundleIdentifier {
            markIfActive(bundleId: bundleId, host: hostProvider())
        }
    }

    private func markIfActive(bundleId: String, host: String?) {
        guard let verdict = evaluate(bundleId, host) else { return }
        if ledger.markLost() {
            switch verdict {
            case .app:
                AppLog.info("Forfeit：应用判荒 \(bundleId)")
            case .site(let name, let host):
                AppLog.info("Forfeit：网址判荒 \(host)（\(name)）")
            }
            onChange()
        }
    }

    private func rollDayIfNeeded() {
        let today = ledger.currentDayKey
        guard today != lastDayKey else { return }
        lastDayKey = today
        ledger.pruneIfNeeded()
        AppLog.info("Forfeit：跨天进入 \(today)")
        onChange()
    }

    private func sleepAgain() {
        awaitingInput = true
    }

    static func hasRecentInput() -> Bool {
        CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: 0xFFFF_FFFF)!) < 60
    }
}

// MARK: - 控制器

@MainActor
final class ForfeitController: ObservableObject {
    /// 视图间接观察对象：账本/名单变更时 +1 触发重渲染。
    @Published private(set) var refreshTick = 0
    @Published private(set) var catalogApps: [CatalogApp] = []

    let store: ForfeitStore
    private var monitor: ForfeitMonitor?

    init() {
        Self.migrateLegacyIfNeeded()
        do {
            store = try ForfeitStore()
        } catch {
            AppLog.error("Forfeit：存储创建失败，降级为临时目录（\(error.localizedDescription)）")
            let fallback = FileManager.default.temporaryDirectory
                .appendingPathComponent("Forfeit-fallback", isDirectory: true)
            store = try! ForfeitStore(directory: fallback)
        }
        let m = ForfeitMonitor(ledger: store.ledger)
        m.evaluate = { [weak store] bundleId, host in
            guard let store else { return nil }
            return ForfeitRules.verdict(
                bundleId: bundleId, host: host,
                isBrowser: Browser.isBrowser,
                isDistractorApp: { store.isDistractor($0) },
                isCustomDomain: { store.isCustomDomain($0) },
                isCategoryEnabled: { store.isCategoryEnabled($0) })
        }
        monitor = m
        m.onChange = { [weak self] in self?.ledgerChanged() }
        m.start()
        AppLog.info("Forfeit：引擎就绪，\(store.ledger.days.count) 天记录，\(store.distractors.count) 个分心应用，\(store.distractCategories.count) 类分心网站")
    }

    /// AppContext 接线：host 提供者（激活路径取当前分段 host）。
    func bind(hostProvider: @escaping () -> String?) {
        monitor?.hostProvider = hostProvider
    }

    /// Poller 分段变化入口（切应用或浏览器 tab 网址变化）。
    func forwardSegmentChange(bundleId: String, host: String?) {
        monitor?.segmentChanged(bundleId: bundleId, host: host)
    }

    /// 一次性迁移：并入前的独立版 Forfeit 应用数据（格式相同）。
    private static func migrateLegacyIfNeeded() {
        let fm = FileManager.default
        let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let target = base.appendingPathComponent("Timebook/forfeit.json")
        let legacy = base.appendingPathComponent("Forfeit/state.json")
        guard !fm.fileExists(atPath: target.path), fm.fileExists(atPath: legacy.path),
              let data = try? Data(contentsOf: legacy)
        else { return }
        try? fm.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        do {
            try data.write(to: target, options: .atomic)
            AppLog.info("Forfeit：已迁移独立版数据（\(legacy.path)）")
        } catch {
            AppLog.error("Forfeit：迁移独立版数据失败：\(error.localizedDescription)")
        }
    }

    var todayLostCount: Int { store.ledger.todayLostCount }

    var weekBars: [(date: Date, hours: Double)] {
        store.ledger.lastNDayBars(7)
    }

    var cleanStreak: Int {
        store.ledger.cleanStreak()
    }

    var distractors: [DistractorApp] { store.distractors }

    /// 分心网站类目（「其他」不可判，不进 UI）
    var siteCategories: [SiteCategory] {
        SiteCategory.all.filter { $0.id != "other" }
    }

    func isCategoryEnabled(_ id: String) -> Bool {
        store.isCategoryEnabled(id)
    }

    func toggleCategory(id: String) {
        store.toggleCategory(id: id)
        ledgerChanged()
    }

    var customDomains: [String] { store.customDomains }

    @discardableResult
    func addCustomDomain(_ raw: String) -> Bool {
        let added = store.addCustomDomain(raw)
        if added { ledgerChanged() }
        return added
    }

    func removeCustomDomain(_ domain: String) {
        store.removeCustomDomain(domain)
        ledgerChanged()
    }

    /// 当前输入的完整判定（主页面实时预览用，与引擎同一规则）。
    func previewVerdict(bundleId: String, host: String?) -> ForfeitRules.Verdict? {
        ForfeitRules.verdict(
            bundleId: bundleId, host: host,
            isBrowser: Browser.isBrowser,
            isDistractorApp: { store.isDistractor($0) },
            isCustomDomain: { store.isCustomDomain($0) },
            isCategoryEnabled: { store.isCategoryEnabled($0) })
    }

    func ledgerChanged() {
        refreshTick &+= 1
        try? store.save()
    }

    func toggleTodayHour(_ hour: Int) {
        _ = store.ledger.toggle(day: store.ledger.currentDayKey, hour: hour)
        ledgerChanged()
    }

    func addDistractor(_ app: CatalogApp) {
        store.addDistractor(DistractorApp(id: app.id, name: app.name, path: app.path))
        ledgerChanged()
    }

    func removeDistractor(id: String) {
        store.removeDistractor(id: id)
        ledgerChanged()
    }

    func ensureCatalogLoaded() {
        guard catalogApps.isEmpty else { return }
        catalogApps = AppCatalog.scan()
        AppLog.info("Forfeit：应用目录扫描 \(catalogApps.count) 个")
    }

    var weekRows: [(key: String, label: String, lost: Set<Int>)] {
        let ledger = store.ledger
        let cal = ledger.calendar
        let rows = ledger.lastNDays(7)
        let oldestDaysAgo = rows.count - 1
        return rows.enumerated().map { index, row in
            let daysAgo = oldestDaysAgo - index
            let label: String
            switch daysAgo {
            case 0: label = T("今天", "Today")
            case 1: label = T("昨天", "Yesterday")
            default:
                if let d = cal.date(byAdding: .day, value: -daysAgo, to: cal.startOfDay(for: Date())) {
                    label = cal.weekdaySymbols[cal.component(.weekday, from: d) - 1]
                } else {
                    label = row.key
                }
            }
            return (row.key, label, row.lost)
        }
    }
}

// MARK: - 颜色

extension Color {
    /// 荒掉的小时（Timebook 语义红）
    static let forfeitLost = Color(hex: 0xE0483E)
    /// 还没到的小时
    static let forfeitFuture = Color.primary.opacity(0.10)
}
