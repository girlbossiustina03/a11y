// Read-only accessibility metadata plus confirmed app activation and exact-control AXPress.
// Never reads AXValue, selected text, clipboard, screenshots, or secure input contents.
import AppKit
import ApplicationServices
import EventKit
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
func scriptLiteral(_ value: String) -> String {
    return "\"" + value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
}
func musicScript(_ body: String) -> NSAppleEventDescriptor {
    var failure: NSDictionary?
    let script = NSAppleScript(source: "with timeout of 30 seconds\ntell application id \"com.apple.Music\"\n" + body + "\nend tell\nend timeout")
    guard let script else { emit(["error": "Could not prepare Music automation."]); exit(1) }
    let result = script.executeAndReturnError(&failure)
    guard failure == nil else {
        emit(["error": "Music automation failed. Check Privacy & Security > Automation for Music; no action will be retried automatically."]); exit(1)
    }
    return result
}
let musicSnapshot = """
set playbackState to player state as text
set trackInfo to {"", "", ""}
try
    set trackInfo to {name of current track, artist of current track, persistent ID of current track}
end try
"""
func mediaFields(_ result: NSAppleEventDescriptor, offset: Int = 0) -> [String: Any] {
    return ["player_state": result.atIndex(offset+1)?.stringValue ?? "unknown",
            "track": ["name": result.atIndex(offset+2)?.stringValue ?? "", "artist": result.atIndex(offset+3)?.stringValue ?? "", "id": result.atIndex(offset+4)?.stringValue ?? ""]]
}
if args.contains("--music-state") {
    guard workspace.runningApplications.contains(where: { $0.bundleIdentifier == "com.apple.Music" && !$0.isTerminated }) else {
        emit(["player_state": "not_running"]); exit(0)
    }
    let result = musicScript(musicSnapshot + "\nreturn {playbackState, item 1 of trackInfo, item 2 of trackInfo, item 3 of trackInfo}")
    emit(mediaFields(result)); exit(0)
}
if let index = args.firstIndex(of: "--music-play"), index+2 < args.count {
    let query = args[index+1], artist = args[index+2]
    guard !query.trimmingCharacters(in: .whitespaces).isEmpty, query.count <= 500, artist.count <= 200,
          (query+artist).unicodeScalars.allSatisfy({ $0.value >= 32 }) else {
        emit(["error": "Name a song title and optional artist."]); exit(1)
    }
    let script = """
    set songName to \(scriptLiteral(query))
    set artistName to \(scriptLiteral(artist))
    set foundTracks to search library playlist 1 for songName only names
    set candidates to {}
    set exactTracks to {}
    set outcome to "not_found"
    set didPlay to false
    set requestedID to ""
    if (count of foundTracks) > 100 then
        set outcome to "too_many"
    else
        repeat with candidate in foundTracks
            if (count of candidates) < 20 then set end of candidates to {name of candidate, artist of candidate}
            ignoring case
                if (name of candidate is songName) and (artistName is "" or artist of candidate contains artistName) then set end of exactTracks to contents of candidate
            end ignoring
        end repeat
        if (count of exactTracks) is 1 then
            set chosen to item 1 of exactTracks
            set requestedID to persistent ID of chosen
            play chosen
            set didPlay to true
            set outcome to "play_submitted"
        else if (count of exactTracks) > 1 then
            set outcome to "ambiguous"
        end if
    end if
    \(musicSnapshot)
    return {outcome, didPlay, requestedID, playbackState, item 1 of trackInfo, item 2 of trackInfo, item 3 of trackInfo, candidates}
    """
    let result = musicScript(script)
    var output = mediaFields(result, offset: 3)
    var candidates: [[String: String]] = []
    if let list = result.atIndex(8), list.numberOfItems > 0 {
        for i in 1...min(20, list.numberOfItems) {
            candidates.append(["name": list.atIndex(i)?.atIndex(1)?.stringValue ?? "", "artist": list.atIndex(i)?.atIndex(2)?.stringValue ?? ""])
        }
    }
    output["submitted"] = true
    output["outcome"] = result.atIndex(1)?.stringValue ?? "unknown"
    output["play_submitted"] = result.atIndex(2)?.booleanValue ?? false
    output["requested_id"] = result.atIndex(3)?.stringValue ?? ""
    output["candidates"] = candidates
    emit(output); exit(0)
}
if let index = args.firstIndex(of: "--input"), index+1 < args.count {
    guard AXIsProcessTrusted(), let data = args[index+1].data(using: .utf8),
          let action = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          let bundle = action["bundle_id"] as? String,
          !deniedBundles.contains(bundle), !["com.apple.Terminal", "com.googlecode.iterm2", "dev.warp.Warp-Stable"].contains(bundle),
          let owner = running.first(where: { $0.bundleIdentifier == bundle }),
          let expected = action["bounds"] as? [String: Double] else {
        emit(["error": "Input needs an observed non-protected app and Accessibility permission."]); exit(1)
    }
    let front = workspace.frontmostApplication
    guard front?.bundleIdentifier == bundle || front?.processIdentifier == ownPID else {
        emit(["error": "Another app became active. Input was cancelled."]); exit(1)
    }
    _ = owner.activate(options: [])
    let deadline = Date().addingTimeInterval(0.5)
    while workspace.frontmostApplication?.bundleIdentifier != bundle && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.02)) }
    let app = AXUIElementCreateApplication(owner.processIdentifier)
    AXUIElementSetMessagingTimeout(app, 0.25)
    guard workspace.frontmostApplication?.bundleIdentifier == bundle,
          let window = element(attr(app, "AXFocusedWindow")), bounds(window) == expected,
          string(window, "AXTitle") == action["window_title"] as? String,
          let focused = element(attr(app, "AXFocusedUIElement")), string(focused, "AXSubrole") != "AXSecureTextField" else {
        emit(["error": "The input window or focus changed. Nothing was sent."]); exit(1)
    }
    let kind = action["type"] as? String ?? ""
    if kind == "type_text" {
        guard let text = action["text"] as? String, !text.isEmpty, text.count <= 2000,
              text.unicodeScalars.allSatisfy({ $0.value >= 32 }),
              ["AXTextField", "AXTextArea", "AXComboBox"].contains(string(focused, "AXRole")),
              string(focused, "AXRole") == action["focused_role"] as? String,
              bounds(focused) == action["focused_bounds"] as? [String: Double] else {
            emit(["error": "Focus the same non-password text field before typing."]); exit(1)
        }
        var chunks: [[UInt16]] = []
        var chunk: [UInt16] = []
        for character in text {
            let units = Array(String(character).utf16)
            guard units.count <= 20 else { emit(["error": "That text contains an unsupported long grapheme."]); exit(1) }
            if chunk.count+units.count > 20 { chunks.append(chunk); chunk = [] }
            chunk.append(contentsOf: units)
        }
        if !chunk.isEmpty { chunks.append(chunk) }
        for characters in chunks {
            guard workspace.frontmostApplication?.bundleIdentifier == bundle,
                  let current = element(attr(app, "AXFocusedUIElement")), CFEqual(current, focused),
                  let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true),
                  let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false) else {
                emit(["error": "Typing stopped because focus changed. Some text may already have been entered; check before retrying."]); exit(1)
            }
            characters.withUnsafeBufferPointer { buffer in
                down.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
                up.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
            }
            down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
        }
    } else if kind == "press_key" {
        let keys: [String: CGKeyCode] = ["enter": 36, "tab": 48, "escape": 53, "space": 49, "backspace": 51,
            "left": 123, "right": 124, "up": 126, "down": 125, "cmd_l": 37, "cmd_f": 3, "cmd_t": 17,
            "cmd_n": 45, "cmd_w": 13, "cmd_a": 0, "cmd_r": 15]
        guard let name = action["key"] as? String, let key = keys[name],
              let down = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: true),
              let up = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: false) else {
            emit(["error": "Unsupported keyboard command."]); exit(1)
        }
        if name.hasPrefix("cmd_") { down.flags = .maskCommand; up.flags = .maskCommand }
        down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
    } else if kind == "scroll" {
        guard let direction = action["direction"] as? String, ["up", "down"].contains(direction),
              let event = CGEvent(scrollWheelEvent2Source: nil, units: .line, wheelCount: 1, wheel1: direction == "up" ? 6 : -6, wheel2: 0, wheel3: 0),
              let rectangle = bounds(window), let x = rectangle["x"], let y = rectangle["y"], let width = rectangle["width"], let height = rectangle["height"] else {
            emit(["error": "Unsupported scroll destination."]); exit(1)
        }
        event.location = CGPoint(x: x+width/2, y: y+height/2)
        event.post(tap: .cghidEventTap)
    } else { emit(["error": "Unsupported input operation."]); exit(1) }
    emit(["submitted": true, "verification_required": true]); exit(0)
}
if let index = args.firstIndex(of: "--click"), index+4 < args.count {
    guard AXIsProcessTrusted(), let x = Double(args[index+1]), let y = Double(args[index+2]),
          x.isFinite, y.isFinite, let displayID = UInt32(args[index+3]), CGDisplayIsActive(displayID) != 0,
          let data = args[index+4].data(using: .utf8),
          let expected = (try? JSONSerialization.jsonObject(with: data)) as? [String: Double] else {
        emit(["error": "A current display and macOS Accessibility permission are required for clicking."]); exit(1)
    }
    let buttonName = index+5 < args.count ? args[index+5] : "left"
    let count = index+6 < args.count ? Int(args[index+6]) ?? 0 : 1
    guard ["left", "right"].contains(buttonName), [1, 2].contains(count), buttonName != "right" || count == 1 else {
        emit(["error": "Unsupported mouse click."]); exit(1)
    }
    let button: CGMouseButton = buttonName == "left" ? .left : .right
    let downType: CGEventType = buttonName == "left" ? .leftMouseDown : .rightMouseDown
    let upType: CGEventType = buttonName == "left" ? .leftMouseUp : .rightMouseUp
    let actual = CGDisplayBounds(displayID)
    guard actual.contains(CGPoint(x: x, y: y)), expected["x"] == actual.origin.x,
          expected["y"] == actual.origin.y, expected["width"] == actual.width, expected["height"] == actual.height,
          let down = CGEvent(mouseEventSource: nil, mouseType: downType, mouseCursorPosition: CGPoint(x: x, y: y), mouseButton: button),
          let up = CGEvent(mouseEventSource: nil, mouseType: upType, mouseCursorPosition: CGPoint(x: x, y: y), mouseButton: button) else {
        emit(["error": "The display changed. No click was sent."]); exit(1)
    }
    for click in 1...count {
        down.setIntegerValueField(.mouseEventClickState, value: Int64(click))
        up.setIntegerValueField(.mouseEventClickState, value: Int64(click))
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        if click < count { RunLoop.current.run(until: Date().addingTimeInterval(0.06)) }
    }
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
// Calendar and Reminders through EventKit (recurring events included, unlike AppleScript).
// Reading needs the user's Calendars/Reminders permission; adding is only ever run after the
// user confirmed that exact item in A11y.
func eventStore(_ type: EKEntityType) -> EKEventStore? {
    let store = EKEventStore()
    let done = DispatchSemaphore(value: 0)
    var granted = false
    if #available(macOS 14.0, *) {
        if type == .event {
            store.requestFullAccessToEvents { ok, _ in granted = ok; done.signal() }
        } else {
            store.requestFullAccessToReminders { ok, _ in granted = ok; done.signal() }
        }
    } else {
        store.requestAccess(to: type) { ok, _ in granted = ok; done.signal() }
    }
    _ = done.wait(timeout: .now() + 60)
    return granted ? store : nil
}
func accessError(_ type: EKEntityType) -> [String: Any] {
    let pane = type == .event ? "Calendars" : "Reminders"
    return ["error": "Allow A11y to use " + pane + " in System Settings > Privacy & Security > " + pane + ", then ask again."]
}
if let index = args.firstIndex(of: "--calendar-events"), index+2 < args.count {
    guard let from = Double(args[index+1]), let to = Double(args[index+2]), to > from, to - from <= 62 * 86400 else {
        emit(["error": "Invalid calendar range."]); exit(1)
    }
    guard let store = eventStore(.event) else { emit(accessError(.event)); exit(1) }
    let predicate = store.predicateForEvents(withStart: Date(timeIntervalSince1970: from), end: Date(timeIntervalSince1970: to), calendars: nil)
    let events = store.events(matching: predicate).sorted { $0.startDate < $1.startDate }.prefix(40)
    emit(["events": events.map { event -> [String: Any] in
        ["title": event.title ?? "", "start": event.startDate.timeIntervalSince1970, "end": event.endDate.timeIntervalSince1970,
         "all_day": event.isAllDay, "location": event.location ?? "", "calendar": event.calendar?.title ?? ""]
    }]); exit(0)
}
if args.contains("--reminders") {
    guard let store = eventStore(.reminder) else { emit(accessError(.reminder)); exit(1) }
    let predicate = store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: nil)
    let done = DispatchSemaphore(value: 0)
    var found: [EKReminder] = []
    store.fetchReminders(matching: predicate) { reminders in found = reminders ?? []; done.signal() }
    _ = done.wait(timeout: .now() + 30)
    emit(["reminders": found.prefix(60).map { reminder -> [String: Any] in
        var item: [String: Any] = ["title": reminder.title ?? "", "list": reminder.calendar?.title ?? "", "id": reminder.calendarItemIdentifier]
        if let due = reminder.dueDateComponents, let date = Calendar.current.date(from: due) { item["due"] = date.timeIntervalSince1970 }
        return item
    }]); exit(0)
}
if let index = args.firstIndex(of: "--add-event"), index+3 < args.count {
    guard let start = Double(args[index+2]), let end = Double(args[index+3]), end > start, !args[index+1].isEmpty else {
        emit(["error": "Invalid event."]); exit(1)
    }
    guard let store = eventStore(.event) else { emit(accessError(.event)); exit(1) }
    let event = EKEvent(eventStore: store)
    event.title = String(args[index+1].prefix(200))
    event.startDate = Date(timeIntervalSince1970: start)
    event.endDate = Date(timeIntervalSince1970: end)
    event.calendar = store.defaultCalendarForNewEvents
    do { try store.save(event, span: .thisEvent, commit: true) } catch {
        emit(["error": "Calendar did not save the event."]); exit(1)
    }
    emit(["submitted": true, "calendar": event.calendar?.title ?? ""]); exit(0)
}
if let index = args.firstIndex(of: "--add-reminder"), index+2 < args.count {
    guard !args[index+1].isEmpty else { emit(["error": "Invalid reminder."]); exit(1) }
    guard let store = eventStore(.reminder) else { emit(accessError(.reminder)); exit(1) }
    let reminder = EKReminder(eventStore: store)
    reminder.title = String(args[index+1].prefix(200))
    reminder.calendar = store.defaultCalendarForNewReminders()
    if let due = Double(args[index+2]), due > 0 {
        reminder.dueDateComponents = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: Date(timeIntervalSince1970: due))
    }
    do { try store.save(reminder, commit: true) } catch {
        emit(["error": "Reminders did not save the reminder."]); exit(1)
    }
    emit(["submitted": true, "list": reminder.calendar?.title ?? ""]); exit(0)
}
if let index = args.firstIndex(of: "--complete-reminder"), index+1 < args.count {
    guard let store = eventStore(.reminder) else { emit(accessError(.reminder)); exit(1) }
    guard let reminder = store.calendarItem(withIdentifier: args[index+1]) as? EKReminder else {
        emit(["error": "That reminder no longer exists."]); exit(1)
    }
    reminder.isCompleted = true
    do { try store.save(reminder, commit: true) } catch {
        emit(["error": "Reminders did not save the change."]); exit(1)
    }
    emit(["submitted": true]); exit(0)
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
    let mode = index+3 < args.count ? args[index+3] : "default"
    guard ["default", "window", "tab"].contains(mode) else {
        emit(["error": "Invalid browser placement."]); exit(1)
    }
    // Reuse an already-open tab for the same site instead of opening another window: the
    // same host for a plain site address, the exact address when it carries a query (a search).
    // Fixed application commands only; addresses are quoted data literals.
    func quoted(_ value: String) -> String {
        return "\"" + value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }
    let exact = url.query != nil
    let sitePrefix = (url.scheme ?? "https") + "://" + (url.host ?? "")
    let chromium = ["com.google.Chrome", "com.microsoft.edgemac"]
    if (bundleID == "com.apple.Safari" || chromium.contains(bundleID)),
       !NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).isEmpty {
        let test = exact ? "u is " + quoted(url.absoluteString) : "u starts with " + quoted(sitePrefix)
        let select = bundleID == "com.apple.Safari" ? "set current tab of w to t" : "set active tab index of w to i"
        let source = "with timeout of 10 seconds\ntell application id \"" + bundleID + "\"\nrepeat with w in windows\nset i to 0\nrepeat with t in tabs of w\nset i to i + 1\nset u to \"\"\ntry\nset u to URL of t\nend try\nif u is missing value then set u to \"\"\nif " + test + " then\n" + select + "\nset index of w to 1\nactivate\nreturn {u, count of windows, count of tabs of w}\nend if\nend repeat\nend repeat\nend tell\nreturn {\"\", 0, 0}\nend timeout"
        var failure: NSDictionary?
        if let script = NSAppleScript(source: source) {
            let found = script.executeAndReturnError(&failure)
            if failure == nil, let existing = found.atIndex(1)?.stringValue, !existing.isEmpty {
                emit(["submitted": true, "verification_required": true, "tab_placement": "existing_tab", "reused_tab": true,
                      "browser_observation": ["url": existing, "window_count": found.atIndex(2)?.int32Value ?? 0,
                                              "tab_count": found.atIndex(3)?.int32Value ?? 0]]); exit(0)
            }
        }
    }
    if bundleID == "com.apple.Safari" {
        // Fixed application commands only. The destination is a quoted data literal,
        // never an LLM-supplied script. No System Events or simulated keystrokes.
        let literal = quoted(url.absoluteString)
        // A new window only when asked for (or none is open); otherwise a tab in the front window.
        let commands = mode == "window"
            ? "make new document with properties {URL:" + literal + "}"
            : "if (count of windows) is 0 then\nmake new document with properties {URL:" + literal + "}\nelse\nset current tab of front window to (make new tab at end of tabs of front window with properties {URL:" + literal + "})\nend if"
        let source = "with timeout of 30 seconds\ntell application id \"com.apple.Safari\"\n" + commands + "\nactivate\nreturn {URL of current tab of front window, count of windows, count of tabs of front window}\nend tell\nend timeout"
        var failure: NSDictionary?
        guard let script = NSAppleScript(source: source) else {
            emit(["error": "Could not prepare Safari navigation."]); exit(1)
        }
        let observation = script.executeAndReturnError(&failure)
        guard failure == nil else {
            let number = failure?[NSAppleScript.errorNumber] as? Int ?? 0
            emit(["error": number == -1743
                ? "Allow Safari control in System Settings > Privacy & Security > Automation, then ask again. No fallback tab was opened."
                : "Safari did not confirm the requested window/tab. Check Safari before retrying; no fallback was attempted."]); exit(1)
        }
        emit(["submitted": true, "verification_required": true, "tab_placement": mode == "tab" ? "tab" : "window",
              "browser_observation": ["url": observation.atIndex(1)?.stringValue ?? "",
                  "window_count": observation.atIndex(2)?.int32Value ?? 0, "tab_count": observation.atIndex(3)?.int32Value ?? 0]]); exit(0)
    }
    guard mode == "default" else {
        emit(["error": "Explicit window/tab placement currently supports Safari. No fallback navigation was sent."]); exit(1)
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
    if args[index+1] == "com.apple.Safari" {
        var failure: NSDictionary?
        let script = NSAppleScript(source: "with timeout of 30 seconds\ntell application id \"com.apple.Safari\"\nmake new document\nactivate\nend tell\nend timeout")
        _ = script?.executeAndReturnError(&failure)
        guard script != nil, failure == nil else {
            emit(["error": "Could not open a Safari window. Check macOS Automation permission for Safari before retrying."]); exit(1)
        }
        emit(["submitted": true, "verification_required": true]); exit(0)
    }
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
if let index = args.firstIndex(of: "--observe-app"), index+1 < args.count {
    observedApp = running.first(where: { $0.bundleIdentifier == args[index+1] })
}
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
    if string(focused, "AXSubrole") != "AXSecureTextField" { output["focused_bounds"] = bounds(focused) ?? [:] }
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
