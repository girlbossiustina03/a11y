// Read-only accessibility metadata plus user-confirmed activation of a running app.
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
if let index = args.firstIndex(of: "--activate"), index+1 < args.count {
    let bundle = args[index+1]
    guard let app = running.first(where: { $0.bundleIdentifier == bundle }) else {
        emit(["error": "The app is no longer available."]); exit(1)
    }
    emit(["activated": app.activate(options: []), "bundle_id": bundle]); exit(0)
}
if args.contains("--request-access") {
    let trusted = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
    emit(["accessibility": trusted ? "granted" : "permission_required"]); exit(0)
}
var output: [String: Any] = [
    "platform": "macOS", "accessibility": AXIsProcessTrusted() ? "granted" : "permission_required",
    "available_apps": running.prefix(25).map { ["name": $0.localizedName ?? "Application", "bundle_id": $0.bundleIdentifier!] }
]
guard let front = workspace.frontmostApplication else {
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
var visited = 0
let traversalStarted = CFAbsoluteTimeGetCurrent()
while !queue.isEmpty && visited < 220 && controls.count < 45 && CFAbsoluteTimeGetCurrent()-traversalStarted < 1.5 {
    let (node, depth) = queue.removeFirst()
    visited += 1
    if let description = descriptor(node, index: controls.count) { controls.append(description) }
    if depth >= 7 || string(node, "AXSubrole") == "AXSecureTextField" { continue }
    if let children = attr(node, "AXChildren") as? [AXUIElement] {
        queue.append(contentsOf: children.prefix(40).map { ($0, depth+1) })
    }
}
output["controls"] = controls
emit(output)
