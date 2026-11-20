import AppKit
import SwiftUI

// 菜单栏：NSStatusItem + NSPopover（AppKit 宿主，事件可靠）。
// 标题由 1 秒定时器直接改 attributed title，不经过 SwiftUI 重渲染。

@MainActor
final class StatusItemController: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private let popover = NSPopover()
    private var timer: Timer?
    private var installed = false

    /// 菜单栏应用常驻：关闭所有窗口（主窗口/设置）不退出，
    /// 退出只经由弹窗菜单的「退出 Timebook」。
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        AppLog.info("应用启动完成，安装状态栏")
        installStatusItem()
        configurePopover()
        if CommandLine.arguments.contains("-uitest-open-popover") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
                self?.togglePopover()
            }
        }
    }

    private func installStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.font = NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize - 1, weight: .medium)
        item.button?.target = self
        item.button?.action = #selector(togglePopover)
        statusItem = item
        refreshTitle()
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.refreshTitle() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    private func configurePopover() {
        popover.behavior = .transient
        popover.animates = true
        let controller = NSHostingController(rootView: MenuPane())
        controller.sizingOptions = [.preferredContentSize]
        popover.contentViewController = controller
        AppContext.shared.closePopover = { [weak self] in
            self?.popover.performClose(nil)
        }
    }

    @objc private func togglePopover() {
        guard let button = statusItem?.button else { return }
        if popover.isShown {
            AppLog.debug("弹窗关闭")
            popover.performClose(nil)
        } else {
            AppLog.debug("弹窗打开")
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKeyAndOrderFront(nil)
        }
    }

    private func refreshTitle() {
        guard let button = statusItem?.button else { return }
        let ctx = AppContext.shared
        let text: String
        var colored = false
        if ctx.pomodoro.state.phase.isRunning {
            let clock = Fmt.clockInterval(ctx.pomodoro.remain)
            text = ctx.pomodoro.state.paused ? "🍅 ⏸ \(clock)" : "🍅 \(clock)"
            colored = !ctx.pomodoro.state.paused
        } else if ctx.poller.paused {
            text = "⏸"
        } else {
            text = Fmt.duration(ctx.poller.todaySeconds, compact: true)
        }
        button.title = text
        if colored {
            button.attributedTitle = NSAttributedString(
                string: text,
                attributes: [
                    .font: NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize - 1, weight: .semibold),
                    .foregroundColor: NSColor(Color.brand),
                ]
            )
        } else {
            button.attributedTitle = NSAttributedString(
                string: text,
                attributes: [
                    .font: NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize - 1, weight: .medium),
                ]
            )
        }
    }
}
