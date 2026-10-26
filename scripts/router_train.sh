#!/bin/bash
# Explicitly run this only when the live Mac test has finished.
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PYTHON=.venv-train/bin/python
DATA=.data/training/router
[[ -s "$DATA/train.jsonl" && -s "$DATA/valid.jsonl" ]] || { echo 'Generate router data first.' >&2; exit 1; }
"$PYTHON" -m mlx_lm.lora --model mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --train --data "$DATA" --adapter-path "$DATA/adapter" \
  --config scripts/router_lora.yaml --mask-prompt --batch-size 1 \
  --iters 1800 --learning-rate 0.00005 --num-layers 16 \
  --max-seq-length 4096 --grad-checkpoint --steps-per-eval 100 --save-every 100 --seed 7
