"""Offline MLX pilot: validation-selected weights, patience 2, <2 hour wall budget.

Run through router_train.sh. Never selects a checkpoint on test performance.
"""
import json
import os
from pathlib import Path
import signal
import time
import types

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'


class StopTraining(Exception):
    pass


class EarlyStop:
    def __init__(self, directory, patience=2):
        self.directory = Path(directory)
        self.best = float('inf')
        self.bad = 0
        self.patience = patience
        self.history = []
        self.model = None

    def on_train_loss_report(self, info):
        pass

    def on_val_loss_report(self, info):
        import mlx.core as mx
        from mlx.utils import tree_flatten
        self.history.append(info)
        loss = info['val_loss']
        if loss < self.best - 0.001:
            self.best, self.bad = loss, 0
            mx.save_safetensors(str(self.directory/'best.safetensors'),
                                dict(tree_flatten(self.model.trainable_parameters())))
            self.best_iteration = info['iteration']
        else:
            self.bad += 1
        (self.directory/'validation.json').write_text(json.dumps(self.history, indent=2)+'\n')
        if self.bad >= self.patience:
            raise StopTraining('validation patience exhausted')


def main():
    from training_priority import require_background
    require_background()
    # Alarm includes model load and initial validation, leaving margin below 2 hours.
    def timeout(*_):
        raise StopTraining('6900 second wall limit')
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(6900)
    start = time.monotonic()
    from mlx_lm import lora
    import yaml
    parser = lora.build_parser()
    args = vars(parser.parse_args())
    if args.get('config'):
        for key, value in yaml.safe_load(Path(args['config']).read_text()).items():
            if args.get(key) is None:
                args[key] = value
    for key, value in lora.CONFIG_DEFAULTS.items():
        if args.get(key) is None:
            args[key] = value
    args = types.SimpleNamespace(**args)
    callback = EarlyStop(args.adapter_path)
    directory = callback.directory
    directory.mkdir(parents=True, exist_ok=True)
    reason = 'iteration limit'
    try:
        model, tokenizer = lora.load(args.model)
        from router_chat import install, check_training_rows
        install(tokenizer)
        for split in ('train', 'valid'):
            rows = [json.loads(line) for line in (Path(args.data)/f'{split}.jsonl').read_text().splitlines() if line.strip()]
            check_training_rows(rows, tokenizer, args.max_seq_length)
        callback.model = model
        train, valid, _ = lora.load_dataset(args, tokenizer)
        lora.train_model(args, model, train, valid, callback)
    except StopTraining as exc:
        reason = str(exc)
    finally:
        signal.alarm(0)
        (directory/'run.json').write_text(json.dumps(dict(
            reason=reason, seconds=time.monotonic()-start,
            best_iteration=getattr(callback, 'best_iteration', None),
            best_validation_loss=callback.best if callback.history else None), indent=2)+'\n')
    # Preserve last/checkpoints; put validation-selected weights in a separate loadable directory.
    if not (directory/'best.safetensors').exists():
        raise RuntimeError('No validation-selected checkpoint produced')
    if (directory/'best.safetensors').exists():
        import shutil
        best = directory/'best'
        best.mkdir(exist_ok=True)
        shutil.copyfile(directory/'best.safetensors', best/'adapters.safetensors')
        shutil.copyfile(directory/'adapter_config.json', best/'adapter_config.json')


if __name__ == '__main__':
    main()
