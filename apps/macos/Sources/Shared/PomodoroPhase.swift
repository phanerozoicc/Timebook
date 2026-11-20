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
}
