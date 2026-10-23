"""Optional background answers from Wikipedia instead of opening a browser.

Off unless A11Y_WEB_ANSWERS=1: it sends the looked-up phrase to Wikipedia, while the
rest of the app stays local. Only titles/summaries are read; nothing is stored."""
import json
import os
import re
import urllib.parse
import urllib.request

API = 'https://{lang}.wikipedia.org'
QUESTION = re.compile(r'^\s*(where|what|who|whom|whose|when|why|how|which|is|are|was|were|can|could|does|do|did|tell me|explain)\b', re.I)
WANTS_BROWSER = re.compile(r'\b(search|look\s*up|lookup|google|open|browse|website|web\s*site|in (safari|chrome|edge|firefox|the browser|a browser))\b', re.I)
LOOKUP = re.compile(r'^\s*(?:please\s+)?(?:search(?:\s+the\s+web)?\s+for|look\s*up|lookup|google|find info(?:rmation)?\s+(?:on|about))\s+(.+?)\s*[.?!]*$', re.I)


def enabled():
    return os.getenv('A11Y_WEB_ANSWERS', '0').strip().lower() in ('1', 'true', 'on')


def plain_question(request):
    """A question to answer, not a request to search or open something."""
    text = request.strip()
    return bool(QUESTION.search(text) or text.endswith('?')) and not WANTS_BROWSER.search(text)


def lookup_phrase(request):
    """'look up X' / 'search for X' (without naming a browser) → X, else None."""
    match = LOOKUP.match(request)
    if not match or re.search(r'\bin (safari|chrome|edge|firefox|the browser|a browser)\b', request, re.I):
        return None
    return match.group(1).strip(' "\'“”')[:200] or None


def fetch_json(url, timeout=4):
    request = urllib.request.Request(url, headers={'User-Agent': 'A11y-desktop-companion/1.0 (accessibility assistant)'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(500_000))


def summary(phrase, lang='en'):
    """{'title', 'extract', 'url'} for the best Wikipedia match, or None."""
    base = API.format(lang=lang)
    try:
        found = fetch_json(base+'/w/api.php?'+urllib.parse.urlencode(
            {'action': 'opensearch', 'search': phrase, 'limit': 1, 'namespace': 0, 'format': 'json'}))
        if not isinstance(found, list) or len(found) < 2 or not found[1]:
            return None
        title = found[1][0]
        page = fetch_json(base+'/api/rest_v1/page/summary/'+urllib.parse.quote(title.replace(' ', '_'), safe=''))
    except (OSError, ValueError):
        return None
    extract = page.get('extract') if isinstance(page, dict) else None
    if not isinstance(extract, str) or not extract.strip() or page.get('type') == 'disambiguation':
        return None
    url = ((page.get('content_urls') or {}).get('desktop') or {}).get('page') or base+'/wiki/'+urllib.parse.quote(title)
    return {'title': str(page.get('title', title))[:200], 'extract': extract.strip()[:1500], 'url': str(url)[:500]}
