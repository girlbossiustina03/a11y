"""Reproducible offline audit of saved predictions; never calls a model."""
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.router_data import build
from scripts.router_scoring import equivalent


def audit(directory):
    baseline = json.loads((directory/'eval-ollama2.json').read_text())
    adapter = json.loads((directory/'eval-adapter-local.json').read_text())
    rows = build()
    revised = {r['request']: r['plan'] for r in rows if r['kind']=='intent' and r['split']=='test'}
    decisions, counts, corrections = [], Counter(), []
    for output in baseline['outputs']:
        old, got = output['gold'], output['prediction']
        if 'operation' not in old:
            continue
        wording = output['request']['current_request']
        gold = revised[wording]
        for field in ('app_name', 'target', 'acts_on_computer', 'goal_mode'):
            if gold.get(field) != old.get(field):
                corrections.append(dict(row=output['row'], request=wording, field=field,
                                        old=old.get(field), revised=gold.get(field)))
            if old.get(field) == got.get(field):
                continue
            if old.get(field) != gold.get(field) and equivalent(field, gold, got, output['request']):
                decision = 'gold_corrected'
            elif equivalent(field, gold, got, output['request']):
                decision = 'scoring_equivalence'
            else:
                decision = 'model_error_kept'
            counts[field+':'+decision] += 1
            decisions.append(dict(row=output['row'], request=wording, field=field,
                                  old_gold=old.get(field), gold=gold.get(field), prediction=got.get(field), decision=decision))
    failure_counts = Counter()
    for failure in adapter['failures']:
        error = failure['error']
        category = ('opening_coverage_unknown' if 'opening the app' in error else
                    'json_unterminated' if 'Unterminated string' in error else
                    'invalid_operation' if 'invalid operation' in error else 'invalid_follow_up')
        failure_counts[category] += 1
    referents = Counter()
    referent_changes = Counter()
    for r in rows:
        if r['kind'] != 'intent':
            continue
        op = r['plan']['operation']
        old_ref = {'move_geometry':'companion','move_object':'companion','highlight':'visible_target'}.get(op,'other')
        referents[r['plan']['referent']] += 1
        if old_ref != r['plan']['referent']:
            referent_changes[r['split']] += 1
    report = dict(counts=dict(counts), mismatched_cells=len(decisions),
                  mismatched_rows=len({d['row'] for d in decisions}),
                  gold_corrections=corrections, referents=dict(referents),
                  referent_changes_by_split=dict(referent_changes),
                  adapter_failure_categories=dict(failure_counts),
                  raw_completion_limitation='Saved outputs contain prediction={} on errors, no raw completions. Cannot prove token truncation, prose or think blocks. Six JSON errors prove unterminated strings only; 45 coverage failures conceal their underlying error.',
                  decisions=decisions)
    (directory/'audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('decisions','gold_corrections')}, indent=2))


if __name__ == '__main__':
    audit(ROOT/'.data/training/router')
