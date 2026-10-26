# Router audit and owner-run pipeline (2026-10-26)

No GPU/Ollama job was run for this audit. No app interaction or companion changes.
The input is the saved 406-row `eval-ollama2.json`, not a new inference result.
Run `.venv/bin/python scripts/router_audit.py` to recreate the complete per-cell
ledger at `.data/training/router/audit.json`. The old result files are unchanged.

## Reviewed baseline mismatches

255 mismatched field cells across 228 rows were reviewed:

| Field | Gold corrected, prediction now right | Scoring equivalence | Model error retained |
|---|---:|---:|---:|
| app_name | 2 | 39 | 92 |
| target | 0 | 28 | 39 |
| acts_on_computer | 11 | 0 | 13 |
| goal_mode | 0 | 0 | 31 |
| Total | 13 | 67 | 175 |

These counts describe **original mismatches**, not total accuracy after relabeling.
There are also labels where the model matched the old, incorrect gold. In total,
38 test-set gold cells change (35 acts_on_computer, 3 contextual app names).
Calendar questions and questions about Mac information are questions, as are
“what do I have to do today” and “what tasks are on my reminders list”. Imperative
“list/read reminders” keeps acts_on_computer=true. `inspect_screen` stays false.
The shared source context is Safari showing Teams Activity: the unqualified Help
link and notification question concern Teams; “type hello” concerns Safari.
A wrong operation does not gain relaxed field credit, including that Help-link row.

Scoring accepts app casing, Teams/Microsoft Teams, an implicit built-in app versus
its correct owner, and Safari versus unspecified browser in these fixtures. A11y
as owner of Mail/Calendar/Notes is still wrong. Target equivalences are scoped:
recent downloads/downloads, this page/empty for read_page, redundant app names in
highlight labels when app_name already names that owner, possessives, movement
“beside the Preview window”, politeness around a full computer task, three reviewed
computer-task paraphrases and the reviewed Peru population topic. Typed text,
note text, reminder titles and URLs/search queries remain exact. Exact field scores
are saved separately from audited scores. Goal-mode mismatches remain model errors:
explicit typing is draft; closing/quitting is inspect under this prompt's default;
run_shortcut retains the existing conservative change label.

## Referents and regenerated corpus

All synthetic families and every source example were reviewed by meaning. Existing
moves stay companion (80 rows); highlighting without activation stays visible_target
(41). Navigating to settings panes, browsing/searching pages, opening files/apps and
focusing apps is destination. Clicking an existing control activates it and is other;
reading information without navigation is other. Source battery-health and browser
history navigation are destination; a notifications question is other.

246 intent rows change other → destination: train 136, valid 48, test 62.
Final intent distribution: other 1,251; companion 80; destination 246;
visible_target 41. Resolver outputs retain their independent `{request: ...}` schema.
Data remains 953 train / 314 valid / 406 test with unchanged family membership and
test row order. Both live_harder.py and live_features.py literals and dynamic
patterns are excluded from training/validation via static AST inspection.

## Adapter failure diagnosis and format fix

Re-derived from `eval-adapter-local.json`: **56 failures**, comprising 45 generic
opening-coverage exceptions, 6 JSON unterminated-string errors, 4 invalid-operation
validations and 1 invalid follow-up response. They cannot honestly be called 56
proven unparseable completions. Every failed output saved prediction={} and omitted
raw text. The six unterminated strings suggest incomplete generation but do not
prove a token-limit hit; prose, repetition or reasoning cannot be classified from
these artifacts. The 45 coverage failures hide the underlying exception. They occur
in a separate schema/classifier call, whose examples are absent from this intent
corpus; pure JSON alone may not fix that classifier's schema adherence.

The cached tokenizer's actual `chat_template.jinja` inserts an empty think block
into completed assistant turns even though generation starts at plain
`<|im_start|>assistant\n`. `enable_thinking=False` does not remove that insertion
from this template. `router_chat.py` now installs plain ChatML for both training
and MLX evaluation, trains only the JSON completion plus `<|im_end|>`, and checks
prefix/mask alignment and the length of every train/validation row before training.
The checked cached tokenizer gives max lengths train 2,593 / valid 2,593 / test
2,634, all below 4,096. Only tokenizer files were loaded for this offline check.
The new MLX evaluator is strict JSON (no think stripping), keeps raw text, token
budget and requested schema for **each** call, including coverage checks, on success
and parse failure. Old base/adapter comparisons must be rerun together with this
renderer; the old MLX figures used a different rendering/parsing policy.

## Run

```bash
bash scripts/router_pipeline.sh
```

The pipeline creates a fresh timestamped run directory; rank 8, 8 layers, <=300
iterations, batch 1, patience 2 and 6,900-second train wall limit; validation selects
`adapter/best`. Every stage runs under nice 19 and verifies effective niceness.
It stops on any command error through pipefail, including tee pipelines. A training
run with no best checkpoint fails. It evaluates MLX, fuses and dequantizes, provisions
llama.cpp and an isolated conversion venv under `.data/training/tools`, converts f16,
quantizes Q4_K_M, copies the installed qwen3:4b-instruct TEMPLATE/PARAMETERS verbatim,
creates only a11y-router-test, inspects its Modelfile and evaluates identical test rows.
Each stage writes `.data/training/router/pipeline-<run>-<stage>.log`; results and data
snapshot are inside `pipeline-<run>/`. Conversion tools may use network; model loads
are cache-only. Existing adapters and app default settings are untouched.
Metal training, fusion, conversion and Ollama registration are prepared, not verified
by execution here. The baseline's actual template is retained for inspection in
`base.Modelfile`; compare it to the ChatML renderer before interpreting cross-runtime
scores if your installed model uses additional wrappers.
