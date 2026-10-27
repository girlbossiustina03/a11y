#!/bin/bash
# Owner-run only: Metal/Ollama access and effective background priority required.
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="$PWD/.data/training/router"
TOOLS="$PWD/.data/training/tools"
PYTHON="$PWD/.venv-train/bin/python"
APP_PYTHON="$PWD/.venv/bin/python"
CONVERTER_VENV="${A11Y_CONVERTER_VENV:-$TOOLS/venv-py313}"
CONVERSION_PYTHON="${A11Y_CONVERSION_PYTHON:-$APP_PYTHON}"
# Fail before training when pinned conversion dependencies lack Python wheels.
CHECK_PYTHON="$CONVERSION_PYTHON"
if [[ -x "$CONVERTER_VENV/bin/python" ]]; then CHECK_PYTHON="$CONVERTER_VENV/bin/python"; fi
"$CHECK_PYTHON" -c 'import sys; assert (3,10) <= sys.version_info[:2] < (3,14), "Conversion needs Python 3.10–3.13; set A11Y_CONVERSION_PYTHON to a compatible interpreter."'
MODEL=mlx-community/Qwen3-4B-Instruct-2507-4bit
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN="$DATA/pipeline-$RUN_ID"
LLAMA="$TOOLS/llama.cpp"
mkdir -p "$RUN" "$TOOLS"
# Each entire stage runs at low priority; the Python guard fails closed if nice fails.
stage() {
    local name="$1"
    shift
    echo "[$name] $DATA/pipeline-$RUN_ID-$name.log"
    nice -n 19 /bin/bash -c 'set -euo pipefail; "$1" scripts/training_priority.py; shift; exec "$@"' _ "$APP_PYTHON" "$@" \
        2>&1 | tee "$DATA/pipeline-$RUN_ID-$name.log"
}
# Stable data snapshot; no previous adapters/checkpoints are overwritten or resumed.
if [[ -n "${A11Y_ROUTER_DATA:-}" ]]; then
    stage data "$APP_PYTHON" -c 'import pathlib,shutil,sys; source=pathlib.Path(sys.argv[1]); assert all((source/name).is_file() for name in ("train.jsonl","valid.jsonl","test.jsonl")); shutil.copytree(source,sys.argv[2])' "$A11Y_ROUTER_DATA" "$RUN/data"
else
    stage data "$APP_PYTHON" scripts/router_data.py --output "$RUN/data"
fi
stage train "$PYTHON" scripts/router_train_local.py --model "$MODEL" \
    --train --data "$RUN/data" --adapter-path "$RUN/adapter" \
    --config scripts/router_lora.yaml --mask-prompt --batch-size 1 \
    --iters "${A11Y_ROUTER_ITERS:-300}" --learning-rate "${A11Y_ROUTER_LR:-0.00005}" --num-layers 8 --max-seq-length 4096 \
    --grad-checkpoint --steps-per-eval 50 --save-every 50 --val-batches -1 --seed 7
stage eval-mlx "$PYTHON" scripts/router_eval.py --adapter "$RUN/adapter/best" \
    --data "$RUN/data/test.jsonl" --output "$RUN/eval-mlx.json"
stage fuse env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "$PYTHON" -m mlx_lm.fuse \
    --model "$MODEL" --adapter-path "$RUN/adapter/best" --save-path "$RUN/fused" --dequantize
# Network is used only to provision conversion tools, never to download model weights.
stage tools /bin/bash -c '
    set -euo pipefail
    tools="$1"; llama="$2"; python="$3"; venv="$4"
    if [[ ! -f "$llama/convert_hf_to_gguf.py" ]]; then
        git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$llama"
    fi
    if [[ ! -x "$venv/bin/python" ]]; then "$python" -m venv "$venv"; fi
    "$venv/bin/python" -m pip install -r "$llama/requirements/requirements-convert_hf_to_gguf.txt"
    cmake -S "$llama" -B "$llama/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF
    cmake --build "$llama/build" --config Release --target llama-quantize -j 2
    git -C "$llama" rev-parse HEAD
' _ "$TOOLS" "$LLAMA" "$CONVERSION_PYTHON" "$CONVERTER_VENV"
stage prepare-gguf "$APP_PYTHON" scripts/router_gguf_input.py "$RUN/fused" "$RUN/gguf-input"
stage convert "$CONVERTER_VENV/bin/python" "$LLAMA/convert_hf_to_gguf.py" \
    "$RUN/gguf-input" --outfile "$RUN/router-f16.gguf" --outtype f16
stage quantize "$LLAMA/build/bin/llama-quantize" "$RUN/router-f16.gguf" "$RUN/router-q4_k_m.gguf" Q4_K_M
stage modelfile /bin/bash -c '
    set -euo pipefail
    ollama show --modelfile qwen3:4b-instruct > "$1/base.Modelfile"
    "$2" scripts/router_modelfile.py "$1/base.Modelfile" ./router-q4_k_m.gguf "$1/Modelfile"
    cat "$1/Modelfile"
' _ "$RUN" "$APP_PYTHON"
stage create ollama create a11y-router-test -f "$RUN/Modelfile"
stage inspect ollama show --modelfile a11y-router-test
stage eval-base-ollama "$APP_PYTHON" scripts/router_eval.py --model qwen3:4b-instruct \
    --data "$RUN/data/test.jsonl" --output "$RUN/eval-base-ollama.json"
stage eval-ollama "$APP_PYTHON" scripts/router_eval.py --model a11y-router-test \
    --data "$RUN/data/test.jsonl" --output "$RUN/eval-ollama.json"
stage compare "$APP_PYTHON" scripts/router_compare.py "$RUN/eval-base-ollama.json" "$RUN/eval-ollama.json" --output "$RUN/comparison.json"
echo "Results: $RUN"
