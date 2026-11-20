import Charts
import SwiftUI

struct MainWindow: View {
    let store: Store
    @ObservedObject var poller: Poller
    @ObservedObject var pomodoro: PomodoroEngine
    @ObservedObject var reminders: RemindersEngine
    @ObservedObject var breakController: BreakController
    @State private var tab: Int? = 0
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        NavigationSplitView {
            SidebarView(tab: $tab, poller: poller, pomodoro: pomodoro)
                .navigationSplitViewColumnWidth(DS.sidebarWidth)
        } detail: {
            // ⌘1–⌘4 快捷切换页面（窗口未开时 ⌘1 同时唤起窗口）
            HStack {
                ForEach(0..<5, id: \.self) { index in
                    Button("") {
                        tab = index
                        if index == 0 { openWindow(id: "main") }
                    }
                    .keyboardShortcut(KeyEquivalent(Character("\(index + 1)")), modifiers: .command)
                    .opacity(0)
                }
            }
            .frame(width: 0, height: 0)
            VStack(spacing: 0) {
                switch tab ?? 0 {
                case 0: TodayPane(store: store, poller: poller,
                                  breakController: breakController)
                case 1: FocusPane(store: store, pomodoro: pomodoro,
                                  reminders: reminders, breakController: breakController)
                case 2: StatsPane(store: store)
                case 3: SegmentsPane(store: store)
                default: ForfeitPane()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(minWidth: 900, minHeight: 580)
        .onAppear {
            AppContext.shared.openMain = { openWindow(id: "main") }
            // 弹窗深链（如「丢小时」入口）预设置的目标页
            if let pending = AppContext.shared.pendingMainTab {
                tab = pending
                AppContext.shared.pendingMainTab = nil
            }
            // 主窗口打开期间切换为 regular 应用：完整菜单栏 + 不被 App Nap 冻结
            NSApp.setActivationPolicy(.regular)
        }
        .onDisappear {
            NSApp.setActivationPolicy(.accessory)
        }
    }
}

// MARK: - 侧边栏

private struct SidebarView: View {
    @Binding var tab: Int?
    @ObservedObject var poller: Poller
    @ObservedObject var pomodoro: PomodoroEngine

    private let items: [(Int, String, String)] = [
        (0, "sun.max.fill", "今日"),
        (1, "timer", "专注"),
        (2, "chart.pie.fill", "统计"),
        (3, "list.bullet.rectangle", "时间线"),
        (4, "hourglass", "丢小时"),
    ]

    var body: some View {
        List(selection: $tab) {
            Section {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 8) {
                        Image(systemName: "timer")
                            .font(.title3.bold())
                            .foregroundStyle(Color.brandGradient)
                        Text("时账").font(.title3.bold())
                    }
                    Text("Timebook").font(.caption2).foregroundStyle(.tertiary)
                }
                .padding(.vertical, 6)
                .listRowSeparator(.hidden)
            }
            Section {
                ForEach(items, id: \.0) { item in
                    Label(T(item.2, english(item.0)), systemImage: item.1)
                        .tag(item.0)
                        .listRowBackground(
                            RoundedRectangle(cornerRadius: DS.radiusSmall, style: .continuous)
                                .fill(tab == item.0 ? Color.brand.opacity(0.16) : .clear)
                        )
                }
            }
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text(T("今日", "Today"))
                        .font(.caption2).foregroundStyle(.tertiary)
                    Text(Fmt.duration(poller.todaySeconds, compact: true))
                        .font(.system(size: 20, weight: .bold, design: .rounded))
                        .monospacedDigit()
                    if pomodoro.state.phase.isRunning {
                        Label("\(T("专注中", "Focusing")) · R\(pomodoro.state.round)", systemImage: "circle.fill")
                            .font(.caption2)
                            .foregroundStyle(Color.brand)
                    } else if poller.paused {
                        Label(T("已暂停", "Paused"), systemImage: "pause.circle")
                            .font(.caption2).foregroundStyle(.tertiary)
                    }
                }
                .padding(.vertical, 4)
                .listRowSeparator(.hidden)
            }
        }
        .listStyle(.sidebar)
    }

    private func english(_ tab: Int) -> String {
        ["Today", "Focus", "Stats", "Timeline", "Forfeit"][tab]
    }
}

// MARK: - Shared periodic loader

@MainActor
private final class DayData: ObservableObject {
    @Published var rows: [EventRow] = []
    private var task: Task<Void, Never>?

    func start(store: Store) {
        task?.cancel()
        task = Task { [weak self] in
            while !Task.isCancelled {
                let now = Date()
                let start = Calendar.current.startOfDay(for: now)
                self?.rows = store.rows(from: start, to: now.addingTimeInterval(60))
                try? await Task.sleep(nanoseconds: 15_000_000_000)
            }
        }
    }

    func stop() {
        task?.cancel()
    }
}

// MARK: - 今日

struct TodayPane: View {
    let store: Store
    @ObservedObject var poller: Poller
    @ObservedObject var breakController: BreakController
    @ObservedObject private var limits = AppContext.shared.limits
    @StateObject private var data = DayData()

    var body: some View {
        let rows = data.rows
        let total = Agg.total(rows)
        let level = BrainLevel.forTotal(total)
        let apps = Agg.byApp(rows)
        let hosts = Agg.byHost(rows)
        let categories = Agg.byCategory(rows)
        let maxSeconds = max(apps.map(\.seconds).max() ?? 1, hosts.map(\.seconds).max() ?? 1,
                             categories.map(\.seconds).max() ?? 1)

        ScrollView {
            VStack(alignment: .leading, spacing: DS.gap) {
                if limits.limitReached {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.octagon.fill")
                        Text(T("已达今日限额 \(AppSettings.limitsDailyLabel)——放下屏幕，去休息吧",
                               "Daily limit of \(AppSettings.limitsDailyLabel) reached — time to rest"))
                            .font(.callout.weight(.semibold))
                        Spacer()
                        Button {
                            breakController.start(seconds: 20)
                        } label: {
                            Text(T("微休息 20 秒", "20s micro-break"))
                                .font(.caption.weight(.semibold))
                        }
                        .buttonStyle(.bordered)
                        .tint(.white)
                    }
                    .foregroundStyle(.white)
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(.red))
                }
                // Hero：等级 + 合计 + 当前状态
                HStack(alignment: .center, spacing: DS.gap) {
                    LevelBadge(level: level.level, name: level.name, size: 64)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(level.name) · \(level.label)")
                            .font(.title3.weight(.semibold))
                        Text(level.message)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                        if let next = level.next {
                            GeometryReader { geo in
                                ZStack(alignment: .leading) {
                                    Capsule().fill(Color.primary.opacity(0.08))
                                    Capsule()
                                        .fill(LinearGradient(colors: [level.color.opacity(0.55), level.color],
                                                             startPoint: .leading, endPoint: .trailing))
                                        .frame(width: geo.size.width * levelProgress(total, low: level.minHours, high: next.minHours))
                                }
                            }
                            .frame(height: 6)
                            Text(nextHint(total: total, next: next))
                                .font(.caption2).foregroundStyle(.tertiary)
                        } else {
                            Text(T("已达最高等级，快去休息吧", "Max level reached — go rest"))
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(Fmt.duration(total))
                            .font(.system(size: 42, weight: .bold, design: .rounded))
                            .monospacedDigit()
                            .foregroundStyle(Color.brandGradient)
                        Text(T("今日已记录", "tracked today"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if let current = poller.currentLine {
                            Label(current, systemImage: "record.circle")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
                .card(highlight: true)

                if !categories.isEmpty {
                    VStack(alignment: .leading, spacing: DS.gapSmall) {
                        SectionHeader(symbol: "square.grid.2x2.fill", title: T("分类", "Categories"))
                        ForEach(categories) { slice in
                            BarRow(label: slice.name, seconds: slice.seconds,
                                   maxSeconds: maxSeconds, dotHex: slice.hex)
                        }
                    }
                    .card()
                }

                if !hosts.isEmpty {
                    VStack(alignment: .leading, spacing: DS.gapSmall) {
                        SectionHeader(symbol: "globe", title: T("按网站", "By site"))
                        ForEach(hosts) { slice in
                            BarRow(label: slice.host, seconds: slice.seconds, maxSeconds: maxSeconds)
                        }
                    }
                    .card()
                }

                VStack(alignment: .leading, spacing: DS.gapSmall) {
                    SectionHeader(symbol: "square.grid.3x3.topleft.filled",
                                  title: T("按应用", "By app"),
                                  trailing: T("共 \(apps.count) 项", "\(apps.count) apps"))
                    if apps.isEmpty {
                        EmptyState(symbol: "sparkles", title: T("开始使用电脑后，这里就会出现排行。", "Rankings appear once you use your Mac."))
                    } else {
                        ForEach(apps) { slice in
                            BarRow(label: slice.name, seconds: slice.seconds, maxSeconds: maxSeconds)
                        }
                    }
                }
                .card()
            }
            .padding(DS.pad)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .onAppear { data.start(store: store) }
        .onDisappear { data.stop() }
    }

    private func levelProgress(_ total: TimeInterval, low: Double, high: Double) -> Double {
        let hours = total / 3600
        return min(1, max(0, (hours - low) / max(0.001, high - low)))
    }

    private func nextHint(total: TimeInterval, next: BrainLevel) -> String {
        let remainHours = next.minHours - total / 3600
        if remainHours < 1 {
            return T("距「\(next.name)」还有不到 1 小时屏幕时间",
                     "Less than 1h of screen time to \(next.name)")
        }
        return T("距「\(next.name)」还有 \(Int(remainHours)) 小时屏幕时间",
                 "\(Int(remainHours))h of screen time to \(next.name)")
    }
}

// MARK: - 专注（番茄钟）

struct FocusPane: View {
    let store: Store
    @ObservedObject var pomodoro: PomodoroEngine
    @ObservedObject var reminders: RemindersEngine
    @ObservedObject var breakController: BreakController
    @State private var focusToday: [Date: (count: Int, seconds: TimeInterval)] = [:]
    @State private var distractions: [(String, TimeInterval)] = []
    @State private var lastWorkStart: Date?
    @State private var cups = 0

    var body: some View {
        let state = pomodoro.state
        let preset = pomodoro.preset
        ScrollView {
            VStack(alignment: .leading, spacing: DS.gap) {
                HStack(alignment: .center, spacing: 40) {
                    TimelineView(.periodic(from: .now, by: 1)) { _ in
                        RingProgress(
                            progress: pomodoro.remain / max(pomodoro.phaseTotal, 1),
                            gradient: ringGradient,
                            label: Fmt.clockInterval(pomodoro.remain),
                            caption: state.phase.label
                        )
                    }
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(spacing: 6) {
                            ForEach(0..<max(1, preset.rounds), id: \.self) { index in
                                Circle()
                                    .fill(index < state.round
                                          ? Color.brand
                                          : Color.primary.opacity(0.15))
                                    .frame(width: 9, height: 9)
                            }
                            Text(T("第 \(min(state.round, preset.rounds))/\(preset.rounds) 轮",
                                   "Round \(min(state.round, preset.rounds))/\(preset.rounds)"))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        controlButtons
                        PresetPills(pomodoro: pomodoro)
                        Toggle(T("自动开始休息", "Auto-start breaks"), isOn: Binding(
                            get: { pomodoro.autoStartBreaks }, set: { pomodoro.autoStartBreaks = $0 }
                        ))
                        .font(.callout)
                        .tint(.brand)
                        Toggle(T("自动开始下一轮专注", "Auto-start next focus"), isOn: Binding(
                            get: { pomodoro.autoStartWork }, set: { pomodoro.autoStartWork = $0 }
                        ))
                        .font(.callout)
                        .tint(.brand)
                        Toggle(T("休息开始时自动微休息", "Auto micro-break on break"), isOn: Binding(
                            get: { AppSettings.pomodoroBreakOverlay }, set: { AppSettings.set($0, forKey: AppSettings.pomoBreakOverlayKey) }
                        ))
                        .font(.callout)
                        .tint(.brand)
                    }
                    Spacer()
                }
                .card(highlight: true)

                HStack(spacing: DS.gap) {
                    StatCard(symbol: "checkmark.circle.fill", title: T("今日完成", "Completed today"),
                             value: T("\(focusToday.values.first?.count ?? 0) 个", "\(focusToday.values.first?.count ?? 0)"))
                    StatCard(symbol: "brain.head.profile", title: T("今日专注", "Focus time today"),
                             value: Fmt.duration(focusToday.values.first?.seconds ?? 0), tint: .calmBlue)
                    StatCard(symbol: "drop.fill", title: T("喝水", "Water"),
                             value: "\(cups)/\(AppSettings.waterGoalCups)",
                             tint: cups >= AppSettings.waterGoalCups ? .wellGreen : .water)
                        .overlay(alignment: .bottomTrailing) {
                            Button(T("记一杯", "+1")) { cups = store.addCup() }
                                .buttonStyle(.borderless)
                                .font(.caption.weight(.semibold))
                                .tint(.water)
                                .padding(10)
                        }
                    StatCard(symbol: "figure.stairs", title: T("连续活跃", "Active streak"),
                             value: Fmt.duration(reminders.activeSeconds, compact: true), tint: .wellGreen)
                        .overlay(alignment: .bottomTrailing) {
                            Button {
                                reminders.resetActiveTime()
                                breakController.start(seconds: 20)
                            } label: {
                                Label(T("微休息", "Break"), systemImage: "pause.fill")
                                    .font(.caption.weight(.semibold))
                            }
                            .buttonStyle(.borderless)
                            .tint(.wellGreen)
                            .padding(10)
                        }
                }

                if !distractions.isEmpty {
                    VStack(alignment: .leading, spacing: DS.gapSmall) {
                        SectionHeader(symbol: "exclamationmark.shield.fill",
                                      title: lastWorkStart.map {
                                          T("专注期间用过的应用（自 \(Fmt.clock($0))）",
                                            "Apps used during focus (since \(Fmt.clock($0)))")
                                      } ?? T("专注期间用过的应用", "Apps used during focus"))
                        ForEach(distractions, id: \.0) { name, seconds in
                            HStack {
                                Text(name).lineLimit(1)
                                Spacer()
                                Text(Fmt.duration(seconds)).foregroundStyle(.secondary).monospacedDigit()
                            }
                            .font(.callout)
                        }
                    }
                    .card()
                }
            }
            .padding(DS.pad)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .onAppear {
            cups = store.cupsToday()
            refreshStats()
        }
        .onReceive(pomodoro.$state) { _ in refreshStats() }
    }

    private var ringGradient: LinearGradient {
        switch pomodoro.state.phase {
        case .work, .workReady: return Color.brandGradient
        case .short, .shortReady:
            return LinearGradient(colors: [.wellGreen, Color(hex: 0x7BD3A8)], startPoint: .top, endPoint: .bottom)
        case .long, .longReady:
            return LinearGradient(colors: [.calmBlue, Color(hex: 0x7FA8F5)], startPoint: .top, endPoint: .bottom)
        case .idle:
            return LinearGradient(colors: [Color.primary.opacity(0.3), Color.primary.opacity(0.15)],
                                  startPoint: .top, endPoint: .bottom)
        }
    }

    @ViewBuilder
    private var controlButtons: some View {
        let state = pomodoro.state
        HStack(spacing: 10) {
            switch state.phase {
            case .idle:
                Button {
                    MenuPane.startPomodoro(pomodoro)
                } label: {
                    Label(T("开始专注", "Start focus"), systemImage: "play.fill")
                        .font(.callout.weight(.semibold))
                }
                .buttonStyle(.borderedProminent)
                .tint(.brand)
            case .work, .short, .long:
                if state.paused {
                    Button(T("继续", "Resume")) { pomodoro.resume() }
                        .buttonStyle(.borderedProminent)
                        .tint(.brand)
                } else {
                    Button(T("暂停", "Pause")) { pomodoro.pause() }
                    Button(T("跳过", "Skip")) { pomodoro.skip() }
                }
                Button(T("结束", "Stop"), role: .destructive) { pomodoro.reset() }
            default:
                Button {
                    MenuPane.startPomodoro(pomodoro, ready: true)
                } label: {
                    Label("\(T("开始", "Start"))\(state.phase.label.dropFirst(2))", systemImage: "play.fill")
                        .font(.callout.weight(.semibold))
                }
                .buttonStyle(.borderedProminent)
                .tint(.brand)
                Button(T("重置", "Reset")) { pomodoro.reset() }
            }
        }
        .tint(.brand)
    }

    private func refreshStats() {
        let calendar = Calendar.current
        let now = Date()
        let start = calendar.startOfDay(for: now)
        let events = store.focusEvents(from: start, to: now.addingTimeInterval(60))
        let completed = events.filter(\.completed)
        focusToday = [start: (completed.count, completed.reduce(0) { $0 + $1.end.timeIntervalSince($1.start) })]

        let workStart: Date? = pomodoro.state.phase == .work
            ? (pomodoro.state.endsAt ?? now).addingTimeInterval(-pomodoro.phaseTotal)
            : events.first?.start
        lastWorkStart = workStart
        if let workStart {
            let overlapping = store.rows(overlapping: workStart, to: now)
            let byApp = Dictionary(grouping: overlapping, by: \.appName)
                .map { name, rows -> (String, TimeInterval) in
                    let totalOverlap = rows.reduce(TimeInterval(0)) { rowTotal, row in
                        let overlapStart = max(row.start, workStart)
                        let overlapEnd = min(row.end, now)
                        return rowTotal + max(0, overlapEnd.timeIntervalSince(overlapStart))
                    }
                    return (name, totalOverlap)
                }
                .sorted { $0.1 > $1.1 }
                .prefix(6)
            distractions = Array(byApp)
        } else {
            distractions = []
        }
    }
}

// MARK: - 统计

struct StatsPane: View {
    let store: Store
    @State private var range = "week"
    @State private var series: [(Date, TimeInterval)] = []
    @State private var categories: [Agg.CategorySlice] = []
    @State private var summary = (total: TimeInterval(0), avg: TimeInterval(0), activeDays: 0)
    @State private var heatDays: [DayPoint] = []
    @State private var heatOffset = 0

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.gap) {
                Picker("", selection: $range) {
                    Text(T("最近 7 天", "Last 7 days")).tag("week")
                    Text(T("最近 30 天", "Last 30 days")).tag("month")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 240)

                HStack(spacing: DS.gap) {
                    StatCard(symbol: "clock.fill", title: T("合计", "Total"), value: Fmt.duration(summary.total))
                    StatCard(symbol: "calendar.day.timeline.left", title: T("活跃天日均", "Daily avg"),
                             value: Fmt.duration(summary.avg), tint: .calmBlue)
                    StatCard(symbol: "flame.fill", title: T("活跃天", "Active days"),
                             value: T("\(summary.activeDays) 天", "\(summary.activeDays) days"), tint: .wellGreen)
                }

                VStack(alignment: .leading, spacing: DS.gapSmall) {
                    SectionHeader(symbol: "chart.bar.fill", title: T("每日趋势", "Daily trend"))
                    Chart(Array(series.enumerated()), id: \.offset) { _, point in
                        BarMark(
                            x: .value("日期", point.0, unit: .day),
                            y: .value("小时", point.1 / 3600),
                            width: range == "week" ? .fixed(30) : .fixed(9)
                        )
                        .cornerRadius(4)
                        .foregroundStyle(Color.brandGradient)
                    }
                    .chartYAxisLabel(T("小时", "hours"))
                    .frame(height: 190)
                }
                .card()

                if !categories.isEmpty {
                    VStack(alignment: .leading, spacing: DS.gapSmall) {
                        SectionHeader(symbol: "square.grid.2x2.fill", title: T("分类占比", "Categories"))
                        HStack(alignment: .center, spacing: 32) {
                            Chart(categories) { slice in
                                SectorMark(
                                    angle: .value("时长", slice.seconds),
                                    innerRadius: .ratio(0.58),
                                    angularInset: 1.5
                                )
                                .cornerRadius(5)
                                .foregroundStyle(Color(hex: slice.hex))
                            }
                            .frame(width: 180, height: 180)
                            .overlay {
                                VStack(spacing: 0) {
                                    Text(Fmt.duration(summary.total, compact: true))
                                        .font(.title3.bold().monospacedDigit())
                                    Text(T("合计", "total"))
                                        .font(.caption2).foregroundStyle(.tertiary)
                                }
                            }
                            VStack(alignment: .leading, spacing: 7) {
                                ForEach(categories) { slice in
                                    HStack(spacing: 8) {
                                        Circle().fill(Color(hex: slice.hex)).frame(width: 9, height: 9)
                                        Text(slice.name)
                                        Spacer()
                                        Text(Fmt.duration(slice.seconds, compact: true))
                                            .foregroundStyle(.secondary)
                                            .monospacedDigit()
                                    }
                                    .font(.callout)
                                }
                            }
                            .frame(maxWidth: 220)
                        }
                        .frame(maxWidth: .infinity, alignment: .center)
                    }
                    .card()
                }

                HeatmapView(days: heatDays, leadingBlanks: heatOffset)
                    .card()
            }
            .padding(DS.pad)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .onAppear { reload() }
        .onChange(of: range) { _ in reload() }
    }

    private func reload() {
        let calendar = Calendar.current
        let now = Date()
        let days = range == "week" ? 6 : 29
        let start = calendar.date(byAdding: .day, value: -days, to: calendar.startOfDay(for: now))!
        let rows = store.rows(from: start, to: now.addingTimeInterval(60))
        let points = Agg.perDay(rows, count: days + 1, now: now)
        series = points.map { ($0.day, $0.seconds) }
        categories = Array(Agg.byCategory(rows, limit: 6))
        let total = points.reduce(TimeInterval(0)) { $0 + $1.seconds }
        let activeDays = max(1, points.filter { $0.seconds > 0 }.count)
        summary = (total, total / TimeInterval(activeDays), activeDays)

        let heatCount = 84
        let heatStart = calendar.date(byAdding: .day, value: -(heatCount - 1), to: calendar.startOfDay(for: now))!
        let heatRows = store.rows(from: heatStart, to: now.addingTimeInterval(60))
        heatDays = Agg.perDay(heatRows, count: heatCount, now: now)
        heatOffset = (calendar.component(.weekday, from: heatDays.first?.day ?? now) - calendar.firstWeekday + 7) % 7
    }
}

// MARK: - 时间线

struct SegmentsPane: View {
    let store: Store
    @StateObject private var data = DayData()

    var body: some View {
        VStack(alignment: .leading, spacing: DS.gapSmall) {
            SectionHeader(symbol: "list.bullet.rectangle", title: T("今日分段", "Today's segments"),
                          trailing: T("共 \(data.rows.count) 段", "\(data.rows.count) segments"))
            if data.rows.isEmpty {
                EmptyState(symbol: "moon.zzz", title: T("今天还没有记录。", "Nothing recorded today yet."))
            } else {
                List(Agg.segments(data.rows)) { row in
                    HStack(spacing: 14) {
                        Text("\(Fmt.clock(row.start)) – \(Fmt.clock(row.end))")
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .frame(width: 104, alignment: .leading)
                        Text(Fmt.duration(row.duration, compact: true))
                            .font(.callout.monospacedDigit().weight(.semibold))
                            .frame(width: 64, alignment: .trailing)
                        Text(row.appName)
                            .font(.callout.weight(.medium))
                            .lineLimit(1)
                        if let host = row.host {
                            Text(host)
                                .font(.callout)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        if let title = row.title {
                            Text(title)
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        Spacer()
                    }
                    .padding(.vertical, 3)
                }
                .listStyle(.inset)
            }
        }
        .padding(DS.pad)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .onAppear { data.start(store: store) }
        .onDisappear { data.stop() }
    }
}
