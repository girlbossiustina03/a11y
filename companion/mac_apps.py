"""Built-in Mac apps, read and changed in code: Calendar, Reminders, Notes, Contacts, Finder,
the browser's current page and Shortcuts.

The interpreter model only decides what the user wants and fills in the details ("tomorrow at
3", "my dentist note"); everything here runs fixed, reviewed commands with those details as
plain data. Nothing is sent to a model except a page's text when the user asks about it.
Reading happens right away. Anything that changes an app (adding an event, reminder or note,
completing a reminder, running a shortcut) is returned as an action the user confirms first.
Calendar and Reminders go through EventKit in the desktop helper (it includes recurring
events); the others use their AppleScript dictionaries or the shortcuts tool."""
from datetime import datetime, timedelta
import html
import os
from pathlib import Path
import re
import subprocess
import sys

SEP, END = '\x1f', '\x1e'
# Operations the interpreter can choose; see request_plan.INTENT_SYSTEM.
READS = ('read_calendar', 'read_reminders', 'read_notes', 'find_contact', 'recent_files', 'open_file',
         'read_page', 'list_shortcuts')
WRITES = ('add_event', 'add_reminder', 'complete_reminder', 'create_note', 'run_shortcut')
OPERATIONS = READS+WRITES
FOLDERS = {'downloads': 'Downloads', 'download': 'Downloads', 'desktop': 'Desktop', 'documents': 'Documents', 'document': 'Documents'}
# Opened directly when asked; anything else (installers, apps, scripts) is only shown in Finder.
OPENABLE = {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.heic', '.webp', '.txt', '.md', '.rtf', '.csv', '.doc', '.docx',
            '.xls', '.xlsx', '.ppt', '.pptx', '.pages', '.numbers', '.key', '.mp3', '.m4a', '.wav', '.mp4', '.mov', '.html'}


class AppError(RuntimeError):
    pass


def available():
    return sys.platform == 'darwin'


def run_script(script, *args, app='The app', timeout=30):
    """Run a fixed AppleScript; arguments are passed as data (argv), never spliced into code."""
    try:
        result = subprocess.run(['osascript', '-e', script, *[str(arg) for arg in args]],
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AppError(app+' took too long to answer. Try again in a moment.') from None
    except OSError:
        raise AppError(app+' could not be reached on this Mac.') from None
    if result.returncode:
        error = result.stderr or ''
        if '-1743' in error:
            raise PermissionError('Allow A11y to control '+app+' in System Settings → Privacy & Security → Automation, then ask again.')
        raise AppError(app+' did not answer. Open it once, then ask again.')
    return result.stdout


def rows(output, fields):
    found = []
    for row in output.split(END):
        if SEP in row or fields == 1:
            parts = row.strip('\n').split(SEP)
            if len(parts) >= fields and any(part.strip() for part in parts):
                found.append([part.strip() for part in parts[:fields]])
    return found


# --- dates -------------------------------------------------------------------------------

def parse_when(value, now=None):
    """'2026-10-24T15:00' (or a date alone) from the interpreter → datetime, else None."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace(' ', 'T'))
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when


def day_range(scope, now=None):
    """(start, end, words) for 'today', 'tomorrow', 'week', 'next', a weekday or an ISO date."""
    now = now or datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    scope = (scope or 'today').strip().casefold()
    if scope in ('tomorrow',):
        return midnight+timedelta(days=1), midnight+timedelta(days=2), 'tomorrow'
    if scope in ('week', 'this week', 'next 7 days', 'upcoming'):
        return now, midnight+timedelta(days=7), 'in the next 7 days'
    if scope in ('next', 'next event', 'next meeting'):
        return now, midnight+timedelta(days=14), 'next'
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    if scope in weekdays:
        ahead = (weekdays.index(scope)-now.weekday()) % 7
        start = midnight+timedelta(days=ahead)
        return start, start+timedelta(days=1), 'on '+scope.capitalize()
    when = parse_when(scope)
    if when is not None:
        start = when.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start+timedelta(days=1), 'on '+start.strftime('%A %d %B')
    return midnight, midnight+timedelta(days=1), 'today'


def clock(when):
    return when.strftime('%H:%M')


def spoken_day(when, now=None):
    now = now or datetime.now()
    days = (when.date()-now.date()).days
    if days == 0:
        return 'today'
    if days == 1:
        return 'tomorrow'
    return when.strftime('%A %d %B')


# --- Calendar and Reminders (EventKit in the desktop helper) -----------------------------------

def read_calendar(bridge, scope, now=None):
    now = now or datetime.now()
    start, end, words = day_range(scope, now)
    events = bridge.calendar_events(int(start.timestamp()), int(end.timestamp()))
    if words == 'next':
        events = [event for event in events if not event.get('all_day')][:1] or events[:1]
        if not events:
            return 'Nothing is on your calendar in the next two weeks.'
        event = events[0]
        begins = datetime.fromtimestamp(event['start'])
        where = ' at '+event['location'] if event.get('location') else ''
        return 'Your next event is '+event['title']+' '+spoken_day(begins, now)+' at '+clock(begins)+where+'.'
    if not events:
        return 'Nothing is on your calendar '+words+'.'
    lines = []
    for event in events[:12]:
        begins, ends = datetime.fromtimestamp(event['start']), datetime.fromtimestamp(event['end'])
        when = 'All day' if event.get('all_day') else clock(begins)+'–'+clock(ends)
        if words.startswith('in the next') and not event.get('all_day'):
            when = begins.strftime('%a ')+when
        lines.append(when+'  '+event['title']+(' ('+event['location']+')' if event.get('location') else ''))
    count = len(events)
    return ('You have '+str(count)+' event'+('s' if count != 1 else '')+' '+words+':\n'+'\n'.join(lines)
            +('\n…and '+str(count-12)+' more.' if count > 12 else ''))


def read_reminders(bridge, scope, now=None):
    now = now or datetime.now()
    items = bridge.reminders()
    end_of_day = now.replace(hour=23, minute=59, second=59)
    if (scope or '').strip().casefold() in ('today', 'due', 'overdue', 'due today'):
        items = [item for item in items if item.get('due') and datetime.fromtimestamp(item['due']) <= end_of_day]
        if not items:
            return 'Nothing is due today.'
    if not items:
        return 'You have no open reminders.'
    items.sort(key=lambda item: item.get('due') or float('inf'))
    lines = []
    for item in items[:10]:
        due = ''
        if item.get('due'):
            when = datetime.fromtimestamp(item['due'])
            due = ' (overdue)' if when < now else ' (due '+spoken_day(when, now)+(' '+clock(when) if when.hour or when.minute else '')+')'
        lines.append(item['title']+due)
    return ('You have '+str(len(items))+' open reminder'+('s' if len(items) != 1 else '')+':\n'+'\n'.join(lines)
            +('\n…and '+str(len(items)-10)+' more.' if len(items) > 10 else ''))


def best_match(name, candidates, key):
    """The one candidate whose key matches name (exact, then contains), or None if 0 or several."""
    wanted = ' '.join(name.casefold().split())
    if not wanted:
        return None
    exact = [item for item in candidates if ' '.join(key(item).casefold().split()) == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [item for item in candidates if wanted in key(item).casefold()]
    return partial[0] if len(partial) == 1 else None


# --- Notes, Contacts, browser page (AppleScript) --------------------------------------------------

NOTES_LIST = '''on run argv
  set output to ""
  set k to 0
  tell application id "com.apple.Notes"
    repeat with n in notes
      set output to output & (id of n) & (ASCII character 31) & (name of n) & (ASCII character 31) & ((modification date of n) as «class isot» as string) & (ASCII character 30)
      set k to k + 1
      if k >= 300 then exit repeat
    end repeat
  end tell
  return output
end run'''
NOTE_TEXT = '''on run argv
  tell application id "com.apple.Notes"
    set t to plaintext of note id (item 1 of argv)
    if (length of t) > 6000 then set t to text 1 thru 6000 of t
    return t
  end tell
end run'''
NOTE_CREATE = '''on run argv
  tell application id "com.apple.Notes"
    set n to make new note at (default folder of default account) with properties {name:(item 1 of argv), body:(item 2 of argv)}
    return name of n
  end tell
end run'''
CONTACTS = '''on run argv
  set output to ""
  set k to 0
  tell application id "com.apple.AddressBook"
    repeat with p in (every person whose name contains (item 1 of argv))
      set phoneList to ""
      repeat with ph in phones of p
        set l to label of ph
        if l is missing value then set l to "phone"
        set phoneList to phoneList & l & ": " & (value of ph) & "; "
      end repeat
      set mailList to ""
      repeat with em in emails of p
        set mailList to mailList & (value of em) & "; "
      end repeat
      set output to output & (name of p) & (ASCII character 31) & phoneList & (ASCII character 31) & mailList & (ASCII character 30)
      set k to k + 1
      if k >= 5 then exit repeat
    end repeat
  end tell
  return output
end run'''
SAFARI_PAGE = '''on run argv
  tell application id "com.apple.Safari"
    set t to current tab of front window
    set pageText to text of t
    if pageText is missing value then set pageText to ""
    if (length of pageText) > 8000 then set pageText to text 1 thru 8000 of pageText
    return (name of t) & (ASCII character 31) & (URL of t) & (ASCII character 31) & pageText
  end tell
end run'''
# One fixed script per Chromium browser: AppleScript needs the app named in the source to
# know its terms ("active tab"), so the browser cannot be passed in as data.
CHROMIUM_PAGE = '''on run argv
  tell application id "BUNDLE"
    set t to active tab of front window
    return (title of t) & (ASCII character 31) & (URL of t) & (ASCII character 31) & ""
  end tell
end run'''
CHROMIUM_PAGES = {bundle: CHROMIUM_PAGE.replace('BUNDLE', bundle) for bundle in ('com.google.Chrome', 'com.microsoft.edgemac')}
SCRIPTS = {'notes_list': NOTES_LIST, 'note_text': NOTE_TEXT, 'note_create': NOTE_CREATE, 'contacts': CONTACTS,
           'safari_page': SAFARI_PAGE, 'chrome_page': CHROMIUM_PAGES['com.google.Chrome'],
           'edge_page': CHROMIUM_PAGES['com.microsoft.edgemac']}
APPS_FOR = {'chrome_page': 'Google Chrome', 'edge_page': 'Microsoft Edge'}  # compiled only where installed


def notes(script=run_script):
    found = [{'id': row[0], 'name': row[1], 'modified': row[2]} for row in rows(script(NOTES_LIST, app='Notes'), 3)]
    found.sort(key=lambda note: note['modified'], reverse=True)
    return found


def read_notes(target, script=run_script):
    found = notes(script)
    if not found:
        return 'You have no notes.'
    wanted = (target or '').strip()
    if wanted.casefold() in ('', 'all', 'list', 'my notes', 'notes'):
        names = [note['name'] for note in found[:6]]
        return 'Your newest notes: '+'; '.join(names)+'. Say “read my note about …” to hear one.'
    note = found[0] if wanted.casefold() in ('latest', 'last', 'newest', 'recent', 'most recent') else best_match(wanted, found, lambda n: n['name'])
    if note is None:
        close = [n['name'] for n in found if any(word in n['name'].casefold() for word in wanted.casefold().split() if len(word) > 2)][:4]
        return 'I could not find one note called “'+wanted+'”.'+(' Did you mean: '+'; '.join(close)+'?' if close else '')
    text = re.sub(r'\n{3,}', '\n\n', script(NOTE_TEXT, note['id'], app='Notes').strip())
    return 'Your note “'+note['name']+'”:\n\n'+(text[:1500].rsplit(' ', 1)[0]+'…' if len(text) > 1500 else text)


def note_body(title, text):
    """Notes stores HTML: the title as the first line, then the text, escaped."""
    lines = ['<div><b>'+html.escape(title)+'</b></div>']+['<div>'+(html.escape(line) or '<br>')+'</div>' for line in text.split('\n')]
    return ''.join(lines)


def find_contact(name, script=run_script):
    name = (name or '').strip()
    if not name:
        return 'Whose contact details do you need?'
    people = rows(script(CONTACTS, name, app='Contacts'), 3)
    if not people:
        return 'I could not find “'+name+'” in your contacts.'
    def clean(value):
        value = re.sub(r'_\$!<([^>]*)>!\$_', r'\1', value)
        return '; '.join(part.strip() for part in value.split(';') if part.strip())
    lines = []
    for person, phones, mails in people[:3]:
        details = ', '.join(part for part in (clean(phones), clean(mails)) if part)
        lines.append(person+(': '+details if details else ': no phone or email saved'))
    return '\n'.join(lines)


def read_page(bundle_id, script=run_script):
    """(title, url, text) of the browser's current tab. Text only from Safari."""
    if bundle_id == 'com.apple.Safari':
        title, url, text = (script(SAFARI_PAGE, app='Safari').split(SEP, 2)+['', '', ''])[:3]
    else:
        if bundle_id not in CHROMIUM_PAGES:
            raise AppError('I can read pages from Safari, Chrome or Edge.')
        title, url, text = (script(CHROMIUM_PAGES[bundle_id], app='your browser').split(SEP, 2)+['', '', ''])[:3]
    return title.strip(), url.strip(), re.sub(r'\n{3,}', '\n\n', text.strip())


# --- Finder ---------------------------------------------------------------------------------------

def recent_files(folder='', home=None, limit=5):
    home = Path(home or Path.home())
    names = [FOLDERS[folder.casefold()]] if folder and folder.casefold() in FOLDERS else ['Downloads', 'Desktop', 'Documents']
    found = []
    for name in names:
        try:
            for entry in os.scandir(home/name):
                if not entry.name.startswith('.'):
                    found.append((entry.stat().st_mtime, Path(entry.path)))
        except OSError:
            continue
    found.sort(reverse=True)
    return [path for _, path in found[:limit]]


def describe_files(paths, folder, now=None):
    if not paths:
        return 'I found no files there.'
    now = (now or datetime.now()).timestamp()
    def age(path):
        minutes = int((now-path.stat().st_mtime)//60)
        return str(minutes)+' min ago' if minutes < 60 else str(minutes//60)+' h ago' if minutes < 1440 else str(minutes//1440)+' days ago'
    place = FOLDERS.get((folder or '').casefold(), 'Downloads, Desktop and Documents')
    return 'Newest in '+place+':\n'+'\n'.join(path.name+' ('+age(path)+')' for path in paths)


def open_file(target, home=None, opener=subprocess.run):
    """Open the named or newest file from Downloads/Desktop/Documents; non-documents are only revealed."""
    wanted = (target or '').strip()
    folder = next((key for key in FOLDERS if key in wanted.casefold()), '')
    candidates = recent_files(folder, home, limit=200)
    plain = re.sub(r'\b(latest|last|newest|recent|most recent|my|the|file|download|downloads|desktop|documents?)\b', ' ', wanted.casefold()).strip()
    path = candidates[0] if candidates and not plain else best_match(plain, candidates, lambda p: p.name)
    if path is None:
        return 'I could not find one file matching “'+wanted+'”.'
    if path.suffix.casefold() in OPENABLE:
        opener(['open', str(path)], capture_output=True, timeout=15)
        return 'Opened '+path.name+'.'
    opener(['open', '-R', str(path)], capture_output=True, timeout=15)
    return 'Showed '+path.name+' in Finder. I only open documents myself; apps and installers you open yourself.'


# --- Shortcuts -------------------------------------------------------------------------------------

def shortcut_names(runner=subprocess.run):
    try:
        result = runner(['shortcuts', 'list'], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        raise AppError('The Shortcuts tool did not answer.') from None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# --- routing ---------------------------------------------------------------------------------------

def fields(target, count):
    parts = [part.strip() for part in (target or '').split('|')]
    return (parts+['']*count)[:count]


def prepare(operation, target, *, bridge, browser=None, script=None, runner=None, now=None):
    """('answer', text) for reads, or ('confirm', action) for changes the user must confirm."""
    now = now or datetime.now()
    script, runner = script or run_script, runner or subprocess.run
    if operation == 'read_calendar':
        return 'answer', read_calendar(bridge, target, now)
    if operation == 'read_reminders':
        return 'answer', read_reminders(bridge, target, now)
    if operation == 'read_notes':
        return 'answer', read_notes(target, script)
    if operation == 'find_contact':
        return 'answer', find_contact(target, script)
    if operation == 'recent_files':
        folder = next((key for key in FOLDERS if key in (target or '').casefold()), '')
        return 'answer', describe_files(recent_files(folder), folder, now)
    if operation == 'open_file':
        return 'answer', open_file(target)
    if operation == 'list_shortcuts':
        names = shortcut_names(runner)
        return 'answer', ('Your shortcuts: '+'; '.join(names[:20])+('…' if len(names) > 20 else '')+'.') if names else 'You have no shortcuts yet.'
    if operation == 'read_page':
        if not browser:
            return 'answer', 'Open the page in Safari, Chrome or Edge first.'
        title, url, text = read_page(browser, script)
        return 'page', {'title': title, 'url': url, 'text': text[:6000]}
    if operation == 'add_event':
        title, start, minutes = fields(target, 3)
        begins = parse_when(start, now)
        if not title or begins is None:
            return 'answer', 'Tell me the event name and when it is, like “add dentist tomorrow at 3”.'
        length = int(minutes) if minutes.isdigit() and 0 < int(minutes) <= 24*60 else 60
        ends = begins+timedelta(minutes=length)
        label = 'Add “'+title[:80]+'” '+spoken_day(begins, now)+' at '+clock(begins)+' to Calendar'
        return 'confirm', {'type': 'app_write', 'kind': 'add_event', 'title': title[:200], 'start': int(begins.timestamp()),
                           'end': int(ends.timestamp()), 'label': label}
    if operation == 'add_reminder':
        title, due = fields(target, 2)
        if not title:
            return 'answer', 'What should I remind you about?'
        when = parse_when(due, now)
        label = 'Add reminder “'+title[:80]+'”'+(' for '+spoken_day(when, now)+' at '+clock(when) if when else '')
        return 'confirm', {'type': 'app_write', 'kind': 'add_reminder', 'title': title[:200],
                           'due': int(when.timestamp()) if when else 0, 'label': label}
    if operation == 'complete_reminder':
        item = best_match(target or '', bridge.reminders(), lambda r: r.get('title', ''))
        if item is None:
            return 'answer', 'I could not find one open reminder called “'+(target or '')+'”.'
        return 'confirm', {'type': 'app_write', 'kind': 'complete_reminder', 'id': item['id'], 'title': item['title'],
                           'label': 'Mark “'+item['title'][:80]+'” as done'}
    if operation == 'create_note':
        title, body = fields(target, 2)
        if not title:
            return 'answer', 'What should the note be called?'
        return 'confirm', {'type': 'app_write', 'kind': 'create_note', 'title': title[:200], 'body': body[:5000],
                           'label': 'Create note “'+title[:80]+'”'}
    if operation == 'run_shortcut':
        names = shortcut_names(runner)
        name = best_match(target or '', names, lambda n: n)
        if name is None:
            return 'answer', 'I could not find one shortcut called “'+(target or '')+'”.'+(' You have: '+'; '.join(names[:8])+'.' if names else '')
        return 'confirm', {'type': 'app_write', 'kind': 'run_shortcut', 'name': name, 'label': 'Run shortcut “'+name[:80]+'”'}
    raise AppError('That app action is not supported.')


def perform(action, *, bridge, script=None, runner=None):
    """Run a change the user confirmed; returns what to tell them."""
    script, runner = script or run_script, runner or subprocess.run
    kind = action.get('kind')
    if kind == 'add_event':
        result = bridge.add_event(action['title'], action['start'], action['end'])
        return 'Added “'+action['title']+'” to '+(result.get('calendar') or 'your calendar')+'.'
    if kind == 'add_reminder':
        result = bridge.add_reminder(action['title'], action.get('due') or 0)
        return 'Added the reminder to '+(result.get('list') or 'Reminders')+'.'
    if kind == 'complete_reminder':
        bridge.complete_reminder(action['id'])
        return 'Marked “'+action['title']+'” as done.'
    if kind == 'create_note':
        script(NOTE_CREATE, action['title'], note_body(action['title'], action.get('body', '')), app='Notes')
        return 'Created the note “'+action['title']+'”.'
    if kind == 'run_shortcut':
        try:
            result = runner(['shortcuts', 'run', action['name']], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            raise AppError('The shortcut did not finish in time.') from None
        if result.returncode:
            raise AppError('The shortcut “'+action['name']+'” stopped with an error.')
        output = (result.stdout or '').strip()
        return 'Ran “'+action['name']+'”.'+(' It returned: '+output[:500] if output else '')
    raise AppError('That app action is not supported.')
