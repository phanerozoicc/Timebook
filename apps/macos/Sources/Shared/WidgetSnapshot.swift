import Foundation

// 桌面小组件的数据快照：主应用每个统计周期写入，widget 扩展读取。
// 两端都不沙箱，直接共享文件路径（无需 App Group）。
struct WidgetSnapshot: Codable {
    var todaySeconds: TimeInterval
    var level: Int
    var levelName: String
    var levelLabel: String
    var pomoPhase: String
    var pomoRemain: TimeInterval
    var pomoRound: Int
    var pomoTotal: TimeInterval
    var topAppName: String?
    var generatedAt: Date

    static var url: URL {
        FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Timebook/widget-snapshot.json")
    }

    static func load() -> WidgetSnapshot? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(WidgetSnapshot.self, from: data)
    }

    func write() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(self) {
            try? data.write(to: Self.url, options: .atomic)
        }
    }

    static func placeholder(todaySeconds: TimeInterval = 0) -> WidgetSnapshot {
        let level = BrainLevel.forTotal(todaySeconds)
        return WidgetSnapshot(
            todaySeconds: todaySeconds,
            level: level.level,
            levelName: level.localName,
            levelLabel: level.label,
            pomoPhase: "idle",
            pomoRemain: 0,
            pomoRound: 1,
            pomoTotal: 0,
            topAppName: nil,
            generatedAt: Date()
        )
    }
}
