# Timebook（中文名：时账）

> 给时间也记个账。—— NetWorth 记钱，Carved 记事，Timebook 记时间去哪了。

一款**纯本地**的 macOS 屏幕时间统计 + 专注工具，住在菜单栏里：自动记录你每天
在哪些 App、哪些网站上花了多少时间，内置番茄钟、大脑疲劳等级、周/月统计与
桌面小组件。全部数据只存在本机一个 SwiftData 文件里，**没有任何云端、账号、
上报、API key**，也不需要辅助功能权限。

## 出处（Product Hunt + 自家基因）

- 对标对象：**ActivityWatch** —— 曾登上 Product Hunt 的开源屏幕时间统计项目
  （本地优先、隐私优先理念的代表作）。9/3–9/6 榜单上的 Omi（"问你电脑看过的一切"）、
  Insight Base（本机知识库）同属「本机数据自己拥有」这一波。
- 番茄钟 / 疲劳等级 / 分类统计 / 组件交互的产品设计**同源自家 Chrome 插件
  项目**：状态机、预设（classic 25/5 · sprint 15/3 · deep 50/10）、10 级疲劳
  文案与配色、9 类域名分类表全部同源。原来只能在浏览器里管，现在整台 Mac
  都管起来。
- 差异化：ActivityWatch 依赖其常驻 server（本地 web UI + REST）+ 浏览器扩展；
  Timebook 是**单一 SwiftData 存储 + 原生 SwiftUI 菜单栏应用**，无常驻服务、
  无浏览器扩展（浏览器网址走系统 AppleScript 自动化授权），装完即用。

## 功能（v4，视觉重构版）

> v4 视觉重构：侧边栏导航 + 设计系统（Theme.swift）+ 品牌色番茄橘 + 卡片质感 +
> ⌘1–4 快捷键 + SF Symbols 图标化，设计事实源见 docs/ui-spec.md 第 0 节。

### 健康与专注管理（v3 新增）

- [x] 每日限额：2/4/6/8h 档位，80%/90%/100% 阈值通知（warn 语义），菜单栏限额进度 Gauge
- [x] 分心网站提醒：分心分类（社交/视频/娱乐/购物）连续使用 ≥10 分钟温和提醒，30 分钟冷却
- [x] 休息提醒：按"连续活跃时长"触发（20/30/45/60 分钟），空闲与番茄休息期自动重置
- [x] 喝水提醒：间隔 + 每日时间窗 + 目标杯数；喝水记录落库，菜单/专注页 +1 杯
- [x] 全屏微休息遮罩：20 秒倒计时环 + 护眼引导文案 + 跳过（NSPanel，不抢键盘焦点）
- [x] 12 周热力图（GitHub 贡献格样式，暖色 7 档配色）
- [x] 窗口标题采集（可选，辅助功能权限，默认关；时间线回看用）
- [x] 导出：明细 CSV（ISO 时间/应用/域名/标题）+ Markdown 周报（合计/等级/每日表/Top/番茄/喝水）
- [x] 双语：中文（源语言）/ English 全量覆盖，跟随系统或手动切换
- [x] 程序化生成 App 图标（深灰底 + 番茄红进度环 + 琥珀指针）

### 屏幕时间（v1 已有）

- [x] 自动记录前台应用（2 秒轮询 `NSWorkspace`），浏览器按域名统计
      （Chrome/Arc/Edge/Brave/Safari，AppleScript 授权，拒绝则退化为只记 App）
- [x] 空闲判定（键鼠停止超过阈值不计入）、合盖睡眠不记
- [x] 排除应用、数据保留期、登录启动、随时暂停

### 番茄钟

- [x] 完整状态机：work → 短休 → … → 第 N 轮长休；`-ready` 待开始阶段；
      开始/暂停/继续/跳过/结束；跳过也计为一次（不完整的）专注段
- [x] 三预设 + 自定义（classic 25/5×4、sprint 15/3×4、deep 50/10×3）
- [x] 自动开始休息 / 自动开始下一轮（可关）
- [x] 阶段结束系统通知（首次开始时请求通知授权）
- [x] **菜单栏倒计时**：专注期间菜单栏变成 `🍅 24:31`（暂停 `🍅 ⏸`）
- [x] 「专注」页：环形进度、轮次圆点、今日完成数与专注时长、
      **分心记录**（本次专注期间用过的 App，从时间记录反查）
- [x] 状态持久化：重启应用后番茄钟状态不丢

### 统计与疲劳等级

- [x] **大脑疲劳等级**：按今日累计屏幕时间 10 级（清醒→躺平），等级卡显示
      进度与距下一级提示；菜单栏组件同款
- [x] 「统计」页：最近 7 天 / 30 天切换，每日趋势柱状图、合计、活跃天日均、
      活跃天数
- [x] **分类占比**：按域名归入 9 类（社交/视频/资讯/购物/工作/学习/娱乐/邮件/
      其他），环形图 + 图例

### 桌面小组件

- [x] WidgetKit 小组件（小号/中号）：今日屏幕时间、疲劳等级徽章、番茄钟
      阶段与倒计时、当前应用
- [x] 数据链路：主应用每分钟写入 `widget-snapshot.json`，widget 每 15 分钟
      刷新读取（双方均不沙箱，共享路径，无需 App Group）

## 设计原则

- **单体**：一个 .app（内嵌一个 widget 扩展），无常驻服务、无守护进程。
- **零权限依赖**：只统计前台 App 不需要任何授权；唯一可选项是浏览器网址的
  AppleScript 自动化授权（拒绝也能用，只是少按域名的统计）。
- **数据可带走**：SwiftData store 是标准 SQLite 文件，拷走即备份。
- **规则同源自家 Chrome 插件**：番茄钟与疲劳等级的规则和文案保持两端一致，
  数据各管各的（浏览器内 vs 全系统）。

## 技术栈

- SwiftUI（MenuBarExtra `.window` + Window/Settings 场景）+ Swift Charts
  （BarMark/SectorMark）
- SwiftData（使用分段 + 专注段两张表）
- NSWorkspace / CGEventSource / NSAppleScript / SMAppService / UserNotifications
- WidgetKit 扩展 + 共享快照文件
- XcodeGen 工程定义

## 构建与运行

```bash
xcodegen generate
xcodebuild -project Timebook.xcodeproj -scheme Timebook \
  -destination 'platform=macOS' -derivedDataPath build build
open build/Build/Products/Debug/Timebook.app
```

单元测试（15 个：聚合、番茄钟状态机全流程、分类映射、疲劳等级阈值、存储）：

```bash
xcodebuild -project Timebook.xcodeproj -scheme Timebook \
  -destination 'platform=macOS' -derivedDataPath build test
```

添加桌面小组件：通知中心 → 编辑小组件 → 搜索「时账」。（Debug 构建首次可能
需要注销/重启后才会出现在小组件库里。）

## 路线图

（v3 已无未排期功能。备选方向：周报定时自动生成、iCloud 同步、浏览器插件与
Timebook 的限额联动。）

## 日志（调试）

- 文件日志：`~/Library/Application Support/Timebook/timebook.log`（INFO/DEBUG/ERROR，
  覆盖启动、应用切换、番茄阶段转换、微休息生命周期、限额/提醒触发、导出）
- 崩溃钩子：未捕获异常 + SIGABRT/SEGV/BUS/ILL/FPE/TRAP 会写 CRASH 记录；
  SIGTERM/SIGHUP/SIGQUIT 干净退出也留痕——「无声闪退」从此可追溯

## 测试

- 25 个单元测试：聚合/存储/番茄状态机/分类映射/疲劳等级/限额阈值/分心冷却/
  休息与喝水提醒/热力图分桶/CSV/周报/双语切换，`xcodebuild test` 全绿
- 端到端（本机实测）：见 `docs/ui-spec.md` 与下文决策记录

## 决策记录

- **2026-09-06**：产品选定（用户在 4 轮 PH 候选中最终选择本地屏幕时间统计）。
  不做 ActivityWatch 式常驻 server，直接 SwiftData；浏览器 URL 不做扩展，
  走 AppleScript（可拒绝、优雅降级）；空闲检测不用辅助功能权限，
  用 CGEventSource 输入间隔近似。
- **2026-09-07**：集成自家 Chrome 插件项目的三大能力：番茄钟状态机（含预设/
  自动开始/跳过语义，逻辑 1:1 移植并补 9 个引擎单测）、10 级大脑疲劳等级、
  9 类域名分类；页面悬浮组件对应实现为 WidgetKit 桌面小组件（共享 JSON 快照，
  不用 App Group，因为两端均不沙箱）。通知授权延迟到首次开始番茄时请求。
- **2026-09-07（v3，功能补完）**：实现路线图全部条目——每日限额（warn 语义，
  80/90/100% 阈值）+ 分心站点连续使用提醒（10 分钟阈值、30 分钟冷却）；
  休息提醒（按连续活跃时长，空闲/番茄休息联动重置）与喝水提醒（时间窗 +
  每日目标杯数， cups 落库）；20 秒全屏微休息遮罩（NSPanel，screenSaver 层）；
  12 周热力图（暖色 7 档配色）；窗口标题采集（辅助功能权限，默认关，
  未授权优雅降级）；导出明细 CSV 与 Markdown 周报（NSSavePanel）；
  en/zh 双语（T() 全量包裹，跟随系统/中文/English 三档）；程序化生成
  App 图标（深灰底 + 番茄红进度环 + 琥珀指针）。设计决策：系统级应用无法
  强制屏蔽其他应用/网站（block/redirect 属浏览器插件能力域），
  Timebook 的限额统一为 warn 语义并记录于设计规范 docs/ui-spec.md。

