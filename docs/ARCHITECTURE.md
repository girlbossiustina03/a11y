# Desktop architecture

A11y is a Python/PyQt6 desktop accessibility companion for macOS and Windows.
`a11y_desktop.py` starts `CompanionWindow`; both native macOS windows and the
frameless Windows/offscreen interface share `Companion` orchestration.

## Request boundary

`Companion.prepare_request` resolves arithmetic, clock, direct mail reads, mascot
movement, exact app commands and quick opening in code before consulting the intent
router. `request_plan.INTENT_SCHEMA` limits model decisions to supported operations.
The router receives reviewed `user_profile`, explicit explanation/pacing settings,
current time and front app. Previous requests are included only for references back.

`Companion.ask(request, mode='answer'|'assist'|'verify', image_data=None)` returns
`message`, `desktop_action`, `target` and `effective` preferences. Built-in mail reads
also set `full_text` and `read_aloud`. Only code may set trusted execution flags.
`models.validate_response` enforces the response shape, finite coordinate bounds,
current desktop observations, and allowlisted actions. Model proposals never execute
arbitrary shell commands. `request_plan.enforce_operation` prevents a grounding
response from changing the chosen operation.

## Computer tasks

Executable goals use `ComputerTask`, `Planner.plan_task`, `start_task` and the
Computer task / Stop computer task menu controls. The bounded loop observes, takes
an exact deterministic step when possible, otherwise asks the model with one image,
OCR and accessibility targets, validates, executes and observes again. Invalid
proposals get a bounded repair attempt. Stop cancels inference and blocks late actions.

Native control IDs and numbered OCR/accessibility targets bind actions to observed
controls. Pixel clicks retain display geometry, age, window and region hash guards.
Typing binds to the foreground non-password field; protected apps stay blocked.
Navigation runs directly; sensitive changes retain user confirmation. Submission is
not proof of success: fresh observations verify results. CompanionPointer and the
guidance overlay show reviewed targets without activating them.

## Privacy and state

`access.py` stores explicit consent and pause/restoration choices. App awareness,
screen vision, microphone and Claude screen sharing have separate controls.
Screenshots are transient and never written to disk. Screen/app-derived exchanges
stay out of persistent history; mail text is shown whole but memory retains only its
first line. Pausing access clears private in-memory context. Cloud conversation
filters private turns.

`storage.py` keeps history, access preferences, explicit settings and reviewed setup
profiles in `employee.sqlite3`. Identity retains its original company/user key pair
solely to preserve storage ownership. Existing files and retired SQLite tables are
left intact. Legacy history rows tagged with document dependencies remain hidden;
the app never replays them or opens the retired document database. New history rows
carry no document dependencies.

`preferences.py` applies defaults plus explicit user choices for explanation detail,
pacing, keyboard navigation and reduced motion. Existing learned profile fields are
preserved as data but never applied. `onboarding.py` and `SetupDialog` preserve draft
versus reviewed personal details; drafts never enter model context.

## Models and platform adapters

Ollama is the local default; ambient remote-provider credentials never select cloud
inference. Claude is opt-in, uses the Anthropic SDK and requires its disclosure and
separate screen consent. `provider.py` retains shared AIConfig, ProviderError and
NoRedirect; transports live in `ollama.py` and `claude.py`.

macOS uses `desktop_context.py`, Swift Accessibility/EventKit and ScreenCaptureKit,
plus argv-based AppleScript app readers. Windows uses Win32/UI Automation, GDI,
Windows OCR and validated SendInput. Windows hardware behavior still needs real
validation; automated doubles do not establish desktop success.

## Validation

Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -q`.
`scripts/ci_tests.py` reports failures and crashes in CI. The `live_*` suites measure
real app outcomes and latency on the host; synthetic `evaluate_*` scripts and
`benchmark_pipeline.py` remain diagnostic tools. See `CLAUDE.md` and
`docs/ai/CLAUDE_HANDOFF.md` for commands, platform gaps and measured history.
