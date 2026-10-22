#!/usr/bin/env python3
"""Measure computer-use latency by stage on the REAL host (macOS or Windows).

Reads desktop metadata, captures transient frames (with and without OCR) and asks
the configured local Ollama model for task proposals. It NEVER executes a proposed
action: propose() only returns a validated suggestion, which is discarded. Frames,
OCR text and model replies are not written anywhere; the report holds numbers only.

    A11Y_AI_MODEL=qwen3-vl:8b-instruct python scripts/benchmark_pipeline.py --runs 5

Grant app awareness (macOS Accessibility) and Screen Recording first. Run it once
with the model unloaded (`ollama stop <model>`) to see the cold first call."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from companion import ollama as ollama_module
from companion.computer_task import ComputerTask
from companion.desktop_context import DesktopContext, desktop_bridge
from companion.ollama import OllamaProvider
from companion.vision import ScreenVision


def summary(values):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return None
    p95 = values[min(len(values)-1, round(.95*(len(values)-1)))]
    return {'n': len(values), 'p50': statistics.median(values),
            'p95': p95, 'max': values[-1]}


def timed(function):
    started = time.monotonic()
    value = function()
    return value, round((time.monotonic()-started)*1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--goal', default='Look at the current window and tell me what it shows. Do not change anything.')
    parser.add_argument('--skip-model', action='store_true', help='only metadata and capture stages')
    parser.add_argument('--data-dir', default=os.getenv('A11Y_DATA_DIR', '.data'))
    args = parser.parse_args()

    report = {'platform': sys.platform, 'model': os.getenv('A11Y_AI_MODEL', ''), 'runs': args.runs}
    desktop = DesktopContext(desktop_bridge(Path(args.data_dir).resolve()))
    desktop.enabled = True
    sample_ms, catalog_ms = [], []
    for _ in range(args.runs):
        _, ms = timed(desktop.collect_once)
        sample_ms.append(ms)
    context = desktop.context()
    if context.get('status') == 'unavailable':
        sys.exit('Desktop metadata is unavailable: '+context.get('reason', '')+'. Grant app awareness first.')
    for _ in range(min(3, args.runs)):
        _, ms = timed(desktop.installed_apps)
        catalog_ms.append(ms)
    report['metadata_ms'] = {'first': sample_ms[0], 'warm': summary(sample_ms[1:])}
    report['catalog_ms'] = {'first': catalog_ms[0], 'warm': summary(catalog_ms[1:])}
    report['controls_observed'] = len(context.get('controls') or [])
    report['focused_role_present'] = 'focused_role' in context

    provider = OllamaProvider()
    vision = ScreenVision(Path(args.data_dir).resolve())
    vision.set_enabled(True)
    plain, ocr, regions, ocr_engine_ms, image_kib = [], [], [], [], []
    for _ in range(args.runs):
        frame, ms = timed(lambda: vision.call('--x', '0', '--y', '0'))
        plain.append(ms)
        image_kib.append(round(len(frame.get('image_data', ''))*3/4/1024))
        frame, ms = timed(lambda: vision.call('--x', '0', '--y', '0', '--ocr'))
        ocr.append(ms)
        regions.append(len(frame.get('text_regions') or []))
        if isinstance(frame.get('ocr_ms'), int):
            ocr_engine_ms.append(frame['ocr_ms'])
        frame = None  # do not keep pixels or text
    report['capture_ms'] = {'first': plain[0], 'warm': summary(plain[1:])}
    report['capture_with_ocr_ms'] = {'first': ocr[0], 'warm': summary(ocr[1:])}
    report['ocr_engine_ms'] = summary(ocr_engine_ms)
    report['ocr_regions'] = summary(regions)
    report['png_kib'] = summary(image_kib)

    if not args.skip_model:
        calls = []
        original = ollama_module.timing
        def record(event, started, **metrics):
            if event == 'ollama.finished':
                calls.append(dict(metrics, elapsed_ms=round((time.monotonic()-started)*1000)))
            return original(event, started, **metrics)
        ollama_module.timing = record
        try:
            _, ms = timed(lambda: provider.interpret_request(args.goal))
            report['intent_ms_first'] = ms
            intent = [timed(lambda: provider.interpret_request(args.goal))[1] for _ in range(max(1, args.runs-1))]
            report['intent_ms_warm'] = summary(intent)
            steps = []
            for _ in range(args.runs):
                task = ComputerTask(args.goal, goal_mode='inspect')
                try:
                    task.propose(desktop, vision, provider, {'x': 0, 'y': 0})
                except (ValueError, RuntimeError) as error:
                    steps.append({'error': type(error).__name__})
                    continue
                finally:
                    task.stop()  # the proposal is discarded; nothing executes
                steps.append(task.timings[-1])
            ok = [step for step in steps if 'total_ms' in step]
            report['task_step_ms'] = summary([step['total_ms'] for step in ok])
            report['task_step_model_calls'] = summary([len(step['model']) for step in ok])
            report['task_step_modes'] = [[call['mode'] for call in step['model']] for step in ok]
            report['task_step_errors'] = [step for step in steps if 'error' in step]
            for mode in ('text', 'image'):
                report[mode+'_inference_ms'] = summary([call['ms'] for step in ok for call in step['model'] if call['mode'] == mode])
            report['ollama_calls'] = [{key: call.get(key) for key in ('elapsed_ms', 'load_ms', 'prompt_eval_count', 'prompt_eval_ms', 'eval_count', 'eval_ms')}
                                      for call in calls]
        finally:
            ollama_module.timing = original
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
