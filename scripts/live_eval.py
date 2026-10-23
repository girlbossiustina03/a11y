#!/usr/bin/env python3
"""Run real requests against A11y on this Mac, several times each, and measure them.

    .venv/bin/python scripts/live_eval.py --runs 3
    .venv/bin/python scripts/live_eval.py --only "click on Chat" --runs 5
    .venv/bin/python scripts/live_eval.py --compare .data/live_eval/<earlier>/summary.json

It launches A11y from source with A11Y_EVAL=1 (see companion/eval_control.py) and local
Ollama forced: nothing calls the cloud. Each request is typed into the companion exactly
as a user would; the harness never confirms a proposal, so writes (a reminder, a note)
stay unconfirmed. Results are checked against the real state of the Mac (Safari's page,
Mail's selection, the mascot's position, Calendar's events) and each run records success,
seconds, the route taken and why it failed. Timing records (model calls, prompt tokens,
step stages) come from the app's own `A11y timing` stream.

Side effects, all cleaned up or harmless: Safari tabs and windows the run opened are
closed (never one that was open before), the harness keeps its own Safari window for
web cases, and Teams/Mail views are switched for setup. Clicking the first email
selects it in Mail, which marks it read.

Grant the terminal Accessibility, Screen Recording and Automation (Safari, Mail,
System Events) first. Your saved consent for app awareness and screen vision in
.data is used as is; the harness does not turn either on."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
NEUTRAL = 'https://example.com/'
TEAMS_HOSTS = ('teams.microsoft.com', 'teams.cloud.microsoft', 'teams.live.com')


# --- the Mac ---------------------------------------------------------------------------------

def osa(*lines, timeout=30):
    result = subprocess.run(['osascript', *sum((['-e', line] for line in lines), [])],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:300])
    return result.stdout.strip()


def running(process):
    return osa('tell application "System Events" to return exists process "'+process+'"') == 'true'


def front_app():
    return osa('tell application "System Events" to return name of first process whose frontmost is true')


def activate(app):
    osa('tell application "'+app+'" to activate')
    time.sleep(0.8)


def mail_front():
    """Mail in front with a message viewer window (it can be open with none)."""
    osa('tell application "Mail"', 'if (count of message viewers) is 0 then make new message viewer', 'activate', 'end tell')
    time.sleep(1.2)


def safari_windows():
    """{window id: tab count}; empty (without launching Safari) when it is not running."""
    if not running('Safari'):
        return {}
    for attempt in range(3):  # a window closing mid-listing makes AppleScript fail
        try:
            out = osa('set out to ""', 'tell application "Safari"', 'repeat with w in windows',
                      'set out to out & (id of w) & ":" & (count of tabs of w) & ","', 'end repeat', 'end tell', 'return out')
            break
        except RuntimeError:
            if attempt == 2:
                raise
            time.sleep(0.5)
    return {int(a): int(b) for a, b in (item.split(':') for item in out.split(',') if ':' in item)}


def safari_restore(before):
    """Close the Safari windows and tabs a run added; never one that existed before it.

    Only windows newer than every window seen before the run (Safari numbers them in order)
    and tabs appended after a window's earlier count. Without a snapshot nothing is closed.
    Returns the addresses closed, for the run record."""
    closed = []
    if not before:
        return closed
    newest = max(before)
    def url(script):
        try:
            return osa(script)
        except RuntimeError:
            return '?'
    def ours(address):
        # Only pages these cases open; a tab the user opened meanwhile is left alone.
        return (address in ('', 'missing value', 'favorites://') or address.startswith('safari-extension://')
                or any(host in address for host in TEAMS_HOSTS+('youtube.com', 'example.com', 'duckduckgo.com', 'safari.com')))
    for window, tabs in safari_windows().items():
        if window not in before and window > newest:
            address = url('tell application "Safari" to return URL of current tab of (window id %d)' % window)
            if ours(address) and osa('tell application "Safari" to return count of tabs of (window id %d)' % window) == '1':
                closed.append(address)
                osa('tell application "Safari" to close (window id %d)' % window)
        elif window in before:
            for index in range(tabs, before[window], -1):
                address = url('tell application "Safari" to return URL of tab %d of (window id %d)' % (index, window))
                if ours(address):
                    closed.append(address)
                    osa('tell application "Safari" to close tab %d of (window id %d)' % (index, window))
    return closed


def safari_front_tab():
    """(address, title) of Safari's front tab; Teams' unread count prefix "(2) " is dropped."""
    if not running('Safari'):
        return '', ''
    out = osa('tell application "Safari" to return (URL of current tab of front window) & "\n" & (name of current tab of front window)')
    url, _, title = out.partition('\n')
    return url, re.sub(r'^\(\d+\)\s*', '', title)


class EvalWindow:
    """The harness's own Safari window for web cases."""
    def __init__(self):
        self.id = None

    def ensure(self, url=NEUTRAL, wait_title=None):
        if self.id is None or self.id not in safari_windows():
            self.id = int(osa('tell application "Safari"', 'make new document with properties {URL:"'+url+'"}',
                              'return id of front window', 'end tell'))
        elif not osa('tell application "Safari" to return URL of current tab of window id %d' % self.id).startswith(url.rstrip('/')):
            current = osa('tell application "Safari" to return URL of current tab of window id %d' % self.id)
            if not (wait_title and any(host in current for host in TEAMS_HOSTS) and url.startswith('https://teams')):
                osa('tell application "Safari" to set URL of current tab of window id %d to "%s"' % (self.id, url))
        osa('tell application "Safari"', 'set index of window id %d to 1' % self.id, 'activate', 'end tell')
        deadline = time.monotonic()+30
        while wait_title and time.monotonic() < deadline:
            if wait_title in osa('tell application "Safari" to return name of current tab of window id %d' % self.id):  # noqa
                break
            time.sleep(0.5)
        time.sleep(0.8)

    def close(self):
        if self.id is not None and self.id in safari_windows():
            osa('tell application "Safari" to close (window id %d)' % self.id)


def teams_view(eval_window, view):
    """Teams on the web, frontmost, showing Activity (1) or Chat (2)."""
    eval_window.ensure('https://teams.microsoft.com/', wait_title='Microsoft Teams')
    name = {1: 'Activity', 2: 'Chat'}[view]
    for _ in range(10):  # a cold Teams page ignores shortcuts until it has loaded
        osa('tell application "Safari" to activate')
        time.sleep(0.4)
        osa('tell application "System Events" to keystroke "%d" using {control down, shift down}' % view)
        time.sleep(1.6)
        if safari_front_tab()[1].startswith(name):
            return
    raise RuntimeError('Teams did not switch to '+name)


def mail_newest(n):
    from companion import mail_reader
    found = mail_reader.newest(n)
    return found[1] if found else None


def mail_selection():
    try:
        return osa('tell application "Mail" to return subject of item 1 of (get selection)')
    except RuntimeError:
        return None


def calendar_reply(scope):
    from companion import mac_apps
    from companion.desktop_context import desktop_bridge
    return mac_apps.read_calendar(desktop_bridge(ROOT/'.data'), scope)


def reminders_reply(scope):
    from companion import mac_apps
    from companion.desktop_context import desktop_bridge
    return mac_apps.read_reminders(desktop_bridge(ROOT/'.data'), scope)


# --- the app ---------------------------------------------------------------------------------

class App:
    def __init__(self, data, log):
        import tempfile
        # A private folder: macOS limits socket paths to 104 characters, too short for some data folders.
        self.socket = Path(tempfile.mkdtemp(prefix='a11y-eval-'))/'eval.sock'
        self.log = log
        self.process = None

    def call(self, command, timeout=25):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(self.socket))
            connection.sendall(json.dumps(command).encode()+b'\n')
            data = b''
            while not data.endswith(b'\n'):
                chunk = connection.recv(1 << 20)
                if not chunk:
                    break
                data += chunk
        reply = json.loads(data)
        if 'error' in reply:
            raise RuntimeError('A11y: '+reply['error'])
        return reply

    def launch(self):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('ANTHROPIC_', 'OPENAI_')) and key not in ('A11Y_AI_BASE_URL', 'A11Y_AI_KEY')}
        env.update(A11Y_EVAL='1', A11Y_EVAL_SOCKET=str(self.socket), A11Y_AI_PROVIDER='ollama', A11Y_WEB_ANSWERS='0', PYTHONUNBUFFERED='1')
        if self.socket.exists():
            self.socket.unlink()
        self.process = subprocess.Popen([sys.executable, str(ROOT/'a11y_desktop.py')], cwd=ROOT, env=env,
                                        stdout=open(self.log, 'a'), stderr=subprocess.STDOUT)
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise SystemExit('A11y exited at launch; see '+str(self.log))
            try:
                state = self.call({'cmd': 'state', 'since': 10**9})
                if all(state['ready'].values()) and state['idle']:
                    return state
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(0.5)
        raise SystemExit('A11y did not get ready (app awareness and screen vision must be remembered as on).')

    def quit(self):
        if self.process and self.process.poll() is None:
            try:
                self.call({'cmd': 'stop'})
                self.call({'cmd': 'quit'})
                self.process.wait(15)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                self.process.terminate()

    def run(self, request, timeout):
        """Type the request, wait until the companion is quiet, return what happened."""
        start = self.call({'cmd': 'state', 'since': 10**9})['event_count']
        while True:
            try:
                self.call({'cmd': 'ask', 'request': request})
                break
            except RuntimeError as error:
                if 'busy' not in str(error):
                    raise
                time.sleep(0.3)
        deadline, events, state = time.monotonic()+timeout, [], {}
        while time.monotonic() < deadline:
            state = self.call({'cmd': 'state', 'since': start+len(events)})
            events.extend(state['events'])
            if state['idle'] and state['quiet_for'] >= 1.6:
                return state, events, False
            time.sleep(0.2)
        self.call({'cmd': 'stop'})
        return state, events, True


# --- cases -----------------------------------------------------------------------------------

def said(events):
    return [event['data']['message'] for event in events if event['kind'] == 'say']


def final_message(events):
    """The last thing said that is not a progress line."""
    from companion.desktop import progress_message
    lines = [message for message in said(events) if not progress_message(message)]
    return lines[-1] if lines else ''


def failed_reply(message):
    return bool(re.match(r'^(I couldn’t do that|I stopped:|I could not find a safe next step)', message))


def task_status(state):
    return (state.get('task') or {}).get('status')


def check_task_done(state, events):
    status = task_status(state)
    if status != 'done':
        return 'task ended '+str(status)+': '+final_message(events)[:160]
    return None


class Case:
    def __init__(self, request, check, *, setup=None, timeout=120, routes=()):
        self.request, self.check, self.setup, self.timeout, self.routes = request, check, setup, timeout, routes


def build_cases(eval_window):
    def teams_open_check(state, events):
        url, _ = safari_front_tab()
        if front_app() != 'Safari' or not any(host in url for host in TEAMS_HOSTS):
            return 'front is '+front_app()+' '+url[:80]
        return None

    def chat_check(state, events):
        _, title = safari_front_tab()
        if not title.startswith('Chat'):
            return 'Teams shows '+title.split('|')[0].strip()
        return check_task_done(state, events)

    def activity_check(state, events):
        _, title = safari_front_tab()
        if not title.startswith('Activity'):
            return 'Teams shows '+title.split('|')[0].strip()
        if task_status(state) != 'done' or failed_reply(final_message(events)):
            return 'task ended '+str(task_status(state))+': '+final_message(events)[:160]
        return None

    def second_email_check(state, events):
        subject = mail_newest(2)
        message = final_message(events)
        if not subject or subject not in message:
            return 'reply lacks subject “'+str(subject)[:60]+'”: '+message[:120]
        return None

    def calendar_check(state, events):
        expected = calendar_reply('tomorrow')
        message = final_message(events)
        if message.strip() != expected.strip():
            return 'reply “'+message[:100]+'” ≠ “'+expected[:100]+'”'
        return None

    def reminder_check(state, events):
        action = state.get('pending_action') or {}
        label = action.get('label') or ''
        # The next 6 o'clock: this evening, or tomorrow (morning or evening) after 18:00.
        times = ('today at 18:00',) if datetime.now().hour < 18 else ('tomorrow at 06:00', 'tomorrow at 18:00')
        if action.get('type') != 'app_write' or 'call mom' not in label.casefold() or not any(t in label for t in times):
            return 'proposal: '+(label or final_message(events))[:160]
        return None

    def youtube_check(state, events):
        # A site blocker on this Mac (Cold Turkey) replaces YouTube with its own page, so what
        # A11y controls is where it navigated: the results page for the query.
        url, _ = safari_front_tab()
        wanted = lambda value: 'youtube.com/results' in value and re.search(r'lo(?:-|\+|%20)?fi', value, re.I)
        sent = [e['data']['message'] for e in events if e['kind'] == 'say' and 'youtube.com/results' in e['data']['message']]
        if wanted(url) or (url.startswith('safari-extension://') and any(wanted(message) for message in sent)):
            return None
        return 'Safari shows '+url[:100]

    def new_window_check(state, events):
        return None  # judged against the window list in run_case

    def move_left_check(state, events):
        mascot, screen = state['mascot'], state['screen']
        if mascot['x'] > screen['x']+40:
            return 'mascot at x=%d' % mascot['x']
        return None

    def first_email_check(state, events):
        clicked = [r for r in (state.get('task') or {}).get('receipts', []) if r['type'] in ('click_point', 'press_control')]
        if not clicked:
            return 'no click: '+final_message(events)[:120]
        selected, newest = mail_selection(), mail_newest(1)
        if not selected or selected != newest:
            return 'selected “'+str(selected)[:50]+'”, newest “'+str(newest)[:50]+'”'
        if failed_reply(final_message(events)):
            return final_message(events)[:160]
        return None

    def screen_check(state, events):
        message = final_message(events)
        if (state.get('plan') or {}).get('operation') != 'inspect_screen':
            return 'route '+str((state.get('plan') or {}).get('operation'))
        if (failed_reply(message) or not re.search(r'\b(mail|inbox|e-?mails?|messages?)\b', message, re.I)
                or re.search(r'\bnot (?:currently )?(?:visible|open|shown)\b', message, re.I)):
            return 'reply: '+message[:160]
        return None

    def reminders_check(state, events):
        expected, message = reminders_reply('today'), final_message(events)
        if message.strip() != expected.strip():
            return 'reply “'+message[:100]+'” ≠ “'+expected[:100]+'”'
        return None

    def calculator_check(state, events):
        message = final_message(events)
        if not re.search(r'\b42\b', message) or failed_reply(message):
            return 'reply: '+message[:160]
        return None

    def follow_up_check(state, events):
        expected, message = calendar_reply('tomorrow'), final_message(events)
        if message.strip() != expected.strip():
            return 'reply “'+message[:100]+'” ≠ “'+expected[:100]+'”'
        return None

    def remembered_check(state, events):
        message = final_message(events)
        if not re.search(r'\b14\b|fourteen', message, re.I):
            return 'reply: '+message[:160]
        return None

    def name_check(state, events):
        message = final_message(events)
        if 'Ana' not in message:
            return 'reply: '+message[:160]
        return None

    def teams_neutral():
        eval_window.ensure(NEUTRAL)
        activate('Finder')

    def at_bottom_right(app):
        app.run('move to the bottom right', 30)

    return [
        Case('Microsoft Teams.', teams_open_check, setup=lambda app: teams_neutral(), timeout=60),
        Case('click on Chat', chat_check, setup=lambda app: teams_view(eval_window, 1)),
        Case('check if I have new notifications on Teams', activity_check, setup=lambda app: teams_view(eval_window, 2), timeout=180),
        Case('read my second last email', second_email_check, timeout=90),
        Case("what's on my calendar tomorrow", calendar_check, timeout=60),
        Case('remind me to call mom at 6', reminder_check, timeout=60),
        Case('open youtube and search for lo-fi', youtube_check, setup=lambda app: teams_neutral(), timeout=180),
        Case('open a new Safari window', new_window_check, setup=lambda app: eval_window.ensure(NEUTRAL), timeout=60),
        Case('move to the left', move_left_check, setup=at_bottom_right, timeout=30),
        Case('click the first email in Mail', first_email_check, setup=lambda app: mail_front(), timeout=180),
        Case("what's on my screen", screen_check, setup=lambda app: mail_front(), timeout=120),
        Case('what do I have to do today', reminders_check, timeout=60),
        Case('open the calculator and add 12 and 30', calculator_check, setup=lambda app: activate('Finder'), timeout=120),
        Case('what about tomorrow?', follow_up_check, setup=lambda app: app.run("what's on my calendar today", 60), timeout=60),
        # A conversation, as reported: Teams just opened, then a question that does not name it.
        Case('are there any notifications that require my attention', activity_check,
             setup=lambda app: (teams_view(eval_window, 2), app.run('open teams in a new safari window', 60)), timeout=180),
        Case('what number did I just say', remembered_check, setup=lambda app: app.run('14', 60), timeout=60),
        Case('my name is Ana. what is my name?', name_check, timeout=60),
    ]


# --- running and reporting -------------------------------------------------------------------

def metrics(events):
    timings = [event['data'] for event in events if event['kind'] == 'timing']
    calls = [record for record in timings if record['event'] == 'ollama.finished']
    return {'model_calls': len(calls), 'model_ms': sum(record.get('elapsed_ms', 0) for record in calls),
            'prompt_tokens': sum(record.get('prompt_eval_count', 0) for record in calls),
            'prompt_ms': sum(record.get('prompt_eval_ms', 0) for record in calls),
            'load_ms': sum(record.get('load_ms', 0) for record in calls),
            'image_calls': sum(1 for record in timings if record['event'] == 'ollama.start' and record.get('image')),
            'invalid_steps': sum(1 for record in timings if record['event'] == 'task.step.invalid'),
            'reconsiders': sum(1 for record in timings if record['event'] == 'task.reconsider.start'),
            'steps': [{key: record.get(key) for key in ('step', 'status', 'total_ms', 'settle_ms', 'capture_ms', 'model_ms', 'model_calls', 'context_chars')}
                      for record in timings if record['event'] == 'task.step.summary']}


def route_of(state, events):
    plan = state.get('plan') or {}
    route = str(plan.get('operation'))+('·code' if plan.get('computed') else '')
    task = state.get('task')
    if task and any(e['kind'] == 'timing' and e['data']['event'].startswith('task.') for e in events):
        route += ' → '+' / '.join((r['type']+(':'+r['label'] if r.get('label') else ''))[:40] for r in task['receipts'])
    return route


def run_case(app, case, attempt):
    if case.setup:
        case.setup(app)
    before = safari_windows()
    state, events, timed_out = app.run(case.request, case.timeout)
    asked = next((event['t'] for event in events if event['kind'] == 'ask'), None)
    # Until the companion went quiet: the last reply, action or animation, whichever ended last.
    seconds = round(state['now']-state['quiet_for']-asked, 2) if asked is not None and 'now' in state else None
    failure = 'timeout' if timed_out else None
    if failure is None:
        if case.check.__name__ == 'new_window_check':
            added = [w for w in safari_windows() if w not in before]
            failure = None if len(added) == 1 else 'new Safari windows: %d' % len(added)
            if not failure:
                url = osa('tell application "Safari" to return URL of current tab of window id %d' % added[0])
                if url.startswith('http'):
                    failure = 'the new window opened '+url[:80]  # a new window, not a website
        else:
            try:
                failure = case.check(state, events)
            except Exception as error:
                failure = 'check failed: '+str(error)[:160]
    record = {'request': case.request, 'attempt': attempt, 'success': failure is None, 'seconds': seconds,
              'route': route_of(state, events), 'failure': failure, 'reply': final_message(events)[:300],
              'task_status': task_status(state), **metrics(events)}
    try:
        record['closed'] = safari_restore(before)
    except RuntimeError as error:
        record['closed'] = ['error: '+str(error)[:100]]
    record['front_app'] = front_app()
    if state.get('task') and state['task']['status'] == 'running':
        app.call({'cmd': 'stop'})
    return record


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values)-1, round(fraction*(len(values)-1)))] if values else None


def summarize(records):
    summary = {}
    for request in dict.fromkeys(record['request'] for record in records):
        runs = [record for record in records if record['request'] == request]
        times = [record['seconds'] for record in runs if record['seconds'] is not None]
        summary[request] = {'runs': len(runs), 'success': sum(record['success'] for record in runs),
                            'rate': round(sum(record['success'] for record in runs)/len(runs), 2),
                            'median_s': round(statistics.median(times), 1) if times else None,
                            'p95_s': round(percentile(times, .95), 1) if times else None,
                            'routes': sorted(set(record['route'] for record in runs)),
                            'failures': [record['failure'] for record in runs if record['failure']]}
    return summary


def table(summary, earlier=None):
    lines = ['%-46s %7s %8s %8s' % ('request', 'success', 'median', 'p95')+('   before' if earlier else '')]
    for request, row in summary.items():
        line = '%-46s %3d/%-3d %7ss %7ss' % (request[:46], row['success'], row['runs'], row['median_s'], row['p95_s'])
        old = (earlier or {}).get(request)
        if old:
            line += '   %d/%d %ss %ss' % (old['success'], old['runs'], old['median_s'], old['p95_s'])
        lines.append(line)
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--only', action='append', help='run only requests containing this text (repeatable)')
    parser.add_argument('--out', default=str(ROOT/'.data'/'live_eval'))
    parser.add_argument('--compare', help='an earlier summary.json to show next to the results')
    args = parser.parse_args()
    out = Path(args.out)/datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    from companion.instance import build_id
    print('build', build_id(), '→', out, flush=True)
    app = App(ROOT/'.data', out/'app.log')
    eval_window = EvalWindow()
    cases = [case for case in build_cases(eval_window) if not args.only or any(text.casefold() in case.request.casefold() for text in args.only)]
    records = []
    app.launch()
    try:
        for case in cases:
            for attempt in range(1, args.runs+1):
                try:
                    record = run_case(app, case, attempt)
                except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                    record = {'request': case.request, 'attempt': attempt, 'success': False, 'seconds': None,
                              'route': '', 'failure': 'harness: '+str(error)[:200], 'reply': ''}
                records.append(record)
                with open(out/'runs.jsonl', 'a') as file:
                    file.write(json.dumps(record, ensure_ascii=False)+'\n')
                print('%s %-44s %6ss  %s%s' % ('✓' if record['success'] else '✗', case.request[:44], record['seconds'],
                      record['route'][:70], '' if record['success'] else '  ← '+str(record['failure'])[:120]), flush=True)
    finally:
        app.quit()
        eval_window.close()
    summary = summarize(records)
    summary_all = {'build': build_id(), 'when': datetime.now().isoformat(timespec='seconds'), 'runs': args.runs, 'requests': summary}
    (out/'summary.json').write_text(json.dumps(summary_all, indent=1, ensure_ascii=False))
    earlier = json.loads(Path(args.compare).read_text())['requests'] if args.compare else None
    print('\n'+table(summary, earlier))
    total = sum(row['success'] for row in summary.values()), sum(row['runs'] for row in summary.values())
    print('\noverall %d/%d' % total)


if __name__ == '__main__':
    main()
