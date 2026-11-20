# 时账 Timebook（Linux 版）

> **纯本地的屏幕时间统计 + 番茄钟**：记录你在哪个应用/网站上花了多久，判断大脑疲劳等级，顺手提醒你休息、喝水和专注。零联网、零账号，数据只留在这台电脑上。
>
> **English TL;DR** — Timebook is a local-first screen-time tracker and pomodoro timer for Linux, rewritten natively with GTK4 + libadwaita + Python. No network, no account, no telemetry. All data lives in a single SQLite file under `~/.local/share/timebook/`.

本项目是 macOS 应用 **Timebook** 的 Linux 原生重写。原项目（SwiftUI / SwiftData / AppKit）：
**<https://github.com/phanerozoicc/Timebook>**

---

## 功能一览 / Features

| 功能 | 说明 |
|---|---|
| **屏幕时间** | 每 2 秒采样前台窗口，按「应用 + 站点」切段落库；空闲、锁屏、暂停、排除应用都不计时，所以「没有记录 == 不在用电脑」。 |
| **番茄钟** | 默认经典 40/5、冲刺 15/3、深度 50/10、自定义 30/5 四组预设；支持暂停/继续、跳过、自动开始休息/下一轮，以及 20 秒全屏微休息遮罩。 |
| **疲劳等级** | 按今日累计屏幕时间分 L1–L10 十级（清醒 → 躺平），每级有独立配色与提示文案，并显示距下一级还差多久。 |
| **统计与热力图** | 最近 7/30 天切换：区间合计、活跃天日均、活跃天数、每日趋势柱状图、分类环形图、最近 12 周 7 档热力图。 |
| **时间线** | 当日分段列表：起止时间、时长、应用、窗口标题（可选采集）、域名标签（按分类着色）。 |
| **丢小时（Forfeit）** | 一天 24 格；分心应用/类目/自定义域名被切到前台，该小时整格记「荒」。可点格子手动改判，附最近 14 天柱状图与连续干净天数。 |
| **限额与提醒** | 每日限额 80% / 90% / 100% 三档提醒（每天各一次）；分心网站连续 10 分钟温和提醒（30 分钟冷却）；定时休息提醒。限额是 **warn 语义**，不强制屏蔽。 |
| **喝水** | 默认每日 8 杯目标，9:00–22:00 每 60 分钟提醒；专注页/托盘可快捷 +1 杯。 |
| **双语** | 跟随系统语言（`LANG` / `LC_ALL`）或手动选择「自动 / 中文 / English」；番茄阶段、通知、导出周报、导航等关键文案已双语。 |
| **导出** | 一键导出当日 CSV 明细 + Markdown 周报到下载目录（默认 `~/Downloads`，遵循 XDG）；CSV 带 UTF-8 BOM，Excel 双击不乱码。 |
| **托盘** | StatusNotifierItem（D-Bus）：实时显示今日时长/番茄倒计时/暂停标记，菜单可打开窗口、开始/暂停/继续番茄钟、暂停记录、+1 杯水、退出；没有 AppIndicator 时自动降级为纯窗口模式。 |

---

## Linux 移植说明 / Porting notes

### 为什么是 GTK4 + libadwaita + Python？

原版是 SwiftUI + SwiftData + AppKit 的 macOS 应用，Linux 上没有可直接复用的 UI 层。这个重写选择：

- **GTK4 + libadwaita**：GNOME 原生外观与交互，自动跟随系统深浅色、高 DPI 与无障碍设置；`Adw.ApplicationWindow` / `Adw.PreferencesPage` 与 macOS 版的信息层级一一对应。
- **Python + PyGObject**：只用标准库（`sqlite3`、`ctypes`、`argparse`、`logging`）和系统 PyGObject，**零 pip 第三方依赖**，打包就是一个目录 + 一个启动器。
- **纯本地**：不引入任何 WebView、账号、云同步或分析 SDK；数据库是单文件 SQLite，拷贝即备份。
- **绘图用 cairo + Pango**：环、柱状图、热力图使用 cairo；24 小时格使用可键盘操作的 GTK 按钮，中文字体走系统字体回退。

### 能力对应关系

| macOS 原版 | Linux 版实现 | 主要代码 |
|---|---|---|
| `NSWorkspace.frontmostApplication` | X11 `_NET_ACTIVE_WINDOW`；用 `_NET_WM_PID` / `WM_CLASS` / `_NET_WM_NAME` 取进程、应用与标题 | [`platform/x11.py`](timebook/platform/x11.py)、[`platform/tracker.py`](timebook/platform/tracker.py) |
| `CGEventSource` 空闲秒数 | `XScreenSaverQueryInfo`（libXss）：空闲秒数 + 熄屏/锁屏状态位 | [`platform/x11.py`](timebook/platform/x11.py) |
| AppleScript 读取浏览器当前 URL | 从窗口标题推断域名：先匹配内置站点表，再用通用域名正则兜底，失败则只按应用统计 | [`platform/browsers.py`](timebook/platform/browsers.py) |
| SwiftData 持久化 | 单文件 SQLite（WAL 模式）：`usage_events` / `focus_events` / `water_logs` / `forfeit_days` / `kv` | [`core/store.py`](timebook/core/store.py) |
| `MenuBarExtra` 菜单栏常驻 | StatusNotifierItem（D-Bus） 托盘（标签 + 菜单）；不可用时优雅降级 | [`ui/tray.py`](timebook/ui/tray.py) |
| WidgetKit 小组件 | 每约 60 秒写 `widget-snapshot.json`（今日秒数、疲劳等级、番茄阶段/剩余、当前应用、生成时间），供第三方小组件或脚本读取 | [`app.py`](timebook/app.py) `_write_snapshot` |
| SwiftUI 视图 + `@AppStorage` | GTK4 控件 + libadwaita + SQLite `kv` 设置表（键名与原版保持一致，便于迁移） | [`ui/`](timebook/ui/)、[`core/settings.py`](timebook/core/settings.py) |
| `NSPanel` 全屏微休息遮罩 | 无边框全屏 `Gtk.Window`（20 秒倒计时环，可跳过） | [`ui/overlay.py`](timebook/ui/overlay.py) |

---

## 安装 / Installation

### 1. 系统依赖

Debian / Ubuntu：

```bash
sudo apt update
sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
# 可选：托盘、空闲检测、桌面通知、中文字体
sudo apt install -y python3-dbus libxss1 x11-utils libnotify-bin fonts-noto-cjk
```

Fedora / RHEL 系：

```bash
sudo dnf install -y python3 python3-gobject gtk4 libadwaita
# 可选
sudo dnf install -y python3-dbus libXScrnSaver xorg-x11-utils libnotify google-noto-sans-cjk-fonts
```

Python 要求 ≥ 3.10（本项目在 Python 3.12 上开发与验证）。

### 2. 一键安装到用户目录（推荐）

```bash
./install.sh              # 安装到 ~/.local
./install.sh --autostart  # 同时安装登录自启
timebook                  # 运行
```

安装脚本会：复制包到 `~/.local/lib/timebook/`，生成 `~/.local/bin/timebook` 启动器，安装桌面入口、四种尺寸图标，并在存在 `update-desktop-database` 时刷新桌面数据库。完整选项：

```bash
./install.sh --help
sudo ./install.sh --prefix /usr/local   # 系统级安装
./install.sh --uninstall             # 卸载程序文件，保留数据库与日志
```

### 3. 不安装，直接从仓库运行

```bash
python3 -m timebook.main
python3 -m timebook.main --page stats
```

在仓库根目录直接运行即可；`timebook/` 是普通 Python 包，没有构建步骤。

---

## 使用 / Usage

主窗口是「侧边栏导航 + 顶栏 + 页面栈」：

- **今日**：今日屏幕时间大数字、疲劳等级、分类/网站/应用占比。
- **专注**：番茄环、轮次圆点、开始/暂停/跳过、预设、自动开始开关、今日番茄与喝水统计、分心记录。
- **统计**：7/30 天汇总、每日趋势、分类环形图、12 周热力图。
- **时间线**：今天每一段的使用明细。
- **丢小时**：24 格「荒/守」视图与分心规则。

**快捷键**：`Ctrl+1` 今日 · `Ctrl+2` 专注 · `Ctrl+3` 统计 · `Ctrl+4` 时间线 · `Ctrl+5` 丢小时。

**暂停**：顶栏「暂停记录」按钮（或托盘菜单）立即停止采集，当前段会结账；暂停期间不产生任何数据。

**托盘**：标签位显示今日时长（番茄运行时显示倒计时），菜单可打开窗口、开始/暂停/继续番茄钟、暂停记录、+1 杯水、退出。托盘可用时关闭窗口会隐藏并继续采集；托盘不可用时关闭窗口会退出。

**导出**：顶栏保存按钮 → 当日 `timebook-detail-<时间戳>.csv` + `timebook-weekly-<时间戳>.md`，默认写入 `~/Downloads`（若系统设置了 XDG 下载目录则以它为准），并可直接打开所在文件夹。

**命令行**（可选）：

```bash
timebook --page focus              # 启动后直接打开专注页
timebook --db /tmp/demo.db         # 使用指定数据库（演示/测试）
timebook --version                 # 版本号
```

想快速看界面效果，可以生成一份演示数据：

```bash
python3 scripts/demo_seed.py --db /tmp/timebook-demo.db --days 14
python3 -m timebook.main --db /tmp/timebook-demo.db
```

---

## 数据与隐私 / Data & privacy

**零联网声明**：程序运行期间不发起任何网络请求，不含遥测、账号、云同步或广告 SDK。唯一的对外进程调用是本机通知（`notify-send`）与打开文件夹（`xdg-open`）。

| 内容 | 默认位置 |
|---|---|
| 数据库（全部使用记录、番茄、喝水、丢小时、设置） | `~/.local/share/timebook/timebook.db` |
| 运行日志（滚动，1 MB × 3） | `~/.local/state/timebook/timebook.log` |
| 小组件快照 | `~/.local/share/timebook/widget-snapshot.json` |
| 导出文件 | `~/Downloads`（遵循 XDG 下载目录） |
| 登录自启（可选） | `~/.config/autostart/timebook.desktop` |

- 路径遵循 `XDG_DATA_HOME` / `XDG_STATE_HOME`；可用 `TIMEBOOK_DB` 环境变量或 `--db` 覆盖数据库位置。
- **窗口标题采集默认关闭**（设置 → 记录）；开启后标题只写入本机数据库，用于时间线回看。
- 浏览器域名由窗口标题推断，不读取浏览历史、不连接浏览器调试端口。
- 删除数据库文件即可彻底清空数据；`./install.sh --uninstall` 只删除程序文件，不动数据与日志。

---

## 已知限制 / Known limitations

1. **Wayland 采集受限**：X11 接口只能看到 XWayland 窗口，原生 Wayland 应用无法被枚举。需要完整采集时请使用 X11 会话，或在 Wayland 下让程序走 XWayland：`GDK_BACKEND=x11 timebook`。此时空闲/锁屏检测依赖 `libXss` 与 XWayland 的行为，可能不如原生 X11 精确。
2. **GNOME 托盘需要扩展**：GNOME Shell 默认不显示 AppIndicator，请安装并启用 `gnome-shell-extension-appindicator`（Fedora 包名 `gnome-shell-extension-appindicator`，Debian 包名 `gnome-shell-extension-appindicator`）。没有扩展时程序自动降级为纯窗口模式（关闭窗口会正常退出），其余功能不受影响。
3. **域名推断不如 AppleScript 精确**：无法读取真实 URL，只能从窗口标题匹配内置站点表或域名形态；标题不含域名时该段只按应用统计。
4. **限额是提醒而非强制**：Linux 桌面没有系统级「应用限额」授权，Timebook 只发通知，不阻止你继续使用。
5. 托盘/通知/图标主题由桌面环境决定；少数精简桌面可能没有通知守护进程或 AppIndicator。
6. 语言覆盖：导航、页面标题、番茄阶段、通知与 Markdown 周报已双语；五个页面正文标签与设置窗口目前仍为中文硬编码，新增文案建议统一走 `core.l10n.T()`。

---

## 开发与测试 / Development

```bash
# 语法编译检查
python3 -m compileall -q timebook

# 全套 unittest（无 GTK/显示器时会跳过 UI 测试）
python3 -m unittest discover -s tests -v

# 完整验收：要求 GTK 和显示器，不能用跳过 UI 测试来通过
python3 scripts/check.py

# 完整验收并截图：X11 + ImageMagick import
python3 scripts/check.py --screenshots /tmp/timebook-ui

# 直接跑（不安装）
python3 -m timebook.main

# 生成演示数据
python3 scripts/demo_seed.py --db /tmp/timebook-demo.db --days 14
```

测试覆盖与验收记录见 [测试说明](docs/testing.md)。新增测试使用内存/临时数据库，不读取个人使用记录。

设计说明见 [UI 规范（Linux）](docs/ui-spec-linux.md) 与 [架构文档](docs/architecture.md)；安装与桌面集成见 [`install.sh`](install.sh)、[`packaging/`](packaging/)。

### 目录结构

```text
timebook/
├── README.md
├── install.sh                     # 安装/卸载脚本
├── pyproject.toml
├── assets/
│   ├── timebook.svg               # 品牌图标（512 视图）
│   ├── timebook-48.png
│   ├── timebook-128.png
│   └── timebook-256.png
├── packaging/
│   ├── timebook.desktop           # 桌面入口
│   └── timebook-autostart.desktop # 登录自启
├── docs/
│   ├── ui-spec-linux.md
│   └── architecture.md
├── scripts/
│   └── demo_seed.py               # 演示数据生成
├── tests/                         # unittest 用例
└── timebook/
    ├── main.py                    # CLI 入口
    ├── app.py                     # Adw.Application：装配上下文、定时器、托盘、快照
    ├── context.py                 # AppContext（store/settings/引擎/tracker）
    ├── core/                      # 纯逻辑：无 GTK 依赖，可单测
    │   ├── models.py              # EventRow / 聚合 / 时长格式化
    │   ├── store.py               # SQLite 存储（WAL）
    │   ├── settings.py            # 类型化设置（kv）
    │   ├── categories.py          # 9 类站点域名表
    │   ├── brain_level.py         # L1–L10 疲劳等级
    │   ├── heatmap.py             # 12 周热力图分桶
    │   ├── pomodoro.py            # 番茄状态机
    │   ├── wellbeing.py           # 限额 / 休息 / 喝水提醒
    │   ├── forfeit.py             # 丢小时账本
    │   ├── exporter.py            # CSV + Markdown 周报
    │   ├── l10n.py                # 中英双语
    │   └── applog.py              # 日志与异常钩子
    ├── platform/                  # Linux 系统能力
    │   ├── x11.py                 # ctypes 直连 libX11 / libXss
    │   ├── tracker.py             # 2 秒采样 → 分段落库
    │   ├── browsers.py            # 浏览器识别 + 标题域名推断
    │   └── notify.py              # 桌面通知（notify-send / GNotification）
    └── ui/                        # GTK4 + libadwaita
        ├── theme.py               # 设计 token + CSS
        ├── widgets.py             # 卡片/环/柱状/热力图等
        ├── main_window.py         # 侧边栏 + 顶栏 + 页面栈 + Ctrl+1..5
        ├── settings_window.py     # 设置
        ├── export_dialog.py       # 导出到下载目录
        ├── overlay.py             # 20 秒微休息遮罩
        ├── tray.py                # AppIndicator 托盘
        ├── introspect.py          # 界面自省（自动化验证）
        └── pages/
            ├── today.py
            ├── focus.py
            ├── stats.py
            ├── timeline.py
            └── forfeit.py
```

---

*Timebook Linux port — 本地优先，专注当下。 / Local-first, focus on now.*
