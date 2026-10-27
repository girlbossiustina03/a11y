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
        self.last_train_iteration = None

    def on_train_loss_report(self, info):
        self.last_train_iteration = info.get('iteration')
        (self.directory/'progress.json').write_text(json.dumps(dict(
            last_reported_iteration=self.last_train_iteration, train_loss=info.get('train_loss')),
            indent=2)+'\n')

    def save_latest(self):
        """Keep current adapter weights on a clean interruption, not only every 50 steps."""
        if self.model is None:
            return False
        import mlx.core as mx
        from mlx.utils import tree_flatten
        parameters = dict(tree_flatten(self.model.trainable_parameters()))
        if not parameters or any('.lora_' not in key for key in parameters):
            return False  # training has not installed adapters; never dump base weights
        temporary = self.directory/'latest.tmp.safetensors'
        mx.save_safetensors(str(temporary), parameters)
        temporary.replace(self.directory/'adapters.safetensors')
        return True

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
    def interrupted(*_):
        raise StopTraining('interrupted by owner or power guard')
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
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
        # A second stop signal must not interrupt the final checkpoint write.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        latest_saved = callback.save_latest()
        (directory/'run.json').write_text(json.dumps(dict(
            reason=reason, seconds=time.monotonic()-start,
            latest_adapter_saved=latest_saved,
            last_reported_iteration=callback.last_train_iteration,
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
