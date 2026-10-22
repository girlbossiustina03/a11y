# Architecture and integration contracts

## Boundaries

`a11y_desktop.py` launches the PyQt6 UI in `companion/desktop.py`; the original
character drawing lives in `companion/mascot.py`. `companion/overlay.py` handles
native click-through guidance. `server.py` serves the existing browser assets and
adapts local HTTP requests to the same `Companion` service.

All business logic is Qt-independent:

- `models.py`: v1 identity, target and AI-output contracts and validators.
- `service.py`: prompt/context assembly, access rechecks, orchestration, plan persistence.
- `provider.py`: configurable transport; no UI, database or OS-action access.
- `knowledge.py`: document ingestion, overlapping chunks, filtered lexical retrieval.
- `adaptation.py`: explicit/observed/suggested/approved behavior profile and precedence.
- `storage.py`: two SQLite databases, schema initialization/migration, transactions.

These modules can be owned separately by contributors. Keep model transport changes
inside the provider and native capture/accessibility changes inside UI adapters.
Do not add provider keys, screenshots, or arbitrary executable model actions to state.

## Application calls

`Companion.ask(request, mode='answer'|'plan', workflow_id=None, image_data=None)` returns:

```json
{
  "message": "Accessible explanation",
  "sources": [{"id": "doc-id:1", "document_id": "doc-id", "title": "Onboarding", "ordinal": 1, "content": "Excerpt"}],
  "workflow": null,
  "target": null,
  "effective": {"detail": "balanced", "pacing": "one_step", "input": "any", "reduced_motion": false}
}
```

With explicit planning, `workflow` may be a persisted object containing `id`, `title`,
ordered `steps`, zero-based `current_step`, `status` (`active` or `completed`), source
snapshots, presentation snapshot, timestamps, and user confirmation audit entries.
Each step contains `instruction`, `application`, `keyboard_hint` and `source_ids`.
Clarifying answers may return no workflow. There is no action executor.

A target contains `label,x,y,width,height`. Coordinates are finite fractions of a
single supplied screenshot, **not global desktop pixels**. The native UI maps these
to the captured screen's logical geometry, checks display/task identity and freshness,
and retains the description in its transcript. A highlight suggests a control; it
never verifies task completion. Changing the visible application without recapturing
can invalidate model guidance; the user must review the current screen.

`Companion.state()` returns visible workflows, filtered history, accessible document
metadata, profile layers, effective preferences, local admin capability and AI readiness.
It never returns credentials or images. `Companion.confirm_step(id, expected_step)`
rechecks source access and compares saved progress transactionally. Replayed confirmations
fail rather than advancing twice.

## Behavior profile

Defaults < approved adaptations (only while enabled) < explicit settings.

- detail: `concise | balanced | detailed`
- pacing: `one_step | all_steps`
- input: `any | keyboard`
- reduced_motion: boolean

Observations currently count a small set of English/Romanian style-request phrases.
Two matching requests create a suggestion. Only a user approval makes it effective.
Explicit UI configuration takes effect immediately. Disabling learning also stops
observations and removes approved adaptations from effective behavior. Reset removes
observations/approvals/suggestions/dismissals and retains explicit settings. No diagnoses
or sensitive personal attributes are inferred. This is behavior-profile adaptation,
not model fine-tuning. Future signals must preserve the same approval boundary.

## Local HTTP surface

All `/api/*` requests require the per-launch `X-A11y-Token` embedded in the served page.
Identity/roles come from process configuration, never request bodies.

| Endpoint | Input |
| --- | --- |
| GET `/api/state` | none |
| POST `/api/ask` | request, mode, optional workflow_id |
| POST `/api/confirm` | workflow_id, expected zero-based step as `step` |
| POST `/api/preferences` | explicit `values` object, boolean learning_enabled |
| POST `/api/adapt` | suggestion `signal`, boolean approve |
| POST `/api/reset-learned` | empty object |
| POST `/api/clear-history` | empty object |
| POST `/api/documents` | title, body, roles; local admin required |
| POST `/api/delete-document` | id; local admin required |

The browser API intentionally has no screenshot-upload or arbitrary filesystem route.
Native capture is user-triggered and previewed. UTF-8 documents are capped at 120,000
characters. AI user requests are capped at 6,000 characters; retrieval includes at most
six 1,600-character chunks; workflow output is capped at 20 steps. Model output must
match the allowlisted schema and cite only retrieved chunks. Company workflow steps
require citations whenever relevant sources are available.

## Reference choices

The provider uses the documented [Chat Completions JSON and image-input fields](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
Screenshot mapping follows [Qt QScreen capture and device-pixel-ratio semantics](https://doc.qt.io/qt-6/qscreen.html):
capture one entire screen with `grabWindow(0)` and map normalized results into logical
screen geometry. These APIs still need on-device, multi-display verification.

## Local Ollama and mascot introduction

`ollama.py` uses the native [Ollama chat API](https://docs.ollama.com/api/chat),
[installed-model discovery](https://docs.ollama.com/api/tags) and JSON output format.
The local provider only connects to loopback and excludes cloud-backed models.
Images use Ollama's base64 `images` message field; model capabilities are checked
before screen transmission. Incomplete or invalid outputs fail before persistence.

`onboarding.py` owns the resumable introduction; drafts are in an employee-owned
`introductions` table. Saving maps reviewed answers into explicit preferences.
Name and work role are not sent to the LLM or used as authorization roles. The UI
in `mascot.py` emits action/submit signals to `desktop.py`, which routes real AI
requests through the same shared service. The character renderer is independent.

## macOS context adapter and confirmed desktop actions

`desktop_context.py` owns an opt-in, two-second metadata sampler. The Swift
helper in `native/DesktopBridge.swift` uses NSWorkspace and AXUIElement APIs, does
not read text values/selected text or capture images, caps traversal depth/count/time,
and skips protected apps/secure inputs. Compilation is cached under the data directory.
Observation status, age, permission state, app, window, controls, and running apps go
into `desktop_context` in each model request. Desktop exchanges use a bounded memory
session instead of the persistent conversation table.

`desktop_action` supports `focus_app` with an observed bundle_id, `highlight_control`
and `press_control` with an observed control_id, `request_screen`, bounded companion
destinations, and normalized `move_to_point` destinations.
Validation binds each proposal to the snapshot supplied to the model; application
checks current freshness/observation before acting. Geometry comes from AX, not LLM
coordinates. The native UI requires review for control presses and supports the same actions from
Desktop access without an LLM. No automation capability is exposed by the web API.

Ollama generation is now constrained by `models.RESPONSE_SCHEMA`, followed by local
semantic validation. `theme.py` pins a Fusion palette and explicit text/background
colors across a shared dark companion, panel, setup and menu appearance.

## Request-time visual perception

`ScreenVision` in `vision.py` is session-opt-in and local-Ollama-only. The native
`ScreenBridge.swift` uses ScreenCaptureKit `SCScreenshotManager` on macOS 14+, excludes
the companion process and known password-manager apps, and emits a single in-memory
PNG plus bounded metadata. It has a separate OS-permission request operation. There
is no background screen recording. Failed capture aborts inference instead of giving
the model an ungrounded screen question. `RequestWorker` handles capture before
`Companion.ask`, sends the PNG as image_data, and retains geometry for validated targets.

The v1 desktop_action extension also allows `request_screen` and `move_companion` with
one of seven bounded destinations, plus normalized move_to_point. These are native-only;
movement executes after validation, while screen vision retains explicit session consent.
The former can request session consent and retry the original question with pixels;
the latter only moves the companion's own window. Native prompt mode `assist` permits
model-generated planning when the user requests a plan, with the same step/citation
validation and explicit completion boundary. No string classifier chooses conversation
answers. Missing window metadata is explicitly labeled unknown rather than empty.

## One-action computer-use loop

`computer_use.py` defines the execution boundary: one user-confirmed AXPress or app
activation, then a fresh observation. `ComputerActionWorker` executes outside the GUI
thread. Every press proposal is bound to the observed app/window/control snapshot.
At execution, the Python monitor checks its observation signature and session state;
the Swift helper independently re-reads the target app's focused window and controls,
checks the label, bounds, enabled state and window title, then calls AXPress. Only the
exact confirmed control is pressed. Presses are never automatically retried, including
API timeouts where the app may already have started an action.

The controller follows submission with a request in `mode=verify`, sharing bounded
pre/post metadata and a fresh screenshot when screen vision is enabled. Verification
outputs cannot contain another action, target or workflow. Neither the API result nor
model verification marks workflow steps complete; those remain user-confirmed.
There is no arbitrary shell or unbounded action loop. Text entry and bounded
automatic navigation are implemented by the computer-task layer below. Confirmed pixel
clicks use the capture-bound path described below.

Ollama's schema now decodes `request_kind` before actions/prose. Movement proposals
containing a located box are converted to moving to its center; highlight requests
remain highlights. Valid fractional boxes intersecting an image edge are clipped.
Invalid responses get at most one model correction with the same current evidence;
invalid proposals are neither executed nor persisted. Local context defaults to
16384 tokens with six bounded history messages; context/thinking settings can be
configured through environment variables for model comparisons.

`scripts/evaluate_movement.py` evaluates actual Ollama responses against an annotated
synthetic desktop: four corners, center, clock with/without pixels, Fastfetch Apple
logo, terminal output, close button, and a nonexistent object. It executes no desktop
actions and does not read the user's screen. Tests in test_computer_use.py cover
execution boundaries and repair with explicit doubles; they do not measure LLM
recognition quality.

## App lifecycle extensions

Installed apps are enumerated from normal /Applications and /System/Applications
locations (including Utilities and Finder); background-only apps and protected apps
are excluded. Regular metadata samples include AX window records across running apps,
with stable-per-observation bundle/index window IDs. Window bounds and titles are
rechecked at execution so reordered, renamed or moved windows cannot be closed by a
stale proposal. There is no fallback from close_window to quit_app.

Lifecycle actions pass through the same confirmed ComputerUse executor and verification
worker as control presses. launch_app uses NSWorkspace.openApplication; quit_app uses
NSRunningApplication.terminate; close_window uses AXCloseButton plus AXPress. Terminal
new_window resolves exactly one enabled unmodified Command-N menu item through AX;
no guessed keystrokes or LLM scripts are executed. Native request_kind declares the
requested operation so runtime rejects incompatible action substitution. request_app_access
handles disabled app metadata, separately from screenshot consent.

Screen capture now enumerates all shareable windows, including hidden ones. When the
companion is not listed as a shareable app, before/after CG window checks must show
no visible owned windows or the image is discarded. Verification capture failure can
fall back to fresh metadata with an explicit unavailable-image observation; this never
re-executes the action. Normal screen-dependent requests still fail closed.


## Intent routing, browser URLs and pixel clicks

`request_plan.py` performs a short intent-only model call before grounding. Old
assistant replies cannot select the new operation. The grounding schema is narrowed
to that operation; runtime validation rejects substitutions. Verification accepts
only a message and cannot issue another action. `app_names.py` resolves approved
aliases against the installed catalog, retaining exact-name priority.

Browser intents are compiled into `browse_url` proposals with a supported installed
browser bundle and bounded HTTP(S) URL. The explicit user request authorizes opening. Safari uses a fixed NSAppleScript
window/tab command with a quoted URL data literal and a bounded timeout; model-supplied
scripts are never executed. Other browsers use NSWorkspace URL-open and reject explicit
placement. Automation denial does not fall back or retry. No terminal commands or
arbitrary URL schemes are involved. This is navigation/search, not an autonomous browser agent.

For `click_point`, RequestWorker binds image coordinates to native display ID,
screen bounds, capture time, overlapping window IDs/bounds and a SHA256 hash of
quantized target-area pixel samples. Only these checks, not image pixels, stay in
the pending proposal. The controller shows a highlight and confirmation. ComputerUse
recaptures and rechecks before DesktopBridge submits one CGEvent down/up pair;
the native helper also checks Accessibility permission and current display bounds.
A changed target, paused session or observation older than 90 seconds prevents the
click. Pixel similarity is not semantic proof; the user must review the target,
and there remains a race between observation and event submission.

Launch verification uses a bounded native process lookup including accessory apps,
separates running from visible, and avoids describing unrelated document content.
The companion's own capture command invokes its reviewed capture UI directly.


The mascot combines WindowStaysOnTopHint with WA_MacAlwaysShowToolWindow, preventing
Qt's default macOS Tool-window hiding on deactivation. Action completion raises it
without activateWindow. Harmless opening/focus/new-window proposals run after the
request worker finishes, avoiding an extra approval button and a worker-busy race;
press/close/quit proposals still require review.


## Restorable access, independent pointer and launch identity

`access.py` persists explicit restoration consent and the two enabled access choices
in a separate employee-owned SQLite table. Restoring a metadata session suppresses
AX permission requests; restoring vision uses --check-access/CGPreflightScreenCaptureAccess,
not CGRequestScreenCaptureAccess. Pause writes a disabled choice. Disabling restoration
clears saved choices. No inference or OS-grant presence enables access without consent.
Screenshots remain request-time-only and local-Ollama-only.

`CompanionPointer` is a separate transparent-for-input, non-focusable floating Qt
window with a labelled arrow. Visual target responses position it independently of
QCursor, with animation disabled for reduced motion, bounded expiry and explicit
cancellation. Screen capture excludes all owned windows, including this pointer.
It does not implement an independent OS input device.

`instance.py` holds a flock for the launcher lifetime; a stale lock file does not
prevent relaunch after process exit. Build hashes are computed from Python/Swift
sources at startup and displayed alongside the current conversation session. Old
instances which predate the lock remain outside this protocol.

Safari's fixed command returns current URL and window/tab counts. ComputerUse keeps
the native receipt; browser verification reports URL observations without allowing an
LLM to turn absent window metadata into an invented failure or issue another action.
No screenshot or page-content description is required to verify a URL-open submission.


## Continuing computer tasks and input tools

`computer_task.py` owns a goal, an eight-action budget, cancellation state and bounded
receipts. `propose()` refreshes metadata, captures one frame, supplies only the goal,
recent receipts and fresh evidence to Ollama, and validates one allowlisted action.
The image is passed separately and released; screenshots are not kept in receipts.
A generation change, cancellation or invalid model payload discards the next action.
Repeated identical proposals against an identical frame pause rather than retry.

`TaskStepWorker` performs each observation/model call off the GUI thread. The controller
previews the proposal, reviews it when required, and reuses ComputerActionWorker for
execution. A successful submission records a receipt and schedules a new observation
450 ms later, never another blind action. A task request starts bounded automatic navigation directly, with no start-mode
selector. The per-task automatic flag remains available internally for tests. Model risk=change, Enter/close shortcuts and sensitive
labels pause for review. This risk classifier is not a guarantee of semantic correctness.
Stop is available during inference and execution; late model replies are discarded.
A previously posted native event cannot be withdrawn. Goal sessions are currently
memory-only; saved onboarding workflows keep their separate user-confirmed progress.

`input_actions.py` defines type_text, press_key and scroll contracts. Python binds them
to an observed app/window and, for typing, a focused field's role and bounds. Native
--input independently rechecks the target, refuses secure fields and shell/protected
apps, then emits bounded Unicode keyboard events, allowlisted key pairs or a six-line
scroll at the window center. Unicode chunks preserve grapheme boundaries. Typing never
adds Enter. --observe-app refreshes non-value metadata for the last external app while
the companion has focus, preventing model latency from invalidating stable fields.

`play_media` searches Music's library and only plays a single exact title/artist match;
`inspect_media` reads actual playback state. These use fixed scripts and Automation
permission, not LLM scripts. Verification requires the requested track ID and playing
state. There is no Apple Music catalog search, purchase or silent player substitution.
The intent contract adds remaining_request, media_artist and computer_task so compound
goals and pending work survive app launch rather than disappearing into its receipt.


## Consent and browser-goal preservation follow-up

AccessPreferences records approved app-awareness/screen-vision consent independently
from enabled flags and the restoration switch. First explicit Enable grants opt in
to restoration with disclosed persistent behavior. Pause clears enabled state while
retaining consent, so re-enabling does not repeat the companion's access sheet.
Explicit restoration opt-out remains effective. Existing remembered enabled grants
are recognized as consent for migration. OS permissions are never represented as
app preferences or bypassed.

preserve_browser_goal() promotes browser open/search/new-window plans with a nonempty
remaining_request to computer_task, preserving the complete original user request.
The same normalization applies to interpreted and explicitly supplied request plans.
A Teams-inspection goal cannot be reduced to a successful browser-open receipt.


## Automatic start and structured-output compatibility

Offering a computer task queues automatic startup after the request worker finishes.
The queued callback is bound to the exact pending proposal, so Stop or a replacement
goal cancels it. Only the Stop action is shown during startup. Access failures and
sensitive actions retain their existing handling.

OllamaRequestError carries an HTTP status and sanitized category, never a raw error
body. Error reads are bounded and closed. Large maxLength grammar constraints are
omitted from wire schemas while runtime validators enforce them. Only a confirmed
HTTP 400 schema/grammar rejection retries inference once in JSON mode, with the exact
schema in the prompt and subsequent local validation. Failed inference never submits
a desktop event. JSON-mode compatibility is cached per model/schema; vision/context/
model/memory errors do not silently downgrade or retry.
