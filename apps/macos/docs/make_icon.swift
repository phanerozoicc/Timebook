import AppKit
import CoreGraphics

// Timebook 应用图标渲染：1024×1024，透明底 + 连续圆角矩形（824 body，Apple 网格）
// 设计：品牌橘渐变底（FF9466→F0663F）+ 白色进度环（走 3/4 圈）+ 指针 + 深橘番茄圆点

let size = 1024
let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                    bytesPerRow: 0, space: colorSpace,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!

func color(_ hex: UInt32, _ alpha: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
}

let softOrange = color(0xFF9466)
let brandOrange = color(0xF0663F)
let deepOrange = color(0xD14A28)
let white = color(0xFFFFFF)

// 底板：连续圆角矩形
let bodyRect = CGRect(x: 100, y: 100, width: 824, height: 824)
let squircle = CGPath(roundedRect: bodyRect, cornerWidth: 185, cornerHeight: 185,
                      transform: nil)

// 投影层
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -12), blur: 34,
              color: color(0x000000, 0.26))
ctx.addPath(squircle)
ctx.setFillColor(white)
ctx.fillPath()
ctx.restoreGState()

// 背景渐变 + 左上高光（裁进圆角内）
ctx.saveGState()
ctx.addPath(squircle)
ctx.clip()
let bg = CGGradient(colorsSpace: colorSpace,
                    colors: [softOrange, brandOrange] as CFArray,
                    locations: [0, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: 512, y: 924), end: CGPoint(x: 512, y: 100), options: [])
let glow = CGGradient(colorsSpace: colorSpace,
                      colors: [color(0xFFFFFF, 0.20), color(0xFFFFFF, 0)] as CFArray,
                      locations: [0, 1])!
ctx.drawRadialGradient(glow, startCenter: CGPoint(x: 340, y: 810), startRadius: 0,
                       endCenter: CGPoint(x: 340, y: 810), endRadius: 620, options: [])
ctx.restoreGState()

// 计时几何：进度弧缺口朝正下方，指针指向弧终点（约 1 点半方向），端点为深橘圆点
let cx = 512.0, cy = 512.0
let ringR = 252.0, ringW = 58.0
let startAngle = -CGFloat.pi / 2 + 0.6545   // 6 点位顺时针让出 37.5°
let sweep = 2 * CGFloat.pi * (285.0 / 360.0)
let endAngle = startAngle - sweep            // 顺时针走 285°

// 进度弧：白，圆头
ctx.saveGState()
ctx.setStrokeColor(white)
ctx.setLineWidth(ringW)
ctx.setLineCap(.round)
ctx.addArc(center: CGPoint(x: cx, y: cy), radius: ringR,
           startAngle: startAngle, endAngle: endAngle, clockwise: true)
ctx.strokePath()
ctx.restoreGState()

// 指针：从圆心指向弧终点
let handLen = 150.0
ctx.saveGState()
ctx.setStrokeColor(white)
ctx.setLineWidth(46)
ctx.setLineCap(.round)
ctx.move(to: CGPoint(x: cx, y: cy))
ctx.addLine(to: CGPoint(x: cx + handLen * cos(endAngle), y: cy + handLen * sin(endAngle)))
ctx.strokePath()
// 圆心轴点
ctx.setFillColor(white)
ctx.fillEllipse(in: CGRect(x: cx - 28, y: cy - 28, width: 56, height: 56))
ctx.restoreGState()

// 弧终点深橘圆点（与弧端同轴同宽，读作「橘色端点」）
let knobR = ringW / 2 + 5
let knobX = cx + ringR * cos(endAngle)
let knobY = cy + ringR * sin(endAngle)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -4), blur: 14, color: color(0x000000, 0.22))
ctx.setFillColor(deepOrange)
ctx.fillEllipse(in: CGRect(x: knobX - knobR, y: knobY - knobR, width: knobR * 2, height: knobR * 2))
ctx.restoreGState()

// 输出
let image = ctx.makeImage()!
let rep = NSBitmapImageRep(cgImage: image)
let png = rep.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: "/tmp/tb_icon_1024.png"))
print("rendered /tmp/tb_icon_1024.png")
