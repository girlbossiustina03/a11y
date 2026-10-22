"""Opt-in macOS desktop metadata. Ephemeral, bounded, and independent of Qt/LLM."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


class MacDesktopBridge:
    def __init__(self, directory):
        self.source = Path(__file__).resolve().parent.parent / 'native' / 'DesktopBridge.swift'
        self.binary = Path(directory).resolve() / 'desktop-bridge'
        self.lock = threading.Lock()

    def prepare(self):
        if sys.platform != 'darwin':
            raise RuntimeError('Live desktop context currently supports macOS.')
        with self.lock:
            if self.binary.exists() and self.binary.stat().st_mtime >= self.source.stat().st_mtime:
                return
            self.binary.parent.mkdir(parents=True, exist_ok=True)
            try:
                result = subprocess.run(['xcrun', 'swiftc', '-O', '-module-cache-path',
                    str(self.binary.parent/'swift-cache'), str(self.source), '-o', str(self.binary)],
                    capture_output=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                raise RuntimeError('macOS bridge needs Xcode Command Line Tools. Install them with xcode-select --install.') from None
            if result.returncode:
                raise RuntimeError('Could not build the macOS desktop bridge. Check Xcode Command Line Tools.')

    def call(self, *args):
        self.prepare()
        try:
            result = subprocess.run([str(self.binary), '--exclude-pid', str(os.getpid()), *args],
                                    capture_output=True, timeout=4)
            value = json.loads(result.stdout)
            if result.returncode or not isinstance(value, dict) or value.get('error'):
                raise RuntimeError('Desktop operation failed; the app may have changed.')
            return value
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise RuntimeError('Desktop context is unavailable. Check macOS Accessibility permissions.') from None

    def sample(self):
        return self.call()

    def request_access(self):
        return self.call('--request-access')

    def activate(self, bundle_id):
        return self.call('--activate', bundle_id)


class DesktopContext:
    def __init__(self, bridge, *, clock=time.monotonic):
        self.bridge, self.clock = bridge, clock
        self.lock = threading.RLock()
        self.enabled = False
        self.snapshot = {}
        self.observed = 0
        self.checked = 0
        self.error = ''
        self.generation = 0
        self.thread = None
        self.stop_event = threading.Event()

    def enable(self):
        with self.lock:
            if self.enabled:
                return
            self.enabled = True
            self.generation += 1
            generation = self.generation
            stop = self.stop_event = threading.Event()
            self.error = 'Preparing desktop access…'
        self.thread = threading.Thread(target=self._run, args=(generation, stop), daemon=True)
        self.thread.start()

    def disable(self):
        with self.lock:
            self.enabled = False
            self.generation += 1
            self.stop_event.set()
            self.snapshot = {}
            self.error = ''
            self.observed = self.checked = 0

    def _run(self, generation, stop):
        try:
            self.bridge.request_access()
        except RuntimeError as e:
            with self.lock:
                if generation == self.generation:
                    self.error = str(e)
            return
        while not stop.is_set():
            self.collect_once(generation=generation)
            stop.wait(2)

    def collect_once(self, *, generation=None):
        try:
            value = self.bridge.sample()
            with self.lock:
                if not self.enabled or (generation is not None and generation != self.generation):
                    return
                now = self.clock()
                self.checked = now
                self.error = ''
                if value.get('status') == 'companion_focused' and self.snapshot.get('app'):
                    self.snapshot['companion_focused'] = True
                    self.snapshot['available_apps'] = value.get('available_apps', [])
                else:
                    self.snapshot = value
                    self.observed = now
        except RuntimeError as e:
            with self.lock:
                if generation is None or generation == self.generation:
                    self.error = str(e)
                    self.snapshot = {}

    def context(self):
        with self.lock:
            if not self.enabled:
                return {'enabled': False, 'status': 'off'}
            if self.error:
                return {'enabled': True, 'status': 'unavailable', 'reason': self.error}
            if not self.checked or self.clock()-self.checked > 10:
                return {'enabled': True, 'status': 'stale', 'reason': 'Desktop observation is not fresh.'}
            result = deepcopy(self.snapshot)
            result['enabled'] = True
            result['age_seconds'] = round(max(0, self.clock()-self.observed), 1)
            if result['age_seconds'] > 15:
                result['controls'] = []
                result['controls_stale'] = True
            signature = {k: result.get(k) for k in ('app', 'window', 'controls')}
            result['observation_id'] = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:16]
            return result

    def authorize_action(self, action, *, snapshot=None):
        context = snapshot if snapshot is not None else self.context()
        if not context.get('enabled') or context.get('status') not in ('available', 'companion_focused'):
            raise ValueError('Fresh desktop context is required for this action.')
        if not isinstance(action, dict):
            raise ValueError('Invalid desktop action.')
        kind = action.get('type')
        if kind == 'focus_app' and set(action) == {'type', 'bundle_id'}:
            app = next((a for a in context.get('available_apps', []) if a['bundle_id'] == action['bundle_id']), None)
            if app:
                return {'type': kind, 'bundle_id': app['bundle_id'], 'label': 'Switch to '+app['name']}
        elif kind == 'highlight_control' and set(action) == {'type', 'control_id'}:
            control = next((c for c in context.get('controls', []) if c['id'] == action['control_id'] and c.get('enabled', True)), None)
            if control:
                return {'type': kind, 'control_id': control['id'], 'label': control['label'],
                        'bounds': control['bounds'], 'observation_id': context['observation_id']}
        raise ValueError('The requested desktop target was not observed or is no longer available.')

    def activate(self, bundle_id):
        action = self.authorize_action({'type': 'focus_app', 'bundle_id': bundle_id})
        result = self.bridge.activate(action['bundle_id'])
        if not result.get('activated'):
            raise RuntimeError('macOS did not activate the app.')
        return result
