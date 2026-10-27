"""Prepare a separate, token-ID-preserving input view for llama.cpp conversion."""
from copy import deepcopy
import argparse
import json
from pathlib import Path


def compatible_config(config, tokenizer):
    result=deepcopy(config)
    extra=result.get('extra_special_tokens')
    if isinstance(extra,list):
        known={token['content'] for token in tokenizer.get('added_tokens',[]) if token.get('special')}
        if not all(isinstance(token,str) and token in known for token in extra):
            raise ValueError('Special tokens must already exist with their original IDs in tokenizer.json.')
        previous=result.get('additional_special_tokens',[])
        if not isinstance(previous,list) or not all(isinstance(token,str) for token in previous):
            raise ValueError('Unexpected additional_special_tokens metadata.')
        result.pop('extra_special_tokens')
        result['additional_special_tokens']=list(dict.fromkeys(previous+extra))
    elif extra is not None and not isinstance(extra,dict):
        raise ValueError('Unexpected extra_special_tokens metadata.')
    return result


def prepare(source,destination):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if source==destination or source in destination.parents:
        raise ValueError('Conversion input must be separate from the fused export.')
    config=json.loads((source/'tokenizer_config.json').read_text())
    tokenizer=json.loads((source/'tokenizer.json').read_text())
    converted=compatible_config(config,tokenizer)
    destination.mkdir(parents=True,exist_ok=True)
    for item in source.iterdir():
        if item.name=='tokenizer_config.json':
            continue
        target=destination/item.name
        if target.is_symlink() and target.resolve()==item.resolve():
            continue
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        target.symlink_to(item,target_is_directory=item.is_dir())
    target=destination/'tokenizer_config.json'
    if target.is_symlink():
        raise ValueError('Refusing to write through a tokenizer-config symlink.')
    target.write_text(json.dumps(converted,indent=2)+'\n')
    return dict(source=str(source),destination=str(destination),metadata_changed=converted!=config)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    print(json.dumps(prepare(args.source,args.destination),indent=2))
