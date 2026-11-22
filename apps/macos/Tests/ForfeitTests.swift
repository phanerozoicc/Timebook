import XCTest
@testable import Timebook

// 自 prod1/Forfeit 独立应用并入的测试（账本语义 / 存储往返 / 目录扫描）。
final class ForfeitTests: XCTestCase {
    private var calendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        return c
    }

    private func date(_ y: Int, _ mo: Int, _ d: Int, _ h: Int, _ mi: Int = 0) -> Date {
        var c = DateComponents()
        c.year = y; c.month = mo; c.day = d; c.hour = h; c.minute = mi
        return calendar.date(from: c)!
    }

    private func ledger(now: @escaping () -> Date, days: [String: DayRecord] = [:]) -> HourLedger {
        HourLedger(days: days, calendar: calendar, now: now)
    }

    // MARK: 账本

    func testDayKeyFormat() {
        let l = ledger { self.date(2026, 10, 26, 15, 30) }
        XCTAssertEqual(l.dayKey(for: date(2026, 10, 26, 15, 30)), "2026-10-26")
        XCTAssertEqual(l.dayKey(for: date(2026, 1, 5, 0, 1)), "2026-01-05")
    }

    func testMarkLostMarksCurrentHourIdempotently() {
        let l = ledger { self.date(2026, 10, 26, 15, 30) }
        XCTAssertTrue(l.markLost())
        XCTAssertEqual(l.lostHours(day: "2026-10-26"), [15])
        XCTAssertFalse(l.markLost(), "重复标记同一小时应幂等")
        XCTAssertEqual(l.todayLostCount, 1)
    }

    func testMarkLostOnExplicitPastDate() {
        let l = ledger { self.date(2026, 10, 26, 15, 30) }
        XCTAssertTrue(l.markLost(at: date(2026, 10, 25, 23, 59)))
        XCTAssertEqual(l.lostHours(day: "2026-10-25"), [23])
        XCTAssertEqual(l.todayLostCount, 0, "标记过去日期不影响今天")
    }

    func testCurrentHour() {
        let l = ledger { self.date(2026, 10, 26, 15, 30) }
        XCTAssertEqual(l.currentHour(), 15)
        XCTAssertEqual(l.currentHour(at: date(2026, 10, 26, 0, 5)), 0)
    }

    func testToggleRejectsFutureHour() {
        let l = ledger { self.date(2026, 10, 26, 15, 30) }
        XCTAssertEqual(l.toggle(day: "2026-10-26", hour: 16), .rejected)
        XCTAssertEqual(l.toggle(day: "2026-10-26", hour: 23), .rejected)
        XCTAssertEqual(l.toggle(day: "2026-10-26", hour: 24), .rejected)
        XCTAssertEqual(l.toggle(day: "2026-10-26", hour: 15), .nowLost, "当前小时可标记")
    }

    func testToggleTogglesBackAndForth() {
        let l = ledger { self.date(2026, 10, 26, 15, 30) }
        XCTAssertEqual(l.toggle(day: "2026-10-26", hour: 10), .nowLost)
        XCTAssertEqual(l.toggle(day: "2026-10-26", hour: 10), .nowKept)
        XCTAssertEqual(l.lostHours(day: "2026-10-26"), [])
    }

    func testTogglePastDayAlwaysAllowed() {
        let l = ledger { self.date(2026, 10, 26, 15, 30) }
        XCTAssertEqual(l.toggle(day: "2026-10-25", hour: 23), .nowLost)
    }

    func testLastNDaysOrderAndContents() {
        var days: [String: DayRecord] = [:]
        days["2026-10-20"] = DayRecord(lost: [1, 2])
        days["2026-10-22"] = DayRecord(lost: [9])
        days["2026-10-26"] = DayRecord(lost: [3])
        days["2026-10-01"] = DayRecord(lost: [5])
        let l = ledger(now: { self.date(2026, 10, 26, 12, 0) }, days: days)
        let week = l.lastNDays(7)
        XCTAssertEqual(week.map(\.key), [
            "2026-10-20", "2026-10-21", "2026-10-22",
            "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26",
        ])
        XCTAssertEqual(week[0].lost, [1, 2])
        XCTAssertEqual(week[6].lost, [3])
        XCTAssertEqual(l.totalLost(inLastDays: 7), 4, "7 天合计，窗口外不算")
    }

    func testPruneKeepsMostRecent60() {
        var days: [String: DayRecord] = [:]
        let start = date(2026, 6, 1, 12)
        for offset in 0..<70 {
            let d = calendar.date(byAdding: .day, value: offset, to: start)!
            let c = calendar.dateComponents([.year, .month, .day], from: d)
            let key = String(format: "%04ld-%02ld-%02ld", c.year!, c.month!, c.day!)
            days[key] = DayRecord(lost: [1])
        }
        let l = ledger(now: { self.date(2026, 8, 9, 12) }, days: days)
        XCTAssertEqual(l.days.count, 60, "初始化即修剪")
        XCTAssertNil(l.days["2026-06-01"], "最旧的被裁掉")
        XCTAssertNotNil(l.days["2026-08-09"])
        XCTAssertEqual(l.pruneIfNeeded(), 0, "已不足上限不再裁")
    }

    func testCrossDayRolloverViaNow() {
        var current = date(2026, 10, 26, 23, 58)
        let l = ledger { current }
        XCTAssertTrue(l.markLost())
        XCTAssertEqual(l.todayLostCount, 1)
        current = date(2026, 10, 27, 0, 2)
        XCTAssertEqual(l.currentDayKey, "2026-10-27")
        XCTAssertEqual(l.todayLostCount, 0, "跨午夜后今天清零")
        XCTAssertEqual(l.lostHours(day: "2026-10-26"), [23], "昨天的记录还在")
    }

    // MARK: 存储

    private func tempDir() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("ForfeitTests-\(UUID().uuidString)", isDirectory: true)
    }

    func testStoreRoundTripPersistsDaysAndDistractors() throws {
        let dir = tempDir()
        let store = try ForfeitStore(directory: dir)
        store.addDistractor(DistractorApp(id: "com.test.safari", name: "Safari", path: "/Applications/Safari.app"))
        store.addDistractor(DistractorApp(id: "com.test.game", name: "Game", path: "/Applications/Game.app"))
        XCTAssertTrue(store.ledger.markLost(at: calendar.date(
            from: DateComponents(timeZone: .current, year: 2026, month: 10, day: 26, hour: 14))!))
        try store.save()

        let reloaded = try ForfeitStore(directory: dir)
        XCTAssertTrue(reloaded.isDistractor("com.test.safari"))
        XCTAssertEqual(reloaded.distractors.count, 2)
        XCTAssertEqual(reloaded.ledger.lostHours(day: "2026-10-26"), [14])
    }

    func testStoreAddDistractorIsIdempotentAndPersistsRemoval() throws {
        let dir = tempDir()
        let store = try ForfeitStore(directory: dir)
        let app = DistractorApp(id: "com.test.x", name: "X", path: "/Applications/X.app")
        store.addDistractor(app)
        store.addDistractor(app)
        XCTAssertEqual(store.distractors.count, 1)

        store.removeDistractor(id: "com.test.x")
        let reloaded = try ForfeitStore(directory: dir)
        XCTAssertEqual(reloaded.distractors.count, 0)
        XCTAssertFalse(reloaded.isDistractor("com.test.x"))
    }

    func testStoreEmptyDirectoryStartsClean() throws {
        let store = try ForfeitStore(directory: tempDir())
        XCTAssertEqual(store.ledger.days.count, 0)
        XCTAssertEqual(store.distractors.count, 0)
    }

    // MARK: 应用目录

    private func makeApp(in root: URL, name: String, bundleId: String?, displayName: String? = nil) throws {
        let contents = root.appendingPathComponent("\(name).app/Contents", isDirectory: true)
        try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true)
        guard let bundleId else { return }
        var plist: [String: Any] = ["CFBundleIdentifier": bundleId, "CFBundleName": name]
        if let displayName { plist["CFBundleDisplayName"] = displayName }
        let data = try PropertyListSerialization.data(
            fromPropertyList: plist, format: .xml, options: 0)
        try data.write(to: contents.appendingPathComponent("Info.plist"))
    }

    func testCatalogScanFindsBundleIdAppsAndSkipsOddities() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ForfeitCatalog-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try makeApp(in: root, name: "Foo", bundleId: "com.foo.foo")
        try makeApp(in: root, name: "Bar", bundleId: nil)                       // 无 Info.plist → 跳过
        try makeApp(in: root, name: "Self", bundleId: AppCatalog.selfBundleId)  // 自己 → 排除
        try Data("x".utf8).write(to: root.appendingPathComponent("note.txt"))

        let apps = AppCatalog.scan(searchPaths: [root.path])
        XCTAssertEqual(apps.map(\.id), ["com.foo.foo"])
        XCTAssertEqual(apps.first?.name, "Foo")
        XCTAssertEqual(apps.first?.path, root.appendingPathComponent("Foo.app").path)
    }

    func testCatalogScanSortsByName() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ForfeitCatalog-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try makeApp(in: root, name: "Zebra", bundleId: "com.z.zebra")
        try makeApp(in: root, name: "Apple", bundleId: "com.a.apple")

        let apps = AppCatalog.scan(searchPaths: [root.path])
        XCTAssertEqual(apps.map(\.name), ["Apple", "Zebra"])
    }

    func testCatalogScanMissingPathIsIgnored() {
        let apps = AppCatalog.scan(searchPaths: ["/nonexistent-Forfeit-\(UUID().uuidString)"])
        XCTAssertEqual(apps, [])
    }

    // MARK: 网址级判定规则

    private let browsers: Set<String> = ["com.google.Chrome", "com.apple.Safari"]

    private func verdict(bundleId: String, host: String?,
                         apps: Set<String> = [],
                         enabled: Set<String> = ["video", "social"],
                         custom: Set<String> = []) -> ForfeitRules.Verdict? {
        ForfeitRules.verdict(
            bundleId: bundleId, host: host,
            isBrowser: { browsers.contains($0) },
            isDistractorApp: { apps.contains($0) },
            isCustomDomain: { custom.contains($0) },
            isCategoryEnabled: { enabled.contains($0) })
    }

    func testVerdictAppListHitsBeforeAnything() {
        XCTAssertEqual(verdict(bundleId: "com.some.game", host: nil, apps: ["com.some.game"]), .app)
        XCTAssertEqual(verdict(bundleId: "com.google.Chrome", host: "douyin.com", apps: ["com.google.Chrome"]), .app,
                       "浏览器在名单里时按应用判，不再看网址")
    }

    func testVerdictDistractingSiteOnEnabledCategory() {
        // 类目名跟随界面语言（Verdict 走 SiteCategory.localName），断言动态取值
        XCTAssertEqual(verdict(bundleId: "com.google.Chrome", host: "www.douyin.com"),
                       .site(name: SiteCategory.forHost("www.douyin.com").localName, host: "www.douyin.com"))
        XCTAssertEqual(verdict(bundleId: "com.apple.Safari", host: "weibo.com"),
                       .site(name: SiteCategory.forHost("weibo.com").localName, host: "weibo.com"))
    }

    func testVerdictDisabledOrNonDistractingCategoryIsClean() {
        XCTAssertNil(verdict(bundleId: "com.google.Chrome", host: "github.com"), "工作类未开启 → 不判")
        XCTAssertNil(verdict(bundleId: "com.google.Chrome", host: "youtube.com", enabled: ["social"]), "视频类被关 → 不判")
        XCTAssertNil(verdict(bundleId: "com.google.Chrome", host: "some-unknown-site.example"), "未知网址归「其他」→ 永不判")
    }

    func testVerdictRequiresBrowserAndHost() {
        XCTAssertNil(verdict(bundleId: "com.apple.finder", host: "douyin.com"), "非浏览器不带 host 判定")
        XCTAssertNil(verdict(bundleId: "com.google.Chrome", host: nil))
        XCTAssertNil(verdict(bundleId: "com.google.Chrome", host: ""))
    }

    // MARK: 类目开关

    func testStoreDefaultCategoriesAreBuiltInDistracting() throws {
        let store = try ForfeitStore(directory: tempDir())
        XCTAssertEqual(store.distractCategories, ForfeitStore.defaultCategories)
        XCTAssertTrue(store.isCategoryEnabled("video"))
        XCTAssertTrue(store.isCategoryEnabled("social"))
        XCTAssertFalse(store.isCategoryEnabled("work"))
    }

    func testStoreCategoryTogglePersistsAndOtherIsUntouchable() throws {
        let dir = tempDir()
        let store = try ForfeitStore(directory: dir)
        XCTAssertFalse(store.isCategoryEnabled("work"), "工作类默认关")
        XCTAssertTrue(store.toggleCategory(id: "work"), "关→开，返回新状态")
        XCTAssertFalse(store.toggleCategory(id: "work"), "开→关")
        XCTAssertFalse(store.isCategoryEnabled("work"))

        let other = store.toggleCategory(id: "other")
        XCTAssertFalse(other, "「其他」永不开启")
        XCTAssertFalse(store.isCategoryEnabled("other"))

        let reloaded = try ForfeitStore(directory: dir)
        XCTAssertFalse(reloaded.isCategoryEnabled("work"), "开关持久化")
        XCTAssertTrue(reloaded.isCategoryEnabled("video"), "默认开启的类目不受影响")
    }

    func testCleanStreakCountsBackFromTodayOrYesterday() {
        var days: [String: DayRecord] = [:]
        days["2026-10-24"] = DayRecord(lost: [3])
        let l = ledger(now: { self.date(2026, 10, 26, 12, 0) }, days: days)
        XCTAssertEqual(l.cleanStreak(), 2, "25/26 两天干净")
        l.markLost(at: date(2026, 10, 26, 10))
        XCTAssertEqual(l.cleanStreak(), 1, "今天荒了则从昨天数起")
        l.markLost(at: date(2026, 10, 25, 10))
        XCTAssertEqual(l.cleanStreak(), 0, "昨天也荒则归零")
    }

    func testLastNDayBarsOrderAndHours() {
        var days: [String: DayRecord] = [:]
        days["2026-10-25"] = DayRecord(lost: [1, 2, 3])
        let l = ledger(now: { self.date(2026, 10, 26, 12, 0) }, days: days)
        let bars = l.lastNDayBars(7)
        XCTAssertEqual(bars.count, 7)
        XCTAssertEqual(bars.first?.date, calendar.date(byAdding: .day, value: -6, to: date(2026, 10, 26, 12)))
        XCTAssertEqual(bars[5].hours, 3, "10-25 有 3 小时")
        XCTAssertEqual(bars[6].hours, 0)
    }

    // MARK: 自定义网站

    func testNormalizeDomainStripsSchemePathAndCasing() {
        XCTAssertEqual(ForfeitStore.normalizeDomain("  https://WWW.Example.com/watch?v=1 "), "www.example.com")
        XCTAssertEqual(ForfeitStore.normalizeDomain(" douyin.com. "), "douyin.com")
        XCTAssertNil(ForfeitStore.normalizeDomain("没有点"))
        XCTAssertNil(ForfeitStore.normalizeDomain("has space.com"))
    }

    func testCustomDomainMatchesSubdomainAndOverridesCategory() throws {
        let clean = try ForfeitStore(directory: tempDir())
        let enabled = ForfeitStore.defaultCategories
        let rules = { (store: ForfeitStore) in
            ForfeitRules.verdict(bundleId: "com.google.Chrome", host: "www.zhihu.com",
                                 isBrowser: { $0 == "com.google.Chrome" },
                                 isDistractorApp: { _ in false },
                                 isCustomDomain: { store.isCustomDomain($0) },
                                 isCategoryEnabled: { enabled.contains($0) })
        }
        XCTAssertNil(rules(clean), "zhihu 不在内建类目表：未自定义前不判")

        XCTAssertTrue(clean.addCustomDomain("zhihu.com"))
        XCTAssertFalse(clean.addCustomDomain("https://zhihu.com/follow"), "规整后视为重复")
        XCTAssertEqual(rules(clean), .site(name: T("自定义", "Custom"), host: "www.zhihu.com"), "自定义后即判")
        XCTAssertTrue(clean.isCustomDomain("www.zhihu.com"), "子域一并命中")
        XCTAssertFalse(clean.isCustomDomain("notzhihu.com"), "非后缀不命中")

        clean.removeCustomDomain("zhihu.com")
        XCTAssertFalse(clean.isCustomDomain("zhihu.com"))
    }

    func testCustomDomainPersists() throws {
        let dir = tempDir()
        let store = try ForfeitStore(directory: dir)
        store.addCustomDomain("example.org")
        let reloaded = try ForfeitStore(directory: dir)
        XCTAssertTrue(reloaded.isCustomDomain("example.org"))
        XCTAssertTrue(reloaded.isCustomDomain("sub.example.org"))
    }
}
