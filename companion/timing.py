"""Content-free timing records for the launcher's existing stdout log."""
import json
import time


def timing(event, started, **metrics):
    record = {'event': event, 'elapsed_ms': round((time.monotonic()-started)*1000)}
    record.update(metrics)
    try:
        print('A11y timing '+json.dumps(record, ensure_ascii=True), flush=True)
    except OSError:
        pass  # A closed log must not change whether a desktop action runs.
