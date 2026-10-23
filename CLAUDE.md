# A11y: notes for Claude Code

A11y is a desktop accessibility companion: a floating cloud mascot you type or talk to
("Hey Ally"). It answers, reads your Mac apps (Mail, Calendar, Reminders, Notes, Contacts,
Finder, Safari/Chrome pages, Shortcuts) and does on-screen tasks (open apps, click, type,
scroll). Python + PyQt6, with a Swift helper on macOS and native adapters on Windows.
macOS first, Windows second: anything shared must keep working on both.

## Current priority

Make the **local** stack (Ollama, everything on this computer) capable, fast and
*predictable*. Today it sometimes works well and sometimes doesn't: the same request can
route differently, clicks miss, and steps stop early. Reduce that variance:
- Measure with real tasks on this Mac (success rate and seconds per task), not only unit
  tests.
- Move what can be deterministic into code and native tools: the accessibility tree, OCR
  targets, app adapters, AppleScript and EventKit.
- Constrain what the model has to decide. Keep prompts small and stable, so Ollama's
  prompt cache holds.
The Claude provider is an optional extra for demos; nothing may depend on it, and nothing
may call the cloud by default.

You may use the Codex CLI (`codex exec "<task>"`) alongside you: for a second opinion on a
diagnosis, a review of a diff, or a separate investigation. Treat its output like any
other contributor's: verify it, test it, and keep the ground rules.

## Ground rules (from the owner, always)

- Extend, don't rebuild. Preserve working features, access consent, privacy protections,
  keyboard access, reduced motion, company knowledge permissions and citations.
- Never give the model arbitrary shell execution, and never bypass target validation to
  go faster. The model proposes; code validates and executes.
- Sensitive changes (sending, deleting, purchasing, writing to apps) keep a confirmation.
  Plain navigation (open, switch, click to navigate) runs without one.
- **Code first.** If code can do it reliably (arithmetic, clock, reading mail/calendar,
  moving the mascot, opening a named app), code does it with no model call. The model
  understands the wording; code acts. Don't add hard-coded phrase lists where the model
  should interpret. Use a small, exact rule plus the model for everything else.
- Replies: one or two short, human sentences. No "Goal achieved", no "Looks done!",
  no narrating steps. Reading an email or note shows the full text.
- Every change ships with tests. Run the whole suite before pushing.

## Commands

```bash
python3 -m pip install -r requirements.txt -r requirements-voice.txt   # voice is optional
python3 a11y_desktop.py                         # run from source (data in .data/)
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -q   # ~480 tests, ~2.5 min
packaging/build_macos.sh                        # → dist/A11y.app and dist/A11y-macOS.dmg
dist/A11y.app/Contents/MacOS/A11y --self-test /tmp/self-test.json   # packaged-app check
```

Run from source, macOS grants Accessibility, Screen Recording and Microphone to the
*terminal app*, not to A11y. Test permissions with the built app. After rebuilding an
ad-hoc signed app, stale permission entries need `tccutil reset Accessibility com.a11y.companion`.

## How a request flows

`CompanionWindow` (`companion/desktop.py`) → `Companion.prepare_request` (`companion/service.py`),
which tries these in order and stops at the first that applies:

1. arithmetic / clock (`arithmetic.py`) → answered in code
2. "never mind" / "no" → drops the pending proposal
3. "read my (second) last email" → `mail_reader.py` (AppleScript), full text, no model
4. "move to the left / top right" → moves the mascot (MOVE_SELF)
5. bare verb ("Open.", "Click.") → asks "Open what?"
6. "click / tap / double-click X" → computer task (CLICK_REQUEST)
7. "close / quit / switch to X" with one running match → `simple_app_command`
8. "open X" → `quick_open.plan` (installed app → known web app → web search);
   a bare app name ("Microsoft Teams.") → `quick_open.bare_name` (exact names only)
9. otherwise the model routes it: `Planner.interpret_request` (`ollama.py`) with
   `INTENT_SYSTEM` / `INTENT_SCHEMA` (`request_plan.py`). Code then maps mac-app
   operations (`mac_apps.py`), `read_mail`, and so on.

`Companion.ask` turns the plan into a reply and at most one desktop action, validated
in `models.validate_response`. Plan flags `computed`, `full_text`, `read_aloud` and
`app_write` are set only by code and stripped from model output. Multi-step goals run in
`computer_task.py` (observe → act → re-observe, with a bounded number of steps, Stop is
instant). Actions run through `computer_use.py` and the platform bridge:
`desktop_context.py` + `native/DesktopBridge.swift` on macOS, `windows_desktop.py` /
`windows_input.py` on Windows. Screenshots come from `vision.py` (ScreenCaptureKit /
Windows capture) and are never written to disk.

## Where things live

| Area | Files |
|---|---|
| Window, mascot, voice wiring, settings | `desktop.py`, `mascot.py`, `settings_ui.py`, `setup_ui.py`, `readiness_ui.py` |
| Routing, schemas, validation | `service.py`, `request_plan.py`, `models.py`, `quick_open.py`, `app_names.py`, `web_apps.py` |
| Models | `ollama.py` (default, local), `claude.py` (opt-in cloud), `provider.py` (OpenAI-compatible) |
| Mac apps in code | `mac_apps.py`, `mail_reader.py`, EventKit in `native/DesktopBridge.swift` |
| Computer use | `computer_task.py`, `computer_use.py`, `desktop_context.py`, `vision.py`, `windows_*.py` |
| Voice | `voice.py` (faster-whisper, tiny.en wake + small.en), `neural_voice.py` (Kokoro) |
| Consent & storage | `access.py`, `storage.py`, `paths.py` (data dir, saved AI settings) |
| Packaging | `packaging/a11y.spec`, `build_macos.sh`, `build_windows.ps1`, `entitlements.plist`, `self_test.py` |

## Models

- **Ollama (default, everything stays local):** qwen3:4b-instruct for text,
  qwen3-vl:4b-instruct for vision (qwen3:1.7b / qwen3-vl:2b-instruct on low-memory machines). The setup window installs Ollama, the models and the
  voices. Choices are saved in `<data>/ai.json`.
- **Claude Sonnet 5.5 (opt-in):** Settings → Advanced → AI model → paste key → Use Claude.
  It uses the official `anthropic` SDK (2.x), streaming, structured outputs
  (`output_config.format`, schema cleaned by `wire_schema`), prompt caching on the system
  prompt, and the server-side refusal fallback beta. Effort is `low` for text and `medium`
  when a screenshot is attached (`A11Y_CLAUDE_EFFORT` overrides).
  - The key is saved in `<data>/anthropic-key` (0600). `ANTHROPIC_API_KEY` wins.
  - User keys (`sk-ant-usr-…`) need a workspace: fill in the Workspace ID field or set
    `ANTHROPIC_WORKSPACE_ID`. Otherwise every request gets HTTP 400. Normal keys are
    `sk-ant-api…`.
  - On a 400 the provider retries without the fallback beta, then with the schema in the
    prompt, remembers what worked, and prints Anthropic's reason to the log.
  - Privacy: requests go to Anthropic after a one-time disclosure (`cloud_ai`). Screen
    images need their own consent (`cloud_screen_vision`), also enforced in
    `vision.capture`. Local screen consent never counts for Claude. Mail, calendar and
    notes reads stay in code.
  - Never commit, log or print a key.

## Debugging

- Every stage logs `A11y timing {...}` (event, ms, token counts, never prompt text or
  screenshots). From source it goes to the terminal; the packaged app writes
  `~/Library/Application Support/A11y/a11y.log`.
- The build ID tells you what the user is running: the packaged app shows the 10-character
  commit, a source run shows a file hash.
- Clicks on macOS: the bridge activates the target app, then sends move/down/hold/up from a
  `.hidSystemState` event source. Clicking an inactive app's window otherwise gets swallowed.
- Real-world failures go in `tests/test_reported_failures.py`, with the reported
  wording.

## Gotchas that have broken builds

- A `QThread` that is still running when its window is destroyed aborts the process
  silently on Windows, and connecting to a closed localhost port takes about 2 s there.
  Never start a worker in a code path a test can end, unless it is waited for
  (`finish_workers`).
- Widget tests must not touch real apps: `tests/test_native.py` stubs
  `mail_reader.available` and the Swift helper catalog. Keep it that way.
- Packaged app: `certifi` provides HTTPS certificates; the spec copies `opentelemetry-api`
  metadata (the Anthropic SDK needs its entry points); onnxruntime and Kokoro are
  excluded on Windows. The self-test covers HTTPS, Qt, speech, voice and the Claude SDK.
  If you add a dependency, make the self-test exercise it.
- AppleScripts are compiled on macOS CI (`osacompile`). Pass user values as `argv`,
  never by splicing them into script text.

## Release

1. Bump `CFBundleShortVersionString` / `CFBundleVersion` in `packaging/a11y.spec`.
2. Push to `main`. GitHub Actions "Package apps" tests and builds the macOS and Windows
   apps, and runs each one's self-test.
3. When it's green: `gh workflow run package.yml -f release=v0.9.12` publishes the release with
   `A11y-macOS.dmg` and `A11y-Windows.zip`. Optional signing secrets: `MACOS_SIGNING_P12`,
   `MACOS_SIGNING_PASSWORD`.

More history and platform status: `docs/ai/CLAUDE_HANDOFF.md`, `docs/ai/ON_DEVICE_TUNING.md`.
