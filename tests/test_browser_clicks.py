"""Browser/name contracts and image-bound click checks; no actual clicks/network."""
import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
import base64
import importlib.util
import json
import time
import unittest
from unittest.mock import Mock, patch
from companion.app_names import resolve_app
from companion.models import validate_response, ValidationError
from companion.vision import ScreenVision
from test_request_plan import StagedProvider
from test_core import CompanionFixture
from test_desktop_context import FakeBridge
from companion.desktop_context import DesktopContext


class NameTests(unittest.TestCase):
    def test_platform_names_resolve_only_to_installed_apps(self):
        catalog = [{'name': 'System Settings', 'bundle_id': 'com.apple.systempreferences'},
                   {'name': 'TextEdit', 'bundle_id': 'com.apple.TextEdit'},
                   {'name': 'Notes', 'bundle_id': 'com.apple.Notes'}]
        for name in ('Settings', "Mac's settings", 'macOS settings', 'System Preferences'):
            self.assertEqual(resolve_app(name, catalog)[0]['bundle_id'], 'com.apple.systempreferences')
        self.assertEqual(resolve_app('Notepad', catalog)[0]['name'], 'TextEdit')
        self.assertEqual(resolve_app('Settings', []), [])

    def test_a_real_installed_notepad_takes_priority_over_alias(self):
        catalog = [{'name': 'Notepad', 'bundle_id': 'installed.notepad'}, {'name': 'TextEdit', 'bundle_id': 'com.apple.TextEdit'}]
        self.assertEqual(resolve_app('notepad', catalog), [catalog[0]])


class BrowserServiceTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()
        self.bridge.catalog = Mock(return_value=[{'name': 'Stremio', 'bundle_id': 'com.fixture.stremio'}])
        self.bridge.app_state = Mock(return_value={'running': True})
        self.bridge.application_action = Mock(return_value={'submitted': True})
        self.monitor = self.app.desktop_context = DesktopContext(self.bridge, clock=lambda: 100)

    def test_search_safari_builds_a_real_url_without_screen_access(self):
        self.bridge.catalog.return_value.append({'name': 'Safari', 'bundle_id': 'com.apple.Safari'})
        provider = self.app.provider = StagedProvider('browser_search', 'Safari', 'youtube cats & dogs')
        result = self.app.ask('open up a new safari tab and search for youtube cats & dogs')
        action = result['desktop_action']
        self.assertEqual(action['type'], 'browse_url')
        self.assertEqual(action['bundle_id'], 'com.apple.Safari')
        self.assertEqual(action['url'], 'https://duckduckgo.com/?q=youtube+cats+%26+dogs')
        self.assertNotIn('Confirm below', result['message'])
        provider.complete_structured.assert_not_called()
        self.assertFalse(self.monitor.enabled)

    def test_blank_new_safari_window_needs_no_screenshot_or_accessibility_metadata(self):
        self.bridge.catalog.return_value.append({'name': 'Safari', 'bundle_id': 'com.apple.Safari'})
        self.app.provider = StagedProvider('new_window', 'Safari')
        action = self.app.ask('open a new Safari window')['desktop_action']
        self.assertEqual(action['type'], 'new_window')
        self.assertEqual(action['bundle_id'], 'com.apple.Safari')
        self.assertFalse(self.monitor.enabled)

    def test_open_website_has_no_screen_guidance_requirement(self):
        self.bridge.catalog.return_value.append({'name': 'Safari', 'bundle_id': 'com.apple.Safari'})
        self.app.provider = StagedProvider('browser_open', 'Safari', 'https://www.youtube.com')
        self.assertEqual(self.app.ask('go to youtube.com in Safari')['desktop_action']['url'], 'https://youtube.com')

    def test_native_automation_denial_and_timeout_are_reported_without_retry(self):
        import subprocess
        from companion.desktop_context import MacDesktopBridge
        bridge = MacDesktopBridge('/private/tmp/a11y-bridge-unit')
        denial = subprocess.CompletedProcess([], 1, b'{"error":"Allow Safari in Automation"}', b'')
        with patch.object(bridge, 'prepare'), patch('companion.desktop_context.subprocess.run', return_value=denial) as run:
            with self.assertRaisesRegex(RuntimeError, 'Allow Safari in Automation'):
                bridge.call('--browse', 'com.apple.Safari', 'https://youtube.com', 'window')
            run.assert_called_once()
        with patch.object(bridge, 'prepare'), patch('companion.desktop_context.subprocess.run', side_effect=subprocess.TimeoutExpired('bridge', 45)) as run:
            with self.assertRaisesRegex(RuntimeError, 'may have been submitted'):
                bridge.call('--browse', 'com.apple.Safari', 'https://youtube.com', 'window')
            run.assert_called_once()
        with patch.object(bridge, 'prepare'), patch('companion.desktop_context.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'[]', b'')):
            with self.assertRaisesRegex(RuntimeError, 'Desktop operation failed'):
                bridge.call('--catalog')

    def test_domain_search_navigates_but_multiword_query_stays_search(self):
        self.bridge.catalog.return_value.append({'name': 'Safari', 'bundle_id': 'com.apple.Safari'})
        for target, expected in [('youtube.com', 'https://youtube.com'),
                                 ('youtube.com cats', 'https://duckduckgo.com/?q=youtube.com+cats'),
                                 ('https://youtube.com/watch?v=1', 'https://youtube.com/watch?v=1')]:
            self.app.provider = StagedProvider('browser_search', 'Safari', target)
            self.assertEqual(self.app.ask('search for '+target)['desktop_action']['url'], expected)

    def test_window_and_tab_mode_survive_validation_and_bridge(self):
        from companion.desktop_context import MacDesktopBridge
        self.bridge.catalog.return_value.append({'name': 'Safari', 'bundle_id': 'com.apple.Safari'})
        for mode in ('window', 'tab'):
            provider = self.app.provider = StagedProvider('browser_open', 'Safari', 'youtube.com')
            provider.interpret_request.return_value['browser_mode'] = mode
            action = self.app.ask('open youtube.com in a new '+mode)['desktop_action']
            self.assertEqual(action['browser_mode'], mode)
            bridge = MacDesktopBridge('/private/tmp/a11y-bridge-unit')
            with patch.object(bridge, 'call', return_value={'submitted': True}) as call:
                bridge.application_action(action)
            self.assertEqual(call.call_args.args, ('--browse', 'com.apple.Safari', 'https://youtube.com', mode))

    def test_non_web_schemes_never_produce_browser_actions(self):
        self.bridge.catalog.return_value.append({'name': 'Safari', 'bundle_id': 'com.apple.Safari'})
        for url in ('file:///etc/passwd', 'javascript://alert/1', 'https://name:password@example.com'):
            self.app.provider = StagedProvider('browser_open', 'Safari', url)
            self.assertIsNone(self.app.ask('open a website')['desktop_action'])

    def test_launch_verification_uses_process_evidence_without_llm_visibility_guess(self):
        provider = self.app.provider = StagedProvider('launch_app', 'Stremio')
        self.app.last_action_result = {'type': 'launch_app', 'label': 'Open Stremio', 'bundle_id': 'com.fixture.stremio'}
        self.bridge.app_state.return_value = {'running': True, 'active': True}
        result = self.app.ask('open Stremio', mode='verify')
        self.assertEqual(result['message'], 'Stremio is running and active.')
        provider.complete_structured.assert_not_called()
        self.bridge.app_state.return_value = {'running': False, 'observation': 'not_observed'}
        self.assertIn('could not confirm', self.app.ask('open Stremio', mode='verify')['message'])

    def test_browser_verification_never_invents_failure_from_missing_window_metadata(self):
        provider = self.app.provider = StagedProvider('browser_open', 'Safari', 'youtube.com')
        self.app.last_action_result = {'type': 'browse_url', 'requested_url': 'https://youtube.com',
            'native_result': {'submitted': True, 'tab_placement': 'window',
                              'browser_observation': {'url': 'https://youtube.com/', 'window_count': 2}}}
        result = self.app.ask('go to youtube.com', mode='verify')
        self.assertIn('Opened https://youtube.com', result['message'])
        self.assertNotIn('not completed', result['message'])
        provider.complete_structured.assert_not_called()
        self.app.last_action_result['native_result'] = {'submitted': True}
        result = self.app.ask('go to youtube.com', mode='verify')
        self.assertEqual('Sent the address to the browser.', result['message'])  # no claim that it loaded
        self.assertNotIn('failed', result['message'])
        self.assertIsNone(result['desktop_action'])

    def test_capture_own_button_uses_internal_capture_not_excluded_image(self):
        provider = self.app.provider = StagedProvider('capture_once', 'A11y', 'Capture screen once')
        result = self.app.ask('press capture screen once on the a11y window')
        self.assertEqual(result['desktop_action']['type'], 'capture_once')
        provider.complete_structured.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec('PyQt6'), 'Qt is required for local click frame checks')
class ClickTests(unittest.TestCase):
    def frame(self, color='blue'):
        from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
        from PyQt6.QtGui import QImage, QColor
        image = QImage(200, 120, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        return {'image_data': 'data:image/png;base64,'+base64.b64encode(bytes(data)).decode(),
                'screen': {'x': 0, 'y': 0, 'width': 1000, 'height': 600}, 'display_id': 7,
                'captured_monotonic': time.monotonic(), 'windows': []}

    def setUp(self):
        self.vision = ScreenVision('/private/tmp/a11y-click-unit')
        self.vision.set_enabled(True)
        self.original = self.frame()
        self.action = {'type': 'click_point', 'x': .5, 'y': .5, 'label': 'Requested button'}
        self.action['capture_guard'] = self.vision.click_guard(self.original['image_data'], self.original, self.action)
        self.desktop = Mock()
        self.desktop.context.return_value = {}
        self.desktop.bridge.click.return_value = {'submitted': True}

    def test_click_requires_pixels_and_finite_interior_coordinates(self):
        raw = {'request_kind': 'click_point', 'message': 'Click proposal', 'source_ids': [], 'workflow': None, 'target': None,
               'desktop_action': {key: self.action[key] for key in ('type', 'x', 'y', 'label')}}
        with self.assertRaises(ValidationError):
            validate_response(raw, set(), desktop=object())
        for number in (-1, 1, float('nan'), True):
            with self.assertRaises(ValidationError):
                validate_response(dict(raw, desktop_action=dict(raw['desktop_action'], x=number)), set(), desktop=object(), has_screen=True)

    def test_click_variants_are_bounded_and_retain_image_guard_requirement(self):
        raw = {'request_kind': 'click_point', 'message': 'Click', 'source_ids': [], 'workflow': None, 'target': None,
               'desktop_action': {'type': 'click_point', 'x': .2, 'y': .3, 'label': 'Folder'}}
        for button, count in [('left', 2), ('right', 1)]:
            action = dict(raw['desktop_action'], button=button, click_count=count)
            result = validate_response(dict(raw, desktop_action=action), set(), desktop=object(), has_screen=True)
            self.assertEqual(result['desktop_action']['click_count'], count)
        for button, count in [('middle', 1), ('left', 3), ('right', 2), ('left', True)]:
            with self.assertRaises(ValidationError):
                validate_response(dict(raw, desktop_action=dict(raw['desktop_action'], button=button, click_count=count)), set(), desktop=object(), has_screen=True)

    def test_matching_fresh_capture_allows_one_click_and_observation(self):
        with patch.object(self.vision, 'capture', return_value=self.frame()):
            self.vision.execute_click(None, self.desktop, self.action)
        self.desktop.bridge.click.assert_called_once()
        self.desktop.collect_once.assert_called_once()
        self.assertNotIn('image_data', json.dumps(self.action['capture_guard']))

    def test_changed_target_never_clicks(self):
        with patch.object(self.vision, 'capture', return_value=self.frame('red')):
            with self.assertRaisesRegex(ValueError, 'target or its window changed'):
                self.vision.execute_click(None, self.desktop, self.action)
        self.desktop.bridge.click.assert_not_called()

    def test_resized_display_or_expired_guard_never_clicks(self):
        changed = self.frame()
        changed['screen']['width'] = 1100
        with patch.object(self.vision, 'capture', return_value=changed):
            with self.assertRaises(ValueError):
                self.vision.execute_click(None, self.desktop, self.action)
        self.action['capture_guard']['captured_monotonic'] -= 100
        with patch.object(self.vision, 'capture') as capture:
            with self.assertRaises(ValueError):
                self.vision.execute_click(None, self.desktop, self.action)
            capture.assert_not_called()
        self.desktop.bridge.click.assert_not_called()

    def test_pause_during_recheck_never_clicks(self):
        def paused(*args, **kwargs):
            self.vision.set_enabled(False)
            return self.frame()
        with patch.object(self.vision, 'capture', side_effect=paused):
            with self.assertRaises(ValueError):
                self.vision.execute_click(None, self.desktop, self.action)
        self.desktop.bridge.click.assert_not_called()
