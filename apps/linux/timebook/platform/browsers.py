"""浏览器识别与域名推断。

macOS 版用 AppleScript 向浏览器要当前标签页 URL（需要「自动化」授权，拒绝则
退化为只记 App）。Linux 上没有统一等价物，这里改为**从窗口标题推断域名**：

* Windows/Linux 的浏览器标题形如 ``"视频标题 - YouTube - Google Chrome"``、
  ``"标题_哔哩哔哩_bilibili"``、``"GitHub · Where software is built"``；
* 先用 ``categories`` 里的已知域名表做子串匹配（覆盖中英文站点），
* 再用通用「域名形态」正则兜底（``xxx.yyy`` 且 TLD 2–24 位字母），
* 解析不出就返回 None → 只按 App 统计，与 macOS 的优雅降级一致。
"""

from __future__ import annotations

import re

from ..core.categories import ALL as ALL_CATEGORIES

#: 已知浏览器（WM_CLASS 小写形式，含常见拼写差异）。
BROWSER_IDS: set[str] = {
    "firefox",
    "firefox-esr",
    "firefoxdeveloperedition",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "brave",
    "microsoft-edge",
    "microsoft-edge-stable",
    "opera",
    "vivaldi",
    "vivaldi-stable",
    "epiphany",
    "org.gnome.epiphany",
    "falkon",
    "qutebrowser",
    "zen-browser",
    "librewolf",
}

#: 浏览器名字（WM_CLASS 缺失、只有标题时用）。
_BROWSER_NAMES = {
    "firefox", "chrome", "chromium", "brave", "edge", "opera", "vivaldi",
    "epiphany", "falkon", "qutebrowser", "librewolf", "zen",
}

#: 通用域名：允许国际化 TLD（纯字母，2–24 位）。排除文件扩展名等噪声。
_DOMAIN_RE = re.compile(
    r"(?<![\w@.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(?![\w-])",
    re.IGNORECASE,
)

#: 形如 ``foo.js`` / ``file.png`` 的假域名（扩展名白名单）。
_FAKE_TLDS = {
    "js", "ts", "jsx", "tsx", "py", "rb", "go", "rs", "java", "c", "h", "cpp", "hpp",
    "json", "yaml", "yml", "toml", "ini", "conf", "cfg", "log", "txt", "md", "csv",
    "png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "pdf", "zip", "tar", "gz",
    "mp3", "mp4", "mkv", "mov", "wav", "flac", "html", "css", "scss", "xml", "sh",
}

#: 过泛的子域/品牌名，不能单凭品牌名命中（否则 "email" 会命中 mail.google.com）。
_GENERIC_SUBDOMAINS = {
    "mail", "news", "docs", "music", "store", "play", "www", "web", "map", "maps",
    "drive", "meet", "chat", "support", "help", "blog", "shop", "open", "read",
}

#: 品牌别名 → host。用于两类情况：
#: * 品牌名太短（如 ``X``），按「≥4 字符」规则会被跳过；
#: * 标题里只写中文名（如「小红书」「哔哩哔哩」），与域名毫无字面重叠。
BRAND_ALIASES: dict[str, str] = {
    # 短品牌 / 易误判
    "x": "x.com",
    "推特": "x.com",
    "v2ex": "v2ex.com",
    # 中文站点名
    "小红书": "xiaohongshu.com",
    "哔哩哔哩": "bilibili.com",
    "b站": "bilibili.com",
    "知乎": "zhihu.com",
    "豆瓣": "douban.com",
    "微博": "weibo.com",
    "优酷": "youku.com",
    "爱奇艺": "iqiyi.com",
    "淘宝": "taobao.com",
    "天猫": "tmall.com",
    "京东": "jd.com",
    "拼多多": "pinduoduo.com",
    "抖音": "douyin.com",
    "网易云音乐": "music.163.com",
    "掘金": "juejin.cn",
    "思否": "segmentfault.com",
    "少数派": "sspai.com",
    "得到": "dedao.cn",
    "语雀": "yuque.com",
    "飞书": "feishu.cn",
    "钉钉": "dingtalk.com",
    "腾讯会议": "meeting.tencent.com",
    "百度": "baidu.com",
    "谷歌": "google.com",
    "油管": "youtube.com",
    "网飞": "netflix.com",
}

#: 已知域名 → 规范 host（长域名优先匹配，避免 ``mail.google.com`` 被 ``gmail.com`` 抢）。
_KNOWN_DOMAINS: list[str] = sorted(
    {domain for category in ALL_CATEGORIES for domain in category.domains},
    key=len,
    reverse=True,
)


def normalize_host(host: str) -> str:
    value = (host or "").strip().lower().rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value


def is_browser(app_id: str, app_name: str = "") -> bool:
    """是否为浏览器（优先 WM_CLASS，退化到应用名/标题里的浏览器名）。"""
    ident = normalize_host(app_id).replace("_", "-")
    if ident in BROWSER_IDS:
        return True
    if any(browser in ident for browser in BROWSER_IDS):
        return True
    name = (app_name or "").strip().lower()
    return any(token in name for token in _BROWSER_NAMES)


def host_from_title(title: str) -> str | None:
    """从窗口标题里推断域名；解析不出返回 None。"""
    if not title:
        return None
    lowered = title.lower()

    # 0) 品牌别名优先（中文名/超短品牌，与域名无字面重叠）
    for alias, domain in BRAND_ALIASES.items():
        if alias.isascii():
            # 纯英文别名必须按词边界匹配，否则 "x" 会命中 "example"
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered):
                return normalize_host(domain)
        elif alias in lowered:
            # 中文别名没有词边界概念，直接用子串
            return normalize_host(domain)

    # 1) 已知站点优先（能正确处理 "哔哩哔哩" 这类只有中文名的标题）
    for domain in _KNOWN_DOMAINS:
        if domain in lowered:
            return normalize_host(domain)
        # 标题里可能只写了品牌名，例如 "YouTube" / "GitHub" / "哔哩哔哩_bilibili"
        brand = domain.split(".")[0]
        if len(brand) >= 4 and brand not in _GENERIC_SUBDOMAINS:
            if re.search(rf"(?<![a-z0-9-]){re.escape(brand)}(?![a-z0-9-])", lowered):
                return normalize_host(domain)

    # 2) 通用域名形态兜底
    for match in _DOMAIN_RE.finditer(title):
        candidate = normalize_host(match.group(1))
        tld = candidate.rsplit(".", 1)[-1].lower()
        if tld in _FAKE_TLDS or len(candidate) > 253:
            continue
        if "." not in candidate:
            continue
        return candidate
    return None


def detail_from_title(title: str | None, app_id: str = "") -> tuple[str | None, str | None]:
    """返回 (host, title)；非浏览器或解析不出 host 时 host 为 None。"""
    if not title:
        return None, None
    if not is_browser(app_id, title):
        return None, title
    return host_from_title(title), title


def browser_label(app_id: str, app_name: str = "") -> str:
    """浏览器显示名（用于「按应用」统计里更友好的名字）。"""
    return app_name or app_id
