"""Training data for clicking: "find the <kind> labelled X" → where it is, from the accessibility tree.

Opens a fixed list of apps and pages, takes a full-screen screenshot (scaled to 1440 wide, as
the task loop does) and reads every named, clickable target with its bounds from the desktop
helper. Each target becomes one example: the screenshot plus "Find the button labelled
“Share”…" and its center on a 0-1000 grid. Scenes from TEST apps are never trained on; they
score the base model against the trained one (scripts/grounding_eval.py).

Screenshots stay under .data/training (never committed; delete the folder to remove them).
Private apps are never opened: Mail, Messages, Photos, Contacts, Teams, WhatsApp.
"""
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'scripts'))
import live_eval as le  # noqa: E402
from companion.desktop_context import desktop_bridge  # noqa: E402

OUT = ROOT/'.data'/'training'
WIDTH = 1440
KINDS = {'AXButton': 'button', 'AXLink': 'link', 'AXTab': 'tab', 'AXRadioButton': 'tab', 'AXTextField': 'text field',
         'AXSearchField': 'search field', 'AXCheckBox': 'checkbox', 'AXPopUpButton': 'pop-up menu', 'AXMenuButton': 'menu button',
         'AXRow': 'row', 'AXCell': 'item', 'AXStaticText': 'text', 'AXImage': 'icon', 'AXDisclosureTriangle': 'disclosure',
         'AXSlider': 'slider', 'AXComboBox': 'combo box', 'AXMenuBarItem': 'menu'}
PROMPT = 'Find the {kind} labelled “{label}” on the screen. Reply with its center as (x, y), each from 0 to 1000.'

PANES = ['Wi-Fi', 'Bluetooth', 'Network', 'Notifications', 'Sound', 'Focus', 'Screen Time', 'General', 'Appearance',
         'Accessibility', 'Control Center', 'Desktop & Dock', 'Displays', 'Wallpaper', 'Battery', 'Keyboard', 'Trackpad',
         'Printers & Scanners', 'Privacy & Security', 'Siri']
PAGES = ['https://en.wikipedia.org/wiki/Coffee', 'https://en.wikipedia.org/wiki/Special:Random', 'https://github.com/explore',
         'https://news.ycombinator.com', 'https://www.apple.com', 'https://support.apple.com', 'https://duckduckgo.com/?q=weather',
         'https://www.bbc.com/news', 'https://developer.apple.com', 'https://www.python.org', 'https://www.mozilla.org',
         'https://en.wikipedia.org/wiki/Main_Page', 'https://commons.wikimedia.org', 'https://www.gutenberg.org']
# App scenes: (name, bundle, how to open). TEST apps are held out from training.
APPS = [('Finder', 'com.apple.finder', ['open', str(Path.home()/'Downloads')]),
        ('Finder', 'com.apple.finder', ['open', str(Path.home()/'Documents')]),
        ('Notes', 'com.apple.Notes', ['open', '-a', 'Notes']), ('Reminders', 'com.apple.reminders', ['open', '-a', 'Reminders']),
        ('Calendar', 'com.apple.iCal', ['open', '-a', 'Calendar']), ('Calculator', 'com.apple.calculator', ['open', '-a', 'Calculator']),
        ('TextEdit', 'com.apple.TextEdit', ['open', '-a', 'TextEdit']), ('Music', 'com.apple.Music', ['open', '-a', 'Music']),
        ('Dictionary', 'com.apple.Dictionary', ['open', '-a', 'Dictionary']), ('Font Book', 'com.apple.FontBook', ['open', '-a', 'Font Book']),
        ('Activity Monitor', 'com.apple.ActivityMonitor', ['open', '-a', 'Activity Monitor'])]
TEST_APPS = [('Maps', 'com.apple.Maps', ['open', '-a', 'Maps']), ('Weather', 'com.apple.weather', ['open', '-a', 'Weather']),
             ('App Store', 'com.apple.AppStore', ['open', '-a', 'App Store']), ('Clock', 'com.apple.clock', ['open', '-a', 'Clock']),
             ('Preview', 'com.apple.Preview', ['open', '-a', 'Preview']), ('Stocks', 'com.apple.stocks', ['open', '-a', 'Stocks'])]
TEST_PAGES = ['https://www.gnu.org', 'https://www.w3.org', 'https://lobste.rs']
TEST_PANES = ['Users & Groups', 'Lock Screen', 'Login Password']


def screen_size():
    """The main display in points (as the helper's bounds are)."""
    out = le.osa('tell application "Finder" to get bounds of window of desktop')
    left, top, right, bottom = (int(v) for v in out.split(','))
    return {'x': left, 'y': top, 'width': right-left, 'height': bottom-top}


def capture(path):
    raw = path.with_suffix('.full.png')
    subprocess.run(['screencapture', '-x', '-m', str(raw)], check=True)
    subprocess.run(['sips', '-Z', str(WIDTH), str(raw), '--out', str(path)], check=True, capture_output=True)
    raw.unlink()


def examples(scene, targets, screen, image):
    seen, rows = set(), []
    for target in targets:
        label = ' '.join(str(target.get('label') or '').split())
        bounds = target.get('bounds') or {}
        if not label or len(label) > 50 or not all(isinstance(bounds.get(k), (int, float)) for k in ('x', 'y', 'width', 'height')):
            continue
        if bounds['width'] < 6 or bounds['height'] < 6:
            continue
        cx = (bounds['x']+bounds['width']/2-screen['x'])/screen['width']
        cy = (bounds['y']+bounds['height']/2-screen['y'])/screen['height']
        if not (0.005 < cx < 0.995 and 0.005 < cy < 0.995):
            continue
        kind = KINDS.get(target.get('role'), 'control')
        key = (kind, label.casefold())
        if key in seen:
            continue  # the same name twice is ambiguous: leave both out
        seen.add(key)
        box = [round(1000*(bounds['x']-screen['x'])/screen['width']), round(1000*(bounds['y']-screen['y'])/screen['height']),
               round(1000*(bounds['x']+bounds['width']-screen['x'])/screen['width']),
               round(1000*(bounds['y']+bounds['height']-screen['y'])/screen['height'])]
        rows.append({'images': [str(image)], 'scene': scene, 'box': box,
                     'messages': [{'role': 'user', 'content': PROMPT.format(kind=kind, label=label)},
                                  {'role': 'assistant', 'content': '(%d, %d)' % (round(1000*cx), round(1000*cy))}]})
    return rows


def scenes(split):
    if split == 'test':
        return ([('app', name, bundle, cmd) for name, bundle, cmd in TEST_APPS]
                + [('page', page, 'com.apple.Safari', ['open', '-a', 'Safari', page]) for page in TEST_PAGES]
                + [('pane', pane, 'com.apple.systempreferences', None) for pane in TEST_PANES])
    return ([('app', name, bundle, cmd) for name, bundle, cmd in APPS]
            + [('page', page, 'com.apple.Safari', ['open', '-a', 'Safari', page]) for page in PAGES]
            + [('pane', pane, 'com.apple.systempreferences', None) for pane in PANES])


def open_pane(name):
    le.quit_settings()
    subprocess.run(['open', '-b', 'com.apple.systempreferences'])
    time.sleep(2.5)
    try:
        le.osa('tell application "System Events" to tell process "System Settings" to set frontmost to true')
        subprocess.run(['open', 'x-apple.systempreferences:'], check=False)
        # Search the sidebar for the pane, as a person would, so every pane opens the same way.
        le.osa('tell application "System Events" to keystroke "f" using {command down}')
        time.sleep(0.4)
        le.osa('tell application "System Events" to keystroke "%s"' % name.replace('"', ''))
        time.sleep(1.2)
        le.osa('tell application "System Events" to key code 36')
    except RuntimeError:
        pass


def main():
    split = sys.argv[1] if len(sys.argv) > 1 else 'train'
    OUT.mkdir(parents=True, exist_ok=True)
    bridge = desktop_bridge(ROOT/'.data')
    screen = screen_size()
    rows = []
    for number, (kind, name, bundle, command) in enumerate(scenes(split)):
        before = le.snapshot()
        try:
            if kind == 'pane':
                open_pane(name)
            else:
                subprocess.run(command, check=False)
            time.sleep(4 if kind == 'page' else 2.5)
            le.activate(name if kind == 'app' else 'Safari' if kind == 'page' else 'System Settings')
            time.sleep(1)
            sample = bridge.sample_targets(bundle)
            image = OUT/('%s-%02d.png' % (split, number))
            capture(image)
            found = examples('%s:%s' % (kind, name), sample.get('targets') or [], screen, image)
            rows += found
            print('%-6s %-44s %3d targets' % (kind, name[:44], len(found)), flush=True)
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
            print('skipped', name, str(error)[:80], flush=True)
        finally:
            try:
                le.restore(before)
            except (RuntimeError, subprocess.SubprocessError):
                pass
    random.Random(7).shuffle(rows)
    with open(OUT/('%s.jsonl' % ('valid' if split == 'test' else 'train')), 'w') as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False)+'\n')
    print(split, len(rows), 'examples', flush=True)


if __name__ == '__main__':
    main()
