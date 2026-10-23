// One fresh frame per request; excludes the companion's own windows. No recording/files.
import AppKit
import ScreenCaptureKit
import CoreGraphics
import Foundation
import Vision

@main struct ScreenBridge {
    static func recognizeText(_ image: CGImage) throws -> [[String: Any]] {
        var textRegions: [[String: Any]] = []
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .fast
        request.usesLanguageCorrection = false
        request.minimumTextHeight = 0.008
        do {
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        } catch {
            let failure = error as NSError
            guard failure.domain == VNErrorDomain && failure.code == VNErrorCode.notImplemented.rawValue else { throw error }
            // Some systems lack the fast recognizer. OCR still avoids image-token
            // inference when the accurate recognizer is available instead.
            request.recognitionLevel = .accurate
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        }
        for observation in (request.results ?? []).prefix(200) {
            guard let candidate = observation.topCandidates(1).first,
                  candidate.confidence >= 0.5 else { continue }
            let box = observation.boundingBox
            func rounded(_ value: Double) -> Double { (value*10000).rounded()/10000 }
            textRegions.append(["text": String(candidate.string.prefix(160)),
                "x": rounded(box.minX), "y": rounded(1-box.maxY),
                "width": rounded(box.width), "height": rounded(box.height)])
        }
        return textRegions
    }

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
        if args.contains("--check-access") {
            emit(["granted": CGPreflightScreenCaptureAccess()]); return
        }
        if args.contains("--request-access") {
            let granted = CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess()
            emit(["granted": granted]); return
        }
        // Offline OCR probe for annotated/synthetic fixtures; does not capture a screen.
        if let index = args.firstIndex(of: "--ocr-image"), index+1 < args.count {
            guard let source = NSImage(contentsOfFile: args[index+1]),
                  let image = source.cgImage(forProposedRect: nil, context: nil, hints: nil),
                  image.width*image.height <= 16000000 else {
                emit(["error": "Could not read the OCR fixture."]); return
            }
            let started = CFAbsoluteTimeGetCurrent()
            do {
                emit(["text_regions": try recognizeText(image),
                      "ocr_ms": Int((CFAbsoluteTimeGetCurrent()-started)*1000)])
            } catch { emit(["error": "OCR fixture recognition failed.", "error_code": (error as NSError).code]) }
            return
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
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            guard let display = content.displays.min(by: {
                let a = CGDisplayBounds($0.displayID).origin, b = CGDisplayBounds($1.displayID).origin
                return hypot(a.x-x, a.y-y) < hypot(b.x-x, b.y-y)
            }) else { emit(["error": "No display is available to capture."]); return }
            let excluded = content.applications.filter { $0.processID == ownPID }
            func companionIsVisible() -> Bool {
                guard ownPID > 0,
                      let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else { return true }
                return windows.contains { ($0[kCGWindowOwnerPID as String] as? Int32) == ownPID }
            }
            // A hidden companion may not appear in SCShareableContent.applications.
            // No exclusion is needed when window-server evidence confirms it has no
            // visible windows. Check again after capture and discard if that changes.
            guard !excluded.isEmpty || !companionIsVisible() else {
                emit(["error": "The companion is visible but could not be excluded. Hide its panels and retry."]); return
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
            // The model gets a 1440-pixel-wide image. OCR reads the display's own pixels: on a
            // Retina screen, 1440 pixels shrank interface text until "Chat" read as "Chpl".
            // Every frame is scaled the same way, OCR or not, so a click's guard (a hash of the
            // pixels around the target) matches between the observation and the re-check.
            let pixelWidth = CGDisplayCopyDisplayMode(display.displayID).map { Int($0.pixelWidth) } ?? 1440
            let captureWidth = min(3200, max(1440, pixelWidth))
            configuration.width = captureWidth
            configuration.height = max(1, Int(Double(captureWidth)*bounds.height/bounds.width))
            configuration.showsCursor = false
            configuration.capturesAudio = false
            let captured = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
            guard !excluded.isEmpty || !companionIsVisible() else {
                emit(["error": "A companion window appeared during capture. The image was discarded."]); return
            }
            var image = captured
            if captured.width > 1440 {
                let height = max(1, Int(1440*Double(captured.height)/Double(captured.width)))
                guard let context = CGContext(data: nil, width: 1440, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
                    emit(["error": "Could not encode screen image."]); return
                }
                context.interpolationQuality = .high
                context.draw(captured, in: CGRect(x: 0, y: 0, width: 1440, height: height))
                guard let scaled = context.makeImage() else { emit(["error": "Could not encode screen image."]); return }
                image = scaled
            }
            let bitmap = NSBitmapImageRep(cgImage: image)
            guard let png = bitmap.representation(using: .png, properties: [:]) else {
                emit(["error": "Could not encode screen image."]); return
            }
            let windows = visibleWindows.filter { CGDisplayBounds(display.displayID).intersects($0.frame) && !protectedBundles.contains($0.owningApplication?.bundleIdentifier ?? "") }.prefix(14).map {
                ["app": $0.owningApplication?.applicationName ?? "Application", "title": String(($0.title ?? "").prefix(160)),
                 "window_id": $0.windowID, "bounds": ["x": $0.frame.origin.x, "y": $0.frame.origin.y, "width": $0.frame.width, "height": $0.frame.height]]
            }
            var textRegions: [[String: Any]] = []
            let ocrStarted = CFAbsoluteTimeGetCurrent()
            if args.contains("--ocr") {
                do { textRegions = try recognizeText(captured) }
                catch { /* Missing OCR falls back to image analysis, never guessed text. */ }
            }
            emit(["image_data": "data:image/png;base64,"+png.base64EncodedString(),
                  "display_id": display.displayID, "screen": ["x": bounds.origin.x, "y": bounds.origin.y, "width": bounds.width, "height": bounds.height],
                  "captured_at": ISO8601DateFormatter().string(from: Date()), "windows": windows,
                  "companion_excluded": true, "text_regions": textRegions,
                  "ocr_ms": Int((CFAbsoluteTimeGetCurrent()-ocrStarted)*1000)])
        } catch {
            emit(["error": "Screen capture failed. Check macOS Screen Recording permission and try again."])
        }
    }
}
