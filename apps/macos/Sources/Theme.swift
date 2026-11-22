import SwiftUI

// MARK: - 设计系统（v4 视觉重构）
//
// 原则：8pt 网格、单一品牌色（番茄橘）+ 语义色两轨、卡片三层质感
// （浅填充 + 发丝描边 + 悬浮投影）、SF Symbols 承载图标、数字一律等宽。

enum DS {
    static let pad: CGFloat = 24          // 页面外边距
    static let gap: CGFloat = 16          // 卡片间距
    static let gapSmall: CGFloat = 10     // 卡内行距
    static let radius: CGFloat = 16       // 卡片圆角
    static let radiusSmall: CGFloat = 10
    static let sidebarWidth: CGFloat = 186
}

extension Color {
    /// 品牌主色：番茄橘
    static let brand = Color(hex: 0xF0663F)
    static let brandSoft = Color(hex: 0xFF9466)
    static let brandDeep = Color(hex: 0xD14A28)
    /// 语义辅助色
    static let wellGreen = Color(hex: 0x53B987)
    static let calmBlue = Color(hex: 0x5B8DEF)
    static let water = Color(hex: 0x4CC3E0)

    static let brandGradient = LinearGradient(
        colors: [Color.brandSoft, Color.brand],
        startPoint: .top, endPoint: .bottom
    )
}

// MARK: - 卡片

private struct CardStyle: ViewModifier {
    var highlight: Bool = false

    func body(content: Content) -> some View {
        content
            .padding(DS.gap)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(Color.primary.opacity(highlight ? 0.07 : 0.045))
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.07), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.10), radius: 8, y: 3)
    }
}

extension View {
    func card(highlight: Bool = false) -> some View { modifier(CardStyle(highlight: highlight)) }
}

// MARK: - 区块标题

struct SectionHeader: View {
    let symbol: String
    let title: String
    var trailing: String?

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: symbol)
                .font(.caption)
                .foregroundStyle(Color.brand)
            Text(title).font(.headline)
            Spacer()
            if let trailing {
                Text(trailing)
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - 统计卡

struct StatCard: View {
    let symbol: String
    let title: String
    let value: String
    var tint: Color = .brand
    /// 行内操作（显示在标题行尾，避免压到下方数值）
    var actionTitle: String?
    var actionSymbol: String?
    var action: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Label(title, systemImage: symbol)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .labelStyle(.titleAndIcon)
                Spacer()
                if let actionTitle, let action {
                    Button(action: action) {
                        Label(actionTitle, systemImage: actionSymbol ?? "")
                            .font(.caption.weight(.semibold))
                    }
                    .buttonStyle(.borderless)
                    .tint(tint)
                }
            }
            Text(value)
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(tint == .brand ? Color.primary : tint)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }
}

// MARK: - 排行条

struct BarRow: View {
    let label: String
    let seconds: TimeInterval
    let maxSeconds: TimeInterval
    var dotHex: UInt32?
    var tint: Color = .brand

    /// 条形填充色与圆点色绑定（分类条形的图例与数据色一致）
    private var fillColor: Color {
        if let hex = dotHex { return Color(hex: hex).opacity(0.9) }
        return tint
    }

    var body: some View {
        HStack(spacing: 12) {
            if let hex = dotHex {
                Circle()
                    .fill(Color(hex: hex))
                    .frame(width: 8, height: 8)
            }
            Text(label)
                .font(.callout)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(width: 160, alignment: .leading)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.07))
                    Capsule()
                        .fill(fillColor)
                        .frame(width: max(4, geo.size.width * seconds / max(maxSeconds, 1)))
                }
            }
            .frame(height: 8)
            Text(Fmt.duration(seconds, compact: true))
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 64, alignment: .trailing)
        }
    }
}

// MARK: - 环形进度

struct RingProgress: View {
    let progress: Double   // 0–1（剩余比例）
    let gradient: LinearGradient
    let label: String
    let caption: String
    var lineWidth: CGFloat = 12
    var size: CGFloat = 196

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.primary.opacity(0.08), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
            Circle()
                .trim(from: 0, to: min(1, max(0, progress)))
                .stroke(gradient, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .shadow(color: Color.brand.opacity(0.35), radius: 6)
            VStack(spacing: 2) {
                Text(label)
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                    .monospacedDigit()
                Text(caption)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(width: size, height: size)
        .animation(.easeInOut(duration: 0.6), value: progress)
    }
}

// MARK: - 空状态

struct EmptyState: View {
    let symbol: String
    let title: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: symbol)
                .font(.system(size: 30))
                .foregroundStyle(.tertiary)
            Text(title)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 22)
    }
}

// MARK: - 等级徽章

struct LevelBadge: View {
    let level: Int
    let name: String
    var size: CGFloat = 52

    var body: some View {
        let meta = BrainLevel.all[min(max(0, level - 1), BrainLevel.all.count - 1)]
        VStack(spacing: 0) {
            ZStack {
                Circle()
                    .fill(LinearGradient(colors: [meta.color.opacity(0.28), meta.color.opacity(0.12)],
                                         startPoint: .top, endPoint: .bottom))
                Text("L\(meta.level)")
                    .font(.system(size: size * 0.32, weight: .heavy, design: .rounded))
                    .foregroundStyle(meta.color)
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel("L\(meta.level) \(name)")
    }
}


// MARK: - 弹窗组件

struct SectionLabel: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.caption2.weight(.bold))
            .foregroundStyle(.tertiary)
            .tracking(0.5)
            .padding(.top, 6)
    }
}

struct ActionRow: View {
    let symbol: String
    let title: String
    var tint: Color = .primary
    var trailing: String?
    var destructive: Bool = false
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: symbol)
                    .font(.callout)
                    .foregroundStyle(destructive ? AnyShapeStyle(.red) : AnyShapeStyle(tint))
                    .frame(width: 18)
                Text(title)
                    .font(.callout)
                    .foregroundStyle(destructive ? AnyShapeStyle(.red) : AnyShapeStyle(.primary))
                Spacer()
                if let trailing {
                    Text(trailing)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(hovering ? Color.primary.opacity(0.07) : .clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
    }
}

struct PresetPills: View {
    private struct Pill: Identifiable {
        let id: String
        let title: String
        let short: String
    }

    @ObservedObject var pomodoro: PomodoroEngine

    private var pills: [Pill] {
        PomodoroPreset.presetNames.map {
            Pill(id: $0.id, title: $0.label, short: PomodoroPreset.presets[$0.id]?.shortLabel ?? "")
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            ForEach(pills) { pill in
                let selected = pomodoro.activePresetName == pill.id
                Button {
                    pomodoro.activePresetName = pill.id
                } label: {
                    Text(pill.short)
                        .font(.caption.weight(selected ? .bold : .medium))
                        .monospacedDigit()
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .background(
                            Capsule().fill(selected ? AnyShapeStyle(Color.brandGradient)
                                                    : AnyShapeStyle(Color.primary.opacity(0.09)))
                        )
                        .foregroundStyle(selected ? AnyShapeStyle(.white) : AnyShapeStyle(.primary.opacity(0.75)))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(pill.title)
            }
            Spacer()
        }
    }
}

extension PomodoroPreset {
    var shortLabel: String { "\(workMin)/\(shortBreakMin)" }
}

struct CapsuleProgress: View {
    let percent: Int
    var tint: Color = .brand

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.08))
                Capsule()
                    .fill(LinearGradient(colors: [tint.opacity(0.75), tint],
                                         startPoint: .leading, endPoint: .trailing))
                    .frame(width: geo.size.width * Double(min(percent, 100)) / 100)
            }
        }
        .frame(height: 7)
    }
}
