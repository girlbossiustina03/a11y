"""Read emails from Apple Mail in code: "read my last email", "what does my second last email say".

Screenshots of a 16,000-message inbox were unreliable (the model mixed up which message was
last and could not read the text). Mail's own scripting interface returns the exact sender,
subject, date and text, so the nth newest inbox message is found by its date, not by eye.
Only fixed scripts run; the request supplies just a number. Nothing is sent to any model.
macOS asks once whether A11y may control Mail."""
import re
import subprocess
import sys

ORDINALS = {'last': 1, 'latest': 1, 'newest': 1, 'most recent': 1, 'recent': 1,
            'first': 1, 'second': 2, '2nd': 2, 'third': 3, '3rd': 3, 'fourth': 4, '4th': 4, 'fifth': 5, '5th': 5}
REQUEST = re.compile(
    r'\b(?:read|reading|what(?:\'s| is| does| did| was)?|check|tell me|show|open|summar\w*|who sent)\b.*?'
    r'\b(?P<position>(?:(?:second|2nd|third|3rd|fourth|4th|fifth|5th)(?:\s+(?:to\s+)?)?)?(?:last|latest|newest|most recent|recent))\b'
    r'\s+(?:(?:un)?read\s+)?(?:e-?mails?|mails?|messages? in mail)\b', re.I)
SEPARATOR, END = '\x1f', '\x1e'
LISTING = '''on run argv
  set cutoff to (current date) - ((item 1 of argv) as integer) * days
  set output to ""
  tell application id "com.apple.mail"
    set found to (messages of inbox whose date received > cutoff)
    repeat with m in found
      set output to output & (id of m as string) & (ASCII character 31) & ((date received of m) as «class isot» as string) & (ASCII character 30)
    end repeat
  end tell
  return output
end run'''
MESSAGE = '''on run argv
  set wanted to (item 1 of argv) as integer
  tell application id "com.apple.mail"
    set m to first message of inbox whose id is wanted
    set bodyText to content of m
    if (length of bodyText) > 4000 then set bodyText to text 1 thru 4000 of bodyText
    return (sender of m) & (ASCII character 31) & (subject of m) & (ASCII character 31) & ((date received of m) as string) & (ASCII character 31) & bodyText
  end tell
end run'''


def position(request):
    """1 for 'last/latest email', 2 for 'second last', … or None when the request is not about that."""
    match = REQUEST.search(request)
    if not match or re.match(r'\s*(?:from|about|regarding|with|in|on|that)\b', request[match.end():], re.I):
        return None  # "latest email from Ana" asks for a specific one, not just the newest
    words = match.group('position').casefold()
    return next((value for word, value in ORDINALS.items() if words.startswith(word) and word not in ('last', 'latest', 'newest', 'most recent', 'recent')), 1)


def available():
    return sys.platform == 'darwin'


def run(script, argument, timeout):
    result = subprocess.run(['osascript', '-e', script, str(argument)], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        error = result.stderr or ''
        if '-1743' in error:
            raise PermissionError('Allow A11y to control Mail in System Settings → Privacy & Security → Automation, then ask again.')
        raise RuntimeError('Mail did not answer. Open Mail once, then ask again.')
    return result.stdout


def newest(n, runner=run):
    """(sender, subject, date, text) of the nth newest inbox message, or None if there are fewer."""
    for days in (3, 30, 365):
        listing = runner(LISTING, days, 60)
        rows = []
        for row in listing.split(END):
            if SEPARATOR in row:
                message_id, received = row.strip().split(SEPARATOR, 1)
                if message_id.strip().isdigit():
                    rows.append((received.strip(), int(message_id)))
        if len(rows) >= n:
            rows.sort(reverse=True)  # ISO dates sort chronologically; newest first
            sender, subject, received, text = (runner(MESSAGE, rows[n-1][1], 30).rstrip('\n').split(SEPARATOR, 3)+['', '', '', ''])[:4]
            return sender.strip(), subject.strip(), received.strip(), text
    return None


def describe(n, found):
    """What A11y says (and reads out) for the nth newest message."""
    which = 'Your last email' if n == 1 else 'Email number '+str(n)+' from the newest'
    if found is None:
        return 'I could not find that many recent emails in your inbox.'
    sender, subject, received, text = found
    name = re.sub(r'\s*<[^>]*>\s*$', '', sender).strip('" ') or sender
    body = re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]+', ' ', text)).strip()
    if len(body) > 1200:
        body = body[:1200].rsplit(' ', 1)[0]+'…'
    return which+' is from '+name+(', subject "'+subject+'"' if subject else '')+(', received '+received if received else '')+'.'+('\n\n'+body if body else '')
