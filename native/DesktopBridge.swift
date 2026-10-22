// Read-only accessibility metadata plus confirmed app activation and exact-control AXPress.
// Never reads AXValue, selected text, clipboard, screenshots, or secure input contents.
import AppKit
import ApplicationServices
import Foundation

func emit(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
        print(String(decoding: data, as: UTF8.self))
    }
}
func attr(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}
func string(_ element: AXUIElement, _ name: String) -> String {
    String(((attr(element, name) as? String) ?? "").prefix(160))
}
func element(_ value: CFTypeRef?) -> AXUIElement? {
    guard let value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
    return (value as! AXUIElement)
}
func bounds(_ node: AXUIElement) -> [String: Double]? {
    guard let position = attr(node, "AXPosition"), let size = attr(node, "AXSize"),
          CFGetTypeID(position) == AXValueGetTypeID(), CFGetTypeID(size) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero
    var extent = CGSize.zero
    guard AXValueGetValue(position as! AXValue, .cgPoint, &point),
          AXValueGetValue(size as! AXValue, .cgSize, &extent), extent.width > 0, extent.height > 0 else { return nil }
    return ["x": point.x, "y": point.y, "width": extent.width, "height": extent.height]
}
let args = CommandLine.arguments
let ownPID = args.firstIndex(of: "--exclude-pid").flatMap { $0+1 < args.count ? Int32(args[$0+1]) : nil }
let workspace = NSWorkspace.shared
let deniedBundles: Set<String> = ["com.apple.Passwords", "com.apple.keychainaccess", "com.agilebits.onepassword7", "com.1password.1password", "com.bitwarden.desktop"]
let running = workspace.runningApplications.filter {
    $0.activationPolicy == .regular && $0.processIdentifier != ownPID && $0.bundleIdentifier != nil && !deniedBundles.contains($0.bundleIdentifier!)
}
if let index = args.firstIndex(of: "--click"), index+4 < args.count {
    guard AXIsProcessTrusted(), let x = Double(args[index+1]), let y = Double(args[index+2]),
          x.isFinite, y.isFinite, let displayID = UInt32(args[index+3]), CGDisplayIsActive(displayID) != 0,
          let data = args[index+4].data(using: .utf8),
          let expected = (try? JSONSerialization.jsonObject(with: data)) as? [String: Double] else {
        emit(["error": "A current display and macOS Accessibility permission are required for clicking."]); exit(1)
    }
    let actual = CGDisplayBounds(displayID)
    guard actual.contains(CGPoint(x: x, y: y)), expected["x"] == actual.origin.x,
          expected["y"] == actual.origin.y, expected["width"] == actual.width, expected["height"] == actual.height,
          let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: CGPoint(x: x, y: y), mouseButton: .left),
          let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: CGPoint(x: x, y: y), mouseButton: .left) else {
        emit(["error": "The display changed. No click was sent."]); exit(1)
    }
    down.post(tap: .cghidEventTap)
    up.post(tap: .cghidEventTap)
    emit(["submitted": true, "verification_required": true]); exit(0)
}
if let index = args.firstIndex(of: "--activate"), index+1 < args.count {
    let bundle = args[index+1]
    guard let app = running.first(where: { $0.bundleIdentifier == bundle }) else {
        emit(["error": "The app is no longer available."]); exit(1)
    }
    emit(["activated": app.activate(options: []), "bundle_id": bundle]); exit(0)
}
func installedApps() -> [[String: String]] {
    let roots = ["/Applications", "/Applications/Utilities", "/System/Applications", "/System/Applications/Utilities"]
    var result: [[String: String]] = []
    var seen = Set<String>()
    for root in roots {
        let urls = ((try? FileManager.default.contentsOfDirectory(at: URL(fileURLWithPath: root), includingPropertiesForKeys: nil)) ?? []) + (root == "/System/Applications" ? [URL(fileURLWithPath: "/System/Library/CoreServices/Finder.app")] : [])
        for url in urls {
            guard url.pathExtension == "app", let bundle = Bundle(url: url), let id = bundle.bundleIdentifier,
                  !deniedBundles.contains(id), (bundle.object(forInfoDictionaryKey: "LSUIElement") as? Bool) != true,
                  (bundle.object(forInfoDictionaryKey: "LSBackgroundOnly") as? Bool) != true,
                  seen.insert(id).inserted else { continue }
            result.append(["bundle_id": id, "name": String(((bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String) ?? url.deletingPathExtension().lastPathComponent).prefix(100))])
        }
    }
    return result.sorted { $0["name"]! < $1["name"]! }
}
if args.contains("--catalog") { emit(["installed_apps": installedApps()]); exit(0) }
if let index = args.firstIndex(of: "--app-state"), index+1 < args.count {
    let bundleID = args[index+1]
    let deadline = Date().addingTimeInterval(1.5)
    var matches: [NSRunningApplication] = []
    repeat {
        // A newly launched app can initially be accessory/background, so do not
        // reuse the regular-app-only guidance inventory as process evidence.
        matches = workspace.runningApplications.filter { $0.bundleIdentifier == bundleID && !$0.isTerminated }
        if !matches.isEmpty { break }
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    } while Date() < deadline
    emit(["bundle_id": bundleID, "running": !matches.isEmpty, "active": matches.contains(where: { $0.isActive }),
          "observation": matches.isEmpty ? "not_observed" : "process_observed"]); exit(0)
}
if let index = args.firstIndex(of: "--browse"), index+2 < args.count {
    let bundleID = args[index+1]
    let browsers = ["com.apple.Safari", "com.google.Chrome", "org.mozilla.firefox", "com.microsoft.edgemac"]
    guard browsers.contains(bundleID), installedApps().contains(where: { $0["bundle_id"] == bundleID }),
          let appURL = workspace.urlForApplication(withBundleIdentifier: bundleID),
          let url = URL(string: args[index+2]), ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
          url.host != nil, url.user == nil, url.password == nil else {
        emit(["error": "Only an installed supported browser and a public HTTP(S) address are allowed."]); exit(1)
    }
    var finished = false
    var submitted = false
    workspace.open([url], withApplicationAt: appURL, configuration: NSWorkspace.OpenConfiguration()) { apps, error in
        submitted = error == nil && apps != nil
        finished = true
    }
    let deadline = Date().addingTimeInterval(3)
    while !finished && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.02)) }
    emit(["submitted": submitted, "verification_required": true, "tab_placement": "browser_preference"]); exit(submitted ? 0 : 1)
}
if let index = args.firstIndex(of: "--launch"), index+1 < args.count {
    let bundleID = args[index+1]
    guard installedApps().contains(where: { $0["bundle_id"] == bundleID }),
          let url = workspace.urlForApplication(withBundleIdentifier: bundleID) else {
        emit(["error": "That installed application is no longer available."]); exit(1)
    }
    var finished = false
    var opened = false
    workspace.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration()) { app, error in
        opened = app != nil && error == nil
        finished = true
    }
    let deadline = Date().addingTimeInterval(3)
    while !finished && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.02)) }
    emit(["submitted": opened, "verification_required": true]); exit(opened ? 0 : 1)
}
if let index = args.firstIndex(of: "--quit"), index+1 < args.count {
    guard let app = running.first(where: { $0.bundleIdentifier == args[index+1] }) else {
        emit(["error": "That application is no longer running."]); exit(1)
    }
    emit(["submitted": app.terminate(), "verification_required": true]); exit(0)
}
if args.contains("--request-access") {
    let trusted = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
    emit(["accessibility": trusted ? "granted" : "permission_required"]); exit(0)
}
var output: [String: Any] = [
    "platform": "macOS", "accessibility": AXIsProcessTrusted() ? "granted" : "permission_required",
    "installed_apps": installedApps(),
    "available_apps": running.prefix(25).map { ["name": $0.localizedName ?? "Application", "bundle_id": $0.bundleIdentifier!] }
]
// Window-server inventory includes unfocused windows. This is geometry, not pixels:
// windows may overlap, and absence from this bounded list proves nothing.
if let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] {
    var candidates: [[String: Any]] = []
    for window in windows {
        guard candidates.count < 40,
              let pid = window[kCGWindowOwnerPID as String] as? Int32,
              let owner = running.first(where: { $0.processIdentifier == pid }),
              (window[kCGWindowLayer as String] as? Int) == 0,
              let rect = window[kCGWindowBounds as String] as? [String: Any],
              let x = rect["X"] as? Double, let y = rect["Y"] as? Double,
              let width = rect["Width"] as? Double, let height = rect["Height"] as? Double,
              width > 1, height > 1 else { continue }
        candidates.append(["app": owner.localizedName ?? "Application", "bundle_id": owner.bundleIdentifier!,
            "bounds": ["x": x, "y": y, "width": width, "height": height]])
    }
    output["onscreen_window_candidates"] = candidates
}
// Every normal window, including unfocused ones, gets its own close target.
var appWindows: [[String: Any]] = []
if AXIsProcessTrusted() {
    let started = CFAbsoluteTimeGetCurrent()
    for owner in running {
        if appWindows.count >= 35 || CFAbsoluteTimeGetCurrent()-started > 1 { break }
        let node = AXUIElementCreateApplication(owner.processIdentifier)
        AXUIElementSetMessagingTimeout(node, 0.1)
        for (index, window) in ((attr(node, "AXWindows") as? [AXUIElement]) ?? []).prefix(12).enumerated() {
            guard let rect = bounds(window) else { continue }
            let close = element(attr(window, "AXCloseButton"))
            appWindows.append(["window_id": "\(owner.bundleIdentifier!):\(index)",
                "bundle_id": owner.bundleIdentifier!, "name": owner.localizedName ?? "Application",
                "title": string(window, "AXTitle"), "bounds": rect,
                "can_close": close != nil && ((close.flatMap { attr($0, "AXEnabled") } as? Bool) ?? true)])
        }
    }
}
output["app_windows"] = appWindows
if let index = args.firstIndex(of: "--close-window"), index+4 < args.count {
    guard AXIsProcessTrusted(),
          let owner = running.first(where: { $0.bundleIdentifier == args[index+1] }),
          let ordinal = Int(args[index+2]), ordinal >= 0,
          let data = args[index+4].data(using: .utf8),
          let expected = (try? JSONSerialization.jsonObject(with: data)) as? [String: Double] else {
        emit(["error": "Accessibility permission and an observed window are required."]); exit(1)
    }
    let app = AXUIElementCreateApplication(owner.processIdentifier)
    AXUIElementSetMessagingTimeout(app, 0.2)
    let windows = (attr(app, "AXWindows") as? [AXUIElement]) ?? []
    guard ordinal < windows.count, let actual = bounds(windows[ordinal]),
          string(windows[ordinal], "AXTitle") == args[index+3],
          ["x", "y", "width", "height"].allSatisfy({
              guard let a = actual[$0], let e = expected[$0], e.isFinite else { return false }
              return abs(a-e) <= 1
          }), let close = element(attr(windows[ordinal], "AXCloseButton")),
          (attr(close, "AXEnabled") as? Bool) != false else {
        emit(["error": "That window changed or cannot be closed. Request a fresh observation."]); exit(1)
    }
    AXUIElementSetMessagingTimeout(close, 1)
    let status = AXUIElementPerformAction(close, kAXPressAction as CFString)
    emit(["submitted": status == .success, "verification_required": true]); exit(0)
}
if let index = args.firstIndex(of: "--new-window"), index+1 < args.count {
    guard AXIsProcessTrusted(), args[index+1] == "com.apple.Terminal",
          let owner = running.first(where: { $0.bundleIdentifier == args[index+1] }) else {
        emit(["error": "New-window automation currently requires running Terminal and Accessibility permission."]); exit(1)
    }
    let app = AXUIElementCreateApplication(owner.processIdentifier)
    AXUIElementSetMessagingTimeout(app, 0.1)
    var queue: [(AXUIElement, Int)] = element(attr(app, "AXMenuBar")).map { [($0, 0)] } ?? []
    var matches: [AXUIElement] = []
    var visited = 0
    let started = CFAbsoluteTimeGetCurrent()
    while !queue.isEmpty && visited < 300 && CFAbsoluteTimeGetCurrent()-started < 1.5 {
        let (node, depth) = queue.removeFirst()
        visited += 1
        if string(node, "AXRole") == "AXMenuItem", string(node, "AXMenuItemCmdChar").lowercased() == "n",
           (attr(node, "AXMenuItemCmdModifiers") as? Int) == 0, (attr(node, "AXEnabled") as? Bool) != false {
            matches.append(node)
        }
        if depth < 5, let children = attr(node, "AXChildren") as? [AXUIElement] {
            queue.append(contentsOf: children.prefix(50).map { ($0, depth+1) })
        }
    }
    guard matches.count == 1 else {
        emit(["error": "Terminal did not expose one unambiguous Command-N menu action. Open its New Window menu manually."]); exit(1)
    }
    guard owner.activate(options: []) else { emit(["error": "Terminal could not be activated."]); exit(1) }
    AXUIElementSetMessagingTimeout(matches[0], 1)
    let status = AXUIElementPerformAction(matches[0], kAXPressAction as CFString)
    emit(["submitted": status == .success, "verification_required": true]); exit(0)
}
let pressIndex = args.firstIndex(of: "--press")
var observedApp = workspace.frontmostApplication
if let index = pressIndex {
    guard index+5 < args.count,
          let app = running.first(where: { $0.bundleIdentifier == args[index+1] }) else {
        emit(["error": "The requested application is no longer available."]); exit(1)
    }
    observedApp = app
}
guard let front = observedApp else {
    output["status"] = "unavailable"; emit(output); exit(0)
}
if front.processIdentifier == ownPID {
    output["status"] = "companion_focused"; emit(output); exit(0)
}
if deniedBundles.contains(front.bundleIdentifier ?? "") {
    output["status"] = "private_app"; emit(output); exit(0)
}
output["status"] = "available"
output["app"] = ["name": front.localizedName ?? "Application", "bundle_id": front.bundleIdentifier ?? "", "pid": front.processIdentifier]
guard AXIsProcessTrusted() else { emit(output); exit(0) }
let app = AXUIElementCreateApplication(front.processIdentifier)
AXUIElementSetMessagingTimeout(app, 0.25)
let window = element(attr(app, "AXFocusedWindow"))
if let window {
    output["window"] = ["title": string(window, "AXTitle"), "bounds": bounds(window) ?? [:]]
}
let actionable: Set<String> = ["AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXTab", "AXLink", "AXDisclosureTriangle", "AXMenuItem"]
func descriptor(_ node: AXUIElement, index: Int) -> [String: Any]? {
    let role = string(node, "AXRole")
    let subrole = string(node, "AXSubrole")
    if subrole == "AXSecureTextField" || role == "AXTextField" || role == "AXTextArea" || role == "AXStaticText" { return nil }
    guard actionable.contains(role) else { return nil }
    let title = string(node, "AXTitle")
    let label = title.isEmpty ? string(node, "AXDescription") : title
    guard !label.isEmpty, let rect = bounds(node) else { return nil }
    return ["id": "control-\(index)", "role": role, "label": label, "bounds": rect,
            "enabled": (attr(node, "AXEnabled") as? Bool) ?? true]
}
if let focused = element(attr(app, "AXFocusedUIElement")) {
    // Text-field role is useful; its content and label are intentionally omitted.
    let role = string(focused, "AXRole")
    output["focused_role"] = string(focused, "AXSubrole") == "AXSecureTextField" ? "secure_input" : role
}
var queue: [(AXUIElement, Int)] = window.map { [($0, 0)] } ?? []
var controls: [[String: Any]] = []
var controlNodes: [AXUIElement] = []
var visited = 0
let traversalStarted = CFAbsoluteTimeGetCurrent()
while !queue.isEmpty && visited < 220 && controls.count < 45 && CFAbsoluteTimeGetCurrent()-traversalStarted < 1.5 {
    let (node, depth) = queue.removeFirst()
    visited += 1
    if let description = descriptor(node, index: controls.count) {
        controls.append(description)
        controlNodes.append(node)
    }
    if depth >= 7 || string(node, "AXSubrole") == "AXSecureTextField" { continue }
    if let children = attr(node, "AXChildren") as? [AXUIElement] {
        queue.append(contentsOf: children.prefix(40).map { ($0, depth+1) })
    }
}
output["controls"] = controls
if let index = pressIndex {
    let controlID = args[index+2]
    let expectedLabel = args[index+3]
    let expectedTitle = args[index+5]
    guard let position = controls.firstIndex(where: { ($0["id"] as? String) == controlID }),
          let actualBounds = controls[position]["bounds"] as? [String: Double],
          let expectedData = args[index+4].data(using: .utf8),
          let expectedBounds = (try? JSONSerialization.jsonObject(with: expectedData)) as? [String: Double],
          controls[position]["label"] as? String == expectedLabel,
          controls[position]["enabled"] as? Bool == true,
          let window, string(window, "AXTitle") == expectedTitle,
          ["x", "y", "width", "height"].allSatisfy({
              guard let actual = actualBounds[$0], let expected = expectedBounds[$0], expected.isFinite else { return false }
              return abs(actual-expected) <= 1
          }) else {
        emit(["error": "The control changed. Request a fresh observation before pressing it."]); exit(1)
    }
    guard front.activate(options: []) else {
        emit(["error": "The application could not be brought forward."]); exit(1)
    }
    AXUIElementSetMessagingTimeout(controlNodes[position], 1)
    let status = AXUIElementPerformAction(controlNodes[position], kAXPressAction as CFString)
    // A timeout may occur after an app starts handling an action. Never retry it.
    guard status == .success else {
        emit(["error": "The press result is uncertain. Check the app before trying again."]); exit(1)
    }
    emit(["submitted": true, "verification_required": true]); exit(0)
}
emit(output)
