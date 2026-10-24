"""Text faces for the companion: every face is a few lines of monospace characters.

A skin is a template plus, for each state, what fills its slots: '1' the eyes (both eyes
get the same cells), '2' the mouth, '3' a two-cell mark (spinner, z, !). States may have
several frames, played in a loop (talking, a spinner). Nothing here draws; the mascot
paints the lines in the terminal font, one cell per character.
"""
STATES = ('idle', 'blink', 'listening', 'thinking', 'speaking', 'working', 'done', 'stuck', 'sleeping')
# The mascot's states, as desktop.py names them.
STATE_ALIASES = {'guiding': 'working', 'celebrate': 'done'}
SPINNER = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
SLOTS = '123'
DEFAULT_SKIN = 'blob'


def marks(blank='  '):
    """The '3' slot per state: a spinner while thinking or working, z's while asleep. blank
    is what the slot shows otherwise (part of the outline when the mark sits in it)."""
    pad = blank[1:]
    return {'thinking': [c+pad for c in SPINNER], 'working': [c+pad for c in SPINNER],
            'sleeping': ['z'+pad, blank[:1]+'z'], 'stuck': [blank[:1]+'!'], 'listening': [blank]}


def skin(template, eyes, mouths, blank='  '):
    """Frames per state from one template: eyes[state] is rows, mouths[state] is a string
    or a list of strings (frames)."""
    states = {}
    mark = marks(blank)
    for state in STATES:
        mouth = mouths.get(state, mouths['idle'])
        mouth_frames = mouth if isinstance(mouth, list) else [mouth]
        mark_frames = mark.get(state, [blank])
        count = max(len(mouth_frames), len(mark_frames))
        states[state] = [fill(template, {'1': eyes.get(state, eyes['idle']),
                                         '2': [mouth_frames[i % len(mouth_frames)]],
                                         '3': [mark_frames[i % len(mark_frames)]]})
                         for i in range(count)]
    return states


def fill(template, slots):
    """Replace each run of a slot character with that slot's row for this line."""
    rows = {key: 0 for key in slots}
    lines = []
    for line in template:
        used = set()
        out = ''
        i = 0
        while i < len(line):
            key = line[i]
            if key in slots:
                j = i
                while j < len(line) and line[j] == key:
                    j += 1
                value = slots[key][rows[key]]
                if len(value) != j-i:
                    raise ValueError(f'slot {key} needs {j-i} cells, got {value!r}')
                out += value
                used.add(key)
                i = j
            else:
                out += line[i]
                i += 1
        for key in used:
            rows[key] += 1
        lines.append(out)
    return lines


BLOB = skin([
    '   ▄▄▓▓▓▓▓▓▓▓▄▄ 33',
    ' ▄▓▓▀▀      ▀▀▓▓▄ ',
    '▓▓  1111  1111  ▓▓',
    '▓▓  1111  1111  ▓▓',
    '▓▓ ░░   2222 ░░ ▓▓',
    ' ▀▓▓▄▄      ▄▄▓▓▀ ',
    '   ▀▀▓▓▓▓▓▓▓▓▀▀   ',
], eyes={
    'idle': ['▄██▄', '█▀██'], 'blink': ['    ', '▀▀▀▀'], 'listening': ['▄▀▀▄', '▀▄▄▀'],
    'thinking': ['  ▄█', '  ▀▀'], 'working': ['▄▄▄▄', '▀██▀'], 'done': ['▄▀▀▄', '    '],
    'stuck': ['▀▄▄▀', '▄▀▀▄'], 'sleeping': ['    ', '▀▀▀▀'],
}, mouths={
    'idle': '╰──╯', 'speaking': ['╰──╯', '╰▄▄╯'], 'listening': ' ╭╮ ', 'thinking': ' ~~ ',
    'working': '────', 'done': '╲▁▁╱', 'stuck': '╭──╮', 'sleeping': ' ── ',
})

GOGGLES = skin([
    '╭────────────────33╮',
    '│  ╭────╮  ╭────╮  │',
    '│  │1111│  │1111│  │',
    '│  │1111│  │1111│  │',
    '│  ╰────╯  ╰────╯  │',
    '│ ░░    2222    ░░ │',
    '╰──────────────────╯',
], eyes={
    'idle': [' ▄▄ ', ' ▀█ '], 'blink': ['    ', '────'], 'listening': ['▄██▄', '▀██▀'],
    'thinking': ['  ▄▄', '  ▀▀'], 'working': ['▄▄▄▄', ' ▀▀ '], 'done': ['▄▀▀▄', '    '],
    'stuck': ['▀▄▄▀', '▄▀▀▄'], 'sleeping': ['    ', '────'],
}, mouths={
    'idle': '╰──╯', 'speaking': ['╰──╯', '╰▄▄╯'], 'listening': ' ╭╮ ', 'thinking': ' ~~ ',
    'working': '────', 'done': '╲▁▁╱', 'stuck': '╭──╮', 'sleeping': ' ── ',
}, blank='──')

CAT = skin([
    '  ╱▔╲          ╱▔╲33',
    ' ╱ ░ ╲▁▁▁▁▁▁▁▁╱ ░ ╲ ',
    '▕   1111    1111   ▏',
    '▕   1111    1111   ▏',
    '▕ ═══   2222   ═══ ▏',
    ' ╲ ░░          ░░ ╱ ',
    '  ╲▁▁▁▁▁▁▁▁▁▁▁▁▁▁╱  ',
], eyes={
    'idle': [' ▄▄ ', '▐█▀▌'], 'blink': ['    ', ' ▀▀ '], 'listening': ['▄██▄', '▀██▀'],
    'thinking': ['  ▄▄', '  █▀'], 'working': ['    ', '▀██▀'], 'done': ['▄▀▀▄', '    '],
    'stuck': ['▀▄▄▀', '▄▀▀▄'], 'sleeping': ['    ', '▀▀▀▀'],
}, mouths={
    'idle': '╲╱╲╱', 'speaking': ['╲╱╲╱', '╲▁▁╱'], 'listening': ' ╲╱ ', 'thinking': ' ~~ ',
    'working': '╲╱╲╱', 'done': '╲▁▁╱', 'stuck': ' ╭╮ ', 'sleeping': ' ╲╱ ',
})

ROBOT = skin([
    '         ◉33       ',
    '  ┏━━━━━━┻━━━━━━┓  ',
    '  ┃ ┌───┐ ┌───┐ ┃  ',
    '╺━┫ │111│ │111│ ┣━╸',
    '  ┃ └───┘ └───┘ ┃  ',
    '  ┃  222222222  ┃  ',
    '  ┗━━━━━━━━━━━━━┛  ',
], eyes={
    'idle': [' ● '], 'blink': [' ─ '], 'listening': [' ◉ '], 'thinking': ['  ●'],
    'working': [' ■ '], 'done': ['╭─╮'], 'stuck': [' × '], 'sleeping': [' ─ '],
}, mouths={
    'idle': ' ╰─────╯ ', 'speaking': [' ╰─────╯ ', ' ╰▄▄▄▄▄╯ '], 'listening': '   ╭─╮   ',
    'thinking': '  ─ ─ ─  ', 'working': '┌┬┬┬┬┬┬┬┐', 'done': ' ╲▁▁▁▁▁╱ ', 'stuck': '  ╭───╮  ',
    'sleeping': '   ───   ',
})

GHOST = skin([
    '    ▄▀▀▀▀▀▀▀▀▄ 33 ',
    '  ▄▀          ▀▄  ',
    ' █   11    11   █ ',
    ' █   11    11   █ ',
    ' █  ░░  22  ░░  █ ',
    ' █▄▀▄▄▀▄▄▀▄▄▀▄▄▀█ ',
], eyes={
    'idle': ['▄▄', '▀▀'], 'blink': ['  ', '▀▀'], 'listening': ['██', '██'], 'thinking': [' ▄', ' ▀'],
    'working': ['▄▄', '██'], 'done': ['╭╮', '  '], 'stuck': ['╲╱', '╱╲'], 'sleeping': ['  ', '──'],
}, mouths={
    'idle': '╰╯', 'speaking': ['╰╯', '▄▄'], 'listening': '╭╮', 'thinking': '──',
    'working': '──', 'done': '╲╱', 'stuck': '╭╮', 'sleeping': '..',
})


def simple(states):
    """A skin drawn whole per state (no slots). Lines are padded to one width; talking
    alternates the idle and listening faces."""
    width = max(len(line) for lines in states.values() for line in lines)
    frames = {state: [[line.ljust(width) for line in lines]] for state, lines in states.items()}
    frames['speaking'] = frames['idle']+frames['listening']
    return frames

EYES = simple({
    'idle': ['╭────╮  ╭────╮', '│ ██ │  │ ██ │', '╰────╯  ╰────╯', '', '    ╰────╯'],
    'blink': ['', '', '──────  ──────', '', '    ╰────╯'],
    'listening': ['╭────╮  ╭────╮', '│ ▄▄ │  │ ▄▄ │', '│ ▀▀ │  │ ▀▀ │', '╰────╯  ╰────╯', '     ╭──╮'],
    'thinking': ['╭────╮  ╭────╮', '│  ▀▀│  │  ▀▀│', '╰────╯  ╰────╯', '', '      ───'],
    'working': ['', '▄▄▄▄▄▄  ▄▄▄▄▄▄', '│ ██ │  │ ██ │', '╰────╯  ╰────╯', '     ────'],
    'done': ['', ' ╭──╮    ╭──╮', ' ╵  ╵    ╵  ╵', '', '   ╰──────╯'],
    'stuck': ['╭────╮  ╭────╮', '│ ╲╱ │  │ ╲╱ │', '│ ╱╲ │  │ ╱╲ │', '╰────╯  ╰────╯', '    ╭────╮'],
    'sleeping': ['            z', '          z', '──────  ──────', '', '     ╶──╴'],
})

PIXEL = simple({
    'idle': [' ▄██▄    ▄██▄', ' ████    ████', ' ▀██▀    ▀██▀', '', '    ▀▄▄▄▄▀'],
    'blink': ['', '', ' ▀▀▀▀    ▀▀▀▀', '', '    ▀▄▄▄▄▀'],
    'listening': ['▄████▄  ▄████▄', '██████  ██████', '▀████▀  ▀████▀', '', '     ▄██▄'],
    'thinking': [' ▄▄▄▄    ▄▄▄▄', ' ▀██▀    ▀██▀', '', '', '     ▄▄▄▄'],
    'working': ['', ' ▄▄▄▄    ▄▄▄▄', ' ▀██▀    ▀██▀', '', '     ▀▀▀▀'],
    'done': [' ▄▀▀▄    ▄▀▀▄', ' ▀  ▀    ▀  ▀', '', '  ▀▄      ▄▀', '    ▀▀▀▀▀▀'],
    'stuck': [' ▀▄▄▀    ▀▄▄▀', ' ▄▀▀▄    ▄▀▀▄', '', '    ▄▀▀▀▀▄', ''],
    'sleeping': ['          ▄▄▄', '            ▀', ' ▄▄▄▄    ▄▄▄▄', '', '     ▀▀▀▀'],
})

BOXY = simple({
    'idle': ['╭───────────╮', '│  •     •  │', '│     ‿     │', '╰───────────╯'],
    'blink': ['╭───────────╮', '│  -     -  │', '│     ‿     │', '╰───────────╯'],
    'listening': ['╭───────────╮', '│  O     O  │', '│     o     │', '╰───────────╯'],
    'thinking': ['╭───────────╮', '│  °     °  │', '│     ~     │', '╰───────────╯'],
    'working': ['╭───────────╮', '│  >     <  │', '│     ─     │', '╰───────────╯'],
    'done': ['╭───────────╮', '│  ^     ^  │', '│     ▽     │', '╰───────────╯'],
    'stuck': ['╭───────────╮', '│  ×     ×  │', '│     ~     │', '╰───────────╯'],
    'sleeping': ['╭───────────╮z', '│  -     -  │', '│     .     │', '╰───────────╯'],
})

KITTY = simple({
    'idle': [' /\\_____/\\', '(  o   o  )', '( =  ω  = )', ' (")___(")'],
    'blink': [' /\\_____/\\', '(  -   -  )', '( =  ω  = )', ' (")___(")'],
    'listening': [' /\\_____/\\', '(  O   O  )', '( =  o  = )', ' (")___(")'],
    'thinking': [' /\\_____/\\', '(  °   °  )', '( =  ~  = )', ' (")___(")'],
    'working': [' /\\_____/\\', '(  >   <  )', '( =  ω  = )', ' (")___(")'],
    'done': [' /\\_____/\\', '(  ^   ^  )', '( =  ω  = )', ' (")___(")'],
    'stuck': [' /\\_____/\\', '(  ×   ×  )', '( =  ~  = )', ' (")___(")'],
    'sleeping': [' /\\_____/\\ z', '(  -   -  )', '( =  ω  = )', ' (")___(")'],
})

BOT = simple({
    'idle': ['      ╷', '┌─────┴─────┐', '│  ■     ■  │', '│   ╶───╴   │', '└───────────┘'],
    'blink': ['      ╷', '┌─────┴─────┐', '│  ▁     ▁  │', '│   ╶───╴   │', '└───────────┘'],
    'listening': ['      ╷  ))', '┌─────┴─────┐', '│  ■     ■  │', '│    ╭─╮    │', '└───────────┘'],
    'thinking': ['      ╷  ?', '┌─────┴─────┐', '│  ▀     ▀  │', '│   ╶───╴   │', '└───────────┘'],
    'working': ['      ╷ ⠹', '┌─────┴─────┐', '│  ▄     ▄  │', '│   ═════   │', '└───────────┘'],
    'done': ['      ╷', '┌─────┴─────┐', '│  ▲     ▲  │', '│   ╰───╯   │', '└───────────┘'],
    'stuck': ['      ╷  !', '┌─────┴─────┐', '│  ×     ×  │', '│   ╭───╮   │', '└───────────┘'],
    'sleeping': ['      ╷  z', '┌─────┴─────┐', '│  ─     ─  │', '│    ───    │', '└───────────┘'],
})


def braille(pixel, width, height):
    """Rows of braille cells (2×4 dots each) for a pixel test over width×height dots."""
    bits = ((0, 0, 1), (0, 1, 2), (0, 2, 4), (1, 0, 8), (1, 1, 16), (1, 2, 32), (0, 3, 64), (1, 3, 128))
    rows = []
    for top in range(0, height, 4):
        row = ''
        for left in range(0, width, 2):
            value = sum(bit for dx, dy, bit in bits if pixel(left+dx, top+dy))
            row += chr(0x2800+value) if value else ' '
        rows.append(row)
    return rows


def dots_face(eyes, mouth):
    """A round head in braille, 18 cells by 6 lines, with the given eye and mouth tests."""
    width, height = 36, 24
    cx, cy, rx, ry = width/2-.5, height/2-.5, width/2-1, height/2-1

    def pixel(x, y):
        d = ((x-cx)/rx)**2+((y-cy)/ry)**2
        return 0.82 < d <= 1.0 or eyes(x, y) or mouth(x, y)
    return braille(pixel, width, height)


def _dots():
    left, right = 11.5, 23.5

    def oval(rx, ry, top=10, hole=False):
        def test(x, y):
            for ex in (left, right):
                if ((x-ex)/rx)**2+((y-top)/ry)**2 <= 1:
                    return not (hole and x in (int(ex)+1, int(ex)+2) and y in (top-2, top-1))
            return False
        return test

    def ring(x, y):
        for ex in (left, right):
            d = ((x-ex)/4)**2+((y-10)/5)**2
            if 0.55 <= d <= 1 or ((x-ex)/1.3)**2+((y-10)/1.6)**2 <= 1:
                return True
        return False

    def line(y0):
        return lambda x, y: y == y0 and any(abs(x-ex) <= 3 for ex in (left, right))

    def arcs(x, y):
        return any(abs(((x-ex)/3.5)**2+((y-10)/2.5)**2-1) < 0.4 and y <= 10 for ex in (left, right))

    def crosses(x, y):
        return any(abs(x-ex) <= 2.5 and abs(y-10) <= 2.5 and abs(abs(x-ex)-abs(y-10)) < 0.8 for ex in (left, right))

    def look(x, y):
        return any(((x-ex-1)/2.4)**2+((y-8)/3)**2 <= 1 for ex in (left, right))

    def smile(x, y):
        return (y == 17 and 15 <= x <= 20) or (y == 16 and x in (14, 21))

    def open_smile(x, y):
        return 14 <= y <= 19 and ((x-17.5)/6)**2+((y-14)/4.5)**2 <= 1

    def talking(x, y):
        return 15 <= y <= 18 and ((x-17.5)/3)**2+((y-16.5)/2)**2 <= 1

    def oh(x, y):
        return abs(((x-17.5)/2)**2+((y-17)/1.6)**2-1) < 0.45

    def flat(x, y):
        return y == 17 and 15 <= x <= 20

    def dotted(x, y):
        return y == 17 and 15 <= x <= 21 and x % 2 == 1

    def frown(x, y):
        return (y == 16 and 15 <= x <= 20) or (y == 17 and x in (14, 21))

    def blush(x, y):
        return y == 15 and (6 <= x <= 8 or 27 <= x <= 29) and x % 2 == 0

    def both(*tests):
        return lambda x, y: any(test(x, y) for test in tests)

    eyes = {'idle': oval(3.2, 4.2, hole=True), 'blink': line(10), 'listening': ring, 'thinking': look,
            'working': oval(3.2, 2.2, top=11), 'done': arcs, 'stuck': crosses, 'sleeping': line(11)}
    mouths = {'idle': both(smile, blush), 'speaking': [both(smile, blush), both(talking, blush)],
              'listening': oh, 'thinking': dotted, 'working': flat, 'done': both(open_smile, blush),
              'stuck': frown, 'sleeping': flat}
    mark = marks()
    states = {}
    for state in STATES:
        mouth = mouths.get(state, mouths['idle'])
        mouth_frames = mouth if isinstance(mouth, list) else [mouth]
        mark_frames = mark.get(state, ['  '])
        frames = []
        for i in range(max(len(mouth_frames), len(mark_frames))):
            rows = dots_face(eyes.get(state, eyes['idle']), mouth_frames[i % len(mouth_frames)])
            rows[0] = rows[0][:-3]+mark_frames[i % len(mark_frames)]+' '
            frames.append(rows)
        states[state] = frames
    return states


SKINS = {'blob': BLOB, 'goggles': GOGGLES, 'cat': CAT, 'robot': ROBOT, 'ghost': GHOST, 'dots': _dots(),
         'eyes': EYES, 'pixel': PIXEL, 'boxy': BOXY, 'kitty': KITTY, 'bot': BOT}
SKIN_NAMES = {'blob': 'Blob', 'goggles': 'Goggles', 'cat': 'Cat', 'robot': 'Robot', 'ghost': 'Ghost', 'dots': 'Dots',
              'eyes': 'Eyes', 'pixel': 'Pixel', 'boxy': 'Boxy', 'kitty': 'Kitty', 'bot': 'Bot'}


def face(skin_name, state, frame=0):
    """Lines for a skin in a state; frame picks from the state's loop."""
    frames = SKINS.get(skin_name, SKINS[DEFAULT_SKIN])
    state = STATE_ALIASES.get(state, state)
    loop = frames.get(state, frames['idle'])
    return loop[frame % len(loop)]


def size(skin_name):
    """(columns, lines) of a skin's largest face."""
    frames = SKINS.get(skin_name, SKINS[DEFAULT_SKIN])
    faces = [lines for loop in frames.values() for lines in loop]
    return max(len(line) for lines in faces for line in lines), max(len(lines) for lines in faces)


def blinking(elapsed_ms, period=4200):
    """True for the short blink at the end of each period."""
    return (elapsed_ms % period)/period >= 0.955

