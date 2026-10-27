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

### Current evaluation session (2026-10-26)

#### Morning continuation (2026-10-27)

- Owner requested a local commit on main. Review/checks: **913 unit tests passed
  in 87.430 s**, plus four focused router-gate tests after adding per-row
  acts_on_computer regression protection (aggregate gains cannot offset a new
  action-classification error). No model adoption. CUDA script remains experimental;
  the attempted real-tokenizer check had no tokenizer at the selected artifact path
  and did not run. No GPU claims are supported for that draft.
- Owner then authorized roughly **two hours of Mac use while at the gym**. Finish
  the requested commit first; resume local live diagnosis on current code, prioritizing
  Finder navigation and false-negative completion verification. No training contention
  or private-app tests; no push unless separately requested.

- Owner asked about deeper training on Arch, then clarified **“not rn js as an
  idea”**. No SSH connection, remote setup, transfer or training is authorized now.
  A draft `scripts/router_train_cuda.py` was prepared before that clarification:
  offline local-HF QLoRA, assistant-only loss, no truncation, full optimizer/RNG
  checkpoint resume checks, validation-only checkpoint selection, no uploads or
  test-set training. Five pure CPU data/resume tests passed; CUDA/PEFT training and
  VRAM fit have **not** been tested. Treat it as experimental, not a working remote
  training setup. No dependency installation or model download occurred for it.
  Resume this idea only when the owner wants to set up the other laptop.

- Powered training run has **finished cleanly** (guard status complete, return 0).
  It stopped early at the 200-step validation boundary of the 300-step continuation
  (about 500 cumulative steps), rather than running all 600. Current adapter weights,
  validation-selected `best/` weights/config and run metadata are preserved under
  `adapter-resumed-300-ac/`. Read `run.json` for exact zero-based best iteration and
  validation loss. No trainer, benchmark or live suite is currently running. No
  conversion/Ollama comparison has been run for this final candidate, so no adoption
  or desktop-quality improvement is established.

- Owner again authorized completing/running training. Power check: **AC, 14%,
  charging**. Long-paused worker 65130 had exceeded its wall budget and was retired.
  Standalone run restarts from saved cumulative step-300 weights for 300 additional
  steps, output `pipeline-20261027T083701Z-62299/adapter-resumed-300-ac/`, log
  `/private/tmp/a11y-router-r2-powered.log`. Fresh optimizer; same frozen data.
  `training_power_guard.py` records `.data/training/router/r2-powered-status.json`
  and cleanly stops if unplugged at <=25% or its `.stop` file appears. No automatic
  resume, live tests, conversion, benchmark or model adoption is chained.
- Trainer now handles interrupt/termination with an atomic save of current LoRA
  weights and records the last reported step, avoiding loss back to a 50-step
  checkpoint on future clean stops. Base weights are explicitly refused by that
  save path. Twelve focused offline training-tool tests passed; no screen activity.

- Owner's manual session exposed “hey ally” → “Which Safari window: Google or
  GitHub?”. Reproduced locally: raw router correctly emits answer/acts=false but
  referent=companion. `semantic_plan` turned it into movement; service also popped
  the action flag, so revalidation lost the conversation classification. Now an
  explicit non-action answer is preserved and the flag survives revalidation.
  Removed the unrelated Safari clarification example from grounding instructions.
- Evaluation confirmations had persisted into the normal messages table.
  Eval-mode Store history is now session-only, while profiles/consent remain in
  their existing store. All history writes (including confirmed app writes) go
  through this boundary. Six exact test exchanges reported by the owner were
  archived under a separate owner with a 0600 SQLite backup and restoration map:
  `.data/backups/history-before-eval-isolation-20261027T124843Z.sqlite3` and matching
  `eval-history-archive-*.json`. No normal conversation was cleared.
- Chat prompt recognizes A11y/Ally as the same name, and questions about the
  companion no longer trigger low-confidence web lookup. Text-only local check
  (temporary memory-only store, no app access) now greets normally and keeps all
  three reported messages free of desktop actions. The final typo/insult still
  gets an overly literal answer; conversation quality is not fully resolved.
  New source build `c19f557c2b`. Final full suite: **904 passed in 87.517 s**.
  Owner approved relaunch after checks; corrected source launched for manual use
  (log `/private/tmp/a11y-manual-session-fixed.log`). No screen tests or training
  were resumed for this diagnosis.

- Owner reported battery drain. **Trainer 65130 is now SIGSTOP-paused** immediately;
  battery probe showed 39%, discharging. Last printed resumed iteration is 40
  (about 340 cumulative); durable resumable checkpoint remains 300 in
  `adapter-resumed-250/`. `adapter-resumed-300/best.safetensors` is its initial
  validation-selected snapshot, not proof of a newly saved 350-step checkpoint.
  Initial full validation took 366 s; another full validation runs every 50 steps.
  No automatic resume. In-memory unsaved progress and memory allocations remain
  while paused; original wall alarm keeps counting and may expire during a long pause.

- **Immediate correction:** owner meant resume TRAINING, not testing. Capability-4
  was interrupted at startup; no suite result. No live-eval/source app worker was
  present on the follow-up process check. Standalone training restarted from the
  saved cumulative step-300 weights for 300 additional steps, output
  `pipeline-20261027T083701Z-62299/adapter-resumed-300/`, log
  `/private/tmp/a11y-router-r2-resumed-300.log`. Fresh optimizer, same frozen data.
  Internal checkpoint validation only; no live tests, conversion or benchmark jobs
  are chained. This correction supersedes the test-resume entry below.

- Owner authorized **resuming testing** after stopping training. Full capability
  rerun is active, `.data/live_eval/capability-4/` (log
  `/private/tmp/a11y-capability-4.log`): Finder gestures/planning, long conversation,
  and loopback web tasks on current code. Training remains stopped; no adoption or
  training job is authorized by this test-resume request. Source stays unchanged
  during each suite. Native reply-button diagnosis remains open afterward.

- **Owner requested stop and save:** resumed worker 63946 has exited cleanly via
  its stop handler. Latest durable weights are resumed step 50 = **300 cumulative
  steps** (`adapter-resumed-250/adapters.safetensors` and numbered checkpoint).
  Last logged work was resumed step 90; later unsaved updates are not retained.
  Best-validation weights are preserved separately, with loadable `best/` config.
  Safetensors headers/offsets and SHA-256 hashes were checked without loading models;
  `adapter-resumed-250/owner-stop.json` records the actual manual-stop reason (the
  handler's generic run.json calls it a wall-limit stop). Optimizer state is not
  checkpointed. No training, benchmark, conversion or live-test worker remains.
  Resume only when the owner asks.

- Owner subsequently authorized **training only, no testing**. The pause exceeded
  the original trainer's SIGALRM wall budget. Old pipeline PID 62299 and paused
  worker 62307 were terminated, preventing all downstream benchmark/live work.
  Training restarted from saved step-250 adapter weights for 350 additional steps,
  output `pipeline-20261027T083701Z-62299/adapter-resumed-250/`, log
  `/private/tmp/a11y-router-r2-resumed.log`. The same frozen data/config are used;
  optimizer state restarts (not an exact step-290 continuation). Internal validation
  still selects checkpoints as part of training. No conversion, Ollama evaluation,
  or live test is chained to this standalone job. No automatic screen activity.

- Owner needs the Mac and proposed moving training to the 32 GB / RTX 4060 laptop.
  **Round-2 trainer PID 62307 is SIGSTOP-paused**, last logged iteration 290,
  durable checkpoint/best weights at iteration 250. Parent pipeline is waiting;
  do not start another GPU job or resume automatically while owner uses this Mac.
  Pausing stops computation but keeps allocated memory. MLX weights need format
  conversion or a fresh CUDA LoRA run to move to NVIDIA; don't claim transparent
  optimizer-state migration. Handoff previously identifies the other laptop as Arch.

- Owner explicitly requested **training and code improvements together** after the
  measurement queue completed. Router round 2 is now running locally in
  `.data/training/router/pipeline-20261027T083701Z-62299/` (driver log
  `/private/tmp/a11y-router-r2.log`). Fresh adapter, 600 planned iterations,
  learning rate 3e-5, same rank/layers. `router_rebalance.py` resamples only existing
  training rows: 760 action versus 160 non-action examples become 760 each;
  33 resolver examples remain, total 1,553. Validation and test files are byte
  identical to round 1, with hashes recorded. This tests the action-bias hypothesis,
  not a proven improvement. Pipeline now includes the conservative paired comparison.
  Offline cache/no-index environment is enforced; model defaults stay unchanged.
- New code fixes: Qt built-in bound methods (notably reply QWidget.close) now get
  weak callback bindings without throwing TypeError halfway through native title-bar
  setup. Native Control-click no longer opens chat on face or margin. Finder rejects
  a second consecutive slow single-selection of the same observed filename, requiring
  an opening gesture or current-selection verification instead of entering rename.
  Twenty focused input/native regression tests passed. Full suite and two arithmetic-
  only native UI live checks are running; no Finder workflow improvement claimed yet.
- Follow-up verification: full suite **897 passed in 91.888 s**, plus eight focused
  mouse/checker regressions after the final checker adjustment. Round-2 trainer
  completed initial full validation (loss 1.7838, 371 s) and reached iteration 40
  (training loss 0.036); this is progress, not a quality/adoption result. Validation
  at each 50-step boundary is slow and may leave the log quiet for several minutes.
- Right-click stimulus was another harness problem: System Events `click at` can
  act as AXPress despite held Control. `eval_mouse.py` now sends real right-button
  events only after an AX hit verifies the exact owned process; no model uses this
  test helper. Right-click passes live in `ui-fixes-3` and `ui-fixes-4`.
  Reply button test still fails to reliably resolve the native reply window through
  AX (Qt's reply_shown flag is not sufficient evidence of native visibility).
  Padding-safe title lookup is tested but does not resolve that failure; don't mark
  reply buttons fixed. Last isolated rerun: `ui-fixes-5/20261027-104811/`.
  No other live task suite is running alongside training.

- **Queue finished (checked 09:42 +02): no live tests or training are currently
  running.** Harder-3: 9/30 raw passes; capability-3: 12/27 raw passes. These are
  baseline results with known checker faults, not adjusted success rates.
- The reviewed candidate patch was applied by the follow-up driver, build
  `4ab0eb100f`. Full unit suite: **886 passed in 252.903 s**. Targeted features
  rerun `.data/live_eval/features-fixes-1/20261027-093449/`: **2/7 passes** (Maps
  and the second Notes turn). Calculator, Finder sort, first Notes turn and both
  UI checks still fail. Do not claim those mechanisms are resolved; inspect each
  saved observation and app.log next. No further screen automation is queued.
- Paired Ollama comparison completed on the same 406 rows. Operation: base
  373/395 (94.43%), candidate 382/395 (96.71%); app names 303/395 (76.71%) versus
  355/395 (89.87%). However targets regress 356→343 and acts_on_computer
  358→322, with individual operation regressions too. **Do not adopt the candidate**
  on these results. Full comparison: router pipeline directory's `comparison.json`.

- Full features baseline finished on build `b0d3bd000b`: **55 recorded turns,
  11 raw passes, 42 failures, one Spaces skip, one drag awaiting owner confirmation**.
  One pass is the deliberately expected first-turn failure in recovery testing;
  this is not 11 successful computer tasks. Provisional per-turn classification:
  `.data/live_eval/features-2/20261027-075542/diagnosis.json`. Several native checks
  are broken (Calendar menu labels, Finder `name column` enum, right-click script,
  missing reply-window setup); do not silently count those as product successes.
- Harder baseline is running at `.data/live_eval/harder-3/20261027-084508/`.
  A static local queue then runs capability and the paired Ollama router scores,
  serially to avoid GPU contention. Progress/stop file live under
  `.data/live_eval/continuation-20261027/`; it stops at the original authorization
  deadline, 2026-10-27 11:07:56 +02, or if source changes. It performs tests only,
  not unattended code changes. No claim of continuous overnight coding is justified.
- Full current-source unit suite: **871 passed in 93.431 s**. Three conversion
  helper tests also passed separately afterward. Production source is held stable
  during baseline runs. Candidate fixes are staged separately in
  `/private/tmp/a11y-next-fixes-20261027/`: app-opening plan idempotence, Notes title
  duplication, and the verified checker faults. They are **not applied** to the
  running source. Focused staged routing/mac-app tests: 44 passed; five focused
  new regressions passed. Staged full suite: **879 tests passed in 98.430 s**;
  three further checker regressions passed afterward (including compiling the
  control-click AppleScript without executing it). Reviewable candidate files,
  original/candidate SHA-256 manifest and `candidate.patch` are also preserved in
  `.data/queued-fixes-20261027/`. Live revalidation remains required. Do not apply
  during the unchanged-build measurement queue.
- Additional staged correction: final native hit validation now requires the exact
  observed name (Unicode normalization allowed), rejecting prefix collisions such
  as `Report` versus `Report backup.txt` and punctuation collisions. Both planning
  and execution share the same check. 345 related tests passed; final full staged
  suite: **885 passed in 94.110 s**. Four checker tests passed separately after
  adding the empty-AX OCR fallback. Cropped Maps shot `retry_maps_place-1/shot-0009.jpg`
  independently confirms Eiffel Tower details were open; its false result is a
  checker failure, not evidence of failed navigation.
- A second static driver, `.data/queued-fixes-20261027/continue.py`, waits for the
  complete baseline/router queue, checks every original file hash, then applies
  **only the reviewed saved candidate files**, runs the full unit suite, and reruns
  six affected feature groups (including both Notes turns). It never adopts a
  router model or commits. It stops on either queue's `STOP` file, an intervening
  edit, a failed stage, or the same 11:07:56 deadline. Progress is in that directory's
  `progress.json`. This is a fixed validation plan, not an agent reasoning/coding
  unattended. If it has applied files, inspect logs/results before claiming fixes.
- Remaining Finder mechanism, **not fixed**: harder-3 nested-folder frames show
  Recipes selected after two single clicks. Observation then has Finder's detached
  `AXTextField`, parent `AXApplication`, with no focused window bounds. The code's
  Escape recovery is rejected by normal input authorization because it cannot bind
  a window. Do not remove that guard; establish the actual native window first or
  prevent the second selection by correctly using observed `open_target`.
- Completion verifier is also rejecting correct native outcomes (Get Info,
  Preview thumbnails, and several Settings panes). It sometimes demands a literal
  phrase such as “Wireless Accessories” even when Bluetooth is the requested view.
  Preserve independent evidence checks; the fix needs semantic goal criteria and
  exact observed facts, not accepting action submission or removing verification.

- The automated overnight goal reached a **session usage limit** after about 53
  active minutes. Do not describe that as 12 hours of continuous work. The owner
  returned in the morning and correctly challenged that claim. No live suites
  had continued during the gap; the background router job later failed at tool setup.
- Finder source prefix rerun: **6/6 turns across three fresh runs**, build
  `b0d3bd000b`, `.data/live_eval/finder-gesture-repeat/20261026-235636/`.
  Single-click selects the exact folder without a filename editor; double-click
  opens it. Times: single 8.69–8.91 s, double 8.33–8.50 s. This is a two-turn
  diagnostic prefix, not a complete capability-suite score.
- Features full run is now active on that unchanged build:
  `.data/live_eval/features-2/20261027-075542/`. Early Calculator/Clock failures
  route to companion `move_object`; Calendar checks also use obsolete menu names
  `Day`/`Week`, while this Mac's native menu lists `By Day`/`By Week`. Final score
  and per-failure classification are pending; do not count these partials as a suite result.
- Router training actually completed 300 iterations (5,378.5 s including pauses),
  best validation checkpoint at iteration 299, loss 0.020032. MLX result on the
  frozen 406 rows: operation 86.08%, 54 invalid/unparseable results, follow-up exact
  90.91%. This does not establish Ollama quality and no app default was changed.
- Conversion recovery: llama.cpp pins NumPy 2.2.6, incompatible with the repo's
  Python 3.14 tool environment. A separate managed Python 3.13.15 and
  `.data/training/tools/venv-py313/` now satisfy the pinned dependencies. A separate
  `gguf-input/` metadata view translates the exported list-valued special-token
  field for Transformers 4.57; the original fused export stays intact. Vocabulary
  hashes and sample token IDs match exactly between original and conversion views.
  F16 GGUF export and Q4_K_M quantization succeeded; `a11y-router-test` is registered
  in local Ollama. Paired base/candidate scoring is pending; app defaults remain
  unchanged. Reproducible metadata preparation lives in `router_gguf_input.py`
  with offline tests. Pipeline now uses `venv-py313` and fails before training if
  its conversion interpreter is incompatible (override `A11Y_CONVERSION_PYTHON`
  or `A11Y_CONVERTER_VENV` for a different compatible installation).

- **Overnight authorization:** owner subsequently authorized up to 12 hours of local
  code/test/training work and use of the Mac, then specifically prioritized Finder's
  accidental renaming. No commits/pushes, private apps or messaging are authorized.
- Added `--suite capability`: isolated Finder primitives, scrolling/planning, a
  long conversation with ten intervening requests, and a loopback-only web workflow.
  Native state and randomized fixture facts determine success. Build is pure.
- Harness now batches cleanup inventories, retains per-turn plans/events and unique
  screenshot folders, and crops saved evidence to the observed test window. Native
  AppleScript probes lift background I/O throttling only; model jobs stay background.
- Finder investigation: generic AX field focus can enter filename editing. Finder
  item clicks now use real mouse events; explicit requested double/right clicks keep
  their gesture after target selection. Read-only filename editors are cancelled;
  renaming keeps confirmation. Exact native filenames supplement unreliable OCR.
  A final native hit check rejects a different file/menu command under the point.
- Live input probe (no inference): after parking the pointer away from traffic-light
  hover menus, one click selected exactly one folder with AXOutline focus (no name
  editor), then a double-click opened that same fixture folder. Evidence:
  `.data/live_eval/input-probe-1.json` and `input-probe-shots/`. Source end-to-end
  validation is still pending; do not claim the whole Finder workflow passes yet.
- Early capability/gesture runs are incomplete diagnostics. A Cold Turkey crash
  notice and later a window-tiling hover menu contaminated some steps. The harness
  now parks the pointer on the test companion before creating fixture windows.
- Conversation retention is extended to 64 bounded messages (18k-character reply
  prompt limit); explicit older-task references get up to 16 prior user requests,
  not app/screen results. Privacy and distant-reference regressions pass offline.
- Router pipeline running locally at background priority in
  `.data/training/router/pipeline-20261026T211046Z-27265/`; training was temporarily
  suspended during live diagnosis, then resumed. It now scores a fresh Ollama base
  on the identical frozen rows. `router_compare.py` rejects mismatched rows/runtime
  and operation/scope regressions; it never changes app defaults.

- Full unit suite run outside the sandbox: **843 tests passed in 85.966 s**.
- Owner handed over the Mac. Features run started on unchanged build `6fd52462ae`:
  `.data/live_eval/features-1/20261026-225657/`. **Stopped at the owner's request**
  after two recorded failed Calculator cases; this is an incomplete run, not a suite
  score. Harder has not been rerun. Resume live testing only when the owner frees
  the Mac again. Local Ollama forced, web-answer fallback disabled, background
  priority applied. No app code changes or commits in this session.
- Baseline caveat: the available `broad-4/20261026-125053/runs.jsonl` has only
  **21 recorded turns / 8 passes**, not the previously summarized 12/33. Preserve
  that distinction when comparing; do not invent missing records. Harder-1 has
  30 recorded turns including two setup failures, 14 recorded passes; five of
  those passes say “I could not finish”.

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
