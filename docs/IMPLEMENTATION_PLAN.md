# Implementation pass: coherent onboarding milestone

## Starting point
Four files: PyQt6 transparent draggable animated chameleon with Romanian scripted
steps; independent Romanian browser ticket simulator with fake delayed responses.
No AI, backend, storage, knowledge retrieval, permissions, or dependencies manifest.
Bundled venv contains empty executables and cannot run. Preserve the vector mascot
and browser assets; keep PyQt6 as the desktop stack.

## Milestone
- [x] Shared, Qt-independent Python services and versioned contracts.
- [x] Separate SQLite company knowledge and employee state; role-filtered retrieval.
- [x] Configurable real AI JSON planning with local validation, citations, bounded context.
- [x] Persisted workflows, explicit completion, reopening, and interruption recovery.
- [x] Inspectable explicit/observed/suggested/approved preference layers.
- [x] Native accessible companion panel, existing mascot, opt-in transient capture,
      preview before transmission, expiring click-through guidance, optional read aloud.
- [x] Connect existing browser prototype to shared services as keyboard-accessible
      fallback and local company document manager; remove fake AI.
- [x] Unit/integration checks for safety, retrieval, persistence, provider failures,
      and end-to-end onboarding; document setup and actual limitations.

## Validation limits
38 Python tests and 4 JavaScript controller checks pass. Python compilation and
JavaScript syntax checks pass. Native PyQt dependencies could not be downloaded;
loopback listening was denied; no browser or provider credentials were available.
Actual native rendering/capture/overlay, browser rendering, speech, assistive
technology behavior and live provider responses require target-machine verification.
The milestone is implemented, but these hardware/provider checks remain open.

## Next passes
Native accessibility-tree adapters and active-application identity; native push-to-talk;
production identity/admin authorization and encrypted storage; PDF/DOCX extraction;
embedding retrieval; packaging, cross-platform screen-reader and display testing.

Keep native OS actions user-driven. No tool executor, shell runner, autonomous click,
implicit screenshot, AI-completed step, diagnosis, or silent profile mutation.

## Mascot-first + local-model pass

Implemented a floating conversation bubble as the default entry point, a resumable
local introduction and reviewed preference saving; moved chat/planning/confirmation/
screen-help/adaptation actions into the mascot. Added session-only AI connection
settings, native Ollama /api/chat transport and installed-model discovery; Ollama is
the default provider. Existing compatible APIs remain supported. Character rendering
is replaceable with supplied artwork. 56 Python checks including native offscreen Qt
checks, plus 4 JavaScript checks pass. A live Ollama server/model is still required
for on-device inference validation.

## UI correction and desktop-context pass

Inspected the supplied desktop screenshot: mixed native dark palette/light styles
caused unreadable controls, and the mascot action area clipped buttons. Added an
explicit application palette, a multiline composer and compact content-sized bubble;
rendered and visually inspected both mascot and management panel offscreen.

Added a compiled macOS accessibility/AppKit bridge, session opt-in, two-second
metadata updates, live permission/status UI, inspectable observations and pause.
Model requests carry current context and a bounded in-memory desktop conversation.
Added user-confirmed app switching and native-control highlighting, snapshot-bound
validation, expiry and protected-app exclusions. Native Swift compilation, 69 Python
checks and 4 JavaScript checks pass. Live OS permission/alignment and live Ollama
inference remain target-session checks. No screenshot recording was introduced.

## Character-only idle and settings polish

Removed the persistent floating menu button; added right-click/Shift+F10 and in-bubble
ellipsis access. Collapsed mode now shrinks the native window around only the character,
preserves its desktop anchor, and keeps incoming replies collapsed. Fixed Qt's cached
expanded minimum height so no large invisible desktop hit area remains. Replaced the
management tab strip with sidebar navigation and a rounded surface matching the bubble.
Opening settings collapses chat. Raw profile data and empty suggestion rows no longer
occupy the default preferences page. Rendered/inspected both settings and character-only
states; 72 Python tests pass, including anchor/idle/late-reply/navigation checks.
Continuous vision and expanded movement behavior were explicitly deferred for this pass.

## Real pixel input and compact interaction pass

Replaced the default mascot action dashboard with a compact prompt/reply. Moved task
controls/setup/history to its actual menu; native assist mode can generate a plan from
a natural request. Added one-time session consent for local screen vision, a macOS
ScreenCaptureKit helper that excludes the companion and known protected apps, and a
fresh image on each enabled request. Failed capture aborts inference. Image exchanges
stay in bounded memory and capture is not continuous. Added the model-requested screen
observation tool, retry after approval, and confirmed own-window edge/corner movement.
Both accessibility and visual guidance can move the character beside a control.
Explicit missing-data evidence prevents treating absent AX window data as an empty
desktop. Rendered compact prompt inspected; both native helpers compile. 84 Python
checks and 4 JavaScript checks pass. Real OS permission and live vision quality remain
on-device checks; the old app process must be quit and relaunched to load changes.

## Prompt-only squircle pass

Replaced the compact chat card with a 62-pixel-high, 500-pixel-wide prompt bar and two
36-pixel circular buttons on the left (Send and Settings). Removed all header/status/
vision/menu labels from that surface. Replies and contextual guidance appear in a
separate speech bubble; clicking the character reopens only the input bar. Added Show
last reply to the context menu, retained setup flows, and retained a screen-vision cue
on the settings circle. Rendered/inspected the result and passed 85 Python checks.

## Centered companion layout refinement

Moved Send and Settings outside the input surface into separate 44-pixel circles.
The full 500-pixel controls row is centered below the character; replies sit above
the character. Neutral surfaces, blue primary action, subtle shadows, and visible
keyboard focus replace the green prompt treatment. Preserved setup, character-only
collapse, screen-vision indicator, and anchored resizing. Rendered both prompt and
reply states and passed all 85 Python checks, including placement assertions.

## Smaller prompt and right-side actions

Narrowed the centered controls row to 240 pixels, moved Send and Settings to the
right of the prompt, and reduced the circles to 32 pixels. The 34-pixel input has
semicircular ends and a shorter placeholder. Verified the actual text viewport fits
the font, inspected the rendered state, and passed 85 Python checks.

## Saved introduction in AI context

Fixed missing personal context: reviewed name and work role now reach the model on
every request, scoped to company and employee, alongside effective preferences.
Draft setup answers stay out of context and existing completed records need no
migration. Clarified profile questions in model instructions and provider disclosure
in setup. Passed 88 Python checks; new tests cover restart, identity isolation, draft
withholding and compatibility. Live Ollama response quality still needs on-device QA.

## Unfocused desktop windows

Added bounded, ephemeral Core Graphics onscreen window geometry for nonprotected
apps, including unfocused windows. Updates while the companion is focused; does not
read document contents or capture pixels. Expanded permission copy and model evidence
rules: focused-window metadata cannot establish that another app is hidden, window
candidates can overlap, and precise spatial guidance requires image evidence or an
exact accessible control. Screen-vision consent remains required. Swift typecheck and
90 Python checks pass; live Ollama grounding and target precision remain unverified.

## Guided setup and simpler native navigation

Added `companion/setup_ui.py`: five guided pages for introduction, optional name/role,
working preferences, actual session-permission controls and a final review. Saves
personal details only on review, preserves partial name/role drafts, and records
that the access tour was completed. Existing users see the new access tour once.
Permission buttons reuse the existing consent/OS-permission paths; no permission is
required to finish. Read-aloud availability and missing native microphone input are
explained accurately. No microphone permission is requested for an unavailable feature.

Settings now opens to essentials with identity, model selection, access controls and
mascot visibility. Default navigation contains Settings, Preferences and Saved tasks.
Advanced reveals history, documents, connection settings and desktop diagnostics;
raw profile inspection/reset are also under Advanced. Navigation still resolves to
existing pages, and context-menu actions are reduced. Unified neutral/blue theme
across setup and management UI; mascot interaction remains the primary chat entry.

Rendered welcome, preferences, permissions and Settings screens. Passed 93 Python
checks, including actual Qt setup completion, explicit permission routing, and
advanced-navigation visibility. Actual macOS permission dialogs still require live
on-device testing. The next priority is an end-to-end onboarding workflow with live
Ollama vision and accurate control targeting.

## Consistent access confirmations

Removed duplicate generic Qt permission confirmations during guided setup. Its
explicit Enable buttons now proceed directly to the existing OS-permission path
after the inline explanation. Settings/context-menu entry points retain consent
through a small AccessSheet with consistent typography, spacing, action labels and
Not now cancellation. One-time capture uses the same component and still requires
preview approval before transmission. macOS permission dialogs remain OS-owned.
Rendered the new access dialog and passed 95 Python checks, including duplicate-
confirmation prevention and declined-access behavior.

## Current-request priority and companion movement

Corrected conflicting model instructions that described desktop actions but omitted
that field from the response example. Ollama's schema now requires an explicit
nullable desktop_action. Current natural-language request is placed after context
and history, with explicit guidance that a new movement request replaces previous
button guidance. Removed obsolete UI paths from current instructions and warned
against repeating them from saved assistant replies.

Validated move_companion actions now move the mascot immediately without another
confirmation; movement remains bounded and respects reduced motion. Other actions
retain review/consent. A movement response cannot include a screen target or workflow.
Passed 97 Python checks, including left-then-right movement through the real Qt worker
with a test model provider and rejection of mixed movement/highlight outputs. Local
Ollama was unreachable from this tool environment, so live semantic routing quality
remains unverified. Existing running instances must be quit before relaunching.

## Model-selected movement coordinates and visual objects

Added move_to_point with normalized x/y, explicit screen/image coordinate basis and
an accessible destination label. Model context now includes display and usable bounds.
Image-based point movement requires a supplied image; native UI binds mapping to
that capture's display, checks age/geometry, centers the character on the selected
point and clamps it within usable screen bounds. Added top_left, top_right and center
to the existing destination tool so upper corners no longer collapse into edge moves.

Updated instructions to allow visual destinations such as logos, drawings and text,
including terminal ASCII art: these need not be clickable Accessibility controls.
Without pixels the model should request local screen vision, rather than invent a
logo or direct users to unrelated screen-sharing tools. The model chooses the point;
native code validates and maps it, with no automatic clicking.

Passed 100 Python checks, including both-axis corner placement, coordinate mapping,
image-required validation, invalid coordinates and expired observation rejection.
Actual visual recognition and destination selection by live Ollama remain unverified
from this restricted environment.

## Shared dark UI refinement

Centralized the mascot styles alongside the panel/menu palette in theme.py. Applied
dark neutral surfaces, bright foreground text, blue primary actions, system font,
hover/pressed/disabled states, visible focus, and grouped context-menu sections.
Added small high-resolution painted Send/Settings icons in icons.py. The compact
input keeps vertically centered text and gains a focus border without changing size.

Reorganized Settings into grouped rows with descriptions and compact trailing
buttons instead of full-width actions. Setup and access dialogs use the same theme.
Rendered and inspected Settings, setup/access, prompt/reply and menu appearances;
100 Python checks pass, including retained input geometry and keyboard interaction.
Actual OS-owned window chrome and permission dialogs remain native.

## Grounded action contracts and first computer-use loop

Added model-declared request_kind before action/prose generation. Move requests that
return an observed target box are converted to movement to its visible center, while
highlight requests retain the review flow. Clip valid boxes at the image boundary;
reject pixel/1000-based or wholly offscreen values. Add a bounded correction attempt
using the same frame for invalid contracts/geometry. Keep failed responses out of
storage and execution. Bound recent history and make local context/thinking tunable.

Added computer_use.py and the action worker for confirmed native control presses and
activation followed by fresh observation. Native AXPress checks exact control and
window metadata at execution. Verification mode cannot emit another action and never
marks tasks complete. Added standalone real-model evaluation over eleven annotated
synthetic-screen requests; explicit-double tests separately cover runtime behavior.

Live baseline testing via desktop UI: upper-right movement succeeded; menu-bar-clock
movement reproduced the invalid-bounds failure. Closed that old app before trying to
restart; the desktop tool refused Terminal access, so the updated build could not be
reopened through that tool. Local Ollama was also unreachable from the code sandbox.
The live evaluator attempted a connection and recorded the block, not a passing model
score. Updated GUI execution and model grounding still need on-device verification.
Swift helper compiles. 115 Python checks pass, including execution/re-observation,
no action chaining in verification, stale/paused-control refusal, uncertain-action
nonretry, edge targets, contract repair and actual Qt worker integration.

Next priority: run both models through evaluate_movement.py, then verify one benign
real Accessibility press (for example opening a folder) and fresh post-action screen
evidence before widening the action set. No unverified typing/clicking autonomy is
presented as working.

## App lifecycle and specific-window actions

Separated focus_app, launch_app, new_window, close_window and quit_app. Native metadata
now includes a catalog of normal installed apps and bounded AX window records for
unfocused apps, including title, bounds and close capability. Launch uses a catalog
bundle ID through NSWorkspace, quit requests graceful termination without force,
close_window presses the exact revalidated AXCloseButton, and new_window invokes the
unique unmodified Command-N AX menu action for running Terminal. Other apps' new-window
commands are intentionally unsupported. All app-changing actions retain explicit
confirmation and one-action verification; Terminal's process/unsaved confirmations
are left to the user.

Native model request_kind now identifies the exact app operation, or move_object vs
move_geometry. Semantic validation rejects focus as a substitute for a new window,
opening or quitting, and prevents a no-image object request from inventing a corner
search. Retry errors are action-specific rather than always describing a movement
failure. request_app_access offers a consent path when required metadata is off.

Fixed ScreenCaptureKit enumeration to include hidden companion windows. If its app
is absent, capture only proceeds when window-server checks before and after capture
establish no visible companion windows; otherwise discard. Verification takes a fresh
metadata sample and may explicitly fall back to metadata when pixels fail; ordinary
screen requests still abort instead of answering blindly. No approved action is
repeated because verification capture failed.

124 Python tests pass. Both Swift helpers compile. Added a nine-case real-model app
operation evaluator with synthetic metadata (including the reported user phrases);
its local Ollama connection is blocked in this coding sandbox, so no semantic score
is claimed. Real app-launch, Terminal new-window menu behavior, specific-window close,
and capture exclusion must still be exercised in the relaunched desktop build.


## Browser navigation and confirmed visual clicks — current milestone

- [x] Isolate current-request intent before action grounding; restrict verification
  to observations rather than new actions.
- [x] Resolve common app aliases against the installed catalog and verify launches
  through native process state rather than window visibility guesses.
- [x] Open HTTP(S) websites/search queries in an installed supported browser after
  confirmation, without requiring a screenshot.
- [x] Bind a proposed visual click to a fresh image; preview, confirm, recapture,
  reject changed/expired targets, and submit one native click with no automatic retry.
- [x] Route requests for the companion's own capture control to its reviewed UI.
- [x] Extend the real-model app evaluator to sixteen cases without executing actions.

146 Python tests pass and both Swift helpers compile. The tests cover mocked native
submission and synthetic images, not real-model grounding quality or actual browser
and click execution. Local Ollama remains unreachable from this coding sandbox.
Next priority: run evaluate_app_actions.py and evaluate_movement.py on-device, then
exercise one harmless browser navigation and a confirmed click on a benign control.
Guaranteed new tabs, page reading/DOM tools, typing, scrolling and unattended task
loops remain unfinished. Preserve the one-action observation boundary while adding
these capabilities.


## Browser placement and companion visibility follow-up

- [x] Preserve browser window/tab mode in intent and validated action contracts.
- [x] Treat a complete domain as direct navigation rather than a search query.
- [x] Use fixed Safari window/tab operations; report Automation denial without fallback.
- [x] Open a blank Safari window without screen context; preserve Terminal's AX path.
- [x] Keep the mascot visible on macOS app deactivation; raise it after actions.
- [x] Use the original request to authorize opening/focusing/new windows, retaining
  confirmation for clicks, closing and quitting.

152 tests pass; DesktopBridge compiles. Safari Automation consent and actual new
window/tab behavior still need live validation; tests use explicit bridge doubles.
A companion-drawn pointer can visualize its target, but independent simultaneous
macOS mouse input is not implemented.


## Deeper action checks, pointer and persistent access

- [x] Add opt-in, per-employee restoration for app awareness and screen vision; pause
  also disables restoration. Do not request new OS grants automatically on startup.
- [x] Add an independent, click-through A11y target pointer without moving QCursor,
  respecting reduced motion, expiry, cancellation and own-window capture exclusion.
- [x] Add launcher single-instance locking and visible build/session identification.
- [x] Preserve native browser URL/window/tab observations; do not invent failure from
  incomplete AX window inventory or describe private page content merely to verify.
- [x] Exercise actual Qt request/action/verification workers with one mocked browser
  execution, plus process-lock contention/release, restoration, pause and cursor checks.

165 Python tests pass and both Swift helpers compile. The sixteen-case real-model
evaluator cannot connect to Ollama from this sandbox; no live model score is claimed.
Computer-use inspection of the running Python UI timed out as well. Quit pre-guard
instances once, relaunch, verify the Settings build ID and run the evaluator locally.
Next: validate Safari Automation on the actual Mac, visual target quality, and native
click behavior on harmless controls. A second independent system input device and
unattended action loops are not implemented.


## Bounded general computer-use loop

- [x] Preserve a whole goal across observe → validated action → execute → fresh frame.
- [x] Offer review-each-step and explicit eight-action navigation runs with a Stop control.
- [x] Add one-line Unicode typing, allowlisted keyboard commands, scroll and loading waits.
- [x] Add image-bound left double clicks and right clicks; keep fresh-target rechecks.
- [x] Stop on cancellation, paused access, invalid output, uncertainty, unchanged repeated
  proposals or action limit. Review changes/submissions instead of inferring approval.
- [x] Retain pending compound work; add Music player-state/library playback as one native
  capability, without treating a running Music process as proof of playback.
- [x] Add five-state synthetic real-model task evaluator and actual Qt controller tests.

188 Python tests pass. DesktopBridge and ScreenBridge compile; Music's fixed playback
script compiles against the installed Music dictionary (compile only, not playback).
The new task evaluator cannot reach local Ollama here, so model-quality and native
input end-to-end success remain unverified. Next highest priority: run the task fixture
on-device, then test harmless real navigation with each-step review before automatic
mode. Task-loop persistence/resumption, drag-and-drop, arbitrary key combinations,
page DOM tools and shell execution are not implemented.


## Recurring access and compound browser requests

Identified actual saved preferences with remember=false and both enabled flags false.
Per the employee's explicit request, saved persistent app-awareness/screen-vision
choices for this account; restoration still preflights OS grants on the next launch.
First Enable now remembers access with clear disclosure, and durable consent prevents
repeating the app sheet after pause/re-enable. Explicit restoration opt-out and pause
remain respected. Browser plans with remaining work now enter the task loop with the
full goal, including the reported Teams new-window/new-tab cases.

195 tests pass, covering consent/enable separation, no re-prompt after pause, declined
grants, explicit session-only choices, and Teams multi-step routing. Native code did
not change in this pass. OS permission persistence and live Teams inspection remain
subject to actual macOS grants, authenticated page state and model targeting quality.


## Direct task start and HTTP 400 handling

Removed task start/mode-choice buttons; a request queues automatic navigation after
the current request worker finishes. Stop/replacement cancels the queued start.
Added sanitized Ollama error categories, bounded error reads and accurate HTTP 400
messages. Removed large maxLength constraints only from the grammar sent to Ollama;
local input bounds remain mandatory. Confirmed schema/grammar rejection retries one
inference call in JSON mode with the schema in the prompt; other errors do not retry.

201 tests pass, including the full Qt task loop through automatic startup, cancellation,
worker handoff, schema-only fallback, cache behavior, private-error suppression and
non-schema/second-error nonretry. The specific live HTTP 400 cause remains unconfirmed;
local Ollama access is still blocked. Native helpers were unchanged in this pass.
