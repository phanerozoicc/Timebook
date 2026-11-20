import Foundation
import SwiftUI

// 网站分类：9 类与域名映射，按后缀匹配。
struct SiteCategory {
    let id: String
    let name: String
    let hex: UInt32
    let distracting: Bool
    let domains: [String]

    static let all: [SiteCategory] = [
        .init(id: "social", name: "社交", hex: 0xE1306C, distracting: true,
              domains: ["facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "reddit.com", "linkedin.com", "weibo.com", "threads.net", "pinterest.com"]),
        .init(id: "video", name: "视频", hex: 0xFF0000, distracting: true,
              domains: ["youtube.com", "netflix.com", "bilibili.com", "twitch.tv", "douyin.com", "iqiyi.com", "youku.com", "vimeo.com"]),
        .init(id: "news", name: "资讯", hex: 0xF59E0B, distracting: false,
              domains: ["news.qq.com", "news.sina.com.cn", "cnn.com", "bbc.com", "bbc.co.uk", "nytimes.com", "thepaper.cn", "reuters.com", "36kr.com"]),
        .init(id: "shopping", name: "购物", hex: 0x10B981, distracting: true,
              domains: ["taobao.com", "jd.com", "tmall.com", "amazon.com", "pinduoduo.com", "ebay.com", "aliexpress.com", "shopify.com"]),
        .init(id: "work", name: "工作", hex: 0x3B82F6, distracting: false,
              domains: ["notion.so", "docs.google.com", "github.com", "gitlab.com", "stackoverflow.com", "figma.com", "atlassian.com", "juejin.cn", "segmentfault.com", "linux.do"]),
        .init(id: "education", name: "学习", hex: 0x8B5CF6, distracting: false,
              domains: ["coursera.org", "udemy.com", "khanacademy.org", "edx.org", "mooc.cn", "icourse163.org", "roadmap.sh", "developer.mozilla.org"]),
        .init(id: "entertainment", name: "娱乐", hex: 0xF97316, distracting: true,
              domains: ["store.steampowered.com", "epicgames.com", "huya.com", "douyu.com", "spotify.com", "music.163.com", "iq.com"]),
        .init(id: "email", name: "邮件", hex: 0x06B6D4, distracting: false,
              domains: ["gmail.com", "mail.google.com", "outlook.com", "mail.qq.com", "mail.163.com"]),
        .init(id: "other", name: "其他", hex: 0x6B7280, distracting: false, domains: []),
    ]

    static func forHost(_ host: String) -> SiteCategory {
        let lowered = host.lowercased()
        for category in all where category.domains.contains(where: { lowered == $0 || lowered.hasSuffix("." + $0) }) {
            return category
        }
        return all.last!
    }

    var color: Color { Color(hex: hex) }
}
