"""Windows input, UI Automation, click and browser contracts.

Win32, SendInput and UIA are doubled: these run on any OS and check what the
bridge decides to send. They do not prove behavior on a real Windows desktop."""
import struct
import sys
import unittest
from unittest import mock
from companion.desktop_context import DesktopContext
from companion.windows_desktop import WindowsDesktopBridge
from companion.windows_input import logical_rect, utf16_units, KEYS, CTRL_LETTERS
from companion.windows_ocr import regions_from_lines
from test_windows_desktop import FakeWin32, bridge as make_bridge

NOTEPAD = (100, 'C:\\Windows\\notepad.exe', 'Untitled - Notepad', {'x': 10, 'y': 20, 'width': 600, 'height': 400})
CMD = (200, 'C:\\Windows\\System32\\cmd.exe', 'Command Prompt', {'x': 10, 'y': 20, 'width': 600, 'height': 400})
FIELD = {'x': 20, 'y': 60, 'width': 580, 'height': 340}


class FakeMonitors:
    """One 2880x1800 physical monitor at the origin, 200% scale."""
    def __init__(self, handle=77, rect=(0, 0, 2880, 1800), scale=2.0):
        self.handle, self.rect, self.scale = handle, rect, scale

    def at(self, x, y):
        return self.handle, self.rect, self.scale


class FakeSender:
    def __init__(self):
        self.events = []

    def click(self, x, y, button='left', count=1):
        self.events.append(('click', x, y, button, count))

    def scroll(self, x, y, direction):
        self.events.append(('scroll', x, y, direction))

    def press(self, name):
        self.events.append(('key', name))

    def type_text(self, text, still_focused):
        if not still_focused():
            raise RuntimeError('Typing stopped because focus changed.')
        self.events.append(('type', text))


class FakeUIA:
    def __init__(self, focus=None, controls=()):
        self.focus, self.found, self.invoked = focus, list(controls), []

    def focused(self):
        return self.focus

    def controls(self, hwnd):
        return [(dict(descriptor), element) for descriptor, element in self.found]

    def invoke(self, element):
        self.invoked.append(element)
        return True


def windows_bridge(records, foreground, *, focus=None, controls=(), screen_root=None):
    value = make_bridge(records, foreground)
    win32 = value.win32
    win32.physical_rect = lambda hwnd: (20, 40, 1220, 840)
    win32.root_at = lambda x, y: screen_root
    value._monitors, value._sender = FakeMonitors(), FakeSender()
    value._uia = FakeUIA(focus, controls)
    return value


def text_focus(**changes):
    return dict({'role': 'AXTextField', 'bounds': dict(FIELD), 'pid': 100, 'key': (42, 1)}, **changes)


class ObservationTests(unittest.TestCase):
    def test_sample_reports_uia_controls_and_focused_role_without_contents(self):
        controls = [({'role': 'button', 'label': 'Plus', 'bounds': {'x': 50, 'y': 300, 'width': 40, 'height': 40}, 'enabled': True}, 'plus')]
        b = windows_bridge({1: NOTEPAD}, 1, focus=text_focus(), controls=controls)
        sample = b.sample()
        self.assertEqual(sample['focused_role'], 'AXTextField')
        self.assertEqual(sample['focused_bounds'], FIELD)
        self.assertEqual(sample['controls'][0]['id'], 'control-0')
        self.assertEqual(sample['controls'][0]['label'], 'Plus')
        self.assertEqual(sample['control_source'], 'uia')
        self.assertNotIn('value', repr(sample))

    def test_focus_from_another_process_is_not_attributed_to_the_foreground_app(self):
        b = windows_bridge({1: NOTEPAD}, 1, focus=text_focus(pid=999))
        with mock.patch.object(b, 'focus_reader', side_effect=OSError):
            self.assertNotIn('focused_role', b.sample())

    def test_without_ui_automation_controls_are_empty_and_reported(self):
        b = windows_bridge({1: NOTEPAD}, 1)
        b._uia = False
        b._focus = mock.Mock(focused=mock.Mock(return_value=None))
        sample = b.sample()
        self.assertEqual(sample['controls'], [])
        self.assertEqual(sample['control_source'], 'unavailable')

    def test_logical_mapping_matches_qt_space_on_a_scaled_secondary_monitor(self):
        monitors = FakeMonitors(rect=(1920, 0, 2880, 1800), scale=1.5)
        rect = logical_rect(monitors, 1920+300, 150, 1920+600, 300)
        self.assertEqual(rect, {'x': 2120.0, 'y': 100.0, 'width': 200.0, 'height': 100.0})


class InputTests(unittest.TestCase):
    def authorized(self, b, action):
        context = DesktopContext(b, clock=lambda: 5)
        context.enabled = True
        context.collect_once()
        return context, context.authorize_action(action)

    def test_typing_goes_to_the_observed_field_through_the_shared_authorization(self):
        b = windows_bridge({1: NOTEPAD}, 1, focus=text_focus())
        context, action = self.authorized(b, {'type': 'type_text', 'text': 'Summary of today'})
        result = context.application_action(action)
        self.assertTrue(result['submitted'])
        self.assertEqual(b._sender.events, [('type', 'Summary of today')])

    def test_typing_refuses_moved_focus_password_fields_and_other_windows(self):
        b = windows_bridge({1: NOTEPAD, 2: NOTEPAD[:2]+('Other - Notepad',)+NOTEPAD[3:]}, 1, focus=text_focus())
        context, action = self.authorized(b, {'type': 'type_text', 'text': 'hello'})
        for change in (lambda: setattr(b._uia, 'focus', text_focus(role='secure_input', bounds=None)),
                       lambda: setattr(b._uia, 'focus', text_focus(bounds=dict(FIELD, x=200)))):
            change()
            with self.assertRaises((RuntimeError, ValueError)):
                b.application_action(action)
        b._uia.focus = text_focus()
        b.win32.foreground = 2
        with self.assertRaises(RuntimeError):
            b.application_action(action)
        self.assertEqual(b._sender.events, [])

    def test_focus_change_between_chunks_stops_typing(self):
        b = windows_bridge({1: NOTEPAD}, 1, focus=text_focus())
        _, action = self.authorized(b, {'type': 'type_text', 'text': 'hello'})
        focus = [text_focus(), text_focus(key=(99,))]
        b._uia.focused = lambda: focus.pop(0) if len(focus) > 1 else focus[0]
        with self.assertRaisesRegex(RuntimeError, 'focus changed'):
            b.application_action(action)

    def test_shell_windows_never_receive_input(self):
        b = windows_bridge({1: CMD}, 1, focus=text_focus(pid=200))
        context = DesktopContext(b, clock=lambda: 5)
        context.enabled = True
        context.collect_once()
        with self.assertRaises(ValueError):
            context.authorize_action({'type': 'press_key', 'key': 'enter'})
        with self.assertRaises(RuntimeError):
            b.input({'type': 'press_key', 'key': 'enter', 'bundle_id': 'cmd.exe', 'window_title': 'Command Prompt',
                     'bounds': CMD[3]})

    def test_keys_and_scroll_use_allowlisted_names(self):
        b = windows_bridge({1: NOTEPAD}, 1, focus=text_focus())
        context, key = self.authorized(b, {'type': 'press_key', 'key': 'cmd_n'})
        context.application_action(key)
        _, scroll = self.authorized(b, {'type': 'scroll', 'direction': 'down'})
        context.application_action(scroll)
        self.assertEqual(b._sender.events, [('key', 'cmd_n'), ('scroll', 620, 440, 'down')])
        self.assertEqual(set(CTRL_LETTERS) | set(KEYS), {'enter', 'tab', 'escape', 'space', 'backspace', 'left', 'right',
                         'up', 'down', 'cmd_l', 'cmd_f', 'cmd_t', 'cmd_n', 'cmd_w', 'cmd_a', 'cmd_r', 'cmd_s'})  # cmd_s (save) always asks the user first

    def test_companion_focus_brings_the_observed_window_forward_before_input(self):
        own = (__import__('os').getpid(), 'C:\\a11y\\python.exe', 'A11y', NOTEPAD[3])
        b = windows_bridge({1: NOTEPAD, 9: own}, 9, focus=text_focus())
        b.own_pid = own[0]
        b.input({'type': 'press_key', 'key': 'tab', 'bundle_id': 'notepad.exe', 'window_title': NOTEPAD[2], 'bounds': NOTEPAD[3]})
        self.assertEqual(b.win32.foreground, 1)

    def test_a_line_break_is_shift_enter_never_a_plain_enter(self):
        from companion.windows_input import SendInput, VK_RETURN, VK_SHIFT
        sender = SendInput.__new__(SendInput)
        sent = []
        sender.send = sent.append
        sender.key = lambda vk, up=False, extended=False: ('key', vk, up)
        sender.unicode = lambda unit, up=False: ('unit', unit, up)
        sender.type_text('a\nb', lambda: True)
        self.assertEqual(sent[1], [('key', VK_SHIFT, False), ('key', VK_RETURN, False), ('key', VK_RETURN, True), ('key', VK_SHIFT, True)])
        self.assertEqual(sent[0], [('unit', 0x61, False), ('unit', 0x61, True)])
        self.assertEqual(len(sent), 3)

    def test_utf16_units_cover_astral_characters(self):
        self.assertEqual(utf16_units('a👋'), [0x61, 0xD83D, 0xDC4B])


class ClickTests(unittest.TestCase):
    guard = {'screen': {'x': 0, 'y': 0, 'width': 1440, 'height': 900}, 'display_id': 77}

    def test_click_maps_image_fractions_to_physical_pixels_of_the_captured_monitor(self):
        b = windows_bridge({1: NOTEPAD}, 1)
        b.click({'x': .5, 'y': .25, 'label': 'Equals'}, self.guard)
        self.assertEqual(b._sender.events, [('click', 1440, 450, 'left', 1)])

    def test_click_refuses_changed_display_or_a_covering_companion(self):
        b = windows_bridge({1: NOTEPAD}, 1)
        for guard in (dict(self.guard, display_id=78), dict(self.guard, screen=dict(self.guard['screen'], width=1920))):
            with self.assertRaisesRegex(RuntimeError, 'display changed'):
                b.click({'x': .5, 'y': .5, 'label': 'x'}, guard)
        own = (__import__('os').getpid(), 'C:\\a11y\\python.exe', 'A11y', NOTEPAD[3])
        b = windows_bridge({1: NOTEPAD, 9: own}, 1, screen_root=9)
        b.own_pid = own[0]
        with self.assertRaisesRegex(RuntimeError, 'covering'):
            b.click({'x': .5, 'y': .5, 'label': 'x'}, self.guard)
        self.assertEqual(b._sender.events, [])


class PressTests(unittest.TestCase):
    PLUS = {'role': 'button', 'label': 'Plus', 'bounds': {'x': 50, 'y': 300, 'width': 40, 'height': 40}, 'enabled': True}

    def test_press_reenumerates_and_invokes_the_same_observed_control(self):
        b = windows_bridge({1: NOTEPAD}, 1, controls=[(self.PLUS, 'plus-element')])
        context = DesktopContext(b, clock=lambda: 5)
        context.enabled = True
        context.collect_once()
        action = context.authorize_action({'type': 'press_control', 'control_id': 'control-0'})
        context.press(action)
        self.assertEqual(b._uia.invoked, ['plus-element'])

    def test_changed_control_is_not_pressed(self):
        b = windows_bridge({1: NOTEPAD}, 1, controls=[(self.PLUS, 'plus-element')])
        action = {'control_id': 'control-0', 'label': 'Plus', 'bounds': self.PLUS['bounds'],
                  'bundle_id': 'notepad.exe', 'window_title': NOTEPAD[2]}
        b._uia.found = [(dict(self.PLUS, label='Minus'), 'minus-element')]
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            b.press(action)
        self.assertEqual(b._uia.invoked, [])

    def test_press_without_ui_automation_explains_the_missing_capability(self):
        b = windows_bridge({1: NOTEPAD}, 1)
        b._uia = False
        with self.assertRaisesRegex(RuntimeError, 'UI Automation'):
            b.press({'control_id': 'control-0'})


class BrowserTests(unittest.TestCase):
    def setUp(self):
        paths = [('browser:edge', 'Microsoft Edge', 'C:\\Edge\\msedge.exe'), ('browser:firefox', 'Firefox', 'C:\\Firefox\\firefox.exe')]
        with mock.patch.object(WindowsDesktopBridge, 'browser_paths', return_value=paths):
            self.bridge = make_bridge({}, None)

    def test_requested_window_and_tab_placement_use_fixed_browser_arguments(self):
        with mock.patch('subprocess.Popen') as popen:
            self.bridge.application_action({'type': 'browse_url', 'bundle_id': 'browser:edge', 'url': 'https://teams.microsoft.com/', 'browser_mode': 'window'})
            self.bridge.application_action({'type': 'browse_url', 'bundle_id': 'browser:firefox', 'url': 'https://example.com/a', 'browser_mode': 'tab'})
        self.assertEqual(popen.call_args_list[0].args[0], ['C:\\Edge\\msedge.exe', '--new-window', 'https://teams.microsoft.com/'])
        self.assertEqual(popen.call_args_list[1].args[0], ['C:\\Firefox\\firefox.exe', '-new-tab', 'https://example.com/a'])
        self.assertNotIn('shell', popen.call_args.kwargs)

    def test_only_web_urls_in_catalog_browsers_are_opened(self):
        with mock.patch('subprocess.Popen') as popen:
            for action in ({'bundle_id': 'browser:edge', 'url': 'file:///C:/secret'},
                           {'bundle_id': 'builtin:notepad', 'url': 'https://example.com'},
                           {'bundle_id': 'browser:chrome', 'url': 'https://example.com'}):
                with self.assertRaises(RuntimeError):
                    self.bridge.application_action(dict(action, type='browse_url'))
        popen.assert_not_called()

    def test_shared_validation_accepts_windows_browser_ids(self):
        context = DesktopContext(self.bridge)
        self.assertEqual(context.authorize_browser({'type': 'browse_url', 'bundle_id': 'browser:edge'})['bundle_id'], 'browser:edge')
        with self.assertRaises(ValueError):
            context.authorize_browser({'type': 'browse_url', 'bundle_id': 'builtin:notepad'})


class OcrTests(unittest.TestCase):
    def test_word_boxes_become_normalized_line_regions(self):
        regions = regions_from_lines([('Activity', [(10, 100, 60, 20)]), ('Post in channel', [(500, 800, 30, 20), (540, 800, 60, 22)]),
                                      ('', [(0, 0, 1, 1)])], 1000, 1000)
        self.assertEqual(regions, [{'text': 'Activity', 'x': .01, 'y': .1, 'width': .06, 'height': .02},
                                   {'text': 'Post in channel', 'x': .5, 'y': .8, 'width': .1, 'height': .022}])

    def test_missing_winrt_reports_unavailable_instead_of_guessing(self):
        from companion.windows_ocr import recognize
        with mock.patch.dict(sys.modules, {'winrt.windows.graphics.imaging': None}):
            self.assertIsNone(recognize(b'\x00'*16, 2, 2))


class PlatformToolTests(unittest.TestCase):
    def test_windows_task_grammar_omits_unimplemented_new_window(self):
        from companion.computer_task import schema_for
        windows = schema_for('Windows', False)['anyOf'][0]['properties']['action']['anyOf']
        mac = schema_for('macOS', False)['anyOf'][0]['properties']['action']['anyOf']
        kinds = lambda variants: {kind for v in variants for kind in v['properties']['type']['enum']}
        self.assertNotIn('new_window', kinds(windows))
        self.assertIn('new_window', kinds(mac))
        self.assertIn('click_point', kinds(windows))


if __name__ == '__main__':
    unittest.main()
