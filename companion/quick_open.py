"""'Open X' without a model: installed app first, then the web.

Resolution order for X:
1. a browser is named ("in Safari", "in a new Chrome tab"): the web, below;
2. exactly one installed app matches X (same rules as launch requests);
3. a known web app (web_apps.WEB_APPS) or a typed address: open it;
4. otherwise: a web search for X.
Anything after "and"/"then" stays for the computer task. Requests this parser
does not clearly understand return None and go to the model as before."""
import re
from .app_names import resolve_app
from .web_apps import BROWSER_WORDS, WEB_APPS

VERB = r'(?:please\s+)?(?:can you\s+|could you\s+)?(?:open(?:\s+up)?|launch|start|go to|bring up)'
PLACEMENT = re.compile(r'\s+(?:in|on|using|with)\s+(?:a\s+|the\s+)?(new\s+)?(?:(safari|chrome|edge|firefox|browser)\s*)?(window|tab)?\s*$', re.I)
FOLLOW_UP = re.compile(r'\s*(?:,\s*)?\b(?:and(?:\s+then)?|then)\b\s+', re.I)
DOMAIN = re.compile(r'(?:https?://)?(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::\d+)?(?:[/?#]\S*)?', re.I)
LOCAL_THINGS = {'folder', 'folders', 'file', 'files', 'document', 'documents', 'email', 'emails', 'message',
                'messages', 'chat', 'tab', 'tabs', 'window', 'windows', 'page', 'link', 'button', 'menu', 'photo', 'photos'}
FILLER = re.compile(r'(?:\s+(?:yourself|please|for me|now|right now|quickly|real quick))+\s*$', re.I)
# Leading words that make X a description rather than a name ("open the second email",
# "open a new window"); those go to the model.
NOT_A_NAME = {'the', 'a', 'an', 'my', 'this', 'that', 'it', 'new', 'another', 'some', 'your', 'our', 'up'}


def parse(request):
    """{'name', 'browser', 'mode', 'rest'} for 'open X [in <browser> window/tab] [and ...]', else None."""
    text = request.strip().rstrip('.!?')
    match = re.match(VERB+r'\s+(.+)$', text, re.I)
    if not match:
        return None
    head, rest = match.group(1), ''
    split = FOLLOW_UP.search(head)
    if split:
        head, rest = head[:split.start()], head[split.end():].strip()
    head = FILLER.sub('', head)
    browser, mode = None, 'default'
    placement = PLACEMENT.search(head)
    if placement and (placement.group(2) or placement.group(3)):
        new, named, kind = placement.groups()
        head = FILLER.sub('', head[:placement.start()])
        browser = BROWSER_WORDS.get((named or '').casefold(), '')
        kind = (kind or '').casefold()
        mode = 'tab' if kind == 'tab' else 'window' if kind == 'window' and new else 'default'
    name = head.strip(' "\'“”')
    words = name.split()
    if not words or len(words) > 5 or words[0].casefold() in NOT_A_NAME or len(name) > 80:
        return None
    return {'name': name, 'browser': browser, 'mode': mode, 'rest': rest}


def plan(request, catalog):
    """A request plan for a parsed 'open X', or None to let the model interpret it."""
    parsed = parse(request)
    if parsed is None:
        return None
    name, browser, rest = parsed['name'], parsed['browser'], parsed['rest']
    if re.search(r'\b(play|pause|resume|skip|shuffle)\b', rest, re.I):
        return None  # "open Music and play X" uses the dedicated playback path.
    base = {'app_name': browser or '', 'browser_mode': parsed['mode'], 'remaining_request': rest}
    if browser is None:
        apps = resolve_app(name, catalog)
        if len(apps) == 1:
            return {'operation': 'launch_app', 'app_name': apps[0]['name'], 'target': '',
                    'browser_mode': 'default', 'remaining_request': rest}
        if len(apps) > 1:
            return None  # Ambiguous installed apps: let the model ask which one.
    if name.casefold() in WEB_APPS:
        return dict(base, operation='browser_open', target=WEB_APPS[name.casefold()])
    if DOMAIN.fullmatch(name):
        return dict(base, operation='browser_open', target=name)
    if LOCAL_THINGS & {word.casefold() for word in name.split()}:
        return None  # "open downloads folder", "open last email": not a web search.
    return dict(base, operation='browser_search', target=name)
