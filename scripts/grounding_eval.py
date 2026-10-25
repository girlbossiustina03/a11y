"""Score clicking on held-out screens: how often the model's point lands inside the element.

    .venv-train/bin/python scripts/grounding_eval.py [--adapter PATH] [--limit N]

Uses .data/training/valid.jsonl (apps never trained on, scripts/grounding_data.py test split).
The base model and the base model plus a trained adapter are scored the same way.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'mlx-community/Qwen3-VL-4B-Instruct-4bit'


def point(text):
    match = re.search(r'\(\s*(\d{1,4})\s*,\s*(\d{1,4})\s*\)', text) or re.search(r'(\d{1,4})\D+(\d{1,4})', text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--adapter')
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--data', default=str(ROOT/'.data'/'training'/'valid.jsonl'))
    args = parser.parse_args()
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
    model, processor = load(MODEL, adapter_path=args.adapter) if args.adapter else load(MODEL)
    config = load_config(MODEL)
    rows = [json.loads(line) for line in open(args.data)][:args.limit]
    hits, by_scene = 0, {}
    for row in rows:
        question = row['messages'][0]['content']
        prompt = apply_chat_template(processor, config, question, num_images=1)
        reply = generate(model, processor, prompt, row['images'], max_tokens=20, temperature=0.0, verbose=False)
        text = reply.text if hasattr(reply, 'text') else str(reply)
        found = point(text)
        left, top, right, bottom = row['box']
        inside = bool(found) and left-5 <= found[0] <= right+5 and top-5 <= found[1] <= bottom+5
        hits += inside
        scene = by_scene.setdefault(row['scene'], [0, 0])
        scene[0] += inside
        scene[1] += 1
    print('%s: %d/%d inside the element (%.0f%%)' % ('adapter' if args.adapter else 'base', hits, len(rows), 100*hits/max(1, len(rows))))
    for scene, (good, total) in sorted(by_scene.items()):
        print('  %-50s %d/%d' % (scene[:50], good, total))


if __name__ == '__main__':
    main()
