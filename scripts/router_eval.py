"""Explicit opt-in inference only; never executes a routed desktop action."""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.ollama import Planner, OllamaProvider
from companion.provider import AIConfig
from companion.service import FOLLOW_UP_SCHEMA
from companion.request_plan import validate_plan

from scripts.router_scoring import equivalent

class MLXPlanner(Planner):
    def __init__(self, model, adapter):
        import mlx.core as mx
        from mlx_lm import load
        self.completions = []
        mx.random.seed(7)
        self.model, self.tokenizer = load(model, adapter_path=adapter)
        from scripts.router_chat import install
        install(self.tokenizer)
    def complete(self, system, messages, *, max_tokens=700, **kwargs):
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler
        prompt = self.tokenizer.apply_chat_template(
            [{'role': 'system', 'content': system}]+messages,
            tokenize=False, add_generation_prompt=True, enable_thinking=False)
        # MLX has no Ollama JSON grammar; invalid JSON counts as failure.
        text = generate(self.model, self.tokenizer, prompt=prompt,
                        max_tokens=max_tokens, sampler=make_sampler(temp=0), verbose=False)
        self.completions.append(dict(raw=text, max_tokens=max_tokens, schema=kwargs.get('response_schema'),
                                     decoded_token_count=len(self.tokenizer.encode(text, add_special_tokens=False))))
        return json.loads(text)


def evaluate(rows, provider):
    confusion = defaultdict(Counter)
    fields = defaultdict(lambda: [0, 0])
    exact_fields = defaultdict(lambda: [0, 0])
    timings, failures, outputs = [], [], []
    correct = total = follow_good = follow_total = 0
    for number, row in enumerate(rows):
        msgs = row['messages']
        payload = json.loads(msgs[1]['content'])
        gold = json.loads(msgs[2]['content'])
        follow = 'request' in gold
        start = time.perf_counter()
        completion_start = len(getattr(provider, 'completions', []))
        try:
            if follow:
                got = provider.complete(msgs[0]['content'], [msgs[1]], response_schema=FOLLOW_UP_SCHEMA,
                                        max_tokens=200, thinking=False)
                if not isinstance(got, dict) or set(got) != {'request'} or not isinstance(got['request'], str):
                    raise ValueError('Invalid follow-up response')
            else:
                context = {k:v for k,v in payload.items() if k not in ('current_request','recent_user_requests')}
                got = provider.interpret_request(payload['current_request'], payload['recent_user_requests'], context)
                validate_plan(got)
        except Exception as exc:
            got = {}
            failures.append({'row':number, 'error':str(exc)})
        timings.append(time.perf_counter()-start)
        outputs.append(dict(row=number, request=payload, gold=gold, prediction=got, seconds=timings[-1], completions=getattr(provider, 'completions', [])[completion_start:]))
        if follow:
            follow_total += 1
            follow_good += got == gold
        else:
            total += 1
            actual = got.get('operation', '<invalid>')
            correct += actual == gold['operation']
            confusion[gold['operation']][actual] += 1
        for field, value in gold.items():
            exact_fields[field][0] += got.get(field) == value
            exact_fields[field][1] += 1
            fields[field][0] += equivalent(field, gold, got, payload)
            fields[field][1] += 1
    return dict(rows=len(rows), operation_accuracy=correct/max(1,total),
                follow_up_exact_accuracy=follow_good/max(1,follow_total),
                field_accuracy={k:dict(correct=v[0], total=v[1], accuracy=v[0]/v[1]) for k,v in fields.items()},
                exact_field_accuracy={k:dict(correct=v[0], total=v[1], accuracy=v[0]/v[1]) for k,v in exact_fields.items()},
                confusion={k:dict(v) for k,v in sorted(confusion.items())},
                outputs=outputs, mean_latency_seconds=sum(timings)/max(1,len(timings)), failures=failures,
                note='Planner includes opening-coverage calls. MLX uses plain ChatML, strict JSON parsing and no JSON grammar. field_accuracy uses conservative audited equivalences; exact_field_accuracy is lexical. Raw MLX completions include coverage calls; decoded_token_count is re-tokenized text, not an authoritative finish reason.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', default='qwen3:4b-instruct')
    p.add_argument('--adapter')
    p.add_argument('--mlx', action='store_true', help='also evaluate the unadapted MLX base')
    p.add_argument('--mlx-model', default='mlx-community/Qwen3-4B-Instruct-2507-4bit')
    p.add_argument('--data', type=Path, default=ROOT/'.data/training/router/test.jsonl')
    p.add_argument('--output', type=Path)
    p.add_argument('--limit', type=int)
    args = p.parse_args()
    from training_priority import require_background
    require_background()
    provider = MLXPlanner(args.mlx_model, args.adapter) if args.adapter or args.mlx else OllamaProvider(AIConfig(model=args.model, timeout=120))
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    if not rows:
        p.error('The evaluation file contains no rows')
    if args.limit is not None and args.limit < 1:
        p.error('--limit must be positive')
    report = evaluate(rows[:args.limit] if args.limit else rows, provider)
    report['backend'] = 'mlx' if args.adapter or args.mlx else 'ollama'
    report['model'] = args.mlx_model if report['backend']=='mlx' else args.model
    report['adapter'] = args.adapter
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text+'\n')
    print(text)

if __name__ == '__main__':
    main()
