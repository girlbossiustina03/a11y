# Grounding pilot versus the app (2026-10-26)

This is a read-only comparison of code and stored results. No capture, inference,
training, fusion or model registration was run.

## What the stored score measures

Both result files have the same data SHA256 and 241 targets in 12 held-out scenes.
Base: 162/241 = 67.22% with historical ±5 tolerance; strict 66.39%; 50 malformed;
304.68 s. Adapter: 188/241 = 78.01%; strict 76.76%; 0 malformed; 363.61 s.
That is +26 hits / +10.79 percentage points, with slower total generation.
Targets within a scene are correlated. These figures establish a gain on the old
point-format task, not an app action-success gain. In fact, among parsed answers,
base hits 162/191 = 84.8% and adapter 188/241 = 78.0%: format compliance accounts
for much of the aggregate difference; these different subsets are not a paired
localization comparison. The parser is permissive (can extract two numbers out of
prose); malformed means “no pair found”, not “violated an app JSON schema”.

`grounding_eval.py` sends the stored user sentence via the VL chat template:
“Find the link/button labelled … Reply with its center as (x, y), each from 0 to
1000.” It generates only 20 tokens, without the app's system prompt, step schema,
current observation, tool metadata, task history or JSON grammar. Its units are
normalized 0–1000; a tolerance of 5 equals 0.005 of the image per axis. Short 20-token
limits can penalize a base that emits prose or reasoning before coordinates.

The app's `companion/computer_task.py` instead sends its computer-task system prompt,
goal and observation through the provider, with a structured action schema:

- `click_point` has fractional image x,y, **0 <= value < 1**, plus the exact visible
  target label. Pixel guesses are a fallback for targets absent from the catalog.
- `click_target` identifies an observed **numbered target** via target_id; IDs are
  constrained to the current catalog. Code resolves the center exactly. The model
  does not emit 0–1000 coordinates for these actions.
- `visual_context.targets` lines are `id|kind|label|x,y` with fractional centers;
  OCR text regions and native controls are also supplied. Deterministic target
  resolution can precede the model. Screenshots use the app's capture scaling;
  labels may then snap clicks to text. Validation and execution are additional gates.

Thus the old prompt and coordinate output do **not** match deployed use.

## Fair app-like offline comparison

Freeze an independent scene-disjoint set and a separate checkpoint-selection set.
Reuse the same stored image bytes and record display/image dimensions and app-like
scaling. Export permissioned observations in a later owner-controlled collection;
old PNGs alone cannot reconstruct their contemporaneous AX tree. No collection is
needed or authorized for this task. For old PNG-only rows explicitly mark AX as
unavailable; derive OCR catalogs deterministically and do not invent native IDs.

Compare base and adapter in the **same runtime**, quantization, image preprocessing,
seed, token budget, system prompt and schema, with identical context. Build the
request through the app's prompt/schema builders with capture-only stubs, never a
live bridge. Use two strata: catalog-present targets requiring click_target, and
catalog-absent targets requiring fractional click_point with exact labels. Catalog
order must come from reading order, not from which element is gold. Include repeated
labels and negative/occluded targets. Also report a deterministic-catalog baseline.

For both models record strict schema validity, operation/tool choice, correct
numbered ID, exact label, strict in-box fractional hit, historical ±0.005 separately,
latency, scene-level results and paired per-scene differences. JSON generation must
get an adequate shared budget (the app's budget, not 20 tokens). In Ollama enforce
the same response schema as the app. A converted adapter needs a further paired
base-versus-adapter **Ollama** evaluation on the same fixtures. Keep malformed rows
in the denominator. Later, an owner-run real-Mac check measures navigation, snapping,
validation and execution; the offline point score cannot establish those outcomes.

## Can this Qwen3-VL LoRA run through Ollama?

Yes in principle as **fused full weights** for a supported Qwen3-VL architecture,
with its matching vision tower/projector. A raw MLX adapters.safetensors is not an
Ollama-importable full model; a projector is not a LoRA adapter. Current upstream
Ollama creation code rejects LoRA adapters, so do not rely on an ADAPTER directive.
That code classifies supplied GGUFs into model and projector layers. The runner has
Qwen3-VL vision compatibility. These are upstream facts, not verification of the
installed Ollama version. [Ollama create source](https://github.com/ollama/ollama/blob/main/server/create.go),
[runner source](https://github.com/ollama/ollama/blob/main/llm/llama_server.go).

llama.cpp registers both Qwen3VL text and vision converters. Its multimodal runner
accepts a language GGUF plus a separate --mmproj. [Qwen3-VL conversion source](https://github.com/ggml-org/llama.cpp/blob/master/conversion/qwen3vl.py),
[multimodal usage](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).

Owner-run steps, **not executed**:

1. Record installed Ollama, mlx-vlm and llama.cpp versions; inspect the old adapter
   config and tensor keys against its exact cached Qwen3-VL base. Preserve originals.
   Confirm only language layers were adapted before reusing an unchanged projector.
2. Load that base through `mlx_vlm.load(..., adapter_path=...)`; fuse each LoRA module
   using its own `fuse(dequantize=True)` and replace those modules; dequantize the
   remaining quantized linear/embedding layers too. Export full unquantized weights,
   processor/tokenizer and architecture config to a fresh `grounding-fused-hf/`.
   **Do not use mlx_lm.fuse for this multimodal model.** The installed mlx-vlm exposes
   LoRA `fuse` and dequantization helpers, but no standalone fuse CLI. An export helper
   needs model-specific HF key/layout restoration: MLX sanitized names/layouts must
   match `Qwen3VLForConditionalGeneration`, including the patch embedding. Validate
   every key/shape against the original HF config; reject leftover LoRA keys, packed
   scales/biases, missing vision/deepstack weights or an unexpected architecture.
   This export step requires implementation/validation before the commands below
   can work; no ready-to-run vision export is claimed here.
3. Convert both components with the current llama.cpp converter (paths shown from
   the repo root after completing the HF export):

   ```bash
   .data/training/tools/venv/bin/python .data/training/tools/llama.cpp/convert_hf_to_gguf.py \
     .data/training/grounding-fused-hf --outtype f16 --outfile .data/training/grounding-f16.gguf
   .data/training/tools/venv/bin/python .data/training/tools/llama.cpp/convert_hf_to_gguf.py \
     .data/training/grounding-fused-hf --mmproj --outtype f16 --outfile .data/training/grounding-mmproj-f16.gguf
   .data/training/tools/llama.cpp/build/bin/llama-quantize \
     .data/training/grounding-f16.gguf .data/training/grounding-Q4_K_M.gguf Q4_K_M
   ```

4. Validate vision with llama.cpp `llama-server -m <Q4_K_M> --mmproj <mmproj-f16>`
   and the exact same stored fixtures. Compare f16 and quantized exports before
   attributing a conversion/quantization regression to the adapter. Use nice 19.
5. For an Ollama version supporting separate GGUF imports, use its blob/create API:
   compute each file's SHA256; POST its bytes to `/api/blobs/sha256:<digest>`; then
   POST `/api/create` with `model: a11y-grounding-test`, `stream: false`, and
   `files: {"grounding-Q4_K_M.gguf": "sha256:<language digest>",
   "grounding-mmproj-f16.gguf": "sha256:<projector digest>"}`. Copy `template` and
   `parameters` from `/api/show` for the **vision** base qwen3-vl:4b-instruct (not the
   text router). Check that creation succeeds and `/api/show` includes vision
   capability, then test a known stored image. Server-side projector classification
   supports this route in current source; verify the installed release first.
   Do not try `ADAPTER mmproj`, a fabricated PROJECTOR directive or two FROM lines.
6. If that installed release cannot import separate components, use the supported
   Qwen3-VL full-HF Safetensors import path for a standard fused checkpoint, or retain
   llama.cpp serving for the experiment; verify image support rather than assuming
   successful text generation means vision works. Do not edit Ollama's blob manifests
   by hand. Only change app defaults after paired app-like and real-Mac evidence.

Ollama documents full Safetensors and GGUF imports, but does not promise arbitrary
MLX tensor layouts or every vision import combination. [Official import guide](https://docs.ollama.com/import).
