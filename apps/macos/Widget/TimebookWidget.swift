import SwiftUI
import WidgetKit

// 桌面小组件：今日屏幕时间 + 大脑疲劳等级 + 番茄钟状态。
// 数据来自主应用每分钟写入的 widget-snapshot.json（双方均不沙箱，共享路径）。

struct SnapshotEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> SnapshotEntry {
        .init(date: .now, snapshot: .placeholder())
    }

    func getSnapshot(in context: Context, completion: @escaping (SnapshotEntry) -> Void) {
        completion(.init(date: .now, snapshot: WidgetSnapshot.load() ?? .placeholder()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SnapshotEntry>) -> Void) {
        let entry = SnapshotEntry(date: .now, snapshot: WidgetSnapshot.load() ?? .placeholder())
        let next = Calendar.current.date(byAdding: .minute, value: 15, to: .now) ?? .now
        completion(Timeline(entries: [entry], policy: .after(next)))
    }
}

struct TimebookWidgetEntryView: View {
    let entry: SnapshotEntry

    private var phaseLine: String? {
        let snapshot = entry.snapshot
        guard let phase = PomodoroPhase(rawValue: snapshot.pomoPhase), phase.isRunning else { return nil }
        let remain = max(0, snapshot.generatedAt.timeIntervalSinceNow + snapshot.pomoRemain)
        let total = Int(remain.rounded())
        let clock = String(format: "%02d:%02d", total / 60, total % 60)
        return "\(phase.label) R\(snapshot.pomoRound) · \(clock)"
    }

    private func compactDuration(_ t: TimeInterval) -> String {
        let total = Int(max(0, t.rounded()))
        let h = total / 3600, m = (total % 3600) / 60
        if h > 0 { return "\(h)h\(String(format: "%02dm", m))" }
        if m > 0 { return "\(m)m" }
        return "\(total)s"
    }

    var body: some View {
        let snapshot = entry.snapshot
        let level = BrainLevel.forTotal(snapshot.todaySeconds)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text("L\(level.level)")
                    .font(.caption2.bold())
                    .padding(.horizontal, 5).padding(.vertical, 1)
                    .background(Capsule().fill(level.color))
                    .foregroundStyle(.white)
                Text(level.name).font(.caption).foregroundStyle(.secondary)
                Spacer()
            }
            Text(compactDuration(snapshot.todaySeconds))
                .font(.system(size: 26, weight: .semibold, design: .rounded))
                .monospacedDigit()
            Text(T("今日屏幕时间", "screen time today")).font(.caption2).foregroundStyle(.secondary)
            if let line = phaseLine {
                Text("🍅 \(line)").font(.caption)
            } else if let top = snapshot.topAppName {
                Text(T("当前 · \(top)", "Now · \(top)")).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .containerBackground(for: .widget) {
            LinearGradient(colors: [level.color.opacity(0.22), .clear],
                           startPoint: .top, endPoint: .bottom)
        }
    }
}

struct TimebookWidgetMain: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "TimebookWidget", provider: Provider()) { entry in
            TimebookWidgetEntryView(entry: entry)
        }
        .configurationDisplayName(T("时账", "Timebook"))
        .description(T("今日屏幕时间、大脑疲劳等级与番茄钟状态", "Screen time, brain level and pomodoro status"))
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

@main
struct TimebookWidgetBundle: WidgetBundle {
    var body: some Widget {
        TimebookWidgetMain()
    }
}
