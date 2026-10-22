# A11y — your workplace, at your pace

An adaptive workplace companion for the accessibility hackathon. Extends the original
PyQt6 desktop chameleon and browser prototype. The vector character is preserved in
`companion/mascot.py` and `index.html`. Scripted task responses have been replaced by
one shared Python application service and an actual configurable AI transport.

## Run

Python 3.10+ is required. Do not use the original committed `venv`: its executables
are empty and its bundled Qt libraries are for Linux. Create a fresh environment:

```sh
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
```

Ollama is the default AI provider. Start it in a separate terminal and keep it running:

```sh
ollama serve
```

Use `ollama list` to check which models you have downloaded. The desktop companion
scans installed local chat models automatically. You can select another in
**Settings → AI connection → Find local Ollama models**, then apply the connection.
If no model is installed, download one with `ollama pull <model-name>` and scan again.
Downloads are not started automatically. Local Ollama requests require no API key.
Cloud-backed Ollama models are excluded. Screen analysis needs a local model with
vision capability; text-only models still support conversation and task planning.

`A11Y_AI_MODEL` selects a specific installed model; `A11Y_OLLAMA_URL` defaults to
`http://127.0.0.1:11434`. To use a compatible cloud/API provider instead, set
`A11Y_AI_PROVIDER=compatible`, `A11Y_AI_BASE_URL`, `A11Y_AI_MODEL` and `A11Y_AI_KEY`.
These can also be entered for the current session in the native AI connection tab.
Keys entered in the UI stay in memory. `.env` files are not automatically loaded.

Launch the desktop app with local document-management permission:

```sh
.venv/bin/python a11y_desktop.py --admin
```

Or launch the browser companion, which needs **no third-party Python dependencies**:

```sh
python3 server.py --admin
```

Open `http://127.0.0.1:8765`. For the browser fallback, set `A11Y_AI_MODEL` to an installed Ollama model before launch. Use `--port 8766` for another port. Without `--admin`,
document management is disabled. Missing AI configuration produces a visible setup
error; document management, preferences and already saved tasks remain usable. There
is no fake AI/demo-response mode.

## Mascot-first interaction

The app now starts with the floating companion; the management panel stays hidden.
He greets you in a compact prompt. The optional local introduction is available by right-clicking the character and choosing Get to know me again. Reply or choose options
inside his speech bubble. Name/role are optional and stay local. Preferences are
reviewed before applying, and an unfinished introduction resumes after restart.

Ordinary conversation and natural-language planning use the compact prompt. Task controls, setup, saved-task selection, read aloud and settings live in the right-click menu or management panel. Right-click the character (or press Shift+F10) for actions and setup; the ⋯ button
inside the open bubble offers the same menu. Settings opens the document/preferences/AI panel.
Closing that panel leaves only the companion running; right-click the character → Quit to exit.
`--panel` also opens the panel at launch. The character toggles chat on click and can
be dragged. The current chameleon remains placeholder artwork pending supplied candy-man
assets; `A11Y_MASCOT_IMAGE=/absolute/path/character.png` loads a transparent image
without changing conversation logic.

The introduction is explicit preference setup. Open-ended conversation, task generation
and company answers are produced by the selected LLM through the shared service.

## Onboarding demonstration

1. Start either UI with `--admin`. In Company knowledge, import
   `examples/onboarding.md` with allowed role `engineering`. This is explicitly a
   fictional company guide; replace it with approved real instructions when ready.
2. Ask “Help me set up my company development environment” and select **Create a
   workflow**. The provider receives retrieved excerpts and returns a validated plan.
   Each company step must cite an actual retrieved chunk.
3. Review the current instruction and company source. Perform the action in its app,
   then select **I completed this step**. Only explicit confirmation advances progress.
4. Ask a question about the active step. The assistant receives saved progress,
   relevant company excerpts, conversation, and your effective behavior preferences.
5. Ask for “shorter answers” twice. Inspect the resulting suggestion in Preferences.
   **Approve** it to apply concise replies to later requests. Alternatively configure
   an explicit setting immediately. Explicit settings override approved adaptations.
6. Quit and reopen. Select the saved task and **Resume**. Progress and approved
   preferences are persisted in SQLite. Text, keyboard and the regular application
   panel work independently of the mascot.
7. In the native app, enter a question about the current screen, choose a display,
   and select **Capture screen once**. After the local permission explanation, review
   the screenshot and approve its transmission. A returned target has an accessible
   textual description; **Show suggested highlight** draws an expiring desktop ring.
   Reduced motion disables mascot animations and movement toward targets.

Browser voice input uses a user-triggered, single-utterance browser speech service
with a 30-second cutoff. Its privacy explanation appears before activation. Review
and edit the transcript before sending it. Availability depends on the browser.
Read aloud uses browser speech synthesis or an installed native Qt speech engine.
Native speech-to-text is not yet implemented. All voice controls are optional.

## What is implemented

- Transparent, floating, draggable native mascot; normal keyboard-accessible companion
  window; show/hide control; Alt+arrow mascot movement; reduced motion.
- Bounded, role-filtered lexical retrieval over imported UTF-8 `.txt`/`.md` documents,
  with document/section references and readable excerpts.
- Configurable real Chat Completions transport, JSON mode, local schema validation,
  unknown-action rejection, provider error handling, and no model tool executor.
- Multiple persisted workflows, ordered user-confirmed progress, duplicate-confirmation
  rejection, sources, and resume across restarts. New plans do not overwrite old tasks.
- Separate explicit preferences, observed style-request counts, pending suggestions,
  and approved adaptations. Inspect, override, disable, dismiss, and reset controls.
  Profile changes use SQLite transactions to avoid lost updates.
- Native opt-in screenshot preview and multimodal requests; normalized-coordinate,
  click-through highlights expire after 10 seconds. Targets expire after 90 seconds,
  or on a task/display change. No automatic clicking or command execution.
- The original browser UI now uses the same backend instead of simulated answers.
  Semantic controls, keyboard focus, status announcements, text alternatives, and
  reduced-motion styles are included.

## Data and scope

Default storage is `.data/company.sqlite3` for company knowledge and
`.data/employee.sqlite3` for employee profiles, conversation and workflows. Change
`A11Y_DATA_DIR` to relocate it. Local files are private to the OS account where
supported, but are **not encrypted**. Conversation is bounded to 100 messages and can
be cleared through either UI. Screenshots and screen-derived answers are not written
to storage; a provider may have its own retention policy.

Company/employee identity and allowed roles are trusted launch configuration through
`A11Y_COMPANY_ID`, `A11Y_USER_ID`, and `A11Y_ROLES`. Retrieval filters company and role
access before building AI context. Saved tasks and conversation sourced from documents
that are no longer accessible are excluded from subsequent state/context loads.
Existing records are retained locally. This is a single-machine prototype, not a
production multi-user authorization system. Do not expose the browser server publicly.
It binds only to loopback, allows only named static assets, checks Host/Origin and a
per-launch session token, and does not log request bodies or activity URLs.

## Verify

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/web.test.cjs
python3 -m compileall -q a11y_desktop.py companion server.py
node --check app.js
```

The Python suite tests the shared services, provider request construction/errors,
and real HTTP handlers through an in-memory socket adapter. Test provider doubles
are confined to `tests/`. JavaScript checks exercise application-controller behavior
with explicit DOM/API doubles. They do not verify actual browser rendering.

Current checks: **85 Python tests** (including 14 real Qt widget/controller checks in
offscreen mode) and **4 JavaScript controller checks** pass. The native tests exercise
the greeting, introduction answers, saving preferences, asynchronous model-backed
planning through a test provider, step completion, collapse/reopen and provider errors.
An offscreen render of the mascot bubble was inspected.

Ollama is installed on the development machine, but no server was reachable on port
11434. Starting it from this restricted tool environment was denied when Ollama tried
to initialize its home directory. Consequently **live Ollama generation has not yet
been verified**. Start `ollama serve` in a normal terminal, install/select a model,
and run the native companion. OS capture permissions, desktop stacking/alignment,
speech and assistive-technology behavior still need hardware verification.


## Ongoing desktop awareness (macOS)

Click **Desktop context off · Enable** at the top of the floating conversation.
Enable it for the session, then briefly focus the app you want help with. A small
native Swift bridge samples the active app, focused window title, and bounded
accessible control metadata every two seconds. This is structured metadata; no
screenshots, document text, field values, selected text, clipboard or keystrokes
are collected. Password-manager apps are excluded. The model receives current
metadata with your questions and retains a short in-memory conversation.

Grant macOS Accessibility permission when requested. Depending on the launch chain,
macOS may name Terminal, Python or desktop-bridge. **Settings → Desktop access** has
an Accessibility-settings shortcut, the exact context the model receives, running-app
selection and observed controls. Without permission the app can report the active
application but may not know window details or controls. Xcode Command Line Tools
are needed to compile the bundled helper on first use; `xcode-select --install`
installs them if missing.

The companion keeps the last external app while you type into its bubble. Control
positions expire after 15 seconds without observing that app again; inactive polling
expires after 10 seconds. Pausing clears context and its in-memory conversation.
Requested task plans still persist as workflow records. Some apps expose limited
accessibility metadata, so image-only questions can still need an optional screenshot.

The model can propose **switch to an observed running app** or **highlight an observed
control**. Only your button click applies it. Highlight coordinates come from the
native observation, and changed observations invalidate the proposal. There is no
LLM-controlled shell, arbitrary click, typing, or automatic task confirmation.

The UI now uses an explicit light palette for consistent macOS dark/light-mode
contrast, a multiline composer (Enter sends; Shift+Enter inserts a newline), compact
controls and content-based bubble sizing. The Swift helper compiles and offscreen Qt
renders were inspected. Live Accessibility permission and desktop alignment still
require testing in your normal desktop session.

## Next priority

Configure an image-capable model and run the entire onboarding scenario on the demo
machine, especially screenshot alignment, OS permissions and keyboard/screen-reader
interaction. Then expand accessibility-tree coverage and add native push-to-talk. Production authentication/admin separation, encrypted storage,
PDF/DOCX ingestion, embedding retrieval, packaging and broader OS support remain future
work. See `docs/ARCHITECTURE.md` for contracts and `docs/IMPLEMENTATION_PLAN.md` for scope.

## Companion-only idle and settings appearance

Click the character, the bubble's minus button, or Escape to collapse chat. The window
shrinks to 166 × 126 logical pixels containing only the animated character; the old
floating Companion menu button has been removed. The character stays anchored while
chat opens/closes. New replies update the hidden conversation without reopening it.
Left-click the character to read the latest reply. Right-click or Shift+F10 opens its
actions; an ellipsis button is also available inside the expanded bubble.

The management panel now shares the bubble's warm colors, rounded surfaces and compact
controls, with sidebar navigation and an explicit Back to desktop button. Opening it
collapses chat, avoiding two competing panels. Detailed learned-profile data is hidden
behind an inspect button, and empty suggestion controls are hidden.

## Fresh visual input and the compact prompt

Clicking the character now opens a small prompt/reply surface, not a second settings
menu. Chat can produce a task plan from a natural request; optional contextual action
buttons appear only for a proposed desktop action or visual guide. The full menu
remains on right-click/Shift+F10/the ellipsis. Explicit setup questions still use
choice controls, and the preferences panel still owns adaptation approval.

The previous metadata-only implementation did not actually show the LLM desktop
pixels. Missing AX window metadata was consequently misinterpreted as an empty
desktop. The prompt now marks missing metadata as unknown, separates running apps
from visible windows, and tells the model to use a real perception tool when needed.

**Right-click the character → Enable screen vision** enables request-time screen vision after explicit
session consent and macOS Screen Recording approval. Each subsequent prompt includes
a fresh display image from ScreenCaptureKit. This requires macOS 14+, Xcode Command
Line Tools, local Ollama, and an installed vision model. No repeated upload/preview is
needed after session consent. The companion and known password-manager windows are
excluded; close other confidential windows before enabling. Known secure-input context
blocks capture. Images are held in memory for the request, never written to disk, and
there is no capture or video recording between prompts. The model may request screen
access itself; approving that tool can retry your original question with an image.

Capture failure stops the model request and shows the error; it does not silently send
a blind question. Model replies based on screen images remain in a bounded memory
session. Pausing clears that session. The native image and capture metadata are
separated: image bytes go through the provider image field, while display bounds,
window hints and capture time supply grounding and guidance coordinates.

The model can propose movement to a bounded desktop edge/corner. Your click applies
it, with a short animation unless reduced motion is enabled. Visual and AX target
highlights can place the character beside the relevant control. These are suggestions;
there is still no autonomous clicking, typing or shell execution.

The ScreenCaptureKit helper compiles and the image-to-model worker pipeline has tests,
including permission/capture failure, local-only routing, pause, memory-only handling
and bounded movement. **Live Screen Recording permission and live Ollama visual-answer
quality still need verification in your desktop session.** Quit the previous running
companion before relaunching; editing Python files does not hot-reload that process.

## Prompt-only bar

Clicking the character opens only a long rounded input bar. Two circular controls sit
outside its right edge: Send, then Settings. The controls and prompt form a compact
240-pixel-wide centered row below the character, with a 34-pixel-high pill input and
32-pixel circular buttons. There are no headings, status labels, screen buttons,
or action menus inside this bar. Settings opens the management panel; right-click or
Shift+F10 on the character opens additional actions, including screen vision.
Assistant replies appear in a separate speech bubble above the character when they arrive.
Reopening the prompt does not reopen an old reply; Show last reply is in the context
menu. The settings circle gains a green outline while local screen vision is enabled.
The entire UI still collapses back to just the character. The rendered prompt-only
state was inspected and 85 Python checks pass.

Saved introduction details (name and self-reported work role) are included in AI
requests alongside current effective preferences. Draft answers are withheld until
reviewed; restarting setup keeps the previously approved details until the next save.
These details go to the configured provider, so Ollama keeps inference local while a
configured remote provider receives them. Existing completed introductions work
without repeating setup.
