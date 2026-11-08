import SwiftUI

// 周热力图（GitHub 贡献格样式，HEAT 暖色 7 档）：最近 12 周每日屏幕时间。

enum Heat {
    static let palette: [UInt32] = [0x262A35, 0x3A4A52, 0x4A5A50, 0x6B6A4C, 0x8A7A4E, 0xB08D4C, 0xE2B15C]

    /// 按小时分 0–6 档。
    static func bucket(seconds: TimeInterval) -> Int {
        let hours = seconds / 3600
        if hours < 0.25 { return 0 }
        if hours < 0.5 { return 1 }
        if hours < 1 { return 2 }
        if hours < 2 { return 3 }
        if hours < 4 { return 4 }
        if hours < 6 { return 5 }
        return 6
    }

    static func color(_ bucket: Int) -> Color {
        Color(hex: palette[min(max(0, bucket), palette.count - 1)])
    }
}

struct HeatmapView: View {
    let days: [DayPoint]
    let leadingBlanks: Int

    private let cell: CGFloat = 13
    private let gap: CGFloat = 3

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(T("最近 12 周", "Last 12 weeks")).font(.headline)
            if days.isEmpty {
                Text(T("还没有足够的数据。", "Not enough data yet."))
                    .font(.callout).foregroundStyle(.secondary)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: gap) {
                        ForEach(0..<leadingBlanks, id: \.self) { _ in
                            VStack(spacing: gap) {
                                ForEach(0..<7, id: \.self) { _ in
                                    RoundedRectangle(cornerRadius: 3)
                                        .fill(.clear).frame(width: cell, height: cell)
                                }
                            }
                        }
                        ForEach(Array(weeks.enumerated()), id: \.offset) { _, week in
                            VStack(spacing: gap) {
                                ForEach(0..<7, id: \.self) { row in
                                    if row < week.count {
                                        cell(week[row])
                                    } else {
                                        RoundedRectangle(cornerRadius: 3)
                                            .fill(.clear).frame(width: cell, height: cell)
                                    }
                                }
                            }
                        }
                    }
                }
                HStack(spacing: 4) {
                    Text(T("少", "Less")).font(.caption2).foregroundStyle(.secondary)
                    ForEach(0..<7, id: \.self) { bucket in
                        RoundedRectangle(cornerRadius: 2)
                            .fill(Heat.color(bucket))
                            .frame(width: 10, height: 10)
                    }
                    Text(T("多", "More")).font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
    }

    /// 按周切列（每列最多 7 天，末列允许不足）。
    private var weeks: [[DayPoint]] {
        var columns: [[DayPoint]] = []
        var index = 0
        while index < days.count {
            let end = min(index + 7, days.count)
            columns.append(Array(days[index..<end]))
            index = end
        }
        return columns
    }

    @ViewBuilder
    private func cell(_ day: DayPoint) -> some View {
        let bucket = Heat.bucket(seconds: day.seconds)
        RoundedRectangle(cornerRadius: 3)
            .fill(day.seconds > 0 ? Heat.color(bucket) : Heat.color(0).opacity(0.6))
            .frame(width: cell, height: cell)
            .help("\(dayFormatter.string(from: day.day)) · \(Fmt.duration(day.seconds))")
    }

    private var dayFormatter: DateFormatter {
        let formatter = DateFormatter()
        formatter.dateFormat = "M/d"
        return formatter
    }
}
