"""Background answers from Wikipedia instead of opening a browser.

On unless turned off in Preferences (or A11Y_WEB_ANSWERS=0): only the looked-up phrase goes to
Wikipedia; screens, mail, files and the conversation never do. Only titles and summaries are
read; nothing is stored. The AI itself stays local."""
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
    value = os.getenv('A11Y_WEB_ANSWERS')
    if value is None:
        from .paths import saved_ai_settings
        value = saved_ai_settings().get('web_lookups', 'on')
    return value.strip().lower() in ('1', 'true', 'on')


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
    request = urllib.request.Request(url, headers={'User-Agent': 'A11y-desktop-companion/1.0 (https://github.com/iediot/a11y; accessibility assistant)'})
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


STOPWORDS = set('the a an of in on at to for is are was were be what who whom whose when where which why how '
                'does do did can could tell me about please and or with as by from this that it its there their'.split())


def fold(text):
    """Lower case without accents, so "Brasov" matches "Brașov"."""
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def words(text):
    return {w for w in re.findall(r'[^\W_]+', fold(text)) if w not in STOPWORDS and len(w) > 1}


def keywords(text):
    """The question's content words, in order: question words make Wikipedia's search drift
    ("who is the mayor of Brasov" found the village of Bran; "mayor brasov" finds Brașov)."""
    kept = [w for w in re.findall(r'[^\W_]+', text) if w.casefold() not in STOPWORDS]
    return ' '.join(kept) or text


def passages(text, question, limit=2600):
    """The article's lead section plus the paragraphs that best share the question's words,
    rarer words counting more (in the Eurovision 2025 article every paragraph says
    "Eurovision"; only one says "won"), in article order, up to limit characters."""
    lead, _, body = text.partition('\n==')
    paragraphs = [p.strip() for p in ('==' + body if body else '').split('\n') if len(p.strip()) > 40 and not p.strip().startswith('==')]
    opening = ' '.join(p.strip() for p in lead.split('\n') if p.strip())[:1400]
    wanted = words(question)
    seen = [words(p) for p in paragraphs]
    frequency = {w: sum(w in s for s in seen) for w in wanted}
    def score(index):
        return sum(1/frequency[w] for w in wanted & seen[index] if frequency[w])
    keep, size = [], len(opening)
    for index in sorted(range(len(paragraphs)), key=lambda i: -score(i))[:6]:
        if score(index) <= 0 or size+len(paragraphs[index]) > limit:
            continue
        keep.append(index)
        size += len(paragraphs[index])
    return '\n'.join([opening]+[paragraphs[i] for i in sorted(keep)]).strip()[:limit]


def best_hit(hits, question):
    """Of the search's first results, the one whose title shares most words with the question
    ("how tall is the Eiffel Tower": Eiffel Tower, not Petřín Lookout Tower)."""
    wanted = words(question)
    asked = ' '+' '.join(re.findall(r'[^\W_]+', fold(question)))+' '
    def rank(pair):
        name = pair[1].get('title', '')
        title = words(name)
        named = ' '+' '.join(re.findall(r'[^\W_]+', fold(name)))+' ' in asked  # the question names this page
        return named, len(wanted & title), -len(title-wanted), -pair[0]  # then fewest extra words, then order
    return max(enumerate(hits), key=rank)[1]


def search(topic, lang='en'):
    """Wikipedia's full-text search for a topic or question, then the parts of that article
    that bear on it: "who is the mayor of Brasov" finds Brașov's article and its mayor."""
    base = API.format(lang=lang)
    try:
        found = fetch_json(base+'/w/api.php?'+urllib.parse.urlencode(
            {'action': 'query', 'list': 'search', 'srsearch': keywords(topic)[:200], 'srlimit': 5, 'format': 'json'}))
        hits = [hit for hit in (found.get('query', {}).get('search', []) if isinstance(found, dict) else []) if hit.get('title')]
        if not hits:
            return None
        title = best_hit(hits, topic)['title']
        pages = fetch_json(base+'/w/api.php?'+urllib.parse.urlencode(
            {'action': 'query', 'prop': 'extracts', 'explaintext': 1, 'exsectionformat': 'wiki', 'redirects': 1, 'titles': title,
             'format': 'json', 'formatversion': 2})).get('query', {}).get('pages', [])
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return None
    text = pages[0].get('extract', '') if pages and isinstance(pages[0], dict) else ''
    chosen = passages(text, topic) if isinstance(text, str) else ''
    if not chosen:
        return None
    return {'title': title[:200], 'extract': chosen, 'url': base+'/wiki/'+urllib.parse.quote(title.replace(' ', '_'))}


GROUNDED_SYSTEM = (
    'Answer the question in one or two short, plain sentences using ONLY the text given. '
    'found is false when the text does not contain the answer (then answer is empty). '
    'Never add facts from memory and never mention "the text".')
GROUNDED_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['found', 'answer'],
                   'properties': {'found': {'type': 'boolean'}, 'answer': {'type': 'string'}}}


def answer(provider, question, topic=''):
    """(answer, source) from a background lookup, answered only from what was found, or None."""
    found = search(topic or question)
    if not found:
        return None
    reply = provider.complete_structured(
        GROUNDED_SYSTEM, [{'role': 'user', 'content': json.dumps(
            {'question': question, 'text': found['extract'], 'title': found['title']}, ensure_ascii=False)}],
        schema=GROUNDED_SCHEMA, max_tokens=160, thinking=False)
    if not isinstance(reply, dict) or reply.get('found') is not True:
        return None
    text = str(reply.get('answer', '')).strip()
    return (text[:600], found) if text else None
