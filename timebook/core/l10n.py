"""双语支持：中文为源语言，English 全量覆盖。

移植自 macOS 版 ``Sources/Shared/L10n.swift``。区别：Linux 版用进程内状态 +
环境变量判断系统语言（``LANG``/``LC_ALL``），而不是 UserDefaults + NSLocale。
"""

from __future__ import annotations

import os
import threading

VALID_LANGUAGES = ("auto", "zh", "en")

_lock = threading.Lock()
_language = "auto"
_detected: str | None = None


def system_language() -> str:
    """系统首选语言，仅区分 zh / en（缓存）。"""
    global _detected
    if _detected is None:
        raw = (
            os.environ.get("LC_ALL")
            or os.environ.get("LC_MESSAGES")
            or os.environ.get("LANGUAGE")
            or os.environ.get("LANG")
            or ""
        )
        _detected = "zh" if raw.lower().startswith("zh") else "en"
    return _detected


def set_system_language(lang: str | None) -> None:
    """测试/嵌入用：覆盖检测到的系统语言（``zh`` / ``en``）。"""
    global _detected
    with _lock:
        _detected = ("zh" if (lang or "").lower().startswith("zh") else "en")


def set_language(pref: str) -> None:
    """设置语言偏好：``auto`` | ``zh`` | ``en``（非法值退化为 auto）。"""
    global _language
    with _lock:
        _language = pref if pref in VALID_LANGUAGES else "auto"


def language_pref() -> str:
    with _lock:
        return _language


def resolved_language() -> str:
    pref = language_pref()
    return system_language() if pref == "auto" else pref


def T(zh: str, en: str) -> str:  # noqa: N802 - 与 Swift 版保持同名，方便逐行对照
    """返回当前语言下的文案。"""
    return zh if resolved_language() == "zh" else en


def reset_for_tests() -> None:
    """仅测试用：恢复默认语言状态。"""
    global _language, _detected
    with _lock:
        _language = "auto"
        _detected = None
