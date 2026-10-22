"""Opt-in macOS metadata and confirmed exact-control actions, independent of Qt/LLM."""
from .input_actions import INPUT_TYPES, authorize_input
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

# macOS bundle IDs and Windows browser ids (see windows_desktop.BROWSERS).
BROWSER_IDS = {'com.apple.Safari', 'com.google.Chrome', 'org.mozilla.firefox', 'com.microsoft.edgemac',
               'browser:edge', 'browser:chrome', 'browser:firefox'}


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
                                    capture_output=True, timeout=45 if any(flag in args for flag in ('--browse', '--music-state', '--music-play')) or ('--new-window' in args and 'com.apple.Safari' in args) else 4)
            value = json.loads(result.stdout)
            if result.returncode or not isinstance(value, dict) or value.get('error'):
                raise RuntimeError(str((value.get('error') if isinstance(value, dict) else '') or 'Desktop operation failed; the app may have changed.'))
            return value
        except subprocess.TimeoutExpired:
            raise RuntimeError('The operation timed out and may have been submitted. Check the app before retrying.') from None
        except (OSError, ValueError):
            raise RuntimeError('Desktop context is unavailable. Check macOS Accessibility permissions.') from None

    def sample(self):
        return self.call()

    def sample_target(self, bundle_id):
        return self.call('--observe-app', bundle_id)

    def request_access(self):
        return self.call('--request-access')

    def activate(self, bundle_id):
        return self.call('--activate', bundle_id)

    def click(self, action, guard):
        screen = guard['screen']
        return self.call('--click', str(screen['x']+action['x']*screen['width']),
                         str(screen['y']+action['y']*screen['height']), str(guard['display_id']), json.dumps(screen), action.get('button', 'left'), str(action.get('click_count', 1)))

    def catalog(self):
        return self.call('--catalog').get('installed_apps', [])

    def app_state(self, bundle_id):
        return self.call('--app-state', bundle_id)

    def media_state(self):
        return self.call('--music-state')

    def application_action(self, action):
        kind = action['type']
        if kind in INPUT_TYPES:
            return self.call('--input', json.dumps(action))
        if kind == 'play_media':
            return self.call('--music-play', action['query'], action['artist'])
        if kind == 'browse_url':
            return self.call('--browse', action['bundle_id'], action['url'], action.get('browser_mode', 'default'))
        if kind == 'close_window':
            return self.call('--close-window', action['bundle_id'], action['window_id'].rsplit(':', 1)[1],
                             action['window_title'], json.dumps(action['bounds']))
        flag = {'launch_app': '--launch', 'quit_app': '--quit', 'new_window': '--new-window'}[kind]
        return self.call(flag, action['bundle_id'])

    def press(self, action):
        return self.call('--press', action['bundle_id'], action['control_id'], action['label'],
                         json.dumps(action['bounds']), action['window_title'])


def desktop_bridge(directory):
    """Native bridge for this platform. Other platforms keep the macOS bridge, which reports unsupported."""
    if sys.platform == 'win32':
        from .windows_desktop import WindowsDesktopBridge
        return WindowsDesktopBridge(directory)
    return MacDesktopBridge(directory)


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

    def enable(self, *, request_permission=True):
        with self.lock:
            if self.enabled:
                return
            self.enabled = True
            self.generation += 1
            generation = self.generation
            stop = self.stop_event = threading.Event()
            self.error = 'Preparing desktop access…'
        self.thread = threading.Thread(target=self._run, args=(generation, stop, request_permission), daemon=True)
        self.thread.start()

    def disable(self):
        with self.lock:
            self.enabled = False
            self.generation += 1
            self.stop_event.set()
            self.snapshot = {}
            self.error = ''
            self.observed = self.checked = 0

    def _run(self, generation, stop, request_permission=True):
        try:
            if request_permission:
                self.bridge.request_access()
        except RuntimeError as e:
            with self.lock:
                if generation == self.generation:
                    self.error = str(e)
            return
        while not stop.is_set():
            self.collect_once(generation=generation)
            stop.wait(2)

    def collect_once(self, *, generation=None, target_bundle=None):
        with self.lock:
            if not self.enabled:
                return
        try:
            value = self.bridge.sample_target(target_bundle) if target_bundle and hasattr(self.bridge, 'sample_target') else self.bridge.sample()
            with self.lock:
                if not self.enabled or (generation is not None and generation != self.generation):
                    return
                now = self.clock()
                self.checked = now
                self.error = ''
                if value.get('status') == 'companion_focused' and self.snapshot.get('app'):
                    self.snapshot['companion_focused'] = True
                    self.snapshot['available_apps'] = value.get('available_apps', [])
                    self.snapshot['onscreen_window_candidates'] = value.get('onscreen_window_candidates', [])
                    self.snapshot['app_windows'] = value.get('app_windows', [])
                    self.snapshot['installed_apps'] = value.get('installed_apps', [])
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

    def installed_apps(self):
        if hasattr(self.bridge, 'catalog'):
            return self.bridge.catalog()
        return self.snapshot.get('installed_apps', [])

    def app_state(self, bundle_id):
        return self.bridge.app_state(bundle_id) if hasattr(self.bridge, 'app_state') else {}

    def media_state(self):
        return self.bridge.media_state()

    def authorize_action(self, action, *, snapshot=None):
        context = snapshot if snapshot is not None else self.context()
        if isinstance(action, dict) and action.get('type') in INPUT_TYPES:
            return authorize_input(action, context)
        if isinstance(action, dict) and action.get('type') == 'play_media':
            if set(action) != {'type', 'query', 'artist'} or not isinstance(action['query'], str) or not action['query'].strip() or len(action['query']) > 500 or not isinstance(action['artist'], str) or len(action['artist']) > 200 or any(ord(c) < 32 for c in action['query']+action['artist']):
                raise ValueError('Name a song title and optional artist.')
            if not any(app['bundle_id'] == 'com.apple.Music' for app in self.installed_apps()):
                raise ValueError('Music is not installed.')
            return dict(action, bundle_id='com.apple.Music', label='Find and play “'+action['query']+'” in Music')
        if isinstance(action, dict) and set(action) == {'type', 'bundle_id'} and action['type'] == 'launch_app':
            app = next((item for item in self.installed_apps() if item['bundle_id'] == action['bundle_id']), None)
            if app:
                return {'type': 'launch_app', 'bundle_id': app['bundle_id'], 'label': 'Open '+app['name']}
            raise ValueError('That application is not in the installed-app catalog.')
        if action == {'type': 'new_window', 'bundle_id': 'com.apple.Safari'}:
            if any(app['bundle_id'] == 'com.apple.Safari' for app in self.installed_apps()):
                return dict(action, label='Open a new Safari window')
            raise ValueError('Safari is not installed.')
        if not context.get('enabled') or context.get('status') not in ('available', 'companion_focused'):
            raise ValueError('Fresh desktop context is required for this action.')
        if not isinstance(action, dict):
            raise ValueError('Invalid desktop action.')
        kind = action.get('type')
        if kind in ('launch_app', 'quit_app', 'new_window') and set(action) == {'type', 'bundle_id'}:
            records = context.get('installed_apps', []) if kind == 'launch_app' else context.get('available_apps', [])
            app = next((item for item in records if item['bundle_id'] == action['bundle_id']), None)
            if app:
                if kind == 'new_window' and context.get('accessibility') == 'permission_required':
                    raise ValueError('Terminal New Window needs macOS Accessibility access. Request app access instead.')
                if kind == 'new_window' and app['bundle_id'] != 'com.apple.Terminal':
                    raise ValueError('New-window automation is currently available only for Terminal.')
                verb = {'launch_app': 'Open ', 'quit_app': 'Quit ', 'new_window': 'Open a new window in '}[kind]
                return {'type': kind, 'bundle_id': app['bundle_id'], 'label': verb+app['name']}
        elif kind == 'close_window' and set(action) == {'type', 'window_id'}:
            window = next((item for item in context.get('app_windows', [])
                           if item['window_id'] == action['window_id'] and item.get('can_close')), None)
            if window:
                return {'type': kind, 'window_id': window['window_id'], 'bundle_id': window['bundle_id'],
                        'window_title': window['title'], 'bounds': window['bounds'],
                        'label': 'Close '+window['name']+' — '+window['title']}
        if kind == 'focus_app'  and set(action) == {'type', 'bundle_id'}:
            app = next((a for a in context.get('available_apps', []) if a['bundle_id'] == action['bundle_id']), None)
            if app:
                return {'type': kind, 'bundle_id': app['bundle_id'], 'label': 'Switch to '+app['name']}
        elif kind in ('highlight_control', 'press_control') and set(action) == {'type', 'control_id'}:
            control = next((c for c in context.get('controls', []) if c['id'] == action['control_id'] and c.get('enabled', True)), None)
            if control:
                return {'type': kind, 'control_id': control['id'], 'label': control['label'],
                        'bounds': control['bounds'], 'observation_id': context['observation_id'],
                        'bundle_id': context.get('app', {}).get('bundle_id', ''),
                        'window_title': context.get('window', {}).get('title', ''),
                        'confirmation_label': ('Press “'+control['label']+'” in '+context.get('app', {}).get('name', 'the app')) if kind == 'press_control' else 'Highlight '+control['label']}
        raise ValueError('The requested desktop target was not observed or is no longer available.')

    def authorize_browser(self, action):
        app = next((app for app in self.installed_apps() if app['bundle_id'] == action['bundle_id'] and app['bundle_id'] in BROWSER_IDS), None)
        if app is None:
            raise ValueError('Choose an installed supported browser.')
        return dict(action)

    def application_action(self, proposal):
        kind = proposal['type']
        if kind in INPUT_TYPES:
            self.collect_once(target_bundle=proposal.get('bundle_id') if self.context().get('companion_focused') else None)
            field = {'type_text': 'text', 'press_key': 'key', 'scroll': 'direction'}[kind]
            current = self.authorize_action({'type': kind, field: proposal[field]})
            for key in ('bundle_id', 'window_title', 'bounds', 'focused_role', 'focused_bounds'):
                if current.get(key) != proposal.get(key):
                    raise ValueError('The input destination changed. Nothing was sent; focus the target and ask again.')
            result = self.bridge.application_action(current)
            if not result.get('submitted'):
                raise RuntimeError('Input submission is uncertain. Check the app before retrying.')
            self.collect_once()
            return result
        if kind == 'play_media':
            current = self.authorize_action({key: proposal[key] for key in ('type', 'query', 'artist')})
            return self.bridge.application_action(current)
        if proposal['type'] == 'browse_url':
            result = self.bridge.application_action(self.authorize_browser(proposal))
            if not result.get('submitted'):
                raise RuntimeError('The browser did not confirm accepting that address. Nothing will be retried automatically.')
            self.collect_once()
            return result
        fields = ('type', 'window_id') if proposal['type'] == 'close_window' else ('type', 'bundle_id')
        current = self.authorize_action({key: proposal[key] for key in fields})
        if proposal['type'] == 'close_window' and any(current[key] != proposal.get(key) for key in ('window_title', 'bounds', 'bundle_id')):
            raise ValueError('That window changed. Ask again before closing it.')
        result = self.bridge.application_action(current)
        if not result.get('submitted'):
            raise RuntimeError('The app action was not confirmed. Check the app before trying again.')
        self.collect_once()
        return result

    def press(self, proposal):
        with self.lock:
            if not self.enabled or self.error:
                raise ValueError('App awareness must be enabled before pressing a control.')
            signature = {key: self.snapshot.get(key) for key in ('app', 'window', 'controls')}
            current_id = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:16]
            if proposal.get('observation_id') != current_id:
                raise ValueError('The observed window changed. Ask again before pressing this control.')
            if proposal.get('type') != 'press_control' or not proposal.get('bundle_id'):
                raise ValueError('No observed control is available to press.')
        # The native helper re-reads the actual window/control before AXPress, even
        # when the companion is focused. It checks label, bounds and window title.
        result = self.bridge.press(proposal)
        if not result.get('submitted'):
            raise RuntimeError('The application did not accept the press action. Nothing will be retried automatically.')
        self.collect_once()
        return result

    def activate(self, bundle_id):
        action = self.authorize_action({'type': 'focus_app', 'bundle_id': bundle_id})
        result = self.bridge.activate(action['bundle_id'])
        if not result.get('activated'):
            raise RuntimeError('macOS did not activate the app.')
        return result
