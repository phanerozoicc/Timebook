# 时账 Timebook

> **纯本地的屏幕时间统计 + 番茄钟**：记录你在哪个应用/网站上花了多久，判断大脑疲劳等级，顺手提醒你休息、喝水和专注。零联网、零账号，数据只留在这台电脑上。
>
> **English TL;DR** — Timebook is a local-first screen-time tracker and pomodoro timer. No network, no account, no telemetry. All data stays on your machine (a single local database).

一个仓库维护两个原生平台实现，共享同一套产品设计与数据语义：

| 平台 | 目录 | 技术栈 | 状态 |
|---|---|---|---|
| **macOS** | [`apps/macos/`](apps/macos/) | SwiftUI + SwiftData + AppKit（XcodeGen 工程） | 原版，v4 |
| **Linux** | [`apps/linux/`](apps/linux/) | GTK4 + libadwaita + Python（PyGObject） | 原生重写，功能对齐 |

两者刻意**不共享代码**，而是共享行为：五个页面（今日 / 专注 / 统计 / 时间线 / 丢小时）、番茄钟状态机、疲劳等级 L1–L10、Forfeit 判定规则在两侧一一对应；Linux 版的模块注释里标注了对应的 macOS 源文件（如 `core/pomodoro.py ↔ Sources/Pomodoro.swift`），修 bug 或加功能时两侧同步改。

---

## 快速开始 / Quick start

### macOS

```bash
cd apps/macos
brew install xcodegen
xcodegen generate          # 生成 Timebook.xcodeproj（工程不入库，source of truth 是 project.yml）
open Timebook.xcodeproj    # Xcode 里 Cmd+R 运行，Cmd+U 跑测试
```

要求 macOS 15+，Xcode 16+。详见 [`apps/macos/README.md`](apps/macos/README.md)。

### Linux

```bash
cd apps/linux
sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
                    python3-dbus libxss1 x11-utils libnotify-bin
./run.sh                   # 直接运行
./install.sh               # 或安装到 ~/.local（桌面入口 + 图标 + 命令行启动器）
```

零 pip 依赖，只需系统包；数据在 `~/.local/share/timebook/timebook.db`，卸载不删。详见 [`apps/linux/README.md`](apps/linux/README.md)。

## 测试 / Tests

- **Linux**：`cd apps/linux && python3 scripts/check.py`（编译检查 + 脚本语法 + 177 项单元/GTK 交互测试；CI 中用 `xvfb-run` 提供显示）
- **macOS**：`cd apps/macos && xcodegen generate && xcodebuild -scheme Timebook test`

两侧都有 GitHub Actions（`.github/workflows/`）：push / PR 时各自平台跑构建与测试。

## 仓库结构 / Layout

```
.
├── apps/
│   ├── macos/          # SwiftUI 版（Sources/ Tests/ Widget/ project.yml …）
│   └── linux/          # GTK4 版（timebook/ tests/ install.sh run.sh …）
├── docs/               # → 各平台文档在各自目录内（apps/*/docs/）
└── .github/workflows/  # macos.yml / linux.yml
```

## 维护约定 / Conventions

- **单主线开发**：日常都在 `main` 上提交；平台专属的大改动先在各自目录内完成，不长期分叉，避免两套主分支漂移。
- **对齐即文档**：跨平台的对应关系写在代码注释与 [`apps/linux/docs/architecture.md`](apps/linux/docs/architecture.md) 里，改动一侧时检查另一侧是否需要同步。
- **发布**：打 `v*` tag 触发 `.github/workflows/release.yml`，自动构建双端安装包（macOS `.app` zip + Linux tar.gz）并附到同一个 GitHub Release。
