import Foundation
import os

// 日志：os.log（Console 可见）+ 文件（~/Library/Application Support/Timebook/timebook.log）。
// 崩溃钩子：未捕获异常与致命信号发生时，同步写一条 CRASH 记录再交还原处理，
// 保证「闪退无痕」的情况也能留下现场。

enum AppLog {
    static let os = Logger(subsystem: "com.haozc.Timebook", category: "app")

    private static let queue = DispatchQueue(label: "com.haozc.Timebook.filelog", qos: .utility)
    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
        return formatter
    }()

    static var fileURL: URL {
        FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Timebook/timebook.log")
    }

    static func info(_ message: String) { write("INFO", message) }
    static func debug(_ message: String) { write("DEBUG", message) }
    static func error(_ message: String) { write("ERROR", message) }

    private static func write(_ level: String, _ message: String) {
        let line = "[\(dateFormatter.string(from: Date()))] [\(level)] \(message)"
        switch level {
        case "ERROR": os.error("Timebook: \(message, privacy: .public)")
        case "DEBUG": os.debug("Timebook: \(message, privacy: .public)")
        default: os.info("Timebook: \(message, privacy: .public)")
        }
        queue.async {
            let text = line + "\n"
            if let data = text.data(using: .utf8) {
                if let handle = try? FileHandle(forWritingTo: fileURL) {
                    defer { try? handle.close() }
                    _ = try? handle.seekToEnd()
                    handle.write(data)
                } else {
                    try? data.write(to: fileURL, options: .atomic)
                }
            }
        }
    }

    // MARK: 崩溃钩子

    private static var crashHandlersInstalled = false
    private static let crashSignalLock = NSLock()

    static func installCrashHandlers() {
        guard !crashHandlersInstalled else { return }
        crashHandlersInstalled = true

        NSSetUncaughtExceptionHandler { exception in
            AppLog.appendCrashSync("UNCAUGHT EXCEPTION \(exception.name.rawValue): \(exception.reason ?? "-")\n\(exception.callStackSymbols.joined(separator: "\n"))")
        }
        for signalValue in [SIGABRT, SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGTRAP] {
            signal(signalValue) { code in
                AppLog.appendCrashSync("SIGNAL \(code)")
                signal(code, SIG_DFL)
                raise(code)
            }
        }
        // 干净退出类信号也留痕（排查「无声消失」）
        for signalValue in [SIGTERM, SIGHUP, SIGQUIT] {
            signal(signalValue) { code in
                AppLog.appendCrashSync("TERMINATED BY SIGNAL \(code)")
                exit(0)
            }
        }
        AppLog.info("崩溃钩子已安装")
    }

    /// 信号处理器内只做异步安全操作：open + write + close。
    static func appendCrashSync(_ message: String) {
        let text = "[\(dateFormatter.string(from: Date()))] [CRASH] \(message)\n"
        let path = fileURL.path
        crashSignalLock.lock()
        let fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0o644)
        if fd >= 0 {
            text.withCString { pointer in
                _ = Darwin.write(fd, pointer, strlen(pointer))
            }
            close(fd)
        }
        crashSignalLock.unlock()
    }
}
