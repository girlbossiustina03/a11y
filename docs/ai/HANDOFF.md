# A11y handoff: state of the project (2026-10-26)

Read this together with `AGENTS.md` / `CLAUDE.md` (architecture, ground rules, commands). This file is
what a new session needs on top of those: the owner's rules learned the hard way, what was done
recently, measured results, and what is open.

## The owner's rules (non-negotiable)

- **Local only.** Nothing may call the cloud by default; Ollama on this Mac. Claude is an opt-in
  provider for demos. No cloud APIs in tests or training.
- **Ask before** anything that sends, deletes or changes data outside a test note/reminder/fixture.
  Never message anyone. Never open private apps in tests: Mail, Messages, Photos, Contacts, Teams,
  WhatsApp, FaceTime.
- **No hard-coded per-task phrase lists** ("we still dont wanna hardcode shit"). Fix the mechanism
  behind a class of failures; code-first only for exact, common actions; the model interprets.
- Never give the model shell execution; never bypass target validation. Sensitive changes keep a
  confirmation. AppleScript gets user values as argv only. Screenshots are never written to disk by
  the app. Never commit/log/print API keys (an old screenshot under `.data/live_eval` shows a note
  title that looks like a key).
- **Commits:** straight to `main`, **no Co-Authored-By / AI attribution lines**. Commit and push
  only when the owner asks (releases were requested explicitly).
- **Live tests take over the screen.** Run them only when the owner is away/agrees ("no testing now
  bro", "allow me to use my pc"). Never launch `/Applications/A11y.app` in tests. YouTube is blocked
  on this Mac (Cold Turkey). Test notes/reminders/documents contain "A11y test" + digits and must be
  cleaned up; TextEdit files the test created may be moved to the Trash from TextEdit's iCloud
  folder; any other deletion needs asking.
- Don't stop to wait for the owner when nothing is blocked. Windows is second priority ("skip
  windows for now").
- Heavy GPU work (training/eval) runs at background priority: `nice -n 19 taskpolicy -b …`.
  Note: in zsh, `N="nice -n 19"; $N cmd` does not split — use a bash script or a function.

## Using Codex in this project

`codex exec --sandbox read-only|workspace-write -C <repo> -o <final.md> "<prompt>" < /dev/null`
(without `< /dev/null` it hangs on stdin). `-c sandbox_workspace_write.network_access=true` allows
network/loopback. The Codex sandbox **has no Metal and cannot `nice`/`taskpolicy`**, and the full
unit suite aborts there (exit 134 in an AppKit menu test in `test_native`): GPU jobs, Ollama evals
and the whole suite must be run outside it. Review Codex diffs before committing: it has twice
removed safety guards and edited existing tests to match a behaviour change.

## Recent work (newest first)

| Commit | What |
|---|---|
| 0d88122 | Training tools: router label audit, JSON-only answers, `scripts/router_pipeline.sh` (train → fuse → GGUF → `ollama create a11y-router-test` → eval), grounding scorer + notes |
| 8ed1c8c, a6f3006 | `--suite features` (48 cases): owner-requested behaviours + special input + earlier failures with new wording. **Not run yet.** |
| 31651e4 | Task steps read exact facts (AXDocument/AXURL, Finder target/view/sort, focused element text — never secure fields); a navigation/change "done" needs evidence quoted from facts or OCR (`completion_evidence`); reading goals are exempt as before |
| a0bf6b3 | Router field `referent` (companion / destination / visible_target / other) → `semantic_plan`; highlight safety net kept (`highlight_only`: pointing never activates; closing/quitting never let through); Reminders with a time stay native; open_file also searches the front Finder folder and can read text files |
| 1bd6ba0 | Her cursor (`cursor_flight.py`): ~system pointer size (`CURSOR = 18 * system_cursor_scale()`), parks where it clicked between steps; next flight starts from it; she re-forms (`settle_cursor`) only when `say()` has a non-progress message |
| 9abfa4e | `--suite harder` (30 turns extending passed tasks) |
| 2eac7c0 | Title bar: built app's launcher stamped SDK 26 (`vtool` in `build_macos.sh`; PyInstaller's prebuilt launcher is SDK 12 → old taller title bar); black hairline added to the theme frame (QNSView is flipped; AppKit draws a light edge over content); icon/title on the buttons' centre line |
| 929feb8 | **v0.11.1 released** (macOS DMG only). v0.11.0 = cf8d22b. v0.10.0 still listed. |
| earlier | Menu bar menus instead of right-click on macOS; Terminal-style title bars (icon + "a11y", 💬 reply); traffic lights live (yellow minimises her, green toggles input; on the reply yellow closes, green disabled); clicking her opens chat; all Spaces; follow-up resolver (`resolve_follow_up`) and CHAT_SYSTEM never denying computer use; prototype leftovers removed (workflows, web version, company docs, OpenAI-compatible provider, learning preferences) |

Commits after 929feb8 are **local, not pushed** (as of writing).

## Measured results

**Live suites** (`.data/live_eval/<suite>-N/…/runs.jsonl`):
- broad: 8/29 → 12/33 (before the evidence work). Persistent failures: Calculator conversion,
  Clock world clock/timer, Calendar day/week view, Maps, Dictionary, Finder sort, TextEdit
  formatting, Notes search/delete, Safari find/zoom/private window, Stocks, Font Book, Activity
  Monitor sort.
- conversation: 15–16/17.
- harder-1: 14/28, and that was flattering — "I could not finish" was counted as a pass (fixed in
  a0bf6b3) and the run spanned two builds (the harness now aborts on a build change). Codex's
  diagnosis: routing misreads (fixed in a0bf6b3), Finder not using the front folder (fixed),
  "done" without evidence (31651e4). Not re-measured since: the rerun was stopped by the owner.

**Router** (text model, 406 held-out rows, family-disjoint split, `.data/training/router/`):
- Ollama qwen3:4b-instruct base: operation 94–97%, app_name 66–79%, target 83–86% (labels since
  audited: 13 gold fixes, 67 scoring equivalences, 175 real model errors; 246 referent labels
  corrected).
- MLX base (no JSON grammar): operation 64%, 146 unparseable.
- LoRA (rank 8, 8 layers, 300 iters, MLX): operation 83% with 56 unparseable (≈97% of parsed),
  app_name 82%. Adapter emitted an empty `<think></think>` prefix (scorer now strips it; training
  data now renders JSON-only assistant turns).
- **Next:** run `bash scripts/router_pipeline.sh` (owner must start it or allow it — Claude Code's
  auto-mode classifier blocked it because it clones/builds llama.cpp). Adopt only if
  `a11y-router-test` beats the base through Ollama on the same rows with no safety/operation
  regression. The app's model is not changed by the pipeline.

**Click grounding** (vision, old pilot adapter `.data/training/adapter`, 241 targets / 12 held-out
scenes): base 67% hit (50 malformed) vs adapter 78% (0 malformed) — but among parsed answers the
base is more accurate (85% vs 78%), and the pilot's prompt (0–1000 points, 20 tokens, no system
prompt) does not match the app (click_target numbers / fractional click_point with schema). Not
proven useful. A fair app-like eval and Ollama serving of a Qwen3-VL LoRA are described in
`scripts/grounding_APP_EVAL.md`. More data needed: ~100–200 independent scenes across 15–20 apps,
collected only when the owner's screen is free.

## Open items

1. Run `--suite features` and `--suite harder` (when the owner allows the screen); compare with
   harder-1 and broad-4.
2. Router pipeline (above), then decide adoption; shipping a fine-tuned model to users would need
   distribution (custom Ollama model) — ask the owner.
3. Remaining computer-task weaknesses: menus/shortcuts only used as a stuck fallback; typing not
   tied to a verified field; change goals sometimes labelled inspect.
4. Windows CI: a Qt slot raises `TypeError: <lambda>() missing 1 required positional argument: 'n'`
   during tests (source unknown; `scripts/ci_tests.py` now prints it). Windows releases skipped.
5. Local `packaging/build_macos.sh` with Homebrew Python 3.14 builds an app that crashes on launch
   (missing `language_tags` data under the voice deps); CI (Python 3.12) is fine.
6. Old releases (v0.10.0, v0.11.0) — owner hasn't said whether to delete.
7. Finder Movies/Music/Pictures open action.

## Second machine

The owner has an Arch laptop (RTX 4060, 32 GB). It can help with LoRA training (router, maybe the
click model) but cannot run live tests; data is the bottleneck, not compute.
