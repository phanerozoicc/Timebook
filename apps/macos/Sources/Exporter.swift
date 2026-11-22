import Foundation

// 导出：CSV 明细 + Markdown 周报。纯函数，便于单测。

enum Exporter {
    static func csv(_ rows: [EventRow]) -> String {
        var lines = ["start,end,duration_seconds,app,host,detail,title"]
        let formatter = ISO8601DateFormatter()
        for row in rows.sorted(by: { $0.start < $1.start }) {
            let fields = [
                formatter.string(from: row.start),
                formatter.string(from: row.end),
                String(Int(row.duration)),
                row.appName,
                row.host ?? "",
                row.detail ?? "",
                row.title ?? "",
            ]
            lines.append(fields.map(escape).joined(separator: ","))
        }
        return lines.joined(separator: "\n") + "\n"
    }

    private static func escape(_ field: String) -> String {
        if field.contains(",") || field.contains("\"") || field.contains("\n") {
            return "\"" + field.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        return field
    }

    /// Markdown 周报：合计、疲劳等级、每日表、Top 应用/网站、番茄与喝水。
    static func weeklyMarkdown(
        now: Date,
        perDay: [DayPoint],
        topApps: [AppSlice],
        topHosts: [HostSlice],
        categories: [Agg.CategorySlice],
        pomodoros: Int,
        focusSeconds: TimeInterval,
        cups: Int,
        goalCups: Int
    ) -> String {
        let dayFormatter = DateFormatter()
        dayFormatter.dateFormat = "yyyy-MM-dd"
        let weekFormatter = DateFormatter()
        weekFormatter.dateFormat = "yyyy-MM-dd"
        let today = dayFormatter.string(from: now)
        let weekStart = perDay.first.map { weekFormatter.string(from: $0.day) } ?? today

        var md = "# \(T("时账周报", "Timebook Weekly")) (\(weekStart) ~ \(today))\n\n"
        let total = perDay.reduce(TimeInterval(0)) { $0 + $1.seconds }
        let todayTotal = perDay
            .first { Calendar.current.isDate($0.day, inSameDayAs: now) }?
            .seconds ?? 0
        let level = BrainLevel.forTotal(todayTotal)
        md += "- \(T("本周合计", "Week total"))：\(Fmt.duration(total))\n"
        md += "- \(T("今日疲劳等级", "Today's brain level"))：L\(level.level) \(level.localName)（\(level.label)）\n"
        md += "- \(T("本周番茄", "Pomodoros this week"))：\(pomodoros) 🍅（\(Fmt.duration(focusSeconds))）\n"
        md += "- \(T("本周喝水", "Water today"))：\(cups)/\(goalCups) 💧\n\n"

        md += "## \(T("每日", "Daily"))\n\n"
        md += "| \(T("日期", "Date")) | \(T("时长", "Time")) |\n|---|---|\n"
        for day in perDay {
            md += "| \(dayFormatter.string(from: day.day)) | \(Fmt.duration(day.seconds)) |\n"
        }

        if !topApps.isEmpty {
            md += "\n## \(T("Top 应用", "Top apps"))\n\n"
            for app in topApps.prefix(8) {
                md += "- \(app.name)：\(Fmt.duration(app.seconds))\n"
            }
        }
        if !topHosts.isEmpty {
            md += "\n## \(T("Top 网站", "Top sites"))\n\n"
            for host in topHosts.prefix(8) {
                md += "- \(host.host)：\(Fmt.duration(host.seconds))\n"
            }
        }
        if !categories.isEmpty {
            md += "\n## \(T("分类", "Categories"))\n\n"
            for slice in categories {
                md += "- \(slice.name)：\(Fmt.duration(slice.seconds))\n"
            }
        }
        md += "\n---\n\n\(T("由 Timebook 本地生成，数据未离开这台电脑。", "Generated locally by Timebook. Data never left this Mac."))\n"
        return md
    }
}
