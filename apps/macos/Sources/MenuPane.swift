import SwiftUI

// 状态栏弹窗内容（NSPopover 宿主）。
// 设计：分区 + 行式操作 + 品牌主按钮；会跳动的数字全部隔离在最小子视图里，
// 保证按钮永远不会被实时重渲染打断点击。

struct MenuPane: View {
    @Environment(\.openWindow) private var openWindow
    @Environment(\.openSettings) private var openSettings
    @State private var cups = AppContext.shared.store.cupsToday()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            if let line = AppContext.shared.poller.currentLine {
                Text(line)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .padding(.horizontal, 14)
            }
            LimitsBlock()
            VStack(alignment: .leading, spacing: 6) {
                SectionLabel(text: T("专注", "FOCUS"))
                PomodoroBlock(pomodoro: AppContext.shared.pomodoro)
            }
            VStack(alignment: .leading, spacing: 3) {
                SectionLabel(text: T("健康", "WELLBEING"))
                ActionRow(symbol: "drop.fill", title: T("记一杯水", "Log a cup"),
                          tint: .water, trailing: "\(cups)/\(AppSettings.waterGoalCups)") {
                    cups = AppContext.shared.store.addCup()
                }
                ActionRow(symbol: "figure.mind.and.body", title: T("微休息 20 秒", "Micro-break 20s"),
                          tint: .wellGreen) {
                    AppContext.shared.reminders.resetActiveTime()
                    AppContext.shared.breakController.start(seconds: 20)
                    AppContext.shared.closePopover?()
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                SectionLabel(text: T("丢小时", "FORFEIT"))
                ForfeitMiniRow()
            }
            VStack(alignment: .leading, spacing: 3) {
                SectionLabel(text: T("应用", "APP"))
                ActionRow(symbol: "macwindow", title: T("打开主窗口", "Open Main Window")) {
                    AppContext.shared.closePopover?()
                    openWindow(id: "main")
                    NSApp.activate(ignoringOtherApps: true)
                }
                ActionRow(symbol: "gearshape", title: T("设置…", "Settings…")) {
                    AppContext.shared.closePopover?()
                    openSettings()
                    NSApp.activate(ignoringOtherApps: true)
                }
                PauseRow()
                ActionRow(symbol: "power", title: T("退出 Timebook", "Quit Timebook"),
                          destructive: true) {
                    NSApp.terminate(nil)
                }
            }
        }
        .padding(.vertical, 14)
        .frame(width: 292)
        .tint(.brand)
    }

    private var header: some View {
        HeaderStats()
            .padding(.horizontal, 14)
    }
}

// MARK: - 头部（唯一观察 poller 的地方）

private struct HeaderStats: View {
    @ObservedObject var poller: Poller
    init() { _poller = ObservedObject(wrappedValue: AppContext.shared.poller) }

    var body: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.brandGradient)
                .frame(width: 30, height: 30)
                .overlay {
                    Image(systemName: "timer")
                        .font(.callout.bold())
                        .foregroundStyle(.white)
                }
            Text("时账").font(.headline)
            Spacer()
            VStack(alignment: .trailing, spacing: 0) {
                Text(Fmt.duration(poller.todaySeconds, compact: true))
                    .font(.system(size: 17, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(Color.brand)
                Text(T("今日", "today")).font(.caption2).foregroundStyle(.tertiary)
            }
        }
    }
}

// MARK: - 限额块

private struct LimitsBlock: View {
    @ObservedObject var limits: LimitsEngine
    init() { _limits = ObservedObject(wrappedValue: AppContext.shared.limits) }

    var body: some View {
        Group {
            if AppSettings.limitsEnabled, AppContext.shared.poller.todaySeconds > 60 {
                VStack(alignment: .leading, spacing: 4) {
                    if limits.todayPercent >= 100 {
                        // 达限醒目条（可点击开始微休息）：不依赖系统通知横幅
                        Button {
                            AppContext.shared.reminders.resetActiveTime()
                            AppContext.shared.breakController.start(seconds: 20)
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: "figure.mind.and.body")
                                Text(T("已达今日限额，点此微休息 20 秒", "Daily limit reached — tap for a 20s break"))
                                    .font(.caption.weight(.bold))
                            }
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 6)
                            .background(Capsule().fill(.red))
                        }
                        .buttonStyle(.plain)
                    }
                    CapsuleProgress(percent: limits.todayPercent,
                                    tint: limits.todayPercent >= 100 ? .red : .brand)
                    Text(T("限额 \(AppSettings.limitsDailyLabel) 的 \(limits.todayPercent)%",
                           "\(limits.todayPercent)% of the \(AppSettings.limitsDailyLabel) limit"))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 14)
                .padding(.top, 2)
            }
        }
    }
}

// MARK: - 番茄块（观察 pomodoro；state 变更才重渲染，倒计时由 TimelineView 驱动）

private struct PomodoroBlock: View {
    @ObservedObject var pomodoro: PomodoroEngine

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Text(pomodoro.state.phase.label)
                    .font(.callout.weight(.semibold))
                if pomodoro.state.phase.isRunning {
                    HStack(spacing: 4) {
                        ForEach(0..<max(1, pomodoro.preset.rounds), id: \.self) { index in
                            Circle()
                                .fill(index < pomodoro.state.round ? Color.brand : Color.primary.opacity(0.15))
                                .frame(width: 5, height: 5)
                        }
                    }
                }
                Spacer()
                if pomodoro.state.phase.isRunning {
                    TimelineView(.periodic(from: .now, by: 1)) { _ in
                        Text(Fmt.clockInterval(pomodoro.remain))
                            .font(.system(size: 15, weight: .bold, design: .rounded))
                            .monospacedDigit()
                            .foregroundStyle(pomodoro.state.paused ? Color.secondary : Color.brand)
                    }
                }
            }
            mainControls
            PresetPills(pomodoro: pomodoro)
            presetHint(pomodoro)
        }
        .padding(.horizontal, 2)
    }

    @ViewBuilder
    private func presetHint(_ pomodoro: PomodoroEngine) -> some View {
        let preset = pomodoro.preset
        if pomodoro.state.phase == .idle {
            Text(T("下次专注 \(preset.workMin) 分钟 · 每轮休息 \(preset.shortBreakMin) 分钟",
                   "Next focus: \(preset.workMin) min · breaks \(preset.shortBreakMin) min"))
                .font(.caption2).foregroundStyle(.tertiary)
        } else if pomodoro.state.phase == .work {
            Text(T("预设 \(preset.workMin)/\(preset.shortBreakMin) 将在下一阶段生效",
                   "\(preset.workMin)/\(preset.shortBreakMin) applies from the next phase"))
                .font(.caption2).foregroundStyle(.tertiary)
        }
    }

    @ViewBuilder
    private var mainControls: some View {
        let state = pomodoro.state
        switch state.phase {
        case .idle:
            Button {
                MenuPane.startPomodoro(pomodoro)
            } label: {
                Label(T("开始专注", "Start focus"), systemImage: "play.fill")
                    .font(.callout.weight(.bold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                    .background(Capsule().fill(Color.brandGradient))
                    .foregroundStyle(.white)
            }
            .buttonStyle(.plain)
        case .work, .short, .long:
            HStack(spacing: 6) {
                if state.paused {
                    pillButton(T("继续", "Resume"), systemImage: "play.fill", prominent: true) {
                        pomodoro.resume()
                    }
                } else {
                    pillButton(T("暂停", "Pause"), systemImage: "pause.fill") { pomodoro.pause() }
                }
                pillButton(T("跳过", "Skip"), systemImage: "forward.fill") { pomodoro.skip() }
                pillButton(T("结束", "Stop"), systemImage: "stop.fill", destructive: true) { pomodoro.reset() }
            }
        default:
            HStack(spacing: 6) {
                pillButton(state.phase.readyStartLabel,
                           systemImage: "play.fill", prominent: true) {
                    MenuPane.startPomodoro(pomodoro, ready: true)
                }
                pillButton(T("重置", "Reset"), systemImage: "arrow.counterclockwise") { pomodoro.reset() }
            }
        }
    }

    private func pillButton(_ title: String, systemImage: String,
                            prominent: Bool = false, destructive: Bool = false,
                            action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.caption.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
                .background(
                    Capsule().fill(prominent
                        ? AnyShapeStyle(Color.brandGradient)
                        : AnyShapeStyle(Color.primary.opacity(0.06)))
                )
                .foregroundStyle(prominent
                    ? AnyShapeStyle(.white)
                    : AnyShapeStyle(destructive ? AnyShapeStyle(.red) : AnyShapeStyle(.primary)))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - 丢小时行（观察 forfeit 的最小子视图；点击进主窗口第 5 页）

private struct ForfeitMiniRow: View {
    @ObservedObject var forfeit: ForfeitController
    @Environment(\.openWindow) private var openWindow
    init() { _forfeit = ObservedObject(wrappedValue: AppContext.shared.forfeit) }

    var body: some View {
        let lost = forfeit.todayLostCount
        Button {
            AppContext.shared.pendingMainTab = 4
            AppContext.shared.closePopover?()
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        } label: {
            HStack(spacing: 8) {
                Text(lost > 0
                     ? T("今日已荒 \(lost) 小时", "\(lost)h lost today")
                     : T("今天还没荒", "No hours lost yet"))
                    .font(.callout)
                    .foregroundStyle(lost > 0 ? Color.forfeitLost : .secondary)
                Spacer()
                HStack(spacing: 1.5) {
                    ForEach(0..<24, id: \.self) { hour in
                        RoundedRectangle(cornerRadius: 1.5)
                            .fill(miniCellColor(hour))
                            .frame(width: 6, height: 11)
                    }
                }
                Image(systemName: "chevron.right")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 14)
    }

    private func miniCellColor(_ hour: Int) -> Color {
        let ledger = forfeit.store.ledger
        if ledger.lostHours(day: ledger.currentDayKey).contains(hour) { return .forfeitLost }
        if hour > ledger.currentHour() { return .forfeitFuture }
        return .wellGreen.opacity(0.75)
    }
}

// MARK: - 暂停行（观察 poller 的最小子视图）

private struct PauseRow: View {
    @ObservedObject var poller: Poller
    init() { _poller = ObservedObject(wrappedValue: AppContext.shared.poller) }

    var body: some View {
        ActionRow(symbol: poller.paused ? "play.circle" : "pause.circle",
                  title: poller.paused ? T("继续记录", "Resume tracking") : T("暂停记录", "Pause tracking"),
                  tint: poller.paused ? .wellGreen : .primary) {
            poller.paused.toggle()
        }
    }
}

extension MenuPane {
    static func startPomodoro(_ engine: PomodoroEngine, ready: Bool = false) {
        AppContext.requestNotifications()
        if ready { engine.beginReady() } else { engine.start() }
    }
}
