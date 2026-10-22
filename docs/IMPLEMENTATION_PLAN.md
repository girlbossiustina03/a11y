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
