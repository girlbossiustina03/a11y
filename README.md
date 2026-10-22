<div align="center">

# A11y

**An adaptive workplace AI companion with floating desktop presence, computer use, and strict local privacy**

   ![macOS](https://img.shields.io/badge/macOS-000000?style=flat-sqircle&logo=apple&logoColor=white)
    ![Windows](https://img.shields.io/badge/Windows-0078D6?style=flat-sqircle&logo=windows&logoColor=white)
    ![Ollama](https://img.shields.io/badge/Ollama-000000?style=flat-sqircle&logo=ollama&logoColor=white)

</div>

---

## Overview

No mock scripts, no fake demo responses — A11y is an adaptive, privacy-first desktop workplace companion built for the accessibility hackathon. At its core sits a floating, frameless vector mascot that lives unobtrusively on your desktop, paired with a unified Python application service and a real, schema-validated LLM transport (via local Ollama or compatible OpenAI endpoints).

Instead of unbounded autonomous execution or rigid scripted workflows, A11y operates on a strict human-in-the-loop paradigm:
- **Desktop awareness & computer use** — inspects window hierarchies and UI controls via native OS bridges (macOS Accessibility APIs and Windows Win32), proposing single, bounded actions that require explicit human approval.
- **Visual grounding** — takes transient, on-demand screenshots through ScreenCaptureKit to resolve spatial targets, verifying pixel geometry and window hashes before any click is dispatched.
- **Enterprise onboarding & retrieval** — indexes local company manuals with bounded, role-filtered lexical retrieval where every generated instruction must cite an exact source chunk.
- **Adaptive learning** — dynamically learns individual pacing, explanation length, and motor preferences over time, suggesting non-intrusive accommodations that only take effect upon user confirmation.
- **Zero-dependency browser fallback** — a pure Python standard library HTTP server and semantic HTML/JS companion ensures full functionality even without GUI dependencies or native compilation tools.

---

## Architecture & Subsystems

| Subsystem | Platform | Implementation Details |
|---|---|---|
| **Mascot Companion** | Cross-platform (PyQt6) | Frameless, transparent floating widget (`Mascot`) with speech balloon, multiline composer (`Enter` to submit, `Shift+Enter` for newline), collapse-to-mascot state, and custom image overrides (`A11Y_MASCOT_IMAGE`). |
| **macOS Desktop Bridge** | macOS 14+ (Swift) | `DesktopBridge.swift` compiled dynamically via `xcrun swiftc`. Inspects active applications, focused window titles, and accessible UI element trees using `AXUIElement`. Supports window focusing, quitting, and Terminal `⌘N`. |
| **Windows Desktop Bridge** | Windows 10/11 (Win32) | `companion/windows_desktop.py` interacts directly with Win32 APIs via `ctypes`. Queries top-level windows, enumerates Start Menu applications, resolves system utilities (Settings, Notepad, Calculator), and manages window states. |
| **Visual Perception & Clicks** | macOS 14+ | `ScreenVision` captures display buffers via ScreenCaptureKit. Computes normalized coordinates, highlights targets with expiring desktop rings, and enforces click guards (sampling pixels around targets to abort on screen shifts). |
| **Computer Task Engine** | Cross-platform / Native | Multi-step perception-action loop (`ComputerTask`) capped at 8 steps. Observes application context, proposes atomic operations (clicks, text input, navigation keys, scrolling), and automatically pauses before destructive actions. |
| **Lexical Retrieval Engine** | Cross-platform (SQLite) | Chunks imported `.txt` and `.md` documents, extracts heading paths, and performs role-bounded keyword search (`DocumentStore`). Enforces citation verification against source chunks to prevent hallucination. |
| **Preferences & Adaptation** | Cross-platform (SQLite) | Dual-tier profile engine (`ProfileStore`). Tracks interaction counters (e.g., repeated requests for shorter replies) to propose explicit adaptations, while respecting direct overrides and reduced motion. |
| **Instance Locking & IPC** | Win32 / POSIX | Single-instance process lock (`DesktopInstance`) preventing split-brain database corruption using `msvcrt.locking` on Windows and `fcntl.flock` on UNIX. Rejects duplicate launches with active PID diagnostics. |
| **Web Companion Fallback** | Universal (`server.py`) | Zero-dependency HTTP daemon (`SimpleHTTPRequestHandler`) with loopback-only binding, per-launch session token auth, semantic accessibility controls, and Web Speech API synthesis/recognition. |

---

## Platform Support

| Capability | macOS (Sonoma+) | Windows (10/11) | Linux / WSL2 | Browser Fallback |
|---|---|---|---|---|
| **Floating Mascot Companion** | Native transparent window | Native transparent window | Wayland / X11 | Embedded SVG in DOM |
| **Active App & Window Awareness** | Swift Accessibility Bridge | Win32 ctypes bridge | — | — |
| **Window Actions (Focus / Close / Quit)** | Full (`AXUIElement`) | Full (Win32 messages) | — | — |
| **Start-Menu / App Launching** | LaunchServices | Windows Start Catalog / Run | Subprocess | — |
| **Screen Vision & Coordinate Clicks** | ScreenCaptureKit + Click Guard | Target highlights | Target highlights | — |
| **Autonomous Computer Tasks** | Full multi-step loop | Observed window actions | Planning & verified steps | Step-by-step guidance |
| **Text-to-Speech (TTS)** | Qt `QTextToSpeech` | Qt `QTextToSpeech` / SAPI | Speech Dispatcher | Web Speech API |
| **Voice Input (STT)** | — | — | — | Web Speech Recognition |

---

## Features

- **Mascot-first interaction** — The app launches into a compact, floating desktop mascot that stays anchored in the corner of your workspace. Left-click toggles the pill-shaped prompt composer; drag anywhere to reposition.
- **Autonomous computer tasks** — Right-click the companion → **Computer task…** to delegate multi-step goals. The assistant captures the display, selects a structured action (clicking, typing, scrolling, launching apps), executes it, and re-evaluates progress—capped at 8 steps with a hard interrupt shortcut (`⌘.` / **Stop task**).
- **Exact-control confirmation** — Actions that alter system state (pressing buttons, quitting applications, closing windows, entering text) require user approval before dispatch. Unambiguous actions highlight the exact target and display source evidence.
- **Screen vision with click guards** — Request-time display analysis captures a fresh frame via ScreenCaptureKit. Before clicking, A11y re-samples a bounding box around the target; if the underlying window shifted or changed, the click is refused.
- **Enterprise onboarding & cited retrieval** — Import internal Markdown or text handbooks (e.g. `examples/onboarding.md`). Generated onboarding steps must cite an exact chunk from the imported material; uncited claims are rejected by the validation pipeline.
- **Adaptive accessibility profiling** — A11y adapts to how you work. Repeatedly asking for shorter answers triggers a suggestion in **Settings → Preferences** to permanently adopt a concise style. Explicit preferences always take precedence over learned ones.
- **Prompt-only bar & speech balloon** — Normal conversation takes place in a minimalist 240px wide input bar. Replies appear in an auto-sizing speech balloon overhead with text-to-speech support and accessible contrast.
- **Multi-instance locking** — A process-lifetime lock in `%LOCALAPPDATA%\A11y` or `.data/` guarantees only one instance touches the SQLite stores at a time, displaying the active PID and git build ID if a collision occurs.

---

## Run & Setup

Python 3.10+ is required.

### Windows

Run natively with Windows Python (WSLg cannot composite frameless transparent windows properly):

1. Install Python 3.12 (if not already installed):
   ```cmd
   winget install Python.Python.3.12 --scope user
   ```
2. Double-click `run_windows.bat` or run from Command Prompt / PowerShell:
   ```cmd
   run_windows.bat --panel --admin
   ```
   *On first launch, the batch script detects Python, initializes a dedicated virtual environment in `%USERPROFILE%\.venvs\a11y`, and installs `requirements.txt`. Data is kept locally in `%LOCALAPPDATA%\A11y`.*

### macOS

1. Ensure Xcode Command Line Tools are installed (needed for the Swift bridge):
   ```bash
   xcode-select --install
   ```
2. Create virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```
3. Launch the desktop companion:
   ```bash
   .venv/bin/python a11y_desktop.py --admin
   ```
   *Grant macOS Accessibility and Screen Recording permissions when prompted.*

### Linux / WSL2

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python a11y_desktop.py --panel --admin
```

### Browser Fallback (Zero Dependencies)

If native GUI dependencies or Qt are unavailable, launch the pure standard-library web companion:

```bash
python3 server.py --admin --port 8765
```

Navigate to `http://127.0.0.1:8765`. Includes full document management, conversational planning, and Web Speech API support without third-party Python packages.

---

## AI Configuration

A11y supports local Ollama inference out of the box with zero cloud leakage, as well as OpenAI-compatible API providers.

### Local Ollama (Default)

1. Start the Ollama daemon:
   ```bash
   ollama serve
   ```
2. Pull a recommended model:
   ```bash
   # Text and task planning
   ollama pull qwen3.5:9b

   # Multimodal screen vision
   ollama pull qwen3-vl:8b-instruct
   ```
3. A11y scans installed models automatically in **Settings → AI connection → Find local Ollama models**.

### OpenAI-Compatible API

To route inference through an API or remote gateway:

```bash
export A11Y_AI_PROVIDER="compatible"
export A11Y_AI_BASE_URL="https://api.together.xyz/v1"
export A11Y_AI_MODEL="meta-llama/Llama-3.3-70B-Instruct-Turbo"
export A11Y_AI_KEY="your-api-key"
```

*API keys entered via the settings UI remain strictly in memory and are never persisted to disk.*

---

## Controls & Keybindings

| Shortcut / Gesture | Target | Action |
|---|---|---|
| **Left Click** | Mascot | Toggle compact prompt input bar / Read latest reply |
| **Click + Drag** | Mascot | Reposition companion across the desktop |
| `Alt` + **Arrow Keys** | Mascot | Move companion to screen edges / corners |
| `Enter` | Prompt Composer | Submit query or command |
| `Shift` + `Enter` | Prompt Composer | Insert newline |
| `Escape` | Prompt / Balloon | Collapse back to idle companion icon |
| **Right Click** / `Shift` + `F10` | Mascot | Open context menu (Screen vision, Computer task, Settings, Quit) |
| `⌘.` / **Stop Task** | Desktop | Instantly interrupt active autonomous computer task |
| `F5` / **Settings → Panel** | Desktop | Open full settings and document management panel |

---

## Where Things Live

```
~/.local/share/A11y/   (or %LOCALAPPDATA%\A11y on Windows)
├── company.sqlite3            # Imported company knowledge, chunk index, document metadata
├── employee.sqlite3           # User profile, adaptive preferences, saved workflow tasks
├── desktop-instance.lock      # Process lock holding active PID and build hash
└── swift-cache/               # Cached compilation artifacts for DesktopBridge.swift
```

- **Transient In-Memory Data**: Screenshot buffers, ScreenCaptureKit frames, window hierarchy snapshots, and API keys are kept strictly in volatile memory and are cleared on task completion or pause.
- **Repository Data**: When running in development mode, databases default to `.data/` unless overridden via `A11Y_DATA_DIR`.

---

## Verification & Tests

A11y includes an automated test suite exercising core service state machines, schema validators, HTTP transports, and Qt widgets in headless offscreen mode:

```bash
# Run full Python test suite
.venv/bin/python -m unittest discover -s tests -v

# Run JavaScript web companion tests
node --test tests/web.test.cjs

# Verify Python syntax and compilation
python3 -m compileall -q a11y_desktop.py companion server.py
```

### Test Suite Status

| Test Suite | Focus Area | Result |
|---|---|---|
| `test_core.py` | Shared companion service, SQLite transactions, profile updates | 15 / 15 Pass |
| `test_provider.py` | Chat completions, schema generation, JSON repair, tool handling | 18 / 18 Pass |
| `test_ollama.py` | Model discovery, grammar constraints, 400 error fallback | 14 / 14 Pass |
| `test_desktop_context.py` | Accessibility metadata aggregation, window tracking, expiration | 16 / 16 Pass |
| `test_windows_desktop.py` | Win32 ctypes bridge, Start menu enumeration, window actions | 12 / 12 Pass |
| `test_vision.py` | Frame capture, coordinate normalization, click guard validation | 15 / 15 Pass |
| `test_computer_use.py` | Control press validation, UI element verification, bounds checking | 14 / 14 Pass |
| `test_computer_task.py` | Multi-step perception loop, risk pauses, step limits | 16 / 16 Pass |
| `test_browser_clicks.py` | Browser URL opening, domain resolution, tab coordination | 15 / 15 Pass |
| `test_native.py` | PyQt6 widgets, mascot animations, composer keyboard events | 40 / 40 Pass |
| `test_http.py` | Loopback server security, session tokens, content negotiation | 15 / 15 Pass |
| `test_introduction.py` | 5-step guided onboarding, answers persistence, accessibility tour | 12 / 12 Pass |
| `test_access_instance.py` | Process-lifetime file locking, stale lock rejection, build ID | 8 / 8 Pass |
| `test_media_requests.py` | Music player control, track resolution, state queries | 10 / 10 Pass |
| **Total Automated Tests** | **Comprehensive test coverage** | **220 / 220 Passed** |

### Benchmark Evaluators

Standalone scripts under `scripts/` evaluate model grounding without desktop side-effects:

```bash
# Evaluate spatial movement targeting against synthetic SVG scenes
.venv/bin/python scripts/evaluate_movement.py --model qwen3.5:9b

# Evaluate application intent routing against synthetic window states
.venv/bin/python scripts/evaluate_app_actions.py --model qwen3.5:9b

# Evaluate 5-step multi-turn computer task planning
.venv/bin/python scripts/evaluate_computer_tasks.py --model qwen3.5:9b
```
