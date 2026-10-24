"""Colours and font for the terminal-style companion.

"terminal" follows the user's terminal: on macOS the default Terminal.app profile (its
colours and font are read from Terminal's preferences, no helper needed). Elsewhere, or
when that can't be read, it falls back to Clear Dark. The built-in themes are always there.
"""
import json
import os
import plistlib
import sys
from dataclasses import dataclass
from pathlib import Path

from .paths import data_dir


@dataclass(frozen=True)
class Palette:
    name: str
    background: str
    text: str
    dim: str
    border: str
    red: str
    yellow: str
    green: str
    cyan: str
    blue: str
    selection: str
    opacity: float = 1.0
    font: str = ''        # family or PostScript name; empty uses the first monospace font found
    font_size: float = 13.0

    @property
    def dark(self):
        value = self.background.lstrip('#')
        r, g, b = (int(value[i:i+2], 16) for i in (0, 2, 4))
        return 0.299*r+0.587*g+0.114*b < 140


THEMES = {
    'clear_dark': Palette('Clear Dark', '#191D27', '#E0E0E0', '#5E7383', '#35424B', '#B35547', '#C4AB62',
                          '#6CAA70', '#7BCACD', '#6D95B3', '#334D5E', 0.95),
    'catppuccin_mocha': Palette('Catppuccin Mocha', '#1E1E2E', '#CDD6F4', '#7F849C', '#45475A', '#F38BA8',
                                '#F9E2AF', '#A6E3A1', '#94E2D5', '#89B4FA', '#45475A'),
    'catppuccin_macchiato': Palette('Catppuccin Macchiato', '#24273A', '#CAD3F5', '#8087A2', '#494D64', '#ED8796',
                                    '#EED49F', '#A6DA95', '#8BD5CA', '#8AADF4', '#494D64'),
    'catppuccin_frappe': Palette('Catppuccin Frappé', '#303446', '#C6D0F5', '#838BA7', '#51576D', '#E78284',
                                 '#E5C890', '#A6D189', '#81C8BE', '#8CAAEE', '#51576D'),
    'catppuccin_latte': Palette('Catppuccin Latte', '#EFF1F5', '#4C4F69', '#8C8FA1', '#BCC0CC', '#D20F39',
                                '#DF8E1D', '#40A02B', '#179299', '#1E66F5', '#ACB0BE'),
    'high_contrast': Palette('High contrast', '#000000', '#FFFFFF', '#C8C8C8', '#FFFFFF', '#FF6B6B', '#FFE066',
                             '#7CFF7C', '#7FFFFF', '#8FB8FF', '#3A3A3A'),
}
THEME_NAMES = {'terminal': 'Match my terminal', **{key: palette.name for key, palette in THEMES.items()}}
FALLBACK = 'clear_dark'
MONOSPACE = ('JetBrains Mono', 'JetBrainsMono Nerd Font', 'SF Mono', 'Menlo', 'Cascadia Mono', 'Consolas', 'Courier New')


def hex_color(red, green, blue):
    return '#%02X%02X%02X' % tuple(max(0, min(255, round(v*255))) for v in (red, green, blue))


def archived_color(data):
    """(#RRGGBB, alpha) from an NSKeyedArchiver NSColor, as Terminal stores its colours."""
    archive = plistlib.loads(data)
    for item in archive.get('$objects', []):
        if not isinstance(item, dict):
            continue
        if 'NSRGB' in item:
            values = [float(v) for v in item['NSRGB'].rstrip(b'\0').split()]
            alpha = values[3] if len(values) > 3 else 1.0
            return hex_color(*values[:3]), alpha
        if 'NSWhite' in item:
            values = [float(v) for v in item['NSWhite'].rstrip(b'\0').split()]
            alpha = values[1] if len(values) > 1 else 1.0
            return hex_color(values[0], values[0], values[0]), alpha
        if 'NSComponents' in item:
            values = [float(v) for v in item['NSComponents'].rstrip(b'\0').split()]
            if len(values) >= 3:
                return hex_color(*values[:3]), values[3] if len(values) > 3 else 1.0
    raise ValueError('no colour in archive')


def archived_font(data):
    """(PostScript name, size) from an archived NSFont."""
    archive = plistlib.loads(data)
    objects = archive.get('$objects', [])
    for item in objects:
        if isinstance(item, dict) and 'NSName' in item:
            name = item['NSName']
            name = objects[name.data] if isinstance(name, plistlib.UID) else name
            return str(name), float(item.get('NSSize', 13.0))
    raise ValueError('no font in archive')


def mix(first, second, amount):
    a, b = (tuple(int(c.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) for c in (first, second))
    return '#%02X%02X%02X' % tuple(round(x+(y-x)*amount) for x, y in zip(a, b))


def terminal_app_palette(preferences=None):
    """The default Terminal.app profile as a Palette, or None."""
    path = Path(preferences or os.path.expanduser('~/Library/Preferences/com.apple.Terminal.plist'))
    try:
        settings = plistlib.loads(path.read_bytes())
        name = settings.get('Default Window Settings') or settings.get('Startup Window Settings')
        profile = settings.get('Window Settings', {}).get(name)
        if not profile:
            return None
        base = THEMES[FALLBACK]

        def color(key, fallback):
            try:
                return archived_color(profile[key])
            except (KeyError, ValueError, plistlib.InvalidFileException, TypeError):
                return fallback, 1.0
        background, opacity = color('BackgroundColor', base.background)
        text, _ = color('TextColor', base.text)
        font, font_size = '', base.font_size
        if 'Font' in profile:
            try:
                font, font_size = archived_font(profile['Font'])
            except (ValueError, plistlib.InvalidFileException):
                pass
        bright_black, _ = color('ANSIBrightBlackColor', mix(background, text, 0.4))
        return Palette(name, background, text, mix(bright_black, text, 0.15), color('ANSIBlackColor', mix(background, text, 0.18))[0],
                       color('ANSIRedColor', base.red)[0], color('ANSIYellowColor', base.yellow)[0],
                       color('ANSIGreenColor', base.green)[0], color('ANSICyanColor', base.cyan)[0],
                       color('ANSIBlueColor', base.blue)[0], color('SelectionColor', base.selection)[0],
                       max(0.85, opacity), font, font_size)
    except (OSError, ValueError, plistlib.InvalidFileException, AttributeError, TypeError):
        return None


def appearance_file():
    return data_dir()/'appearance.json'


def saved_appearance():
    """{'theme': key, 'face': skin}, with defaults."""
    values = {'theme': 'terminal', 'face': 'blob'}
    try:
        stored = json.loads(appearance_file().read_text())
        if isinstance(stored, dict):
            values.update({key: str(stored[key]) for key in values if key in stored})
    except (OSError, ValueError):
        pass
    return values


def save_appearance(**values):
    current = saved_appearance()
    current.update({key: value for key, value in values.items() if key in current})
    path = appearance_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2))
    return current


def palette(theme=None):
    theme = theme or saved_appearance()['theme']
    if theme == 'terminal':
        found = terminal_app_palette() if sys.platform == 'darwin' else None
        return found or THEMES[FALLBACK]
    return THEMES.get(theme, THEMES[FALLBACK])

