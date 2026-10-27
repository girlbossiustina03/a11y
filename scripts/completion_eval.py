"""Local, screen-free completion checks using the app's actual verifier protocol.

This is a diagnostic set, not an adoption gate or a training dataset. Paired scenes
separate a visible label/selection from a completed task and include compound goals.
No apps are opened, screenshots read, or defaults changed.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from companion.computer_task import MET_SYSTEM,completion_schema,completion_result,completion_evidence
from companion.ollama import OllamaProvider
from companion.provider import AIConfig


def build(seed=0):
    rng=random.Random(seed)
    folder=rng.choice(['Materials','Supplies','Resources','Equipment'])
    parent=rng.choice(['Expedition','Research','Workshop','Project'])
    other='Archive'
    file='A11y test %08d manifest.txt' % rng.randrange(100000000)
    root='/tmp/a11y-completion-fixture'
    path=f'{root}/{parent}/{folder}'
    base=dict(goal=f'Continue into the {folder} subfolder.',app='Finder',window=folder,last_click=folder,
        screen_text=[folder,file],facts={'finder':{'target':path,'view':'list view','sort':'name column',
        'folder_name':folder,'parent_folder_name':parent}},
        navigation={'from_folder':parent,'item':folder,'entered':True})
    rows=[]
    def add(name,gold,obs):
        rows.append(dict(name=name,gold=gold,observation=deepcopy(obs)))
    add('entered_folder',True,base)
    selected=deepcopy(base)
    selected.update(window=parent)
    selected['facts']['finder'].update(target=f'{root}/{parent}',folder_name=parent,parent_folder_name='a11y-completion-fixture')
    selected['navigation']['entered']=False
    add('selected_child',False,selected)
    wrong=deepcopy(base);wrong['goal']=f'Enter {folder} inside {other}.'
    add('wrong_parent',False,wrong)
    compound=deepcopy(base);compound['goal']=f'Enter {folder}, read the manifest, and tell me the total packs.'
    add('unread_compound',False,compound)
    sort=deepcopy(base);sort.pop('navigation');sort['last_click']='Name'
    sort['goal']='Put this folder in list view sorted by name.'
    add('right_sort',True,sort)
    sort['goal']='Sort this folder by modification date.'
    add('wrong_sort',False,sort)
    for pane in ['Sound','Displays']:
        settings=dict(goal='Go to the Sound pane in System Settings.',app='System Settings',window=pane,
                      last_click='Sound',facts={},screen_text=[pane,'Sound','Output','Input'])
        add('settings_'+('active' if pane=='Sound' else 'sidebar_only'),pane=='Sound',settings)
    doc=dict(goal=f'Open {file} in TextEdit.',app='TextEdit',window=file,last_click=file,
             facts={'document':f'file://{path}/{file}','document_name':file},
             screen_text=[file,'Equipment inventory','Amber packs: 17','Violet packs: 26','Destination: Cedar ridge'])
    add('document_open',True,doc)
    doc['goal']='Read the manifest and tell me the number of packs.'
    add('document_content',True,doc)
    doc['screen_text']=[file]
    add('document_content_missing',False,doc)
    selected_doc=deepcopy(base);selected_doc.pop('navigation');selected_doc['goal']=f'Open {file} in TextEdit.'
    selected_doc['facts']['selected']=[{'role':'AXRow','name':file}]
    selected_doc['last_click']=file
    add('document_selected',False,selected_doc)
    return rows


def score(rows):
    return dict(total=len(rows),correct=sum(r['correct'] for r in rows),
                false_positives=sum(r['effective_met'] and not r['gold'] for r in rows),
                false_negatives=sum(not r['effective_met'] and r['gold'] for r in rows))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',default='qwen3:4b-instruct')
    parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--with-plan',action='store_true',help='generate completion criteria with the app planner before checking the final scene')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    provider=OllamaProvider(AIConfig(model=args.model,timeout=120))
    results=[]
    for row in build(args.seed):
        started=time.monotonic()
        plan=None
        if args.with_plan:
            observation=row['observation']
            initial_window=(observation.get('navigation') or {}).get('from_folder',observation['window'])
            plan=provider.plan_task(dict(goal=observation['goal'],front_app=observation['app'],
                front_window=initial_window,installed_apps=['Finder','System Settings','TextEdit']))
            if 'navigation' in observation and isinstance(plan,dict) and plan.get('done_when'):
                observation['planned_outcome']=str(plan['done_when'])[:200]
        reply=provider.complete_structured(MET_SYSTEM,[dict(role='user',content=json.dumps(row['observation']))],
            schema=completion_schema(row['observation']),max_tokens=320,thinking=False)
        met=completion_evidence(completion_result(reply),row['observation'])
        result=dict(row,plan=plan,prediction=reply,effective_met=met,correct=met==row['gold'],seconds=round(time.monotonic()-started,3))
        results.append(result)
        print(row['name'],result['correct'],flush=True)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(dict(model=args.model,seed=args.seed,with_plan=args.with_plan,system=MET_SYSTEM,
            summary=score(results),rows=results),indent=2)+'\n')
    print(json.dumps(score(results)))


if __name__=='__main__':main()
