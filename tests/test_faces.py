import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from companion import faces, terminal_theme


def archived(objects):
    """A minimal NSKeyedArchiver plist, as Terminal.app stores colours and fonts."""
    return plistlib.dumps({'$archiver': 'NSKeyedArchiver', '$version': 100000,
                           '$top': {'root': plistlib.UID(1)}, '$objects': ['$null', *objects]},
                          fmt=plistlib.FMT_BINARY)


def color(text, space=1):
    return archived([{'NSRGB': text.encode()+b'\0', 'NSColorSpace': space, '$class': plistlib.UID(2)},
                     {'$classname': 'NSColor', '$classes': ['NSColor', 'NSObject']}])


class FaceTests(unittest.TestCase):
    def test_every_face_is_a_clean_block_of_text(self):
        for name, states in faces.SKINS.items():
            columns, lines = faces.size(name)
            self.assertLessEqual(columns, 22, name)   # fits her window at any terminal font size
            self.assertLessEqual(lines, 7, name)
            for state in faces.STATES:
                self.assertIn(state, states, (name, state))
                for frame in states[state]:
                    self.assertEqual({len(line) for line in frame}, {columns}, (name, state, frame))
                    self.assertFalse(any(slot in line for line in frame for slot in faces.SLOTS), (name, state))

    def test_states_look_different_and_mascot_states_map_onto_them(self):
        for name in faces.SKINS:
            idle = faces.face(name, 'idle')
            for state in ('blink', 'thinking', 'done', 'stuck', 'sleeping'):
                self.assertNotEqual(faces.face(name, state), idle, (name, state))
            self.assertEqual(faces.face(name, 'guiding'), faces.face(name, 'working'))
            self.assertEqual(faces.face(name, 'celebrate'), faces.face(name, 'done'))
        # A spinner turns while she thinks; she talks while speaking.
        self.assertNotEqual(faces.face('blob', 'thinking', 0), faces.face('blob', 'thinking', 1))
        self.assertNotEqual(faces.face('blob', 'speaking', 0), faces.face('blob', 'speaking', 1))
        self.assertEqual(faces.face('no-such-skin', 'idle'), faces.face(faces.DEFAULT_SKIN, 'idle'))

    def test_reported_thinking_face_stays_centred(self):
        # Reported: the Pixel face moved off centre while thinking.
        def middle(lines):
            columns = [i for line in lines for i, c in enumerate(line) if c != ' ']
            return (min(columns)+max(columns))/2
        for name in ('pixel', 'kitty', 'bot'):
            idle, thinking = faces.face(name, 'idle'), faces.face(name, 'thinking')
            self.assertLessEqual(abs(middle(idle[1:])-middle(thinking[1:])), 0.5, name)  # (line 0 may carry a mark)

    def test_slot_sizes_are_checked(self):
        with self.assertRaises(ValueError):
            faces.fill(['[11]'], {'1': ['abc']})


class TerminalThemeTests(unittest.TestCase):
    def test_reads_colours_and_font_from_a_terminal_profile(self):
        profile = {'BackgroundColor': color('0.0984 0.1139 0.1526 0.95'), 'TextColor': color('0.8776 0.8776 0.8776'),
                   'ANSIGreenColor': color('0.4242 0.6673 0.4415', 2),
                   'Font': archived([{'NSSize': 12.0, 'NSfFlags': 16, 'NSName': plistlib.UID(2), '$class': plistlib.UID(3)},
                                     'JetBrainsMonoNF-SemiBold', {'$classname': 'NSFont', '$classes': ['NSFont', 'NSObject']}])}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'com.apple.Terminal.plist'
            path.write_bytes(plistlib.dumps({'Default Window Settings': 'Clear Dark',
                                             'Window Settings': {'Clear Dark': profile}}))
            found = terminal_theme.terminal_app_palette(path)
        self.assertEqual((found.name, found.background, found.text, found.green), ('Clear Dark', '#191D27', '#E0E0E0', '#6CAA71'))
        self.assertAlmostEqual(found.opacity, 0.95)
        self.assertEqual((found.font, found.font_size), ('JetBrainsMonoNF-SemiBold', 12.0))
        self.assertTrue(found.dark)

    def test_terminal_colours_are_converted_and_blur_is_read(self):
        profile = {'BackgroundColor': color('0.0984 0.1139 0.1526 0.95'), 'BackgroundBlur': 0.5,
                   'BackgroundBlurInactive': 0.0, 'BackgroundSettingsForInactiveWindows': True}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'com.apple.Terminal.plist'
            path.write_bytes(plistlib.dumps({'Default Window Settings': 'Clear Dark', 'Window Settings': {'Clear Dark': profile}}))
            spaces = []
            found = terminal_theme.terminal_app_palette(path, convert=lambda r, g, b, space: spaces.append(space) or (1.0, 0.5, 0.0))
        self.assertEqual(found.background, '#FF8000')   # what the converter said, not the raw numbers
        self.assertIn(1, spaces)                        # Terminal's calibrated RGB
        self.assertEqual((found.blur, found.blur_inactive), (0.5, 0.0))

    @unittest.skipUnless(sys.platform == 'darwin', 'AppKit conversion')
    def test_reported_clear_dark_background_matches_terminal_on_screen(self):
        # Reported: her window was darker than Terminal. Terminal shows #212733 for these numbers.
        from companion.mac_window import to_srgb
        rgb = to_srgb(0.09838771145, 0.1138777476, 0.152602838, 1)
        self.assertEqual(terminal_theme.hex_color(*rgb)[:5], '#2127')

    def test_unreadable_preferences_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(terminal_theme.terminal_app_palette(Path(folder)/'missing.plist'))
            broken = Path(folder)/'broken.plist'
            broken.write_bytes(b'not a plist')
            self.assertIsNone(terminal_theme.terminal_app_palette(broken))
        with patch.object(terminal_theme, 'terminal_app_palette', return_value=None):
            self.assertEqual(terminal_theme.palette('terminal'), terminal_theme.THEMES['clear_dark'])
        self.assertEqual(terminal_theme.palette('no-such-theme'), terminal_theme.THEMES['clear_dark'])
        self.assertFalse(terminal_theme.palette('catppuccin_latte').dark)

    @unittest.skipUnless(sys.platform == 'darwin', 'AppKit menus')
    def test_reported_menu_is_a_real_macos_menu(self):
        # Reported: her right-click menu didn't look like macOS (it was Qt imitating one).
        from companion import mac_window
        actions = []
        menu = mac_window.build_menu([('Talk to me', 'talk'), None, ('Face', [('Blob', 'face:blob', True), ('Cat', 'face:cat')]),
                                      ('Quit companion', 'quit')], actions)
        self.assertEqual(mac_window.send(menu, 'numberOfItems', restype=mac_window.ctypes.c_long), 4)
        self.assertEqual(actions, ['talk', 'face:blob', 'face:cat', 'quit'])

    def test_reported_she_stays_on_screen_across_spaces(self):
        # Reported: switching to another virtual desktop left her behind on the first one.
        from companion import mac_window
        calls = []

        def send(receiver, selector, *args, **kwargs):
            calls.append((selector, args))
            return 0
        with patch.object(mac_window, 'ns_window', return_value=1), patch.object(mac_window, 'send', send), \
                patch.object(mac_window, 'runtime', return_value=type('Runtime', (), {'sel_registerName': lambda self, name: 0})()):
            self.assertTrue(mac_window.prepare_window(object()))
        behavior = dict(calls)['setCollectionBehavior:'][0]
        self.assertTrue(behavior & mac_window.ALL_SPACES and behavior & mac_window.FULL_SCREEN_AUXILIARY)

    def test_appearance_is_saved_in_the_data_folder(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'A11Y_DATA_DIR': folder}):
            self.assertEqual(terminal_theme.saved_appearance(), {'theme': 'terminal', 'face': 'blob'})
            terminal_theme.save_appearance(face='cat', unknown='ignored')
            self.assertEqual(terminal_theme.saved_appearance(), {'theme': 'terminal', 'face': 'cat'})
            (Path(folder)/'appearance.json').write_text('{broken')
            self.assertEqual(terminal_theme.saved_appearance()['face'], 'blob')


if __name__ == '__main__':
    unittest.main()
