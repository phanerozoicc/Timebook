"""双语支持：中文为源语言，English 全量覆盖。

移植自 macOS 版 ``Sources/Shared/L10n.swift``。区别：Linux 版用进程内状态 +
环境变量判断系统语言（``LANG``/``LC_ALL``），而不是 UserDefaults + NSLocale。

应用自身的文案全部走 ``T()``；GTK/libadwaita 内置控件文案（DropDown 弹层搜索
占位、空态占位、Entry 清除按钮提示等）由 GTK 的 gettext 按进程消息 locale
翻译，因此在语言变化时同步 ``LC_MESSAGES``/``LANGUAGE``，让内置文案与应用
语言保持一致（应用语言 ≠ 系统语言时避免中英混排）。
"""

from __future__ import annotations

import locale
import os
import threading

VALID_LANGUAGES = ("auto", "zh", "en")

_lock = threading.Lock()
_language = "auto"
_detected: str | None = None
_process_lang: str | None = None

# 进程初始语言环境快照：系统语言检测永远读快照，运行时切换进程 locale
# 不会反过来污染检测结果。
_BOOT_ENV = {
    name: os.environ.get(name)
    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")
}


def system_language() -> str:
    """系统首选语言，仅区分 zh / en（缓存）。"""
    global _detected
    if _detected is None:
        raw = (
            _BOOT_ENV["LC_ALL"]
            or _BOOT_ENV["LC_MESSAGES"]
            or _BOOT_ENV["LANGUAGE"]
            or _BOOT_ENV["LANG"]
            or ""
        )
        _detected = "zh" if raw.lower().startswith("zh") else "en"
    return _detected


def set_system_language(lang: str | None) -> None:
    """测试/嵌入用：覆盖检测到的系统语言（``zh`` / ``en``）。"""
    global _detected
    with _lock:
        _detected = ("zh" if (lang or "").lower().startswith("zh") else "en")
    _apply_process_locale()


def set_language(pref: str) -> None:
    """设置语言偏好：``auto`` | ``zh`` | ``en``（非法值退化为 auto）。"""
    global _language
    with _lock:
        _language = pref if pref in VALID_LANGUAGES else "auto"
    _apply_process_locale()


def language_pref() -> str:
    with _lock:
        return _language


def resolved_language() -> str:
    pref = language_pref()
    return system_language() if pref == "auto" else pref


def _apply_process_locale() -> None:
    """同步进程消息 locale 到应用语言，GTK 内置文案随之切换。

    新建控件在构造时由 GTK 按当前 locale 取内置文案；已存在控件的内置串
    由界面层的 stock 重翻处理（``ui/widgets.py``）。找不到目标 locale 时
    退回 ``C.UTF-8``（gettext 原文即英文；zh 仅在装了对应 mo 文件时生效）。
    """
    global _process_lang
    lang = resolved_language()
    if lang == _process_lang:
        return
    if lang == "en":
        candidates = (("en_US.UTF-8", "en_US:en"), ("C.UTF-8", "en_US:en"))
    else:
        candidates = (("zh_CN.UTF-8", "zh_CN:zh"), ("C.UTF-8", "zh_CN:zh"))
    for loc, env in candidates:
        try:
            locale.setlocale(locale.LC_MESSAGES, loc)
        except locale.Error:
            continue
        os.environ["LANGUAGE"] = env
        break
    _process_lang = lang


def T(zh: str, en: str) -> str:  # noqa: N802 - 与 Swift 版保持同名，方便逐行对照
    """返回当前语言下的文案。"""
    return zh if resolved_language() == "zh" else en


def reset_for_tests() -> None:
    """仅测试用：恢复默认语言状态。"""
    global _language, _detected, _process_lang
    with _lock:
        _language = "auto"
        _detected = None
    _process_lang = None
    _apply_process_locale()


_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_label(month: int) -> str:
    return T(f"{month}月", _MONTHS_EN[month - 1])


def date_label(day) -> str:
    """Use the app language, independently of the process C locale."""
    return T(f"{day.year}年{day.month}月{day.day}日", f"{_MONTHS_EN[day.month - 1]} {day.day}, {day.year}")


def count_label(count: int, unit: str) -> str:
    zh, singular, plural = {
        "day": ("天", "day", "days"),
        "hour": ("小时", "hour", "hours"),
        "minute": ("分钟", "minute", "minutes"),
    }[unit]
    return T(f"{count} {zh}", f"{count} {singular if count == 1 else plural}")
