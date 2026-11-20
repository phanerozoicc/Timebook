"""网站分类：9 类与域名映射，按后缀匹配。

移植自 ``Sources/Shared/Categories.swift``，域名表保持一致。
Linux 版补充了把「宿主名」从浏览器窗口标题里提取出来的辅助函数所需的数据。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SiteCategory:
    id: str
    name_zh: str
    name_en: str
    hex_color: int
    distracting: bool
    domains: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """当前语言下的分类名（延迟解析，切换语言后自动生效）。"""
        from .l10n import T

        return T(self.name_zh, self.name_en)

    @property
    def color_hex(self) -> str:
        return f"#{self.hex_color:06X}"


ALL: tuple[SiteCategory, ...] = (
    SiteCategory(
        id="social",
        name_zh="社交",
        name_en="Social",
        hex_color=0xE1306C,
        distracting=True,
        domains=(
            "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
            "reddit.com", "linkedin.com", "weibo.com", "threads.net", "pinterest.com",
            "discord.com", "telegram.org", "mastodon.social", "bsky.app", "zhihu.com",
            "douban.com", "xiaohongshu.com", "v2ex.com",
        ),
    ),
    SiteCategory(
        id="video",
        name_zh="视频",
        name_en="Video",
        hex_color=0xFF0000,
        distracting=True,
        domains=(
            "youtube.com", "netflix.com", "bilibili.com", "twitch.tv", "douyin.com",
            "iqiyi.com", "youku.com", "vimeo.com", "disneyplus.com", "primevideo.com",
            "hbomax.com", "huya.com", "douyu.com",
        ),
    ),
    SiteCategory(
        id="news",
        name_zh="资讯",
        name_en="News",
        hex_color=0xF59E0B,
        distracting=False,
        domains=(
            "news.qq.com", "news.sina.com.cn", "cnn.com", "bbc.com", "bbc.co.uk",
            "nytimes.com", "thepaper.cn", "reuters.com", "36kr.com", "news.ycombinator.com",
            "theguardian.com", "wsj.com", "ft.com",
        ),
    ),
    SiteCategory(
        id="shopping",
        name_zh="购物",
        name_en="Shopping",
        hex_color=0x10B981,
        distracting=True,
        domains=(
            "taobao.com", "jd.com", "tmall.com", "amazon.com", "pinduoduo.com",
            "ebay.com", "aliexpress.com", "shopify.com", "etsy.com", "temu.com",
        ),
    ),
    SiteCategory(
        id="work",
        name_zh="工作",
        name_en="Work",
        hex_color=0x3B82F6,
        distracting=False,
        domains=(
            "notion.so", "docs.google.com", "github.com", "gitlab.com", "stackoverflow.com",
            "figma.com", "atlassian.com", "juejin.cn", "segmentfault.com", "linux.do",
            "slack.com", "linear.app", "trello.com", "bitbucket.org", "gitee.com",
        ),
    ),
    SiteCategory(
        id="education",
        name_zh="学习",
        name_en="Learning",
        hex_color=0x8B5CF6,
        distracting=False,
        domains=(
            "coursera.org", "udemy.com", "khanacademy.org", "edx.org", "mooc.cn",
            "icourse163.org", "roadmap.sh", "developer.mozilla.org", "arxiv.org",
            "wikipedia.org", "duolingo.com",
        ),
    ),
    SiteCategory(
        id="entertainment",
        name_zh="娱乐",
        name_en="Fun",
        hex_color=0xF97316,
        distracting=True,
        domains=(
            "store.steampowered.com", "epicgames.com", "spotify.com", "music.163.com",
            "iq.com", "pixiv.net", "9gag.com", "imgur.com",
        ),
    ),
    SiteCategory(
        id="email",
        name_zh="邮件",
        name_en="Email",
        hex_color=0x06B6D4,
        distracting=False,
        domains=(
            "gmail.com", "mail.google.com", "outlook.com", "mail.qq.com", "mail.163.com",
            "proton.me", "fastmail.com",
        ),
    ),
    SiteCategory(
        id="other",
        name_zh="其他",
        name_en="Other",
        hex_color=0x6B7280,
        distracting=False,
        domains=(),
    ),
)

OTHER = ALL[-1]
BY_ID: dict[str, SiteCategory] = {c.id: c for c in ALL}


def for_host(host: str) -> SiteCategory:
    """按后缀把宿主名归入 9 类之一；未知域名归「其他」。"""
    lowered = (host or "").strip().lower()
    if not lowered:
        return OTHER
    for category in ALL:
        for domain in category.domains:
            if lowered == domain or lowered.endswith("." + domain):
                return category
    return OTHER


def is_distracting(host: str) -> bool:
    return for_host(host).distracting


def color_map() -> dict[str, int]:
    """分类 id → 颜色（图表用）。"""
    return {c.id: c.hex_color for c in ALL}
