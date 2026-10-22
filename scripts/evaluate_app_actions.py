#!/usr/bin/env python3
"""Evaluate a real Ollama model on synthetic app/window metadata. Executes NO actions."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from companion.desktop_context import DesktopContext
from companion.models import Identity
from companion.ollama import OllamaProvider
from companion.provider import AIConfig
from companion.service import Companion
from companion.storage import Store


class FixtureBridge:
    def __init__(self):
        self.value = {'status': 'available', 'accessibility': 'granted',
            'app': {'name': 'Finder', 'bundle_id': 'com.apple.finder'}, 'controls': [],
            'available_apps': [{'name': 'Terminal', 'bundle_id': 'com.apple.Terminal'},
                               {'name': 'Finder', 'bundle_id': 'com.apple.finder'}],
            'installed_apps': [{'name': 'Terminal', 'bundle_id': 'com.apple.Terminal'},
                               {'name': 'Stremio', 'bundle_id': 'com.example.fixture.stremio'}],
            'app_windows': [
                {'window_id': 'com.apple.Terminal:0', 'name': 'Terminal', 'bundle_id': 'com.apple.Terminal',
                 'title': 'API requests', 'bounds': {'x': 40, 'y': 60, 'width': 640, 'height': 300}, 'can_close': True},
                {'window_id': 'com.apple.Terminal:1', 'name': 'Terminal', 'bundle_id': 'com.apple.Terminal',
                 'title': 'zsh', 'bounds': {'x': 650, 'y': 410, 'width': 500, 'height': 330}, 'can_close': True}]}

    def catalog(self):
        return deepcopy(self.value['installed_apps'])

    def sample(self):
        return deepcopy(self.value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.getenv('A11Y_AI_MODEL', 'qwen3-vl:8b-instruct'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    provider = OllamaProvider(AIConfig(base_url=os.getenv('A11Y_OLLAMA_URL', 'http://127.0.0.1:11434'), model=args.model, timeout=180))
    cases = [
        ('open installed Stremio', 'open up Stremio please', 'launch_app', 'bundle_id', 'com.example.fixture.stremio'),
        ('new Terminal window', 'open up a new terminal then', 'new_window', 'bundle_id', 'com.apple.Terminal'),
        ('focus existing Terminal', 'bring Terminal to the front', 'focus_app', 'bundle_id', 'com.apple.Terminal'),
        ('close lower-right window', 'close the lower right terminal please', 'close_window', 'window_id', 'com.apple.Terminal:1'),
        ('close named zsh window', 'close the one with zsh in its title please', 'close_window', 'window_id', 'com.apple.Terminal:1'),
        ('quit Terminal', 'quit the Terminal application', 'quit_app', 'bundle_id', 'com.apple.Terminal'),
        ('unknown app', 'open the app named NonexistentFixtureApp123', None, None, None),
        ('ambiguous window', 'close the zsh window', None, None, None),
        ('launch with access off', 'open Stremio', 'launch_app', 'bundle_id', 'com.example.fixture.stremio'),
        ('access off', 'close the lower right Terminal', 'request_app_access', None, None),
    ]
    records = []
    with tempfile.TemporaryDirectory(prefix='a11y-app-eval-') as directory:
        bridge = FixtureBridge()
        desktop = DesktopContext(bridge)
        app = Companion(Store(directory), Identity('evaluation', 'synthetic-metadata'), provider)
        app.desktop_context = desktop
        for name, request, expected_type, field, value in cases:
            desktop.enabled = 'access off' not in name
            bridge.value['app_windows'][0]['title'] = 'zsh' if name == 'ambiguous window' else 'API requests'
            desktop.collect_once()
            app.desktop_session.clear()
            started = time.monotonic()
            record = {'case': name, 'pass': False}
            try:
                response = app.ask(request, mode='assist')
                action = response.get('desktop_action') or {}
                record['intent'] = app.last_request_plan
                record['action'] = {key: action[key] for key in ('type', 'bundle_id', 'window_id') if key in action}
                record['pass'] = (action.get('type') == expected_type
                                  and (field is None or action.get(field) == value)
                                  and response['target'] is None)
            except (ValueError, RuntimeError) as error:
                record['error'] = str(error)
            record['seconds'] = round(time.monotonic()-started, 2)
            records.append(record)
            print(json.dumps(record), flush=True)
            if 'not reachable' in record.get('error', ''):
                break
    report = {'model': args.model, 'fixture': 'synthetic metadata; no actual apps launched, closed or quit',
              'passed': sum(item['pass'] for item in records), 'total': len(records), 'expected_total': len(cases), 'results': records}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('model', 'passed', 'total', 'expected_total')}))
    return 0 if len(records) == len(cases) and all(item['pass'] for item in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
