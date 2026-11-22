import Foundation

// 番茄钟阶段（主应用与 widget 扩展共用；rawValue 与快照 JSON 对齐）。
enum PomodoroPhase: String, Codable, CaseIterable {
    case idle
    case work
    case short
    case long
    case workReady = "work-ready"
    case shortReady = "short-ready"
    case longReady = "long-ready"

    var isRunning: Bool { self == .work || self == .short || self == .long }
    var isBreak: Bool { self == .short || self == .long }

    /// "work-ready" → "work"（手动开始待开始的下一阶段）。
    var readyBase: PomodoroPhase? {
        switch self {
        case .workReady: return .work
        case .shortReady: return .short
        case .longReady: return .long
        default: return nil
        }
    }

    var label: String {
        switch self {
        case .idle: return T("待机", "Idle")
        case .work: return T("专注", "Focus")
        case .short: return T("短休", "Short break")
        case .long: return T("长休", "Long break")
        case .workReady: return T("准备专注", "Focus ready")
        case .shortReady: return T("准备短休", "Short-break ready")
        case .longReady: return T("准备长休", "Long-break ready")
        }
    }

    /// 待开始阶段的完整开始按钮文案（修英文标签被 dropFirst(2) 截成 "Startcus ready"）。
    var readyStartLabel: String {
        switch self {
        case .shortReady: return T("开始短休", "Start short break")
        case .longReady: return T("开始长休", "Start long break")
        default: return T("开始专注", "Start focus")
        }
    }
}
