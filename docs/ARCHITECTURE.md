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

`desktop_context.py` owns a session-only, two-second metadata sampler. The Swift
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
coordinates. The native UI requires a user click and supports the same actions from
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
There is no arbitrary shell, text-entry, coordinate-click or unattended action loop.

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
