// One fresh frame per request; excludes the companion's own windows. No recording/files.
import AppKit
import ScreenCaptureKit
import CoreGraphics
import Foundation

@main struct ScreenBridge {
    static func emit(_ value: [String: Any]) {
        if let data = try? JSONSerialization.data(withJSONObject: value) {
            print(String(decoding: data, as: UTF8.self))
        }
    }
    static func main() async {
        guard #available(macOS 14.0, *) else {
            emit(["error": "Screen vision requires macOS 14 or later."]); return
        }
        let args = CommandLine.arguments
        if args.contains("--request-access") {
            let granted = CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess()
            emit(["granted": granted]); return
        }
        guard CGPreflightScreenCaptureAccess() else {
            emit(["error": "Allow Screen & System Audio Recording for the requested Terminal/Python/bridge entry in macOS Privacy & Security, then try again."]); return
        }
        func argument(_ name: String) -> String? {
            guard let index = args.firstIndex(of: name), index+1 < args.count else { return nil }
            return args[index+1]
        }
        let ownPID = Int32(argument("--exclude-pid") ?? "0") ?? 0
        let x = Double(argument("--x") ?? "0") ?? 0
        let y = Double(argument("--y") ?? "0") ?? 0
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.min(by: {
                let a = CGDisplayBounds($0.displayID).origin, b = CGDisplayBounds($1.displayID).origin
                return hypot(a.x-x, a.y-y) < hypot(b.x-x, b.y-y)
            }) else { emit(["error": "No display is available to capture."]); return }
            let excluded = content.applications.filter { $0.processID == ownPID }
            guard !excluded.isEmpty else {
                emit(["error": "Could not identify the companion's windows for exclusion. Screen vision was not captured."]); return
            }
            let visibleWindows = content.windows.filter {
                $0.isOnScreen && $0.windowLayer == 0 && $0.owningApplication?.processID != ownPID
            }
            let protectedBundles = ["com.apple.Passwords", "com.apple.keychainaccess", "com.1password.1password", "com.agilebits.onepassword7", "com.bitwarden.desktop"]
            let front = NSWorkspace.shared.frontmostApplication
            if protectedBundles.contains(front?.bundleIdentifier ?? "") {
                emit(["error": "Screen vision paused while a protected app is active."]); return
            }
            let sensitiveApps = content.applications.filter { protectedBundles.contains($0.bundleIdentifier) }
            let filter = SCContentFilter(display: display, excludingApplications: excluded+sensitiveApps, exceptingWindows: [])
            let bounds = CGDisplayBounds(display.displayID)
            let configuration = SCStreamConfiguration()
            configuration.width = 1440
            configuration.height = max(1, Int(1440*bounds.height/bounds.width))
            configuration.showsCursor = false
            configuration.capturesAudio = false
            let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
            let bitmap = NSBitmapImageRep(cgImage: image)
            guard let png = bitmap.representation(using: .png, properties: [:]) else {
                emit(["error": "Could not encode screen image."]); return
            }
            let windows = visibleWindows.filter { CGDisplayBounds(display.displayID).intersects($0.frame) && !protectedBundles.contains($0.owningApplication?.bundleIdentifier ?? "") }.prefix(14).map {
                ["app": $0.owningApplication?.applicationName ?? "Application", "title": String(($0.title ?? "").prefix(160))]
            }
            emit(["image_data": "data:image/png;base64,"+png.base64EncodedString(),
                  "screen": ["x": bounds.origin.x, "y": bounds.origin.y, "width": bounds.width, "height": bounds.height],
                  "captured_at": ISO8601DateFormatter().string(from: Date()), "windows": windows,
                  "companion_excluded": true])
        } catch {
            emit(["error": "Screen capture failed. Check macOS Screen Recording permission and try again."])
        }
    }
}
