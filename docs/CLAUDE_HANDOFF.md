# A11y handoff for Claude

## Main instruction: support macOS AND Windows

Extend this repository; do not rebuild the product or replace working components.
**Every desktop improvement must account for both macOS and Windows.** Implement
shared orchestration, schemas and UI once, behind explicit platform adapters. Add
the corresponding native implementations and tests for both systems. If a platform
cannot support a capability yet, report that accurately and provide a usable
fallback. Do not present macOS-only computer use as cross-platform functionality.

## Immediate assignment: make existing computer use faster and more reliable

The user wants the companion to actually operate applications, rather than explain
what the user should click. Improve the **tools, observations, schemas and execution
loop already implemented** so the assistant completes real tasks with less waiting
and fewer wrong actions. Start implementing after inspecting the current code.

Prioritize a coherent result over adding more disconnected features. This is not a
request for more app-name rules, canned responses or a different mascot. Keep the
LLM responsible for interpreting goals and choosing actions, with deterministic
validation and platform tools responsible for safe execution.

### What success should look like

- A read-only goal such as “open Teams in a new Safari window and see whether I have
  tasks” opens the requested destination and continues inspecting it. It does not
  stop after opening Safari, navigate to an unrelated composer, or ask whether to
  perform steps already authorized by the request.
- Ordinary navigation clicks run without an extra confirmation button. Sending,
  submitting, deleting, purchasing and sensitive changes retain appropriate review.
- A screenshot/observation is refreshed after actions. Missing accessibility labels
  do not prevent a properly grounded visual click.
- Users can stop a task promptly. Slow or cancelled inference must not trigger a
  late click, and old requests should not monopolize the local model indefinitely.
- Responses shown by the cloud and History agree. Submission is distinguished from
  observed success. “Show/mark where” highlights a target without activating it.
- Measure latency and targeting accuracy on real tasks on **both platforms**.
  Unit tests with doubled model/native responses do not prove live reliability.

## Product and stack

A workplace accessibility companion: floating cloud mascot, text interaction,
optional speech output, company document retrieval, explicit/adaptive preferences,
saved workflows and desktop guidance. Normal use should happen through the mascot.

- Python / PyQt6 desktop entry point: `a11y_desktop.py`.
- Shared service and SQLite stores: `companion/service.py`, `storage.py`,
  `knowledge.py`, `adaptation.py`, `onboarding.py`.
- No separate backend is required for desktop use. `server.py` and the HTML/JS files
  provide the browser fallback; preserve it.
- Default data directory: `.data/`, configurable with `A11Y_DATA_DIR`.
- Windows launcher uses a local Windows venv and `%LOCALAPPDATA%\A11y`.
- Current local model used by the user: `qwen3-vl:8b-instruct` via Ollama.
- Keep provider/model configuration in environment variables/settings. No embedded
  API keys, automatic cloud fallback or unrequested model downloads.

## Read these files first

| Area | Files | Why it matters |
|---|---|---|
| Request routing | `companion/request_plan.py`, `service.py` | Intent, full-goal preservation, deterministic app/browser shortcuts, validation and verification |
| Task loop | `companion/computer_task.py` | Scope classification, fresh observations, text/image decision paths, repair budget and review rules |
| Model transport | `companion/ollama.py`, `provider.py` | Local inference, output budgets, schema handling, provider errors and timing |
| Desktop controller | `companion/desktop.py` | Qt workers, action scheduling, UI state, cancellation, shared cloud/History messages |
| Screen context | `companion/vision.py`, `desktop_context.py` | Permission state, transient captures, native adapters and click guards |
| macOS tools | `native/DesktopBridge.swift`, `native/ScreenBridge.swift` | AX/window metadata, app/browser actions, input, capture and OCR |
| Windows tools | `companion/windows_desktop.py`, `windows_screen.py` | Win32 app/window actions, Start-menu catalog and GDI capture |
| Input/execution | `companion/input_actions.py`, `computer_use.py`, `models.py` | Allowlisted input, observed target binding, executors and schemas |
| UI | `companion/mascot.py`, `overlay.py`, `settings_ui.py`, `theme.py` | Mascot, rounded menu, white pointer/highlight, compact settings |
| Notes/tests | `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAN.md`, `tests/`, `scripts/evaluate_*.py` | Existing contracts, change history, regression coverage and model evaluation fixtures |

Read the actual code when notes and implementation disagree. The implementation
plan includes historical milestones and limitations, not a guarantee that every
previously attempted live scenario works.

## Current execution path and contracts

1. `OllamaProvider.interpret_request` produces a structured intent. Simple app and
   browser requests can use direct native tools. A small coverage check protects
   against silently dropping follow-up work.
2. `preserve_desktop_goal` routes compound desktop goals and direct click/control
   requests into `ComputerTask`. A compatibility alias retains the former
   `preserve_browser_goal` name.
3. Tasks classify the goal once as `inspect`, `draft` or `change` when the provider
   supports this classifier. Inspection rejects compose/post/send/change proposals,
   including actual AX/OCR labels under model-selected coordinates.
4. The task obtains current desktop metadata and one transient screenshot. macOS
   can return OCR text rectangles from the same frame. The app excludes its own
   windows; sensitive/protected app checks remain important.
5. When OCR or supported AX evidence is available, the first model call is text-only.
   It can select an exact control ID or a point grounded in a text/control rectangle.
   Missing visual detail returns `needs_vision`; ungrounded points or uncertainty
   fall back to a full image. When there is no fast evidence, use the image path.
6. The structured schema separates action responses from terminal responses:
   `status=action` requires one operation; `done`/`needs_user` require `action=null`.
   The fast schema also allows `needs_vision` with a null action.
7. At most two decision calls are allowed per observation, shared between correction,
   pause reconsideration and image fallback. Invalid proposals are never executed.
8. The GUI executes approved navigation automatically, then schedules another fresh
   observation. There is a 24-action bound and visible Stop control / `⌘.` shortcut.
9. Clicks retain capture age, display geometry, target-region hash and window checks.
   Input is rebound to a fresh observed app/window/focused non-password field.

Useful actions currently include `browse_url`, `launch_app`, `focus_app`,
`new_window`, `press_control`, `click_point`, `type_text`, `press_key`, `scroll`,
and `wait`, subject to platform support. Avoid assuming that schema availability
means every platform adapter implements an action.

## Important platform gaps

### macOS

- Uses Swift Accessibility/Quartz/ScreenCaptureKit helpers compiled with Xcode tools.
- Safari URL navigation distinguishes requested new windows and tabs. Preserve this.
- Native mouse clicks, observed AX presses, keyboard shortcuts, focused text input
  and vertical scrolling are implemented, with target checks.
- Request-time OCR now uses Vision `.fast`, with `.accurate` fallback specifically
  when the fast recognizer returns `VNErrorNotImplemented`.
- The new OCR helper compiles, but its offline synthetic-image probe failed in the
  restricted coding environment. **Native OCR runtime performance is unverified.**
  AX text-only decisions and image fallback remain available.
- A11y settings highlights use a small selector over actual Qt section IDs and
  current Qt bounds, since screenshot capture intentionally excludes A11y's windows.
  Do not “fix” this by hallucinating controls from a screenshot that excludes them.

### Windows

- Win32 window metadata, installed-app resolution, Store/Start-menu apps, launch,
  focus, observed close and graceful quit are implemented.
- Request-time GDI screen capture and own-window exclusion are implemented. Permission
  checks must not take a screenshot. Known protected windows block capture.
- **Coordinate clicks, keyboard/text input, AX/UI Automation control presses and OCR
  parity are not implemented in the current Windows adapter.** These are major gaps
  for the requested macOS/Windows outcome. Implement and validate them explicitly.
- Windows runtime has not been exercised by this coding environment. Test with real
  Windows apps, DPI scaling, multiple monitors and foreground/focus changes.

## Observed bottlenecks and suggested priorities

Real user logs showed capture around **0.14–0.18 s**, while image/prompt processing
often took **8–11 s per step**, followed by roughly **1–2 s** generating a short answer.
An earlier request generated 3,000 tokens and failed after about 83 s. The recent
task path caps output at 1,200 tokens and requests thinking off when supported.

These are observations from prior runs, not measured performance of the latest OCR
path. Logs emit `A11y timing` records without screen/prompt/model content.

1. **Benchmark the current pipeline before changing it again.** Measure cold/warm
   classification, metadata, capture/OCR, text/image inference, validation, execution
   and verification separately. Include p50/p95 step latency and task success rates.
2. **Make fast grounding genuinely work on both OSes.** Evaluate native accessibility,
   Windows UI Automation, native/available OCR and targeted image fallback. Do not
   bypass coordinate/focus validation for speed. Reuse native tools where they work.
3. **Improve tool/schema design.** Keep status/action combinations consistent, expose
   only platform-supported tools, avoid large generic grammars when a small tool
   set suffices, and give bounded actionable feedback for rejected proposals.
4. **Reduce inference overhead.** Review redundant intent/coverage/scope passes;
   preserve full goals while consolidating where justified. Current prompt packing
   removes old before/after snapshots, redundant visual window lists and unused
   receipt data; it puts the stable goal/app catalog before changing observations.
   Verify actual prompt-cache behavior instead of assuming it improves latency.
5. **Support prompt cancellation properly.** The current cancellation checks prevent
   subsequent execution, but the non-streaming Ollama HTTP request may continue
   consuming time/model capacity. Investigate cancellable streaming or transport
   cancellation with honest UI state and no late actions.
6. **Use structured browser information where appropriate.** Evaluate tools such as
   Playwright/CDP or browser-use behind a browser adapter, rather than guessing every
   web control from pixels. Check current browser compatibility and permissions.
   Preserve requested Safari window/tab behavior and the user's authenticated session;
   do not silently replace their browser/profile or move data to a hosted service.
7. **Review model suitability after tool improvements.** Compare installed/configured
   models with the same fixtures and latency measurements. Do not claim a larger
   model or another runtime is faster without measuring it on the target machine.

## Current local changes in this implementation pass

These changes followed merged commit `f576bfc` (PRs #2/#3 plus earlier task/UI work):

- Corrected contradictory status/action schemas and added one bounded repair attempt.
- Added goal-scope checks, smaller task context, native OCR and text-first grounding.
- Unified cloud/History messages and removed duplicate action narration and false
  claims that ephemeral computer-task progress had been saved.
- Added own-settings highlights via Qt bounds and stronger highlight-only intent.
- Simplified settings and Advanced pages, added keyboard-accessible disclosures,
  scrolling and real resize support; removed the bottom status bar/divider.
- **Latest preference: Advanced stays at the bottom of navigation.**
- Startup is mascot-only. Saved screen access restores silently; it must not replace
  a conversation or open the “Screen vision is on…” prompt every launch.

Keep the current visual direction: dark settings, rounded popup with transparent
corners, small white pointer without the blue badge, and one thin white highlight.
The mascot is a white cloud; the user may provide different assets later.

## Validation status: be precise

- Latest full automated run: **262 Python tests passed**; **4 web tests passed**.
- Python compilation and the Swift ScreenBridge compilation passed.
- Tests include actual Qt workers/UI sequencing, but model responses and OS action
  submission are doubled. They do **not** prove real Teams/Calculator/TextEdit success.
- The synthetic native OCR runtime probe failed here; both fast and accurate paths
  remain unverified on the user's host. No live speedup is established.
- Tools in this environment could not connect to the user's local Ollama listener.
- Real Windows input/capture validation is still required.

Add meaningful integration/regression tests for failures actually reported:

- Teams task/activity inspection must not select “Post in channel.”
- “Open Calculator and sum 2+2” must continue after app launch.
- “Open Notepad and write a summary” must create/focus an editor and draft text.
- Highlight a Terminal close button without closing it.
- Highlight A11y's Desktop tools using its actual settings geometry.
- Stop during inference/verification, foreground changes, stale targets, missing OCR,
  icon fallback, malformed outputs and permission pause/restart.
- Verify Windows equivalents rather than skipping them under a macOS-only success claim.

## Run and test

Quit the running companion from its mascot menu before relaunching. A background
launch command returning zero does not prove a new process loaded new code. Compare
the startup build ID in the log with `companion.instance.build_id()` when uncertain.

```sh
# macOS, foreground (useful while debugging)
A11Y_AI_PROVIDER=ollama A11Y_AI_MODEL=qwen3-vl:8b-instruct .venv/bin/python a11y_desktop.py --admin

# App logs when using the user's nohup launcher
tail -f /private/tmp/a11y-desktop.log

# Automated checks
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -q
node --test tests/web.test.cjs
.venv/bin/python -m compileall -q companion scripts a11y_desktop.py server.py

# Synthetic model evaluation; does not operate the actual desktop
.venv/bin/python scripts/evaluate_computer_tasks.py --model qwen3-vl:8b-instruct
```

```bat
rem Windows: use native Windows Python, not a WSL GUI session
run_windows.bat --admin
```

The Swift `ScreenBridge` also accepts `--ocr-image <fixture.png>` for an offline
OCR probe without screen capture. Use annotated/synthetic fixtures, and distinguish
that diagnostic result from actual application task completion.

## Collaboration and non-negotiables

- User wants commit/push **one-liners**; do not push directly. Inspect git status and
  preserve all working changes. Do not reset or replace teammates' work.
- Do not claim a task completed from app launch acceptance, a URL receipt or an
  invented model description. Verify the relevant outcome using fresh evidence.
- No arbitrary LLM shell commands, password entry, secret/clipboard capture or
  continuous screen recording. Do not persist screenshots/OCR unnecessarily.
- Preserve consent, access pause/restoration, keyboard alternatives, reduced motion,
  source access/citations and the separation of company knowledge from preferences.
- If an external dependency is useful, integrate it behind a small tested adapter;
  do not add a new heavyweight agent framework just to wrap existing functionality.
- Start with a short concrete implementation plan, implement it, and report the
  measured results and remaining gaps honestly. The main goal is **faster, more
  capable, reliable computer use on macOS and Windows**, not another UI-only pass.
