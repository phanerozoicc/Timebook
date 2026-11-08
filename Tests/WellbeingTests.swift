import XCTest
@testable import Timebook

@MainActor
final class WellbeingTests: XCTestCase {
    private var notifications: [(String, String)] = []
    private let defaults = UserDefaults(suiteName: "TimebookWellbeingTests")!

    override func setUp() {
        super.setUp()
        notifications = []
        defaults.removePersistentDomain(forName: "TimebookWellbeingTests")
        UserDefaults.standard.set("zh", forKey: "language") // 断言中文文案，固定语言
    }

    override func tearDown() {
        UserDefaults.standard.removeObject(forKey: "language")
        super.tearDown()
    }

    private func makeLimits(enabled: Bool, distract: Bool = false) -> LimitsEngine {
        let engine = LimitsEngine()
        engine.onNotify = { [weak self] title, body in self?.notifications.append((title, body)) }
        engine.resetForTesting()
        UserDefaults.standard.set(enabled, forKey: AppSettings.limitsEnabledKey)
        UserDefaults.standard.set(distract, forKey: AppSettings.distractNudgeKey)
        return engine
    }

    func testLimitWarnsAt80And100Once() {
        let engine = makeLimits(enabled: true)
        UserDefaults.standard.set(120, forKey: AppSettings.limitsDailyMinKey) // 2h 限额
        let now = Date(timeIntervalSince1970: 1_783_000_000)

        // 96 分钟 = 80%
        var message = engine.minute(LimitCheckInputs(
            todayTotal: 96 * 60, dailyLimitMinutes: 120,
            currentHost: nil, currentSegmentStart: nil, now: now))
        XCTAssertEqual(message, "limit-80")
        XCTAssertEqual(notifications.count, 1)

        // 97 分钟：不再重复 80% 提醒
        message = engine.minute(LimitCheckInputs(
            todayTotal: 97 * 60, dailyLimitMinutes: 120,
            currentHost: nil, currentSegmentStart: nil, now: now))
        XCTAssertNil(message)
        XCTAssertEqual(notifications.count, 1)

        // 90%
        message = engine.minute(LimitCheckInputs(
            todayTotal: 108 * 60, dailyLimitMinutes: 120,
            currentHost: nil, currentSegmentStart: nil, now: now))
        XCTAssertEqual(message, "limit-90")
        XCTAssertEqual(notifications.count, 2)

        // 到 100%
        message = engine.minute(LimitCheckInputs(
            todayTotal: 120 * 60, dailyLimitMinutes: 120,
            currentHost: nil, currentSegmentStart: nil, now: now))
        XCTAssertEqual(message, "limit-100")
        XCTAssertTrue(engine.limitReached)
        XCTAssertEqual(notifications.count, 3)
    }

    func testLimitDisabledIsSilent() {
        let engine = makeLimits(enabled: false)
        let message = engine.minute(LimitCheckInputs(
            todayTotal: 999 * 60, dailyLimitMinutes: 120,
            currentHost: nil, currentSegmentStart: nil, now: Date()))
        XCTAssertNil(message)
        XCTAssertFalse(engine.limitReached)
    }

    func testDistractNudgeAfterTenMinutesWithCooldown() {
        let engine = makeLimits(enabled: true, distract: true)
        let start = Date(timeIntervalSince1970: 1_783_000_000)

        // 9 分钟：不到阈值
        var message = engine.minute(LimitCheckInputs(
            todayTotal: 0, dailyLimitMinutes: 120,
            currentHost: "bilibili.com", currentSegmentStart: start,
            now: start.addingTimeInterval(9 * 60)))
        XCTAssertNil(message)

        // 12 分钟：提醒一次
        message = engine.minute(LimitCheckInputs(
            todayTotal: 0, dailyLimitMinutes: 120,
            currentHost: "bilibili.com", currentSegmentStart: start,
            now: start.addingTimeInterval(12 * 60)))
        XCTAssertEqual(message, "distract")

        // 冷却期内（29 分钟后）：不再提醒
        message = engine.minute(LimitCheckInputs(
            todayTotal: 0, dailyLimitMinutes: 120,
            currentHost: "bilibili.com", currentSegmentStart: start,
            now: start.addingTimeInterval(12 * 60 + 29 * 60)))
        XCTAssertNil(message)

        // 冷却结束后：再次提醒
        message = engine.minute(LimitCheckInputs(
            todayTotal: 0, dailyLimitMinutes: 120,
            currentHost: "bilibili.com", currentSegmentStart: start,
            now: start.addingTimeInterval(12 * 60 + 31 * 60)))
        XCTAssertEqual(message, "distract")

        // 工作站点不提醒
        message = engine.minute(LimitCheckInputs(
            todayTotal: 0, dailyLimitMinutes: 120,
            currentHost: "github.com", currentSegmentStart: start,
            now: start.addingTimeInterval(60 * 60)))
        XCTAssertNil(message)
    }

    func testBreakReminderFiresAfterIntervalAndResets() {
        let engine = RemindersEngine()
        engine.onNotify = { [weak self] title, _ in self?.notifications.append((title, "")) }
        engine.resetForTesting()
        UserDefaults.standard.set(true, forKey: AppSettings.breakReminderKey)
        UserDefaults.standard.set(false, forKey: AppSettings.waterEnabledKey)
        UserDefaults.standard.set(30, forKey: AppSettings.breakIntervalKey)

        // 29 分钟：不提醒
        for _ in 0..<((29 * 60) / 5) {
            engine.tick(idle: false, inPomodoroBreak: false, tickInterval: 5)
        }
        XCTAssertEqual(notifications.count, 0)

        // 再过 1 分钟：提醒并清零
        for _ in 0..<(60 / 5) {
            engine.tick(idle: false, inPomodoroBreak: false, tickInterval: 5)
        }
        XCTAssertEqual(notifications.count, 1)
        XCTAssertEqual(engine.activeSeconds, 0, accuracy: 0.001)

        // 空闲重置
        engine.tick(idle: true, inPomodoroBreak: false, tickInterval: 5)
        XCTAssertEqual(engine.activeSeconds, 0, accuracy: 0.001)
    }

    func testPomodoroBreakResetsActiveStreak() {
        let engine = RemindersEngine()
        engine.resetForTesting()
        UserDefaults.standard.set(false, forKey: AppSettings.breakReminderKey)
        UserDefaults.standard.set(false, forKey: AppSettings.waterEnabledKey)
        for _ in 0..<20 { engine.tick(idle: false, inPomodoroBreak: false, tickInterval: 5) }
        XCTAssertEqual(engine.activeSeconds, 100, accuracy: 0.001)
        engine.tick(idle: false, inPomodoroBreak: true, tickInterval: 5)
        XCTAssertEqual(engine.activeSeconds, 0, accuracy: 0.001, "番茄休息期联动重置")
    }

    func testWaterNudgeOnlyInWindow() {
        let engine = RemindersEngine()
        engine.onNotify = { [weak self] title, _ in self?.notifications.append((title, "")) }
        engine.resetForTesting()
        UserDefaults.standard.set(false, forKey: AppSettings.breakReminderKey)
        UserDefaults.standard.set(true, forKey: AppSettings.waterEnabledKey)
        UserDefaults.standard.set(60, forKey: AppSettings.waterIntervalKey)
        UserDefaults.standard.set(9, forKey: AppSettings.waterStartHourKey)
        UserDefaults.standard.set(22, forKey: AppSettings.waterEndHourKey)

        // 窗口外（凌晨 3 点）：不提醒
        var calendar = Calendar.current
        calendar.timeZone = .current
        var outside = calendar.date(from: DateComponents(year: 2026, month: 9, day: 7, hour: 3))!
        for _ in 0..<13 { engine.tick(idle: false, inPomodoroBreak: false, now: outside, tickInterval: 300) }
        XCTAssertEqual(notifications.count, 0)

        // 窗口内（上午 10 点）：第一次 tick 即提醒（从未提醒过）
        var inside = calendar.date(from: DateComponents(year: 2026, month: 9, day: 7, hour: 10))!
        engine.tick(idle: false, inPomodoroBreak: false, now: inside, tickInterval: 5)
        XCTAssertEqual(notifications.count, 1)
        _ = outside; _ = inside
    }

    func testExporterCSVAndMarkdown() {
        let base = Date(timeIntervalSince1970: 1_783_000_000)
        let rows = [
            EventRow(appID: "c", appName: "Chrome", detail: "https://github.com/a,b",
                     host: "github.com", start: base, end: base.addingTimeInterval(125)),
        ]
        let csv = Exporter.csv(rows)
        XCTAssertTrue(csv.hasPrefix("start,end,duration_seconds,app,host,detail,title"))
        XCTAssertTrue(csv.contains("\"https://github.com/a,b\""), "含逗号的字段要加引号")
        XCTAssertTrue(csv.contains("125"))

        let day = Calendar.current.startOfDay(for: base)
        let markdown = Exporter.weeklyMarkdown(
            now: base,
            perDay: [DayPoint(day: day, seconds: 3600)],
            topApps: [AppSlice(appID: "c", name: "Chrome", seconds: 125)],
            topHosts: [HostSlice(host: "github.com", seconds: 125)],
            categories: [Agg.CategorySlice(name: "工作", hex: 0x3B82F6, seconds: 125)],
            pomodoros: 3, focusSeconds: 3750, cups: 4, goalCups: 8)
        XCTAssertTrue(markdown.contains("# 时账周报"))
        XCTAssertTrue(markdown.contains("L"))
        XCTAssertTrue(markdown.contains("| \(daySuffix(day)) | 1 小时 0 分 |"))
        XCTAssertTrue(markdown.contains("3 🍅"))
    }

    private func daySuffix(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    func testHeatBuckets() {
        XCTAssertEqual(Heat.bucket(seconds: 0), 0)
        XCTAssertEqual(Heat.bucket(seconds: 20 * 60), 1)
        XCTAssertEqual(Heat.bucket(seconds: 45 * 60), 2)
        XCTAssertEqual(Heat.bucket(seconds: 1.5 * 3600), 3)
        XCTAssertEqual(Heat.bucket(seconds: 3 * 3600), 4)
        XCTAssertEqual(Heat.bucket(seconds: 5 * 3600), 5)
        XCTAssertEqual(Heat.bucket(seconds: 8 * 3600), 6)
        XCTAssertEqual(Heat.palette.count, 7)
    }

    func testWaterStoreRoundtrip() throws {
        let store = try Store(inMemory: true)
        let base = Date(timeIntervalSince1970: 1_783_000_000)
        XCTAssertEqual(store.cupsToday(now: base), 0)
        XCTAssertEqual(store.addCup(now: base), 1)
        XCTAssertEqual(store.addCup(now: base), 2)
        XCTAssertEqual(store.addCup(delta: -1, now: base), 1)
        XCTAssertEqual(store.cupsToday(now: base), 1)
    }

    func testLocalizationToggles() {
        UserDefaults.standard.set("en", forKey: "language")
        XCTAssertEqual(T("今日", "Today"), "Today")
        UserDefaults.standard.set("zh", forKey: "language")
        XCTAssertEqual(T("今日", "Today"), "今日")
        UserDefaults.standard.set("auto", forKey: "language")
    }
}
