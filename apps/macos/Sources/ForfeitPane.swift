import Charts
import SwiftUI

// 丢小时主页面（仪表盘）：指标卡 + 今日 24 格 + 7 天趋势 + 判定范围。
// 遵循时账设计系统：DS 网格、.card() 卡片、SectionHeader、StatCard、Swift Charts。
// 注意：macOS 27 上 Form+Toggle 会触发系统 Metal 崩溃（Timebook/Knot 实证），全程不用 Toggle。

struct ForfeitPane: View {
    @ObservedObject private var forfeit: ForfeitController
    @Environment(\.openSettings) private var openSettings

    init() {
        _forfeit = ObservedObject(wrappedValue: AppContext.shared.forfeit)
    }

    var body: some View {
        let _ = forfeit.refreshTick
        ScrollView(.vertical) {
            VStack(alignment: .leading, spacing: DS.gap) {
                statRow
                todayCard
                trendCard
                scopeCard
            }
            .padding(DS.pad)
        }
    }

    // MARK: - 指标行

    private var statRow: some View {
        HStack(spacing: DS.gap) {
            StatCard(symbol: "hourglass", title: T("今日荒", "Forfeited today"),
                     value: T("\(forfeit.todayLostCount) 小时", "\(forfeit.todayLostCount)h"),
                     tint: .forfeitLost)
            StatCard(symbol: "calendar.day.timeline.left", title: T("本周共荒", "Forfeited this week"),
                     value: T("\(forfeit.store.ledger.totalLost(inLastDays: 7)) 小时",
                              "\(forfeit.store.ledger.totalLost(inLastDays: 7))h"),
                     tint: .calmBlue)
            StatCard(symbol: "flame.fill", title: T("连续干净", "Clean streak"),
                     value: T("\(forfeit.cleanStreak) 天", "\(forfeit.cleanStreak) days"),
                     tint: .wellGreen)
        }
    }

    // MARK: - 今日 24 小时

    private var todayCard: some View {
        let ledger = forfeit.store.ledger
        let lost = ledger.lostHours(day: ledger.currentDayKey)
        let currentHour = ledger.currentHour()
        return VStack(alignment: .leading, spacing: DS.gapSmall) {
            SectionHeader(symbol: "clock.fill", title: T("今日 24 小时", "Today's 24 hours"),
                          trailing: T("点格子可改判", "Click a cell to override"))
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 12), spacing: 6) {
                ForEach(0..<24, id: \.self) { hour in
                    hourCell(
                        hour,
                        isLost: lost.contains(hour),
                        isFuture: hour > currentHour,
                        isCurrent: hour == currentHour
                    )
                    .onTapGesture { forfeit.toggleTodayHour(hour) }
                }
            }
            HStack(spacing: DS.gap) {
                legendDot(Color.forfeitLost, T("荒掉了", "lost"))
                legendDot(Color.wellGreen.opacity(0.85), T("属于你", "yours"))
                legendDot(Color.forfeitFuture, T("还没到", "not yet"))
                Spacer()
            }
        }
        .card()
    }

    private func hourCell(_ hour: Int, isLost: Bool, isFuture: Bool, isCurrent: Bool) -> some View {
        RoundedRectangle(cornerRadius: 7, style: .continuous)
            .fill(isLost ? Color.forfeitLost : (isFuture ? Color.forfeitFuture : Color.wellGreen.opacity(0.85)))
            .frame(height: 34)
            .overlay {
                Text(String(format: "%02d", hour))
                    .font(.system(size: 11, weight: isCurrent ? .bold : .regular, design: .monospaced))
                    .foregroundStyle(
                        isLost ? Color.white : Color.primary.opacity(isFuture ? 0.35 : 0.7))
            }
            .overlay {
                if isCurrent {
                    RoundedRectangle(cornerRadius: 7, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.55), lineWidth: 1.5)
                }
            }
    }

    private func legendDot(_ color: Color, _ label: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 8, height: 8)
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
    }

    // MARK: - 最近 7 天（与统计页同款 Charts 柱状图）

    private var trendCard: some View {
        VStack(alignment: .leading, spacing: DS.gapSmall) {
            SectionHeader(symbol: "chart.bar.fill", title: T("最近 7 天", "Last 7 days"),
                          trailing: T("共 \(forfeit.store.ledger.totalLost(inLastDays: 7)) 小时",
                                      "\(forfeit.store.ledger.totalLost(inLastDays: 7))h total"))
            Chart(forfeit.weekBars, id: \.date) { point in
                BarMark(
                    x: .value("日期", point.date, unit: .day),
                    y: .value("小时", point.hours),
                    width: .fixed(30)
                )
                .cornerRadius(4)
                .foregroundStyle(Color.forfeitLost.opacity(0.85))
            }
            .chartYAxisLabel(T("小时", "hours"))
            .frame(height: 150)
        }
        .card()
    }

    // MARK: - 判定范围（管理入口在设置）

    private var scopeCard: some View {
        VStack(alignment: .leading, spacing: DS.gapSmall) {
            SectionHeader(symbol: "shield.lefthalf.filled", title: T("判定范围", "What counts"),
                          trailing: T("管理在设置", "Manage in Settings"))
            CurrentJudgmentRow(forfeit: forfeit)
            scopeRow(symbol: "globe", title: T("分心网站", "Distracting sites"),
                     detail: siteSummary) {
                openSettings()
                NSApp.activate(ignoringOtherApps: true)
            }
            scopeRow(symbol: "app.badge.fill", title: T("分心应用", "Distracting apps"),
                     detail: appSummary) {
                openSettings()
                NSApp.activate(ignoringOtherApps: true)
            }
        }
        .card()
    }

    private var siteSummary: String {
        let enabled = forfeit.siteCategories.filter { forfeit.isCategoryEnabled($0.id) }
        let names = enabled.map(\.name).joined(separator: T("、", ", "))
        var line = names.isEmpty ? T("未开启类目", "No categories") : names
        if !forfeit.customDomains.isEmpty {
            line += T(" +自定义 \(forfeit.customDomains.count)", " +\(forfeit.customDomains.count) custom")
        }
        return line
    }

    private var appSummary: String {
        let n = forfeit.distractors.count
        return n == 0 ? T("未添加", "None added") : T("\(n) 个应用", "\(n) apps")
    }

    private func scopeRow(symbol: String, title: String, detail: String,
                          action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: symbol)
                    .font(.callout)
                    .foregroundStyle(Color.brand)
                    .frame(width: 18)
                Text(title).font(.callout)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: - 实时判定预览（与引擎同一规则）

    private struct CurrentJudgmentRow: View {
        @ObservedObject var poller: Poller
        @ObservedObject var forfeit: ForfeitController

        init(forfeit: ForfeitController) {
            self.forfeit = forfeit
            _poller = ObservedObject(wrappedValue: AppContext.shared.poller)
        }

        var body: some View {
            let segment = poller.currentSegment
            let verdict = segment.map { forfeit.previewVerdict(bundleId: $0.appID, host: $0.host) } ?? nil
            return Group {
                switch verdict {
                case .app:
                    line(T("前台应用在分心名单 → 记荒", "Frontmost app is on the list → forfeit"), lost: true)
                case .site(let name, let host):
                    line("\(host) → \(name) → \(T("记荒", "forfeit"))", lost: true)
                case nil:
                    if let host = segment?.host, !host.isEmpty,
                       Browser.isBrowser(segment?.appID ?? "") {
                        line("\(host) → \(T("不判", "ignored"))", lost: false)
                    }
                }
            }
        }

        private func line(_ text: String, lost: Bool) -> some View {
            HStack(spacing: 5) {
                Image(systemName: lost ? "exclamationmark.circle.fill" : "checkmark.circle")
                    .font(.caption2)
                Text(text).font(.caption)
                Spacer()
            }
            .foregroundStyle(lost ? Color.forfeitLost : Color.wellGreen)
        }
    }
}
