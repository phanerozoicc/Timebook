import Foundation
import SwiftData

// One contiguous segment of using a single app (optionally a browser tab).
// Idle time and excluded apps never produce rows, so absence == away.
@Model
final class UsageEvent {
    var appID: String
    var appName: String
    var detail: String?
    var host: String?
    var title: String?
    var start: Date
    var end: Date

    init(appID: String, appName: String, detail: String?, host: String?, title: String? = nil, start: Date, end: Date) {
        self.appID = appID
        self.appName = appName
        self.detail = detail
        self.host = host
        self.title = title
        self.start = start
        self.end = end
    }
}

// 喝水记录：一天一行（每日杯数）。
@Model
final class WaterLog {
    var dayKey: String
    var cups: Int

    init(dayKey: String, cups: Int) {
        self.dayKey = dayKey
        self.cups = cups
    }
}

// One completed (or skipped) pomodoro work segment.
@Model
final class FocusEvent {    var start: Date
    var end: Date
    var completed: Bool
    var presetName: String

    init(start: Date, end: Date, completed: Bool, presetName: String) {
        self.start = start
        self.end = end
        self.completed = completed
        self.presetName = presetName
    }
}

// Value type mirror used by aggregation so pure functions stay testable
// without SwiftData.
struct EventRow: Identifiable {
    let id: UUID
    let appID: String
    let appName: String
    let detail: String?
    let host: String?
    let title: String?
    let start: Date
    let end: Date

    var duration: TimeInterval { max(0, end.timeIntervalSince(start)) }

    init(appID: String, appName: String, detail: String?, host: String?, title: String? = nil, start: Date, end: Date) {
        self.id = UUID()
        self.appID = appID
        self.appName = appName
        self.detail = detail
        self.host = host
        self.title = title
        self.start = start
        self.end = end
    }
}

@MainActor
final class Store: ObservableObject {
    let container: ModelContainer

    init(inMemory: Bool = false) throws {
        let config: ModelConfiguration
        if inMemory {
            config = ModelConfiguration(isStoredInMemoryOnly: true)
        } else {
            let dir = FileManager.default
                .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Timebook", isDirectory: true)
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            config = ModelConfiguration(url: dir.appendingPathComponent("Timebook.store"))
        }
        container = try ModelContainer(
            for: UsageEvent.self, FocusEvent.self, WaterLog.self,
            configurations: config
        )
        AppLog.info("存储初始化成功 url=\(config.url.path)")
    }

    var context: ModelContext { container.mainContext }

    func rows(from: Date, to: Date) -> [EventRow] {
        let predicate = #Predicate<UsageEvent> { $0.end >= from && $0.start < to }
        let descriptor = FetchDescriptor<UsageEvent>(
            predicate: predicate,
            sortBy: [SortDescriptor(\.start, order: .reverse)]
        )
        let events = (try? context.fetch(descriptor)) ?? []
        return events.map {
            EventRow(appID: $0.appID, appName: $0.appName, detail: $0.detail,
                     host: $0.host, title: $0.title, start: $0.start, end: $0.end)
        }
    }

    // MARK: Water (喝水记录，每天一行)

    static func dayKey(_ date: Date, calendar: Calendar = .current) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    func cupsToday(now: Date = Date()) -> Int {
        let key = Self.dayKey(now)
        let predicate = #Predicate<WaterLog> { $0.dayKey == key }
        return (try? context.fetch(FetchDescriptor(predicate: predicate)))?.first?.cups ?? 0
    }

    /// Returns the new cup count for today.
    @discardableResult
    func addCup(delta: Int = 1, now: Date = Date()) -> Int {
        let key = Self.dayKey(now)
        let predicate = #Predicate<WaterLog> { $0.dayKey == key }
        let log = (try? context.fetch(FetchDescriptor(predicate: predicate)))?.first
            ?? {
                let fresh = WaterLog(dayKey: key, cups: 0)
                context.insert(fresh)
                return fresh
            }()
        log.cups = max(0, log.cups + delta)
        try? context.save()
        return log.cups
    }

    /// Distinct apps ever recorded, for the exclusion list UI.
    func knownApps() -> [(appID: String, appName: String)] {
        let descriptor = FetchDescriptor<UsageEvent>(
            sortBy: [SortDescriptor(\.start, order: .reverse)]
        )
        let events = (try? context.fetch(descriptor)) ?? []
        var seen = Set<String>()
        var result: [(appID: String, appName: String)] = []
        for event in events where !seen.contains(event.appID) {
            seen.insert(event.appID)
            result.append((event.appID, event.appName))
        }
        return result
    }

    /// Retention cleanup. `days <= 0` means keep forever.
    func deleteOlderThan(days: Int, now: Date = Date()) {
        guard days > 0 else { return }
        let cutoff = now.addingTimeInterval(-TimeInterval(days) * 86_400)
        let predicate = #Predicate<UsageEvent> { $0.end < cutoff }
        let descriptor = FetchDescriptor<UsageEvent>(predicate: predicate)
        if let stale = try? context.fetch(descriptor) {
            for event in stale { context.delete(event) }
            try? context.save()
        }
    }

    // MARK: Focus sessions

    func recordFocus(start: Date, end: Date, completed: Bool, presetName: String) {
        context.insert(FocusEvent(start: start, end: end, completed: completed, presetName: presetName))
        try? context.save()
    }

    func focusEvents(from: Date, to: Date) -> [FocusEvent] {
        let predicate = #Predicate<FocusEvent> { $0.end >= from && $0.start < to }
        let descriptor = FetchDescriptor<FocusEvent>(
            predicate: predicate,
            sortBy: [SortDescriptor(\.start, order: .reverse)]
        )
        return (try? context.fetch(descriptor)) ?? []
    }

    /// Usage rows overlapping the given interval (for "apps used during focus").
    func rows(overlapping from: Date, to: Date) -> [EventRow] {
        let predicate = #Predicate<UsageEvent> { $0.end > from && $0.start < to }
        let descriptor = FetchDescriptor<UsageEvent>(
            predicate: predicate,
            sortBy: [SortDescriptor(\.start, order: .reverse)]
        )
        let events = (try? context.fetch(descriptor)) ?? []
        return events.map {
            EventRow(appID: $0.appID, appName: $0.appName, detail: $0.detail,
                     host: $0.host, title: $0.title, start: $0.start, end: $0.end)
        }
    }
}

// MARK: - Aggregation (pure, unit-tested)

struct AppSlice: Identifiable {
    let appID: String
    let name: String
    let seconds: TimeInterval
    var id: String { appID }
}

struct HostSlice: Identifiable {
    let host: String
    let seconds: TimeInterval
    var id: String { host }
}

struct DayPoint: Identifiable {
    let day: Date
    let seconds: TimeInterval
    var id: Date { day }
}

struct StackedPoint: Identifiable {
    let day: Date
    let appName: String
    let minutes: Double
    var id: String { "\(day.timeIntervalSince1970)-\(appName)" }
}

enum Agg {
    static func total(_ rows: [EventRow]) -> TimeInterval {
        rows.reduce(0) { $0 + $1.duration }
    }

    static func byApp(_ rows: [EventRow], limit: Int = 8) -> [AppSlice] {
        var seconds: [String: TimeInterval] = [:]
        var names: [String: String] = [:]
        for row in rows {
            seconds[row.appID, default: 0] += row.duration
            if names[row.appID] == nil { names[row.appID] = row.appName }
        }
        return seconds
            .map { AppSlice(appID: $0.key, name: names[$0.key] ?? $0.key, seconds: $0.value) }
            .sorted { $0.seconds > $1.seconds }
            .prefix(limit)
            .map { $0 }
    }

    static func byHost(_ rows: [EventRow], limit: Int = 8) -> [HostSlice] {
        var seconds: [String: TimeInterval] = [:]
        for row in rows where row.duration > 0 {
            guard let host = row.host, !host.isEmpty else { continue }
            seconds[host, default: 0] += row.duration
        }
        return seconds
            .map { HostSlice(host: $0.key, seconds: $0.value) }
            .sorted { $0.seconds > $1.seconds }
            .prefix(limit)
            .map { $0 }
    }

    static func segments(_ rows: [EventRow]) -> [EventRow] {
        rows.sorted { $0.start > $1.start }
    }

    struct CategorySlice: Identifiable {
        let name: String
        let hex: UInt32
        let seconds: TimeInterval
        var id: String { name }
    }

    /// Group browser rows into the site category set by host.
    static func byCategory(_ rows: [EventRow], limit: Int = 8) -> [CategorySlice] {
        let byId = Dictionary(uniqueKeysWithValues: SiteCategory.all.map { ($0.id, $0) })
        var seconds: [String: TimeInterval] = [:]
        for row in rows {
            guard let host = row.host, !host.isEmpty, row.duration > 0 else { continue }
            let category = SiteCategory.forHost(host)
            seconds[category.id, default: 0] += row.duration
        }
        return seconds
            .map { id, total in
                let category = byId[id] ?? SiteCategory.all.last!
                return CategorySlice(name: category.name, hex: category.hex, seconds: total)
            }
            .sorted { $0.seconds > $1.seconds }
            .prefix(limit)
            .map { $0 }
    }

    /// Daily totals for the trailing `count` days ending at `now`.
    static func perDay(_ rows: [EventRow], calendar: Calendar = .current,
                       count: Int = 7, now: Date = Date()) -> [DayPoint] {
        var buckets: [Date: TimeInterval] = [:]
        for offset in (0..<count).reversed() {
            if let day = calendar.date(byAdding: .day, value: -offset, to: calendar.startOfDay(for: now)) {
                buckets[day] = 0
            }
        }
        for row in rows {
            let day = calendar.startOfDay(for: row.start)
            if buckets[day] != nil { buckets[day, default: 0] += row.duration }
        }
        return buckets.keys.sorted().map { DayPoint(day: $0, seconds: buckets[$0] ?? 0) }
    }

    /// Stacked chart points: per day, minutes of each of the overall top apps
    /// (everything else folded into "其他").
    static func stacked(_ rows: [EventRow], calendar: Calendar = .current,
                        count: Int = 7, now: Date = Date(), top: Int = 5) -> [StackedPoint] {
        let topApps = Set(byApp(rows, limit: top).map(\.appID))
        var buckets: [Date: [String: TimeInterval]] = [:]
        for offset in (0..<count).reversed() {
            if let day = calendar.date(byAdding: .day, value: -offset, to: calendar.startOfDay(for: now)) {
                buckets[day] = [:]
            }
        }
        for row in rows {
            let day = calendar.startOfDay(for: row.start)
            guard buckets[day] != nil else { continue }
            let name = topApps.contains(row.appID) ? row.appName : "其他"
            buckets[day, default: [:]][name, default: 0] += row.duration / 60
        }
        return buckets.flatMap { day, apps in
            apps.map { StackedPoint(day: day, appName: $0.key, minutes: $0.value) }
        }
    }
}

// MARK: - Formatting

enum Fmt {
    static func duration(_ t: TimeInterval, compact: Bool = false) -> String {
        let total = Int(max(0, t.rounded()))
        let h = total / 3600, m = (total % 3600) / 60, s = total % 60
        if compact {
            if h > 0 { return "\(h)h\(String(format: "%02dm", m))" }
            if m > 0 { return "\(m)m" }
            return "\(s)s"
        }
        if h > 0 { return "\(h) 小时 \(m) 分" }
        if m > 0 { return "\(m) 分" }
        return "\(s) 秒"
    }

    static func clock(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    static func clockInterval(_ t: TimeInterval) -> String {
        let total = Int(t.rounded())
        return String(format: "%02d:%02d", total / 60, total % 60)
    }
}

extension String {
    var urlHost: String? {
        guard let url = URL(string: self) else { return nil }
        return url.host()
    }
}
