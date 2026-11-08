import AppKit
import SwiftUI

// 全屏微休息遮罩（20 秒全屏微休息）：盖住所有空间，
// 倒计时结束或手动跳过即关。非激活面板，不抢键盘焦点。

// 边框面板默认 cannotBecomeKey，内部按钮收不到键盘/部分点击——必须子类化。
final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

@MainActor
final class BreakController: ObservableObject {
    private var keyMonitor: Any?
    @Published var active = false
    @Published var remaining = 0
    @Published var total = 20

    var onFinished: (() -> Void)?

    private var panel: NSPanel?
    private var gcdTimer: DispatchSourceTimer?
    private var armedAt = Date.distantPast

    func start(seconds: Int = 20) {
        AppLog.info("微休息: start(\(seconds)) panel=\(panel == nil ? "nil" : "存在")")
        guard panel == nil else { return }
        total = max(1, seconds)
        remaining = total
        active = true
        armedAt = Date()

        let panel = KeyablePanel(
            contentRect: NSScreen.main?.frame ?? NSRect(x: 0, y: 0, width: 800, height: 600),
            styleMask: [.borderless],
            backing: .buffered, defer: false
        )
        panel.level = .screenSaver
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.isOpaque = true
        panel.backgroundColor = .black
        panel.isMovable = false
        panel.hasShadow = false
        panel.acceptsMouseMovedEvents = true
        panel.contentView = NSHostingView(rootView: BreakOverlayView(controller: self))
        panel.makeKeyAndOrderFront(nil)
        panel.orderFrontRegardless()
        self.panel = panel
        // 遮罩必须接管键盘焦点：否则 Esc 会路由给用户原来的前台应用（真实点击回归发现）
        NSApp.activate(ignoringOtherApps: true)

        // Esc / 点击任意处均可跳过——绝不把用户困在遮罩里。
        // 启动后 0.6 秒内的鼠标事件忽略（吞掉触发按钮的点击尾巴，防止双击误关）。
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .leftMouseDown, .rightMouseDown]) { [weak self] event in
            guard self?.panel != nil else { return event }
            if event.type == .keyDown && event.keyCode == 53 { // Esc
                Task { @MainActor [weak self] in self?.stop() }
                return nil
            }
            if event.type == .leftMouseDown || event.type == .rightMouseDown {
                if let armedAt = self?.armedAt, Date().timeIntervalSince(armedAt) > 0.6 {
                    Task { @MainActor [weak self] in self?.stop() }
                    return nil
                }
                return nil // 武装期内吞掉点击，不关闭
            }
            return event
        }
        AppLog.info("微休息: 面板已显示")

        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now() + 1, repeating: 1)
        timer.setEventHandler { [weak self] in
            Task { @MainActor [weak self] in self?.tick() }
        }
        timer.resume()
        gcdTimer = timer
    }

    private func tick() {
        remaining -= 1
        if remaining <= 0 {
            AppLog.info("微休息: 倒计时归零自动关闭")
            stop()
        }
    }

    func stop() {
        guard active else { return }
        AppLog.info("微休息: stop")
        gcdTimer?.cancel()
        gcdTimer = nil
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        keyMonitor = nil
        panel?.orderOut(nil)
        panel = nil
        active = false
        onFinished?()
    }
}

struct BreakOverlayView: View {
    @ObservedObject var controller: BreakController

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(hex: 0x101418), Color(hex: 0x1C2430)],
                           startPoint: .top, endPoint: .bottom)
            VStack(spacing: 28) {
                Text(T("微休息", "Micro-break"))
                    .font(.title2)
                    .foregroundStyle(.secondary)
                ZStack {
                    Circle().stroke(.white.opacity(0.12), lineWidth: 12)
                    Circle()
                        .trim(from: 0, to: controller.total > 0
                              ? Double(controller.remaining) / Double(controller.total) : 0)
                        .stroke(Color(hex: 0x6FAF8C), style: StrokeStyle(lineWidth: 12, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .animation(.linear(duration: 0.9), value: controller.remaining)
                    Text("\(controller.remaining)")
                        .font(.system(size: 84, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                        .monospacedDigit()
                }
                .frame(width: 220, height: 220)
                VStack(spacing: 8) {
                    Text(T("看向 6 米以外，缓慢眨眼，深呼吸。", "Look 6 meters away, blink slowly, breathe."))
                        .font(.title3)
                        .foregroundStyle(.white.opacity(0.85))
                    Text(T("顺便站起来活动一下肩颈。", "Stand up and roll your shoulders."))
                        .font(.callout)
                        .foregroundStyle(.white.opacity(0.5))
                }
                VStack(spacing: 6) {
                    Button(T("跳过", "Skip")) { controller.stop() }
                        .buttonStyle(.bordered)
                        .foregroundStyle(.white.opacity(0.85))
                    Text(T("点击屏幕任意处或按 Esc 也可跳过", "Click anywhere or press Esc to skip"))
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.45))
                }
                .padding(.top, 12)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
