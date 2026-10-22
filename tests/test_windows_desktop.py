import os
import unittest
from unittest import mock

from companion.desktop_context import DesktopContext, MacDesktopBridge, desktop_bridge
from companion.windows_desktop import WindowsDesktopBridge


class FakeUser32:
    def __init__(self, owner):
        self.owner = owner
        self.posted = []

    def GetForegroundWindow(self):
        return self.owner.foreground

    def PostMessageW(self, hwnd, message, wparam, lparam):
        self.posted.append((hwnd, message))
        self.owner.records.pop(hwnd, None)
        return True

    def IsWindow(self, hwnd):
        return hwnd in self.owner.records

    def IsWindowVisible(self, hwnd):
        return hwnd in self.owner.records

    def IsIconic(self, hwnd):
        return False

    def ShowWindow(self, hwnd, command):
        return True

    def SetForegroundWindow(self, hwnd):
        self.owner.foreground = hwnd
        return True


class FakeWin32:
    """hwnd -> (pid, executable path, title, bounds)."""
    def __init__(self, records, foreground=None):
        self.records = dict(records)
        self.foreground = foreground
        self.user32 = FakeUser32(self)

    def top_level_windows(self):
        return list(self.records)

    def is_app_window(self, hwnd):
        return True

    def title(self, hwnd):
        return self.records[hwnd][2]

    def pid(self, hwnd):
        return self.records[hwnd][0] if hwnd in self.records else 0

    def executable(self, pid):
        return next((path for p, path, _, _ in self.records.values() if p == pid), '')

    def bounds(self, hwnd):
        return self.records[hwnd][3]

    def description(self, path):
        return {'notepad.exe': 'Notepad'}.get(path.rsplit('\\', 1)[-1], '')


BOUNDS = {'x': 10, 'y': 20, 'width': 600, 'height': 400}


def bridge(records, foreground=None, start_apps=()):
    with mock.patch.dict(os.environ, {'PROGRAMDATA': '', 'APPDATA': ''}), \
            mock.patch.object(WindowsDesktopBridge, 'start_apps', return_value=list(start_apps)):
        value = WindowsDesktopBridge(win32=FakeWin32(records, foreground))
        value.catalog()
    return value


class WindowsDesktopBridgeTest(unittest.TestCase):
    def test_platform_selects_bridge(self):
        with mock.patch('sys.platform', 'win32'), mock.patch('companion.windows_desktop._Win32'):
            self.assertIsInstance(desktop_bridge('.data'), WindowsDesktopBridge)
        with mock.patch('sys.platform', 'darwin'):
            self.assertIsInstance(desktop_bridge('.data'), MacDesktopBridge)

    def test_sample_reports_front_app_and_windows(self):
        b = bridge({1: (100, 'C:\\Windows\\notepad.exe', 'notes.txt - Notepad', BOUNDS),
                    2: (200, 'C:\\Windows\\ApplicationFrameHost.exe', 'Settings', BOUNDS)}, foreground=1)
        sample = b.sample()
        self.assertEqual(sample['status'], 'available')
        self.assertEqual(sample['platform'], 'Windows')
        self.assertEqual(sample['app'], {'name': 'Notepad', 'bundle_id': 'notepad.exe', 'pid': 100})
        self.assertEqual([a['bundle_id'] for a in sample['available_apps']], ['notepad.exe', 'uwp:settings'])
        self.assertEqual(sample['controls'], [])
        self.assertNotIn('installed_apps', sample)

    def test_companion_focus_and_private_apps(self):
        b = bridge({1: (os.getpid(), 'C:\\py\\python.exe', 'A11y', BOUNDS),
                    2: (300, 'C:\\Apps\\Bitwarden.exe', 'Vault', BOUNDS)}, foreground=1)
        sample = b.sample()
        self.assertEqual(sample['status'], 'companion_focused')
        self.assertEqual(sample['app_windows'], [])

    def test_catalog_ids_match_running_windows(self):
        b = bridge({2: (200, 'C:\\Windows\\ApplicationFrameHost.exe', 'Settings', BOUNDS),
                    3: (400, 'C:\\Windows\\notepad.exe', 'Untitled - Notepad', BOUNDS)})
        names = {app['name'] for app in b.catalog()}
        self.assertTrue({'Settings', 'Notepad', 'Calculator'} <= names)
        self.assertTrue(b.app_state('builtin:settings')['running'])
        self.assertTrue(b.app_state('builtin:notepad')['running'])
        self.assertFalse(b.app_state('builtin:calculator')['running'])

    def test_store_apps_from_start_menu(self):
        teams = {'name': 'Microsoft Teams', 'app_id': 'MSTeams_8wekyb3d8bbwe!MSTeams'}
        b = bridge({7: (500, 'C:\\Apps\\ms-teams.exe', 'Chat | Microsoft Teams', BOUNDS)}, start_apps=[teams])
        b.win32.description = lambda path: 'Microsoft Teams'
        self.assertIn({'bundle_id': 'startapp:'+teams['app_id'], 'name': 'Microsoft Teams'}, b.catalog())
        self.assertTrue(b.app_state('startapp:'+teams['app_id'])['running'])
        with mock.patch('os.startfile', create=True) as start, mock.patch('time.sleep'), \
                mock.patch('companion.windows_desktop.time.monotonic', side_effect=[0, 0, 10]):
            b.application_action({'type': 'launch_app', 'bundle_id': 'startapp:'+teams['app_id']})
        start.assert_called_once_with('shell:AppsFolder\\'+teams['app_id'])

    def test_launch_only_catalog_apps(self):
        b = bridge({})
        with mock.patch('os.startfile', create=True) as start, mock.patch('time.sleep'), \
                mock.patch('companion.windows_desktop.time.monotonic', side_effect=[0, 0, 10]):
            self.assertTrue(b.application_action({'type': 'launch_app', 'bundle_id': 'builtin:settings'})['submitted'])
        start.assert_called_once_with('ms-settings:')
        with self.assertRaises(RuntimeError):
            b.application_action({'type': 'launch_app', 'bundle_id': 'shortcut:C:\\evil.lnk'})

    def test_close_window_requires_unchanged_observation(self):
        b = bridge({5: (100, 'C:\\Windows\\notepad.exe', 'notes.txt - Notepad', BOUNDS)})
        action = {'type': 'close_window', 'window_id': 'notepad.exe:5', 'bundle_id': 'notepad.exe',
                  'window_title': 'other.txt - Notepad', 'bounds': BOUNDS}
        with self.assertRaises(RuntimeError):
            b.application_action(action)
        action['window_title'] = 'notes.txt - Notepad'
        self.assertTrue(b.application_action(action)['submitted'])
        self.assertEqual(b.win32.user32.posted, [(5, 0x0010)])

    def test_quit_and_focus(self):
        b = bridge({5: (100, 'C:\\Windows\\notepad.exe', 'a - Notepad', BOUNDS),
                    6: (100, 'C:\\Windows\\notepad.exe', 'b - Notepad', BOUNDS)})
        self.assertTrue(b.activate('notepad.exe')['activated'])
        self.assertTrue(b.application_action({'type': 'quit_app', 'bundle_id': 'notepad.exe'})['submitted'])
        self.assertEqual(sorted(h for h, _ in b.win32.user32.posted), [5, 6])
        with self.assertRaises(RuntimeError):
            b.activate('notepad.exe')

    def test_unsupported_actions_fail_clearly(self):
        b = bridge({})
        with self.assertRaises(RuntimeError):
            b.press({'type': 'press_control'})
        with self.assertRaises(RuntimeError):
            b.application_action({'type': 'new_window', 'bundle_id': 'cmd.exe'})

    def test_desktop_context_launch_uses_catalog(self):
        context = DesktopContext(bridge({}))
        action = context.authorize_action({'type': 'launch_app', 'bundle_id': 'builtin:settings'})
        self.assertEqual(action['label'], 'Open Settings')



class CitationSchemaTest(unittest.TestCase):
    def test_schema_allows_only_retrieved_sources(self):
        from companion.models import RESPONSE_SCHEMA, cite_only
        schema = cite_only(RESPONSE_SCHEMA, {'doc-1'})
        self.assertEqual(schema['properties']['source_ids']['items'], {'enum': ['doc-1']})
        steps = schema['properties']['workflow']['anyOf'][1]['properties']['steps']['items']
        self.assertEqual(steps['properties']['source_ids']['items'], {'enum': ['doc-1']})
        self.assertEqual(cite_only(RESPONSE_SCHEMA, set())['properties']['source_ids'], {'type': 'array', 'maxItems': 0})
        self.assertEqual(RESPONSE_SCHEMA['properties']['source_ids']['items'], {'type': 'string'})



class WindowsScreenTest(unittest.TestCase):
    def test_permission_checks_do_not_capture_any_screen(self):
        from companion.windows_screen import WindowsScreenBridge
        bridge = object.__new__(WindowsScreenBridge)
        bridge.capture = mock.Mock(side_effect=AssertionError('A permission check must not capture.'))
        self.assertEqual(bridge.call('--check-access'), {'granted': True})
        self.assertEqual(bridge.call('--request-access'), {'granted': True})
        bridge.capture.assert_not_called()

    def test_visible_protected_app_prevents_capture(self):
        from companion.windows_screen import WindowsScreenBridge
        bridge = object.__new__(WindowsScreenBridge)
        bridge.protected_visible = mock.Mock(return_value=True)
        bridge.grab = mock.Mock()
        self.assertIn('protected app', bridge.capture(0, 0)['error'])
        bridge.grab.assert_not_called()

    def test_png_encoding(self):
        import struct
        import zlib
        from companion.windows_screen import png
        # Two pixels, BGRA: blue, red.
        data = png(2, 1, bytes([255, 0, 0, 255, 0, 0, 255, 255]))
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(struct.unpack('>II', data[16:24]), (2, 1))
        start = data.index(b'IDAT')+4
        length = struct.unpack('>I', data[start-8:start-4])[0]
        self.assertEqual(zlib.decompress(data[start:start+length]), bytes([0, 0, 0, 255, 255, 0, 0]))

    def test_vision_uses_windows_capture_on_windows(self):
        from companion.vision import ScreenVision
        vision = ScreenVision('.data')
        bridge = mock.Mock()
        bridge.call.return_value = {'error': 'Screen vision paused while a protected app is active.'}
        vision.windows_bridge = bridge
        with mock.patch('sys.platform', 'win32'):
            with self.assertRaisesRegex(RuntimeError, 'protected app'):
                vision.call('--x', '0', '--y', '0')
            bridge.call.return_value = {'granted': True}
            self.assertEqual(vision.request_access(), {'granted': True})


if __name__ == '__main__':
    unittest.main()
