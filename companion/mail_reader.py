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
# Mail's scripting costs ~0.1 s per property per message on a large inbox: listing 30 messages
# at both ends of a 17,865-message unified inbox took 17 s (live). Instead, each account's own
# inbox is checked for which end is newest (two dates) and only k messages are read from that
# end. Each row is "<inbox>:<position>:<id>" so the text is fetched without searching by id.
LISTING = '''on run argv
  set k to (item 1 of argv) as integer
  set output to ""
  tell application id "com.apple.mail"
    set boxes to mailboxes of inbox
    repeat with b from 1 to count of boxes
      set mb to item b of boxes
      set c to count of messages of mb
      if c > 0 then
        set n to k
        if c < n then set n to c
        if (date received of message 1 of mb) ≥ (date received of message c of mb) then
          set top to 1
        else
          set top to c - n + 1
        end if
        set idList to id of messages top thru (top + n - 1) of mb
        set stamps to date received of messages top thru (top + n - 1) of mb
        repeat with i from 1 to n
          set output to output & b & ":" & (top + i - 1) & ":" & (item i of idList) & (ASCII character 31) & ((item i of stamps) as «class isot» as string) & (ASCII character 30)
        end repeat
      end if
    end repeat
  end tell
  return output
end run'''
MESSAGE = '''on run argv
  set AppleScript's text item delimiters to ":"
  set parts to text items of (item 1 of argv)
  set AppleScript's text item delimiters to ""
  set wanted to (item 3 of parts) as integer
  tell application id "com.apple.mail"
    set mb to item ((item 1 of parts) as integer) of (mailboxes of inbox)
    set m to missing value
    try
      set m to message ((item 2 of parts) as integer) of mb
      if (id of m) is not wanted then set m to missing value
    end try
    -- Mail changed since the listing (new or archived mail): find it by id instead.
    if m is missing value then set m to first message of inbox whose id is wanted
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
    rows = {}
    for row in runner(LISTING, n+5, 45).split(END):
        if SEPARATOR in row:
            key, received = row.strip().split(SEPARATOR, 1)
            if re.fullmatch(r'\d+:\d+:\d+', key.strip()):
                rows[key.strip()] = received.strip()
    if len(rows) < n:
        return None
    ordered = sorted(rows.items(), key=lambda item: item[1], reverse=True)  # ISO dates: newest first
    sender, subject, received, text = (runner(MESSAGE, ordered[n-1][0], 30).rstrip('\n').split(SEPARATOR, 3)+['', '', '', ''])[:4]
    return sender.strip(), subject.strip(), received.strip(), text


def describe(n, found):
    """What A11y says (and reads out) for the nth newest message."""
    which = 'Your last email' if n == 1 else 'Email number '+str(n)+' from the newest'
    if found is None:
        return 'I could not find that many recent emails in your inbox.'
    sender, subject, received, text = found
    name = re.sub(r'\s*<[^>]*>\s*$', '', sender).strip('" ') or sender
    # Mail's plain text keeps image placeholders (U+FFFC) and layout whitespace from HTML mail.
    lines = [re.sub(r'[ \t\u00a0\ufffc]+', ' ', line).strip() for line in text.replace('\r', '').split('\n')]
    body = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()
    if len(body) > 1200:
        body = body[:1200].rsplit(' ', 1)[0]+'…'
    return which+' is from '+name+(', subject "'+subject+'"' if subject else '')+(', received '+received if received else '')+'.'+('\n\n'+body if body else '')
