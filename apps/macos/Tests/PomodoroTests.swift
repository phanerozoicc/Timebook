import Combine
import XCTest
@testable import Timebook

@MainActor
final class PomodoroTests: XCTestCase {
    private var workSegments: [(Date, Date, Bool)] = []
    private var notifications: [(String, String)] = []
    private let defaults = UserDefaults(suiteName: "TimebookTests")!

    private func makeEngine() -> PomodoroEngine {
        defaults.removePersistentDomain(forName: "TimebookTests")
        workSegments = []
        notifications = []
        let engine = PomodoroEngine(defaults: defaults)
        engine.onWorkSegment = { [weak self] start, end, completed in
            self?.workSegments.append((start, end, completed))
        }
        engine.onNotify = { [weak self] title, body in
            self?.notifications.append((title, body))
        }
        engine.onStateChange = nil
        engine.reset()
        return engine
    }

    private let t0 = Date(timeIntervalSince1970: 1_783_000_000)

    func testStartBeginsWorkPhase() {
        
        let engine = makeEngine()
        engine.start(now: t0)
        XCTAssertEqual(engine.state.phase, .work)
        XCTAssertEqual(engine.state.round, 1)
        XCTAssertEqual(engine.state.endsAt, t0.addingTimeInterval(25 * 60))
        XCTAssertEqual(engine.remain, 25 * 60, accuracy: 0.001)
    }

    func testWorkCompletesIntoShortBreakAndRecordsSegment() {
        
        let engine = makeEngine()
        engine.start(now: t0)
        let workEnd = t0.addingTimeInterval(25 * 60)
        engine.tick(now: workEnd) // 自然到期
        XCTAssertEqual(engine.state.phase, .short, "autoStartBreaks 默认开，直接进入短休")
        XCTAssertEqual(engine.state.round, 2)
        XCTAssertEqual(workSegments.count, 1)
        XCTAssertEqual(workSegments[0].0.timeIntervalSince1970, t0.timeIntervalSince1970, accuracy: 0.001)
        XCTAssertEqual(workSegments[0].1.timeIntervalSince1970, workEnd.timeIntervalSince1970, accuracy: 0.001)
        XCTAssertTrue(workSegments[0].2)
        XCTAssertEqual(notifications.first?.0, "番茄完成 🍅")
    }

    func testFourthRoundGoesLongBreak() {
        
        let engine = makeEngine()
        engine.start(now: t0)
        var now = t0
        for round in 1...4 {
            now = now.addingTimeInterval(25 * 60)
            engine.tick(now: now) // work 结束 → break
            if round < 4 {
                now = now.addingTimeInterval(5 * 60)
                engine.tick(now: now) // 短休结束（autoStartWork 默认关 → work-ready）
                XCTAssertEqual(engine.state.phase, .workReady)
                engine.beginReady(now: now)
            }
        }
        XCTAssertEqual(engine.state.phase, .long)
        XCTAssertEqual(notifications.last?.0, "该长休啦 ☕️")
        XCTAssertEqual(engine.state.round, 1, "长休后回到第 1 轮")
        XCTAssertEqual(workSegments.count, 4)
    }

    func testSkipRecordsPartialAndJumpsToBreak() {
        let engine = makeEngine()
        engine.start(now: t0)
        engine.skip(now: t0.addingTimeInterval(10 * 60))
        // skip 语义：立即进入下一阶段（不受 autoStartBreaks 影响）
        XCTAssertEqual(engine.state.phase, .short)
        XCTAssertEqual(workSegments.count, 1)
        XCTAssertEqual(workSegments[0].1.timeIntervalSince(workSegments[0].0), 600, accuracy: 0.001)
        XCTAssertFalse(workSegments[0].2)
    }

    func testBreakEndsWithoutAutoWorkGoesReady() {
        let engine = makeEngine()
        defaults.set(false, forKey: "pomodoroAutoBreaks")
        engine.start(now: t0)
        var now = t0.addingTimeInterval(25 * 60)
        engine.tick(now: now) // work 结束，autoStartBreaks=false → 短休待开始
        XCTAssertEqual(engine.state.phase, .shortReady)
        engine.beginReady(now: now)
        XCTAssertEqual(engine.state.phase, .short)
        now = now.addingTimeInterval(5 * 60)
        engine.tick(now: now) // 休息结束，autoStartWork=false → work-ready
        XCTAssertEqual(engine.state.phase, .workReady)
        defaults.removeObject(forKey: "pomodoroAutoBreaks")
    }

    func testPauseResumeKeepsRemaining() {
        
        let engine = makeEngine()
        engine.start(now: t0)
        engine.pause(now: t0.addingTimeInterval(5 * 60))
        XCTAssertTrue(engine.state.paused)
        XCTAssertEqual(engine.remain, 20 * 60, accuracy: 0.001)
        engine.tick(now: t0.addingTimeInterval(60 * 60)) // 暂停中不触发到期
        XCTAssertEqual(engine.state.phase, .work)
        engine.resume(now: t0.addingTimeInterval(70 * 60))
        XCTAssertEqual(engine.state.endsAt?.timeIntervalSince1970 ?? -1,
                       t0.addingTimeInterval(70 * 60 + 20 * 60).timeIntervalSince1970,
                       accuracy: 0.001)
    }

    func testAutoStartWorkContinuesLoop() {
        
        let engine = makeEngine()
        defaults.set(true, forKey: "pomodoroAutoWork")
        engine.start(now: t0)
        var now = t0.addingTimeInterval(25 * 60)
        engine.tick(now: now) // → short
        now = now.addingTimeInterval(5 * 60)
        engine.tick(now: now) // short 结束 → 自动开始 work
        XCTAssertEqual(engine.state.phase, .work)
        XCTAssertEqual(engine.state.round, 2)
        defaults.removeObject(forKey: "pomodoroAutoWork")
    }

    func testCategoryMapping() {
        XCTAssertEqual(SiteCategory.forHost("github.com").id, "work")
        XCTAssertEqual(SiteCategory.forHost("www.github.com").id, "work")
        XCTAssertEqual(SiteCategory.forHost("v2ex.github.io").id, "other", "后缀匹配不能误伤子串")
        XCTAssertEqual(SiteCategory.forHost("bilibili.com").id, "video")
        XCTAssertEqual(SiteCategory.forHost("mail.qq.com").id, "email")
    }

    func testBrainLevelThresholds() {
        XCTAssertEqual(BrainLevel.forTotal(0).level, 1)
        XCTAssertEqual(BrainLevel.forTotal(3600 * 3.5).level, 4)
        XCTAssertEqual(BrainLevel.forTotal(3600 * 13).level, 10)
        let level = BrainLevel.forTotal(3600 * 1.5)
        XCTAssertEqual(level.next?.level, 3)
    }
}

extension PomodoroTests {
    func testPresetChangeNotifiesObservers() {
        let engine = makeEngine()
        var notified = false
        let token = engine.objectWillChange.sink { _ in notified = true }
        engine.activePresetName = "deep"
        XCTAssertTrue(notified, "预设切换必须触发 objectWillChange（修复高亮/提示不刷新的缺陷）")
        XCTAssertEqual(engine.activePresetName, "deep")
        _ = token
    }
}
