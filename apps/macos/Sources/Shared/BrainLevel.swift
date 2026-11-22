import SwiftUI

// 大脑疲劳等级：按今日累计屏幕时间分 10 级。
struct BrainLevel: Identifiable {
    let level: Int
    let label: String
    let name: String
    let nameEn: String
    let minHours: Double
    let hex: UInt32
    let message: String
    let messageEn: String
    var id: Int { level }

    /// 按当前语言取等级名/文案（修复英文界面拼出 "1h of screen time to 炸毛"）。
    var localName: String { T(name, nameEn) }
    var localMessage: String { T(message, messageEn) }

    static let all: [BrainLevel] = [
        .init(level: 1, label: "Fresh", name: "清醒", nameEn: "Fresh",
              minHours: 0, hex: 0x6FAF8C,
              message: "状态极佳，保持这个节奏", messageEn: "Peak condition — keep it up"),
        .init(level: 2, label: "Chill", name: "放松", nameEn: "Chill",
              minHours: 1, hex: 0x8BB271,
              message: "轻松区，注意别刷太久", messageEn: "Easy zone — don't overdo it"),
        .init(level: 3, label: "Meh", name: "一般", nameEn: "Meh",
              minHours: 2, hex: 0xC4A968,
              message: "有点麻木了，来次微休息吧", messageEn: "Numbness creeping in — take a micro-break"),
        .init(level: 4, label: "Tired", name: "疲倦", nameEn: "Tired",
              minHours: 3, hex: 0xC99A45,
              message: "大脑开始疲劳，效率在下降", messageEn: "Fatigue setting in, efficiency dropping"),
        .init(level: 5, label: "Strained", name: "紧绷", nameEn: "Strained",
              minHours: 4, hex: 0xC28053,
              message: "注意力涣散，该停一停了", messageEn: "Attention fraying — time to pause"),
        .init(level: 6, label: "Drained", name: "透支", nameEn: "Drained",
              minHours: 5, hex: 0xBC6A55,
              message: "能量见底，继续刷只会更累", messageEn: "Running on fumes — more scrolling only hurts"),
        .init(level: 7, label: "Foggy", name: "迷糊", nameEn: "Foggy",
              minHours: 6, hex: 0xB06070,
              message: "脑雾状态，判断力已下降", messageEn: "Brain fog — judgment is impaired"),
        .init(level: 8, label: "Fried", name: "炸毛", nameEn: "Fried",
              minHours: 8, hex: 0x9A6386,
              message: "严重过载，先照顾好自己", messageEn: "Badly overloaded — take care of yourself first"),
        .init(level: 9, label: "Melting", name: "融化", nameEn: "Melting",
              minHours: 10, hex: 0x746BB0,
              message: "再刷下去明天会崩盘", messageEn: "Keep going and tomorrow collapses"),
        .init(level: 10, label: "Dead", name: "躺平", nameEn: "Offline",
              minHours: 12, hex: 0x585E68,
              message: "大脑已离线…", messageEn: "Brain has left the building…"),
    ]

    static func forTotal(_ seconds: TimeInterval) -> BrainLevel {
        let hours = seconds / 3600
        var current = all[0]
        for candidate in all where hours >= candidate.minHours {
            current = candidate
        }
        return current
    }

    var next: BrainLevel? {
        Self.all.first { $0.level == level + 1 }
    }

    var color: Color { Color(hex: hex) }
}

extension Color {
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255
        )
    }
}
