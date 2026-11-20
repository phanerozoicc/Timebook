import XCTest
@testable import Timebook

@MainActor
final class TimebookTests: XCTestCase {
    private func row(_ appID: String, _ appName: String, start: Date, duration: TimeInterval,
                     detail: String? = nil) -> EventRow {
        let host = detail?.urlHost
        return EventRow(appID: appID, appName: appName, detail: detail, host: host,
                        start: start, end: start.addingTimeInterval(duration))
    }

    func testTotalSumsDurations() {
        let base = Date(timeIntervalSince1970: 1_783_000_000)
        let rows = [
            row("a", "A", start: base, duration: 60),
            row("b", "B", start: base.addingTimeInterval(120), duration: 30),
        ]
        XCTAssertEqual(Agg.total(rows), 90, accuracy: 0.001)
    }

    func testByAppGroupsAndSorts() {
        let base = Date(timeIntervalSince1970: 1_783_000_000)
        let rows = [
            row("chrome", "Chrome", start: base, duration: 100, detail: "https://github.com/x"),
            row("chrome", "Chrome", start: base.addingTimeInterval(200), duration: 50, detail: "https://news.ycombinator.com/"),
            row("zcode", "ZCode", start: base.addingTimeInterval(300), duration: 200),
        ]
        let apps = Agg.byApp(rows)
        XCTAssertEqual(apps.count, 2)
        XCTAssertEqual(apps[0].appID, "zcode")
        XCTAssertEqual(apps[0].seconds, 200, accuracy: 0.001)
        XCTAssertEqual(apps[1].seconds, 150, accuracy: 0.001)
    }

    func testByHostUsesHostOnly() {
        let base = Date(timeIntervalSince1970: 1_783_000_000)
        let rows = [
            row("chrome", "Chrome", start: base, duration: 100, detail: "https://github.com/a/b"),
            row("chrome", "Chrome", start: base.addingTimeInterval(150), duration: 60, detail: "https://github.com/c"),
            row("chrome", "Chrome", start: base.addingTimeInterval(250), duration: 30, detail: "https://apple.com"),
        ]
        let hosts = Agg.byHost(rows)
        XCTAssertEqual(hosts.count, 2)
        XCTAssertEqual(hosts[0].host, "github.com")
        XCTAssertEqual(hosts[0].seconds, 160, accuracy: 0.001)
    }

    func testPerDayBucketsSevenDays() {
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date(timeIntervalSince1970: 1_783_000_000))
        let rows = [
            row("a", "A", start: today, duration: 600),
            row("a", "A", start: calendar.date(byAdding: .day, value: -2, to: today)!, duration: 300),
            row("a", "A", start: calendar.date(byAdding: .day, value: -9, to: today)!, duration: 9_999),
        ]
        let days = Agg.perDay(rows, calendar: calendar, count: 7, now: today)
        XCTAssertEqual(days.count, 7)
        XCTAssertEqual(days[6].seconds, 600, accuracy: 0.001)
        XCTAssertEqual(days[4].seconds, 300, accuracy: 0.001)
        XCTAssertEqual(days[0].seconds, 0, accuracy: 0.001)
    }

    func testStackedFoldsOthers() {
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date(timeIntervalSince1970: 1_783_000_000))
        let rows = [
            row("top", "TopApp", start: today, duration: 600),
            row("tiny1", "Tiny1", start: today, duration: 60),
            row("tiny2", "Tiny2", start: today, duration: 60),
        ]
        let points = Agg.stacked(rows, calendar: calendar, count: 1, now: today, top: 1)
        let names = Set(points.map(\.appName))
        XCTAssertEqual(names, ["TopApp", "其他"])
        let other = points.first { $0.appName == "其他" }
        XCTAssertEqual(other?.minutes ?? -1, 2, accuracy: 0.001)
    }

    func testStoreRoundtripAndRetention() throws {
        let store = try Store(inMemory: true)
        let context = store.context
        let base = Date(timeIntervalSince1970: 1_783_000_000)
        context.insert(UsageEvent(appID: "a", appName: "A", detail: nil, host: nil,
                                  start: base, end: base.addingTimeInterval(60)))
        context.insert(UsageEvent(appID: "b", appName: "B", detail: "https://apple.com",
                                  host: "apple.com",
                                  start: base.addingTimeInterval(120), end: base.addingTimeInterval(300)))
        try context.save()

        let rows = store.rows(from: base, to: base.addingTimeInterval(1_000))
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(Agg.total(rows), 240, accuracy: 0.001)

        store.deleteOlderThan(days: 7, now: base.addingTimeInterval(30 * 86_400))
        XCTAssertEqual(store.rows(from: base, to: base.addingTimeInterval(1_000)).count, 0)
    }
}
