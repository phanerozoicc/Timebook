import SwiftUI

@main
struct TimebookApp: App {
    @NSApplicationDelegateAdaptor(StatusItemController.self) private var statusDelegate
    static let isUITest = CommandLine.arguments.contains("-uitest-open-main")

    var body: some Scene {
        Window("时账", id: "main") {
            MainWindow(store: AppContext.shared.store,
                       poller: AppContext.shared.poller,
                       pomodoro: AppContext.shared.pomodoro,
                       reminders: AppContext.shared.reminders,
                       breakController: AppContext.shared.breakController)
        }
        .defaultLaunchBehavior(TimebookApp.isUITest ? .presented : .suppressed)
        .defaultSize(width: 980, height: 640)

        Settings {
            SettingsView(store: AppContext.shared.store,
                         poller: AppContext.shared.poller,
                         forfeit: AppContext.shared.forfeit)
        }
        .commands {
            AppMenus()
        }
    }
}

// MARK: - 主窗口激活时的顶部菜单栏（LSUIElement 应用激活时也有完整菜单）

struct AppMenus: Commands {
    @ObservedObject private var pomodoro = AppContext.shared.pomodoro
    @ObservedObject private var poller = AppContext.shared.poller
    @ObservedObject private var limits = AppContext.shared.limits

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button(T("打开主窗口", "Open Main Window")) {
                AppContext.shared.openMain?()
                NSApp.activate(ignoringOtherApps: true)
            }
            .keyboardShortcut("n", modifiers: .command)
        }
        CommandMenu(T("专注", "Focus")) {
            PomodoroMenuItems()
        }
        CommandMenu(T("记录", "Tracking")) {
            Button(T("微休息 20 秒", "Micro-break 20s")) {
                AppContext.shared.reminders.resetActiveTime()
                AppContext.shared.breakController.start(seconds: 20)
            }
            Button(poller.paused ? T("继续记录", "Resume tracking") : T("暂停记录", "Pause tracking")) {
                poller.paused.toggle()
            }
        }
    }
}

struct PomodoroMenuItems: View {
    @ObservedObject private var pomodoro = AppContext.shared.pomodoro

    var body: some View {
        Button(T("开始专注", "Start focus")) { MenuPane.startPomodoro(pomodoro) }
            .keyboardShortcut("s", modifiers: [.command, .shift])
        if pomodoro.state.phase.isRunning {
            Button(pomodoro.state.paused ? T("继续", "Resume") : T("暂停", "Pause")) {
                pomodoro.state.paused ? pomodoro.resume() : pomodoro.pause()
            }
            .keyboardShortcut("p", modifiers: [.command, .shift])
            Button(T("跳过", "Skip")) { pomodoro.skip() }
        }
        Button(T("结束", "Stop")) { pomodoro.reset() }
    }
}

