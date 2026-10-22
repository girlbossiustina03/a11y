from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from companion.desktop_context import DesktopContext
from companion.models import validate_response, ValidationError
from test_core import CompanionFixture


SAMPLE = {'status': 'available', 'platform': 'macOS', 'accessibility': 'granted',
          'app': {'name': 'Finder', 'bundle_id': 'com.apple.finder', 'pid': 42},
          'window': {'title': 'Projects', 'bounds': {'x': 10, 'y': 20, 'width': 900, 'height': 600}},
          'available_apps': [{'name': 'Finder', 'bundle_id': 'com.apple.finder'}],
          'controls': [{'id': 'control-0', 'label': 'New Folder', 'role': 'AXButton',
                        'enabled': True, 'bounds': {'x': 100, 'y': 100, 'width': 80, 'height': 30}}]}


class FakeBridge:
    def __init__(self):
        self.value = deepcopy(SAMPLE)
        self.activated = []

    def sample(self):
        return deepcopy(self.value)

    def activate(self, bundle):
        self.activated.append(bundle)
        return {'activated': True}


class DesktopContextTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.bridge = FakeBridge()
        self.monitor = DesktopContext(self.bridge, clock=lambda: self.now)
        self.monitor.enabled = True
        self.monitor.collect_once()

    def test_context_updates_and_keeps_last_external_app_when_companion_focused(self):
        self.bridge.value = {'status': 'companion_focused', 'available_apps': SAMPLE['available_apps']}
        original = self.monitor.context()['observation_id']
        self.now += 2
        self.monitor.collect_once()
        context = self.monitor.context()
        self.assertEqual(context['app']['name'], 'Finder')
        self.assertTrue(context['companion_focused'])
        self.assertEqual(context['age_seconds'], 2)
        self.assertEqual(context['observation_id'], original)

    def test_stale_observations_cannot_authorize_actions(self):
        self.now += 12
        self.assertEqual(self.monitor.context()['status'], 'stale')
        with self.assertRaises(ValueError):
            self.monitor.activate('com.apple.finder')

    def test_controls_expire_even_when_companion_remains_in_focus(self):
        self.bridge.value = {'status': 'companion_focused', 'available_apps': SAMPLE['available_apps']}
        self.now += 20
        self.monitor.collect_once()
        self.assertEqual(self.monitor.context()['controls'], [])
        with self.assertRaises(ValueError):
            self.monitor.authorize_action({'type': 'highlight_control', 'control_id': 'control-0'})

    def test_pause_erases_context_and_blocks_desktop_actions(self):
        self.monitor.disable()
        self.assertEqual(self.monitor.context(), {'enabled': False, 'status': 'off'})
        self.assertEqual(self.monitor.snapshot, {})
        with self.assertRaises(ValueError):
            self.monitor.activate('com.apple.finder')

    def test_private_app_discards_previously_observed_controls(self):
        self.bridge.value = {'status': 'private_app'}
        self.monitor.collect_once()
        self.assertNotIn('app', self.monitor.context())
        self.assertNotIn('controls', self.monitor.context())

    def test_focus_requires_observed_running_app(self):
        self.monitor.activate('com.apple.finder')
        self.assertEqual(self.bridge.activated, ['com.apple.finder'])
        with self.assertRaises(ValueError):
            self.monitor.activate('com.unknown.app')
        self.assertEqual(self.bridge.activated, ['com.apple.finder'])

    def test_highlight_bounds_come_from_native_observation(self):
        result = self.monitor.authorize_action({'type': 'highlight_control', 'control_id': 'control-0'})
        self.assertEqual(result['bounds'], SAMPLE['controls'][0]['bounds'])
        with self.assertRaises(ValueError):
            self.monitor.authorize_action({'type': 'highlight_control', 'control_id': 'control-0', 'x': 99})

    def test_ai_action_contract_rejects_unobserved_or_executable_actions(self):
        value = {'message': 'Try New Folder', 'source_ids': [], 'workflow': None, 'target': None,
                 'desktop_action': {'type': 'highlight_control', 'control_id': 'control-0'}}
        result = validate_response(value, set(), desktop=self.monitor)
        self.assertEqual(result['desktop_action']['label'], 'New Folder')
        with self.assertRaises(ValidationError):
            validate_response(value, set())
        for action in [{'type': 'shell', 'command': 'anything'}, {'type': 'click', 'control_id': 'control-0'},
                       {'type': 'focus_app', 'bundle_id': 'com.unknown.app'}]:
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    validate_response(dict(value, desktop_action=action), set(), desktop=self.monitor)


class DesktopServiceTests(CompanionFixture, unittest.TestCase):
    def test_current_desktop_is_in_model_context_and_not_written_to_storage(self):
        self.app.desktop_context = DesktopContext(FakeBridge(), clock=lambda: 100)
        self.app.desktop_context.enabled = True
        self.app.desktop_context.collect_once()
        self.app.ask('What app is open?')
        context = self.provider.contexts[-1]['desktop_context']
        self.assertEqual(context['app']['name'], 'Finder')
        self.assertEqual(context['window']['title'], 'Projects')
        self.assertEqual(self.store.history(self.employee), [])
        self.app.ask('And which control should I use?')
        messages = self.provider.calls[-1][1]
        self.assertTrue(any(m['content'] == 'What app is open?' for m in messages))
        for file in Path(self.temp.name).glob('*.sqlite3'):
            self.assertNotIn(b'"pid": 42', file.read_bytes())

    def test_model_context_follows_application_switch(self):
        bridge = FakeBridge()
        self.app.desktop_context = DesktopContext(bridge, clock=lambda: 100)
        self.app.desktop_context.enabled = True
        self.app.desktop_context.collect_once()
        self.app.ask('Which app?')
        bridge.value = dict(deepcopy(SAMPLE), app={'name': 'Xcode', 'bundle_id': 'com.apple.dt.Xcode'})
        self.app.desktop_context.collect_once()
        self.app.ask('And now?')
        self.assertEqual(self.provider.contexts[-1]['desktop_context']['app']['name'], 'Xcode')

    def test_action_is_bound_to_observation_given_to_model(self):
        bridge = FakeBridge()
        monitor = self.app.desktop_context = DesktopContext(bridge, clock=lambda: 100)
        monitor.enabled = True
        monitor.collect_once()
        original = self.provider.complete
        def changed_during_generation(*args, **kwargs):
            response = original(*args, **kwargs)
            bridge.value['window']['title'] = 'Different window'
            bridge.value['controls'][0]['label'] = 'Delete item'
            monitor.collect_once()
            response['desktop_action'] = {'type': 'highlight_control', 'control_id': 'control-0'}
            return response
        with patch.object(self.provider, 'complete', side_effect=changed_during_generation):
            response = self.app.ask('Highlight New Folder')
        self.assertEqual(response['desktop_action']['label'], 'New Folder')
        self.assertNotEqual(response['desktop_action']['observation_id'], monitor.context()['observation_id'])

    def test_pausing_during_request_does_not_restore_session_context(self):
        monitor = self.app.desktop_context = DesktopContext(FakeBridge(), clock=lambda: 100)
        monitor.enabled = True
        monitor.collect_once()
        original = self.provider.complete
        def paused_during_generation(*args, **kwargs):
            response = original(*args, **kwargs)
            monitor.disable()
            return response
        with patch.object(self.provider, 'complete', side_effect=paused_during_generation):
            self.app.ask('What app?')
        self.assertEqual(list(self.app.desktop_session), [])
        self.assertEqual(self.store.history(self.employee), [])
