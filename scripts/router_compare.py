"""Compare paired Ollama router outputs; never changes the app's model settings."""
import argparse
import json
from pathlib import Path
from router_scoring import equivalent


def compare(base, candidate):
    if base.get('backend')!='ollama' or candidate.get('backend')!='ollama':
        raise ValueError('Adoption requires paired Ollama results, not cross-runtime scores.')
    left,right=base.get('outputs',[]),candidate.get('outputs',[])
    if not left or len(left)!=len(right):
        raise ValueError('Missing or unequal paired rows.')
    regressions,improvements=[],[]
    metrics={}
    for b,c in zip(left,right):
        if any(b.get(k)!=c.get(k) for k in ('row','request','gold')):
            raise ValueError('Rows, requests and gold labels must match exactly in order.')
        gold=b['gold']
        for field in gold:
            old=equivalent(field,gold,b.get('prediction',{}),b['request'])
            new=equivalent(field,gold,c.get('prediction',{}),c['request'])
            metric=metrics.setdefault(field,dict(total=0,base_correct=0,candidate_correct=0))
            metric['total']+=1
            metric['base_correct']+=bool(old)
            metric['candidate_correct']+=bool(new)
            if old and not new:
                regressions.append(dict(row=b['row'],field=field,gold=gold[field],base=b['prediction'].get(field),candidate=c.get('prediction',{}).get(field)))
            elif new and not old:
                improvements.append(dict(row=b['row'],field=field))
    # Aggregate gains cannot hide formerly correct operation/scope decisions.
    critical={'operation','goal_mode','referent','request','acts_on_computer'}
    critical_regressions=[r for r in regressions if r['field'] in critical]
    app=metrics.get('app_name',{})
    op=metrics.get('operation',{})
    better=(app.get('candidate_correct',0)>app.get('base_correct',0)
            and op.get('candidate_correct',0)>=op.get('base_correct',0))
    any_field_loss=any(m['candidate_correct']<m['base_correct'] for m in metrics.values())
    failures=len(candidate.get('failures',[]))
    return dict(rows=len(left),metrics=metrics,regressions=regressions,improvements=improvements,
                critical_regressions=critical_regressions,candidate_parse_failures=failures,
                qualifies_for_live_validation=bool(better and not critical_regressions and not any_field_loss and failures==0),
                note='Passing this conservative offline gate permits further live validation only. It does not adopt the model or establish desktop success.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base',type=Path)
    parser.add_argument('candidate',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=compare(json.loads(args.base.read_text()),json.loads(args.candidate.read_text()))
    value=json.dumps(result,indent=2)
    if args.output:
        args.output.write_text(value+'\n')
    print(value)


if __name__=='__main__':
    main()
