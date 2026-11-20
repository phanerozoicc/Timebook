import Foundation

// 双语：zh 为源语言，en 全量覆盖。"auto" 跟随系统首选语言。
// 主应用读取用户在设置里选择的语言；widget 扩展读取自己的 defaults（跟随系统）。

func T(_ zh: String, _ en: String) -> String {
    switch UserDefaults.standard.string(forKey: "language") ?? "auto" {
    case "en": return en
    case "zh": return zh
    default:
        return Locale.preferredLanguages.first?.hasPrefix("zh") ?? false ? zh : en
    }
}
