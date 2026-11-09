# 时账 Timebook · 架构说明 / Architecture

> 目标：在 Linux 上以 **纯本地、零联网、零第三方 Python 依赖** 的方式，复刻 macOS 版 Timebook 的屏幕时间统计与专注能力。
> 本文描述分层、模块职责、数据流、定时器、线程模型与错误降级策略。
>
> 代码入口：`timebook/main.py` → `timebook/app.py`；应用装配：`timebook/context.py`。

---

## 1. 分层架构 / Layers

```text
┌──────────────────────────────────────────────────────────────────────┐
│ UI 层  timebook/ui/                      GTK4 + libadwaita            │
│  main_window · pages/* · widgets · settings_window · export_dialog   │
│  overlay（微休息遮罩） · tray（AppIndicator） · theme（token + CSS）  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 只通过 AppContext 读数据/调命令
┌───────────────────────────────▼──────────────────────────────────────┐
│ 应用装配层  timebook/app.py · context.py · main.py                   │
│  Adw.Application · AppContext · GLib 定时器 · 引擎回调接线 · 快照     │
└───────────────┬──────────────────────────────────┬───────────────────┘
                │                                  │
┌───────────────▼──────────────────┐  ┌────────────▼───────────────────┐
│ 平台层  timebook/platform/       │  │ 核心层  timebook/core/         │
│  x11（ctypes libX11/libXss）     │  │  纯 Python，无 GTK 依赖         │
│  tracker（2s 采样 → 分段落库）   │  │  store / models / settings      │
│  browsers（标题 → 域名）         │  │  pomodoro / wellbeing / forfeit │
│  notify（notify-send 通知）      │  │  categories / brain_level       │
│                                  │  │  heatmap / exporter / l10n      │
└───────────────┬──────────────────┘  └────────────┬───────────────────┘
                │                                  │
                └──────────────┬───────────────────┘
                               ▼
                    SQLite  ~/.local/share/timebook/timebook.db
```

**依赖方向**：`ui → core`（通过 `AppContext`），`app → ui + platform + core`，`platform → core`，`core` 不依赖上层。这样 `core/` 可以在无显示器、无 GTK 的环境下完整单测。

**为什么这样分**：

- UI 只消费聚合结果，不直接调用 X11 / SQLite，换界面（GTK → 其他）不影响采集与统计。
- 平台差异全部收敛在 `platform/x11.py` 与 `platform/browsers.py`，便于未来接 Wayland 协议或测试替身。
- `core/` 用注入时钟（`now_fn`）与协议（`WindowSource`），状态机可以瞬间推进测试。

---

## 2. 模块职责 / Module map

| 模块 | 职责 | 关键点 |
|---|---|---|
| `main.py` | CLI 入口 | `--page` / `--db` / `--screenshot` / `--dump` / `--hidden` / `--version` / `-v`；设置 `GSK_RENDERER`，初始化 Adw |
| `app.py` | `Adw.Application` 子类 | 启动装配、GLib 定时器、引擎回调、托盘、微休息遮罩、`widget-snapshot.json` |
| `context.py` | `AppContext` 数据类 | 持有 store/settings/pomodoro/limits/reminders/tracker/forfeit/notifier；UI 的唯一依赖入口 |
| `core/store.py` | SQLite 单文件存储 | WAL、`check_same_thread=False` + `RLock`、5 张表、迁移、导出查询 |
| `core/models.py` | 领域模型与聚合 | `EventRow` / `FocusRow`；按应用/网站/分类/天聚合；时长格式化 |
| `core/settings.py` | 类型化设置 | 键名与 macOS 版一致；每次实时读，改动立即生效；非法值回落默认 |
| `core/pomodoro.py` | 番茄状态机 | `idle/work/short/long/*-ready`、暂停/恢复、跳过、自动开始、持久化 |
| `core/wellbeing.py` | 限额与提醒引擎 | 80/90/100% 三档、分心站点 10 分钟/30 分钟冷却、休息与喝水提醒 |
| `core/forfeit.py` | 丢小时账本 | 24 小时格、分心应用/类目/域名规则、手动改判、连续干净天数 |
| `core/categories.py` | 站点分类 | 9 类、域名后缀匹配、分类颜色与「是否分心」 |
| `core/brain_level.py` | 疲劳等级 | L1–L10 阈值/配色/中英文案；进度到下一级 |
| `core/heatmap.py` | 热力图分桶 | 最近 12 周、7 档、周一为首列 |
| `core/exporter.py` | 导出 | CSV 明细（UTF-8 BOM）+ Markdown 周报（纯函数） |
| `core/l10n.py` | 双语 | `auto/zh/en`、环境变量检测、`T(zh, en)` |
| `core/applog.py` | 文件日志 | `~/.local/state/timebook/timebook.log`，1 MB × 3 滚动，未捕获异常钩子 |
| `platform/x11.py` | X11 原生调用 | ctypes 直连 libX11/libXss；`_NET_ACTIVE_WINDOW`、`WM_CLASS`、`_NET_WM_PID`、`_NET_WM_NAME`、`XScreenSaverQueryInfo` |
| `platform/tracker.py` | 采集循环 | 2 秒 tick；暂停/锁屏/空闲/排除门控；应用或域名变化切段；退出前结账 |
| `platform/browsers.py` | 浏览器识别 | `WM_CLASS` 白名单 + 标题域名推断（已知站点优先，通用正则兜底） |
| `platform/notify.py` | 通知 | 优先 `notify-send`，退化到 `Gio.Notification`；不可用时静默 |
| `ui/theme.py` | 设计系统 | 品牌/语义色、间距、圆角、CSS、单色图标 |
| `ui/widgets.py` | 可复用控件 | 卡片、统计卡、胶囊条、环、柱状图、环形图、热力图、等级徽章、空状态 |
| `ui/main_window.py` | 主窗口 | 侧边栏 + HeaderBar + 页面栈 + `Ctrl+1..5` + 暂停 |
| `ui/pages/*.py` | 五个页面 | 今日 / 专注 / 统计 / 时间线 / 丢小时 |
| `ui/settings_window.py` | 设置 | Adw.PreferencesPage：记录、限额、提醒、排除应用、外观与数据 |
| `ui/export_dialog.py` | 导出 | XDG 下载目录、CSV + Markdown、Adw.Toast、打开文件夹 |
| `ui/overlay.py` | 微休息 | 20 秒全屏渐变遮罩 + 倒计时环 + 跳过 |
| `ui/tray.py` | 托盘 | StatusNotifierItem（D-Bus）：标签 + 菜单；不可用则 `available=False` |
| `ui/introspect.py` | 界面自省 | 导出可见控件文本/数量，供自动化验证，不参与产品逻辑 |

---

## 3. 数据流 / Data flow

### 3.1 采集主链路（X11 → Tracker → SQLite → 聚合 → 页面）

```text
X11Display.active_window()                    platform/x11.py
   ├─ _NET_ACTIVE_WINDOW / XGetInputFocus
   ├─ _NET_WM_PID → /proc/<pid>/comm（应用名兜底）
   ├─ WM_CLASS   → (app_id, app_name)
   └─ _NET_WM_NAME → title
              │
              ▼  WindowInfo
Tracker.tick()（每 2 秒，GLib 主循环）         platform/tracker.py
   ├─ settings.paused?           → 关段且不记录
   ├─ screensaver_active()?      → 关段且不记录（锁屏/熄屏）
   ├─ idle_seconds ≥ threshold?  → 结束时间回退到空闲开始前，关段记录
   ├─ 排除应用?                   → 关段且不记录
   ├─ 浏览器 && 标题解析?          → host = host_from_title(title)
   ├─ app_id / host 变化?         → 关闭旧段写库 + 打开新段
   └─ 休眠恢复大跳跃?             → 丢弃该段，重新开始
              │
              ▼  Store.add_event()
SQLite  usage_events（app_id/app_name/host/title/start_ts/end_ts）
              │
              ▼  Store.rows / today_rows / rows_overlapping
core/models.py  聚合：total / by_app / by_host / by_category / per_day / segments
              │
              ▼  App 每 2 秒 UI tick（窗口可见时）
ui/pages/*  刷新当前页；侧边栏与托盘同步更新
```

**关键语义**：数据库只保存**已关闭的段**；当前段在内存中，`Tracker.today_seconds()` 会把「现在 − 段开始」加进去，所以界面数字实时增长。暂停、空闲、锁屏、排除应用都不产生数据，保证「没有记录 == 不在用电脑」。

**段变化副作用**：`Tracker.on_segment_change(app_id, host)` → `ForfeitStore.observe()`，若命中分心应用/类目/域名，把当前小时记入 `forfeit_days`，并立即持久化。

### 3.2 番茄链路

```text
FocusPage 按钮 / 快捷键 / 托盘
   → PomodoroEngine.toggle() / skip() / reset()
   → 状态写入 kv（pomodoroState）
   → 每 1 秒 tick() 检查 ends_at
   → 工作段结束：on_work_segment → Store.record_focus(focus_events)
   → 休息开始：on_break_start → RemindersEngine.reset_active_time()
                             → 可选 BreakOverlay（20 秒全屏）
   → 通知：on_notify → Notifier.send → notify-send / GNotification
```

### 3.3 提醒与限额链路

```text
每 5 秒  RemindersEngine.tick(idle, in_pomodoro_break, settings)
           ├─ 空闲/番茄休息 → active_seconds = 0
           ├─ 否则 active_seconds += 5
           └─ ≥ 休息间隔 → 通知「该休息一下了」
           └─ 喝水时间窗内 & ≥ 间隔 → 通知「该喝水了」（带今日杯数）

每 60 秒 LimitsEngine.minute(today_total, current_host, segment_start)
           ├─ 80/90/100% 各提醒一次（每天重置）
           └─ 分心站点连续 10 分钟 → 温和提醒（30 分钟冷却）
```

### 3.4 快照与导出

- **快照**：`App._write_snapshot()` 在 UI tick 中调用，内部 55 秒节流（约 60 秒一次），原子写入 `~/.local/share/timebook/widget-snapshot.json`。字段：`todaySeconds`、`level`、`levelName`、`levelLabel`、`pomoPhase`、`pomoRemain`、`pomoRound`、`pomoTotal`、`topAppName`、`generatedAt`。对应 macOS WidgetKit 的数据面，Linux 上作为可选读取方（脚本/第三方小组件）。
- **导出**：`export_dialog.extract_to_downloads()` → `store.today_rows()` → `exporter.export_csv()`（UTF-8 BOM）与 `exporter.export_markdown()`（7 天周报）→ 写入 XDG 下载目录 → Adw.Toast。

### 3.5 数据库结构

| 表 | 字段 | 用途 |
|---|---|---|
| `usage_events` | `id, app_id, app_name, detail, host, title, start_ts, end_ts` | 每次前台段；时间存 Unix epoch（REAL） |
| `focus_events` | `id, start_ts, end_ts, completed, preset_name` | 番茄工作段（含跳过的段） |
| `water_logs` | `day_key, cups` | 每日喝水杯数 |
| `forfeit_days` | `day_key, lost_hours` | 每日「荒」小时集合（JSON） |
| `kv` | `key, value` | 设置、番茄状态、预设等（JSON 值） |

索引：`usage_events(start_ts/end_ts/app_id)`、`focus_events(start_ts)`。WAL 模式 + `synchronous=NORMAL`，崩溃不丢已提交数据。数据库路径可用 `TIMEBOOK_DB` / `--db` 覆盖。

---

## 4. 定时器节奏 / Timer cadence

所有定时器由 GTK 主循环的 `GLib.timeout_add_seconds()` 驱动；**首次 activate 时启动**（`App._start_timers`），并在启动时立即执行一次采集与番茄 tick。

| 任务 | 周期 | 回调 | 说明 |
|---|---:|---|---|
| **前台采集** | **2 s** | `_tick_tracker` → `Tracker.tick()` | 采样前台窗口；变化时切段、写库 |
| **番茄钟** | **1 s** | `_tick_pomodoro` → `PomodoroEngine.tick()` | 检查 `ends_at`，阶段切换/通知 |
| **界面刷新** | **2 s** | `_refresh_all` | 主窗口可见时刷新当前页；同时刷新托盘 |
| **休息/喝水提醒** | **5 s** | `_tick_reminders` | 连续活跃计时、时间窗、冷却 |
| **限额检查** | **60 s** | `_tick_limits` | 80/90/100% 与分心站点提醒 |
| **Widget 快照** | **约 60 s** | `_write_snapshot`（由 2 s UI tick 调用，内部 55 s 节流） | 原子写 `widget-snapshot.json` |

补充：日志中的「应用切换、番茄阶段转换、提醒、导出」均按事件即时记录；数据库清理在每天首次采集 tick 时执行（按 `retentionDays`）。

---

## 5. 线程模型 / Threading

| 执行体 | 职责 | 同步/安全 |
|---|---|---|
| **GTK 主线程（唯一）** | GLib 主循环、全部定时器回调、Tracker.tick、番茄/提醒/限额引擎、UI 构建与刷新、SQLite 读写、快照写入 | 所有产品逻辑默认在此线程顺序执行，无并发竞争 |
| `Tracker` | 段状态机 | 内部 `threading.RLock`；`tick` / `force_close` / 查询可被其他线程调用；异常在 tick 内捕获，绝不打断采集 |
| `Store` | SQLite 连接 | `check_same_thread=False` + `RLock` 串行化；WAL 允许读写并存；`close()` 由 shutdown 调用 |
| 子进程 | `notify-send`（超时 5 s）、`xdg-open`（非阻塞） | 同步等待通知进程；`xdg-open` 仅 `Popen` 不等待 |
| 截图 | `import -window <xid>`（`--screenshot`） | 同步 `subprocess.run`，超时 20 s；失败退化到 `GdkTexture` |

**设计取舍**：当前没有自建后台线程，采集在 GTK 主循环中执行（2 秒一次、调用很短），便于状态一致与测试；`Store`/`Tracker` 的锁为未来把采集移到 worker 线程预留。唯一可能阻塞界面的是 `notify-send` 最长 5 秒超时，正常桌面瞬时返回；若后续出现卡顿，可把通知投递移到线程池。

**生命周期**：`shutdown` 时移除所有 GLib source → `tracker.force_close()` 结账当前段 → `forfeit.save()` → `store.close()` → 销毁托盘 → 写日志「已退出」。

---

## 6. 错误降级策略 / Failure handling

| 故障 | 行为 | 用户可见影响 |
|---|---|---|
| libX11 / libXss 缺失或 `DISPLAY` 不可用 | `X11Display` 懒加载失败后缓存错误；`active_window()` 返回 `None`；`idle_seconds()` 先尝试 `xprintidle`，仍失败则返回 `0.0`；`screensaver_active()` 返回 `False` | 界面/番茄/历史数据正常；不再产生新采集段，日志记录原因 |
| Wayland 原生窗口不可枚举 | `active_window()` 拿不到窗口 | 无新数据；建议 X11 会话或 `GDK_BACKEND=x11` |
| 单次采集 tick 异常 | `Tracker.tick` 捕获并 `log.exception`，下一 tick 继续 | 当前段可能丢弃，程序不崩 |
| 写 `usage_events` 失败 | `Store.add_event` 异常被捕获并记录 | 当前段丢失，不影响后续采集 |
| 空闲/屏保查询异常 | 空闲回退到 `xprintidle`，再失败按 0；屏保按 False | 可能继续计时，不会误杀数据 |
| 窗口缺少 `WM_CLASS` | `app_id="unknown"`，应用名兜底 | 记录归入 unknown；不影响时长 |
| 浏览器标题解析失败 | `host=None` | 只按应用统计；不猜测域名 |
| 设置值非法（语言/保留期/阈值等） | `Settings` 回落到默认值 | 无崩溃；下次写入可修正 |
| 番茄持久化状态损坏 | `PomodoroState.from_dict` 回落到 `idle` | 当前番茄重置，不阻塞启动 |
| 托盘/AppIndicator 不可用 | `Tray.available=False`，不创建 indicator | 仅窗口模式；关闭窗口默认隐藏，重新运行 `timebook` 可再次激活窗口 |
| `notify-send` 不存在/失败 | 退化到 `GApplication.send_notification`；再失败只写日志 | 无桌面通知，其余功能正常 |
| `widget-snapshot.json` 写入失败 | `OSError` 捕获，`log.debug` | 快照不更新，不影响主功能 |
| `update-desktop-database` 缺失 | 安装脚本跳过刷新 | 桌面菜单可能延迟出现，重新登录后正常 |
| GTK4 / Adw typelib 缺失 | `main.py` 的 `gi.require_version` 直接报错；`install.sh` 启动前检测并打印两套安装命令 | 安装阶段即阻止，不产生半安装状态 |
| 数据库损坏/不可打开 | 异常由启动阶段抛出并写入日志；不自动删除或重建 | 保护数据，需人工备份/修复 |
| 休眠/挂起恢复后时间大跳跃 | Tracker 丢弃该段并重新开始 | 不会把休眠时间误记为屏幕时间 |

**原则**：采集链路「永不因单次失败而崩溃」；持久化失败只丢当前段；UI 能力缺失（托盘/通知）优雅降级；涉及数据安全的操作（数据库打开失败）宁可失败也不静默重置。

---

## 7. 安装布局 / Installed layout

```text
<prefix>/                        默认 prefix = ~/.local 或 /usr/local
├── bin/timebook                 #!/bin/sh，设置 PYTHONPATH=<prefix>/lib 后 exec python3 -m timebook.main
├── lib/timebook/                # timebook 包（无 __pycache__）
├── share/applications/timebook.desktop
└── share/icons/hicolor/
    ├── scalable/apps/timebook.svg
    ├── 48x48/apps/timebook.png
    ├── 128x128/apps/timebook.png
    └── 256x256/apps/timebook.png
```

登录自启（可选）：`~/.config/autostart/timebook.desktop`，`Exec=timebook --hidden`，`X-GNOME-Autostart-enabled=true`。
数据与日志不随卸载删除：`~/.local/share/timebook/timebook.db`、`~/.local/state/timebook/timebook.log`。

---

## 8. 扩展点 / Extension points

- **新的窗口来源**：实现 `WindowSource` 协议（`active_window` / `idle_seconds` / `screensaver_active`），注入 `Tracker` 即可接 Wayland 或测试替身。
- **新的聚合维度**：在 `core/models.py` 增加纯函数，页面只消费结果；保持 `core` 无 GTK 依赖。
- **新的提醒**：扩展 `RemindersEngine` / `LimitsEngine`，通过 `on_notify` 接线，不改 UI。
- **新的快照读取方**：读取 `widget-snapshot.json` 即可，不需要链接任何库。
- **新语言**：在 `core/l10n.py` 扩展 `VALID_LANGUAGES`，并用 `T(zh, en)` 覆盖文案；当前仅 zh/en。
