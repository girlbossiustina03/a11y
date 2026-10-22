"""Browser/name contracts and image-bound click checks; no actual clicks/network."""
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
        self.assertIn('Tab/window placement', result['message'])
        provider.complete_structured.assert_not_called()
        self.assertFalse(self.monitor.enabled)

    def test_open_website_has_no_screen_guidance_requirement(self):
        self.bridge.catalog.return_value.append({'name': 'Safari', 'bundle_id': 'com.apple.Safari'})
        self.app.provider = StagedProvider('browser_open', 'Safari', 'https://www.youtube.com')
        self.assertEqual(self.app.ask('go to youtube.com in Safari')['desktop_action']['url'], 'https://www.youtube.com')

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
