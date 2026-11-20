#!/usr/bin/env bash
#
# 时账 Timebook —— Linux 安装脚本
#   ./install.sh                 # 安装到 ~/.local（默认）
#   ./install.sh --autostart     # 同时安装登录自启
#   sudo ./install.sh --prefix /usr/local
#   ./install.sh --uninstall
#
# 只复制程序文件，不联网、不写系统配置；数据始终留在用户目录。
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX="${HOME}/.local"
DO_UNINSTALL=0
DO_AUTOSTART=0

usage() {
    cat <<'USAGE'
用法: ./install.sh [选项]

选项:
  --user                安装到 ~/.local（默认）
  --prefix DIR          安装到 DIR（例如 /usr/local）
  --autostart           同时安装登录自启（~/.config/autostart/timebook.desktop）
  --uninstall           卸载程序文件（保留数据库与日志）
  -h, --help            显示本帮助

示例:
  ./install.sh
  ./install.sh --autostart
  sudo ./install.sh --prefix /usr/local
  ./install.sh --uninstall
USAGE
}

die() {
    printf '错误: %s\n' "$*" >&2
    exit 1
}

expand_path() {
    case "$1" in
        "~")     printf '%s\n' "$HOME" ;;
        "~/"*)   printf '%s\n' "$HOME/${1#\~/}" ;;
        *)       printf '%s\n' "$1" ;;
    esac
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --user)
            PREFIX="${HOME}/.local"
            shift
            ;;
        --prefix)
            [ "$#" -ge 2 ] || die "--prefix 需要一个目录参数"
            PREFIX="$2"
            shift 2
            ;;
        --prefix=*)
            PREFIX="${1#*=}"
            shift
            ;;
        --autostart)
            DO_AUTOSTART=1
            shift
            ;;
        --uninstall)
            DO_UNINSTALL=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "未知参数: $1（用 --help 查看用法）"
            ;;
    esac
done

[ -n "$PREFIX" ] || die "安装前缀不能为空"
PREFIX=$(expand_path "$PREFIX")
case "$PREFIX" in
    /*) ;;
    *) PREFIX="${PWD}/${PREFIX}" ;;
esac
# 去掉末尾斜杠，但保留根目录的判断
while [ "${#PREFIX}" -gt 1 ] && [ "${PREFIX%/}" != "$PREFIX" ]; do
    PREFIX="${PREFIX%/}"
done
[ "$PREFIX" != "/" ] || die "拒绝安装到根目录 /"

LIB_ROOT="${PREFIX}/lib"
PKG_DIR="${LIB_ROOT}/timebook"
BIN_DIR="${PREFIX}/bin"
LAUNCHER="${BIN_DIR}/timebook"
APPS_DIR="${PREFIX}/share/applications"
DESKTOP_FILE="${APPS_DIR}/timebook.desktop"
ICON_ROOT="${PREFIX}/share/icons/hicolor"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart"
AUTOSTART_FILE="${AUTOSTART_DIR}/timebook.desktop"
DATA_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/timebook"
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/timebook"

refresh_desktop_database() {
    if command -v update-desktop-database >/dev/null 2>&1 && [ -d "$APPS_DIR" ]; then
        update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
    fi
}

check_dependencies() {
    local missing=()
    echo "==> 检查系统依赖"

    if ! command -v python3 >/dev/null 2>&1; then
        missing+=("python3（Python 3 解释器）")
    else
        echo "    ✓ python3: $(python3 --version 2>&1)"
    fi

    if command -v python3 >/dev/null 2>&1; then
        if python3 -c 'import gi' >/dev/null 2>&1; then
            echo "    ✓ python3-gi / PyGObject"
        else
            missing+=("python3-gi（PyGObject 绑定）")
        fi
        if python3 -c 'import gi; gi.require_foreign("cairo")' >/dev/null 2>&1; then
            echo "    ✓ python3-gi-cairo / cairo 桥接"
        else
            missing+=("python3-gi-cairo（PyGObject 的 cairo 结构转换器，图表绘制必需）")
        fi
        if python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
            echo "    ✓ gir1.2-gtk-4.0 / GTK 4 typelib"
        else
            missing+=("gir1.2-gtk-4.0（GTK 4 typelib）")
        fi
        if python3 -c 'import gi; gi.require_version("Adw", "1"); from gi.repository import Adw' >/dev/null 2>&1; then
            echo "    ✓ gir1.2-adw-1 / libadwaita typelib"
        else
            missing+=("gir1.2-adw-1（libadwaita typelib）")
        fi
    fi

    if [ "${#missing[@]}" -gt 0 ]; then
        printf '\n缺少以下依赖：\n' >&2
        local item
        for item in "${missing[@]}"; do
            printf '  - %s\n' "$item" >&2
        done
        cat >&2 <<'HELP'

请按发行版安装（Debian / Ubuntu）:
  sudo apt update
  sudo apt install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 python3-dbus libxss1 x11-utils libnotify-bin

Fedora / RHEL 系:
  sudo dnf install -y python3 python3-gobject gtk4 libadwaita

可选增强（托盘 / 空闲检测 / 通知 / 中文字体）:
  Debian: sudo apt install -y python3-dbus libxss1 x11-utils libnotify-bin fonts-noto-cjk
  Fedora: sudo dnf install -y python3-dbus libXScrnSaver xorg-x11-utils libnotify google-noto-sans-cjk-fonts
HELP
        exit 1
    fi
    echo "    ✓ 依赖齐全"
}

do_uninstall() {
    echo "==> 卸载时账 Timebook"
    echo "    安装前缀: $PREFIX"

    rm -f "$LAUNCHER"
    rm -f "$DESKTOP_FILE"
    rm -f "$ICON_ROOT/scalable/apps/timebook.svg"
    local size
    for size in 48 128 256; do
        rm -f "${ICON_ROOT}/${size}x${size}/apps/timebook.png"
    done
    rm -f "$AUTOSTART_FILE"
    rm -rf "$PKG_DIR"

    refresh_desktop_database

    echo "==> 卸载完成"
    echo "    已删除：$PKG_DIR、$LAUNCHER、桌面入口、图标、自启文件"
    echo "    已保留数据：$DATA_DIR/timebook.db"
    echo "    已保留日志：$STATE_DIR/timebook.log"
}

do_install() {
    echo "==> 时账 Timebook 安装程序"
    echo "    源码目录: $SCRIPT_DIR"
    echo "    安装前缀: $PREFIX"

    [ -f "$SCRIPT_DIR/timebook/main.py" ] || die "找不到 timebook/main.py，请在仓库根目录运行本脚本"
    [ -f "$SCRIPT_DIR/packaging/timebook.desktop" ] || die "找不到 packaging/timebook.desktop"
    [ -f "$SCRIPT_DIR/assets/timebook.svg" ] || die "找不到 assets/timebook.svg"

    check_dependencies

    echo "==> 复制程序文件 → ${PKG_DIR}/"
    mkdir -p "$LIB_ROOT"
    rm -rf "$PKG_DIR"
    cp -a "$SCRIPT_DIR/timebook" "$PKG_DIR"
    find "$PKG_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
    find "$PKG_DIR" -type f -name '*.pyc' -delete

    echo "==> 生成启动器 → ${LAUNCHER}"
    mkdir -p "$BIN_DIR"
    {
        printf '%s\n' '#!/bin/sh'
        printf '%s\n' '# Generated by Timebook install.sh — do not edit.'
        printf 'export PYTHONPATH="%s/lib${PYTHONPATH:+:$PYTHONPATH}"\n' "$PREFIX"
        printf '%s\n' 'exec python3 -m timebook.main "$@"'
    } > "$LAUNCHER"
    chmod 0755 "$LAUNCHER"

    echo "==> 安装桌面入口 → ${DESKTOP_FILE}"
    command install -Dm644 "$SCRIPT_DIR/packaging/timebook.desktop" "$DESKTOP_FILE"

    echo "==> 安装图标 → ${ICON_ROOT}/"
    command install -Dm644 "$SCRIPT_DIR/assets/timebook.svg" "${ICON_ROOT}/scalable/apps/timebook.svg"
    local size src
    for size in 48 128 256; do
        src="$SCRIPT_DIR/assets/timebook-${size}.png"
        [ -f "$src" ] || die "缺少图标文件: $src"
        command install -Dm644 "$src" "${ICON_ROOT}/${size}x${size}/apps/timebook.png"
    done

    if [ "$DO_AUTOSTART" -eq 1 ]; then
        echo "==> 安装登录自启 → ${AUTOSTART_FILE}"
        command install -Dm644 "$SCRIPT_DIR/packaging/timebook-autostart.desktop" "$AUTOSTART_FILE"
    fi

    refresh_desktop_database

    echo
    echo "安装完成，运行 \`timebook\` 启动。"
    echo "  程序目录: $PKG_DIR"
    echo "  启动器:   $LAUNCHER"
    echo "  桌面入口: $DESKTOP_FILE"
    echo "  图标目录: $ICON_ROOT"
    if [ "$DO_AUTOSTART" -eq 1 ]; then
        echo "  登录自启: $AUTOSTART_FILE"
    else
        echo "  登录自启: 未安装（可加 --autostart 重新运行）"
    fi
    echo "  数据位置: $DATA_DIR/timebook.db（卸载不会删除）"
    echo "  日志位置: $STATE_DIR/timebook.log"

    case ":${PATH}:" in
        *":${BIN_DIR}:"*) ;;
        *)
            echo
            echo "提示: ${BIN_DIR} 不在 PATH 中，请把下面一行加入 ~/.profile 或 ~/.bashrc："
            echo "  export PATH=\"${BIN_DIR}:\$PATH\""
            ;;
    esac
}

if [ "$DO_UNINSTALL" -eq 1 ]; then
    do_uninstall
else
    do_install
fi
