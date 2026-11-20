import Foundation

// 番茄钟：work → short/long break 循环，逻辑移植自 自研的状态机设计。
// PomodoroPhase 定义在 Shared/PomodoroPhase.swift（widget 扩展也要用）。

struct PomodoroPreset: Codable, Equatable {
    var workMin: Int = 25
    var shortBreakMin: Int = 5
    var longBreakMin: Int = 15
    var rounds: Int = 4

    static let presets: [String: PomodoroPreset] = [
        "classic": .init(workMin: 25, shortBreakMin: 5, longBreakMin: 15, rounds: 4),
        "sprint": .init(workMin: 15, shortBreakMin: 3, longBreakMin: 10, rounds: 4),
        "deep": .init(workMin: 50, shortBreakMin: 10, longBreakMin: 20, rounds: 3),
        "custom": .init(workMin: 30, shortBreakMin: 5, longBreakMin: 15, rounds: 4),
    ]
    static let presetNames: [(id: String, label: String)] = [
        ("classic", "经典 25/5"),
        ("sprint", "冲刺 15/3"),
        ("deep", "深度 50/10"),
        ("custom", "自定义 30/5"),
    ]
}

struct PomodoroState: Codable {
    var phase: PomodoroPhase = .idle
    var round: Int = 1
    var endsAt: Date?
    var paused: Bool = false
    var pausedRemaining: TimeInterval = 0
}

// 一次完成的专注段（含手动跳过的）。
@MainActor
final class PomodoroEngine: ObservableObject {
    @Published private(set) var state = PomodoroState()
    // 注意：now 故意不发布——倒计时展示由 TimelineView 驱动，
    // 否则每秒重渲染会吃掉弹窗里正在进行的点击。
    private(set) var now = Date()

    /// 统计落点：专注段开始/结束/是否完整完成。
    var onWorkSegment: ((Date, Date, Bool) -> Void)?
    /// 通知落点：标题 / 内容。
    var onNotify: ((String, String) -> Void)?
    /// 状态变化（供快照/菜单刷新）。
    var onStateChange: (() -> Void)?
    /// 进入休息阶段（短休/长休开始，含手动）——供联动（微休息/重置活跃计时）。
    var onBreakStart: (() -> Void)?

    private var gcdTimer: DispatchSourceTimer?
    private let persistKey = "pomodoroState"
    private let defaults: UserDefaults

    var activePresetName: String {
        get { defaults.string(forKey: "pomodoroPreset") ?? "classic" }
        set {
            objectWillChange.send() // 计算属性不自动通知，必须手动发
            defaults.set(newValue, forKey: "pomodoroPreset")
            onStateChange?()
        }
    }

    var preset: PomodoroPreset {
        PomodoroPreset.presets[activePresetName] ?? PomodoroPreset.presets["classic"]!
    }

    var autoStartBreaks: Bool {
        get { defaults.object(forKey: "pomodoroAutoBreaks") as? Bool ?? true }
        set {
            objectWillChange.send()
            defaults.set(newValue, forKey: "pomodoroAutoBreaks")
        }
    }

    var autoStartWork: Bool {
        get { defaults.object(forKey: "pomodoroAutoWork") as? Bool ?? false }
        set {
            objectWillChange.send()
            defaults.set(newValue, forKey: "pomodoroAutoWork")
        }
    }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: persistKey),
           let saved = try? JSONDecoder().decode(PomodoroState.self, from: data) {
            state = saved
        }
        startTimer()
    }

    func stop() {
        gcdTimer?.cancel()
        gcdTimer = nil
    }

    private func startTimer() {
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now() + 1, repeating: 1)
        timer.setEventHandler { [weak self] in
            Task { @MainActor [weak self] in self?.tick() }
        }
        timer.resume()
        gcdTimer = timer
    }

    // MARK: - Commands

    func start(now: Date = Date()) {
        AppLog.info("番茄: 开始")
        state.round = 1
        beginPhase(.work, now: now)
    }

    func pause(now: Date = Date()) {
        guard state.phase.isRunning, !state.paused else { return }
        AppLog.info("番茄: 暂停")
        state.paused = true
        state.pausedRemaining = max(0, (state.endsAt ?? now).timeIntervalSince(now))
        persist()
    }

    func resume(now: Date = Date()) {
        guard state.paused else { return }
        AppLog.info("番茄: 继续")
        state.paused = false
        state.endsAt = now.addingTimeInterval(state.pausedRemaining)
        persist()
    }

    func reset() {
        AppLog.info("番茄: 重置/结束")
        state = PomodoroState()
        persist()
    }

    func skip(now: Date = Date()) {
        guard state.phase.isRunning else { return }
        AppLog.info("番茄: 跳过")
        complete(skipped: true, now: now)
    }

    /// 手动开始“待开始”的下一阶段。
    func beginReady(now: Date = Date()) {
        guard let base = state.phase.readyBase else { return }
        beginPhase(base, now: now)
    }

    // MARK: - Engine

    func tick(now: Date = Date()) {
        self.now = now
        guard state.phase.isRunning, !state.paused, let endsAt = state.endsAt, now >= endsAt else { return }
        complete(skipped: false, now: now)
    }

    var remain: TimeInterval {
        guard state.phase.isRunning else { return 0 }
        if state.paused { return state.pausedRemaining }
        return max(0, (state.endsAt ?? now).timeIntervalSince(now))
    }

    /// 当前阶段总时长（画进度环用；ready/idle 阶段按工作时长展示）。
    var phaseTotal: TimeInterval {
        let preset = preset
        let minutes: Int
        switch state.phase {
        case .work, .workReady, .idle: minutes = preset.workMin
        case .short, .shortReady: minutes = preset.shortBreakMin
        case .long, .longReady: minutes = preset.longBreakMin
        }
        return TimeInterval(minutes * 60)
    }

    private func beginPhase(_ phase: PomodoroPhase, now: Date) {
        AppLog.info("番茄: 进入阶段 \(phase.rawValue) round \(state.round)")
        self.now = now
        let preset = preset
        let minutes: Int
        switch phase {
        case .work: minutes = preset.workMin
        case .short: minutes = preset.shortBreakMin
        case .long: minutes = preset.longBreakMin
        default: minutes = preset.workMin
        }
        state.phase = phase
        state.paused = false
        state.pausedRemaining = 0
        state.endsAt = now.addingTimeInterval(TimeInterval(minutes * 60))
        persist()
        if phase.isBreak { onBreakStart?() }
    }

    private func complete(skipped: Bool, now: Date) {
        AppLog.info("番茄: 阶段完成 skipped=\(skipped) phase=\(state.phase.rawValue)")
        if state.phase == .work {
            let preset = preset
            let startedAt = (state.endsAt ?? now).addingTimeInterval(-TimeInterval(preset.workMin * 60))
            let endedAt = skipped ? now : (state.endsAt ?? now)
            let worked = max(0, min(endedAt.timeIntervalSince(startedAt), TimeInterval(preset.workMin * 60)))
            onWorkSegment?(startedAt, startedAt.addingTimeInterval(worked), !skipped)

            let isLong = state.round >= preset.rounds
            state.round = isLong ? 0 : state.round
            state.round += 1
            let next: PomodoroPhase = isLong ? .long : .short
            if isLong {
                onNotify?(T("该长休啦 ☕️", "Long break time ☕️"),
                          T("完成 \(preset.rounds) 轮专注，休息 \(preset.longBreakMin) 分钟",
                            "\(preset.rounds) rounds done — rest \(preset.longBreakMin) min"))
            } else {
                onNotify?(T("番茄完成 🍅", "Pomodoro done 🍅"),
                          T("休息 \(preset.shortBreakMin) 分钟，顺便喝口水",
                            "Rest \(preset.shortBreakMin) min — grab some water"))
            }
            if skipped || autoStartBreaks {
                beginPhase(next, now: now)
            } else {
                state.phase = readyVariant(of: next)
                state.endsAt = nil
                persist()
            }
        } else if state.phase.isBreak {
            onNotify?(T("休息结束 🙌", "Break over 🙌"),
                      T("准备好开始下一个番茄了吗？", "Ready for the next pomodoro?"))
            if autoStartWork {
                beginPhase(.work, now: now)
            } else {
                state.phase = .workReady
                state.endsAt = nil
                persist()
            }
        }
    }

    private func readyVariant(of phase: PomodoroPhase) -> PomodoroPhase {
        switch phase {
        case .short: return .shortReady
        case .long: return .longReady
        default: return .workReady
        }
    }

    private func persist() {
        if let data = try? JSONEncoder().encode(state) {
            defaults.set(data, forKey: persistKey)
        }
        onStateChange?()
    }
}
