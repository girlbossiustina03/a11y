"""Addresses of common web apps, so "open Teams in Safari" needs no model to find a URL.

Used only when the request names a browser (or the web); "open Teams" alone still
means the installed app. Small local models often produced a bare name such as
"teams" instead of an address, which stalled tasks in live use."""
import re

WEB_APPS = {
    'microsoft teams': 'https://teams.microsoft.com', 'teams': 'https://teams.microsoft.com',
    'outlook': 'https://outlook.office.com/mail', 'office': 'https://www.office.com',
    'onedrive': 'https://onedrive.live.com', 'sharepoint': 'https://www.office.com/launch/sharepoint',
    'gmail': 'https://mail.google.com', 'google mail': 'https://mail.google.com',
    'google calendar': 'https://calendar.google.com', 'google drive': 'https://drive.google.com',
    'google docs': 'https://docs.google.com', 'google sheets': 'https://sheets.google.com',
    'youtube': 'https://www.youtube.com', 'wikipedia': 'https://www.wikipedia.org',
    'whatsapp': 'https://web.whatsapp.com', 'slack': 'https://app.slack.com',
    'github': 'https://github.com', 'linkedin': 'https://www.linkedin.com',
}
# Where a site really lives once open: Teams redirects teams.microsoft.com to
# teams.cloud.microsoft, so the open tab never matched and every request opened another one
# (live: three Teams tabs in a row).
SITE_ALIASES = {
    'teams.microsoft.com': ('teams.cloud.microsoft', 'teams.live.com'),
    'outlook.office.com': ('outlook.cloud.microsoft', 'outlook.office365.com', 'outlook.live.com'),
    'www.office.com': ('m365.cloud.microsoft', 'www.microsoft365.com'),
    'onedrive.live.com': ('onedrive.cloud.microsoft',),
}


def same_site_hosts(url):
    """Other hosts an open tab of this site may show: known redirects and the www. twin."""
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or '').casefold()
    if not host:
        return []
    twin = host[4:] if host.startswith('www.') else 'www.'+host
    return [h for h in (twin, *SITE_ALIASES.get(host, ())) if h != host]


# Sites whose own search results have a fixed address: "open YouTube and search for lo-fi" is
# one navigation instead of a task that clicks through the page (it ended in Safari's address
# bar in live runs). {} is the URL-encoded query.
SEARCH_URLS = {
    'youtube': 'https://www.youtube.com/results?search_query={}', 'google': 'https://www.google.com/search?q={}',
    'wikipedia': 'https://en.wikipedia.org/w/index.php?search={}', 'github': 'https://github.com/search?q={}',
    'duckduckgo': 'https://duckduckgo.com/?q={}', 'bing': 'https://www.bing.com/search?q={}',
    'amazon': 'https://www.amazon.com/s?k={}',
}
SEARCH_PHRASE = re.compile(r'^(?:search|look)(?:\s+(?:it|up|for))*\s+(?P<query>.+?)(?:\s+(?:there|on it))?$', re.I)
BROWSER_WORDS = {'safari': 'Safari', 'chrome': 'Google Chrome', 'edge': 'Microsoft Edge', 'firefox': 'Firefox'}


def find_site(text):
    """(name, url) of the longest known web app named in text, else None."""
    lowered = text.casefold()
    for name in sorted(WEB_APPS, key=len, reverse=True):
        if re.search(r'\b'+re.escape(name)+r'\b', lowered):
            return name, WEB_APPS[name]
    return None


# "the article on Penguin" first, then "the Coffee article" (which also matches "the Wikipedia article").
ARTICLES = (re.compile(r"\b(?:article|page)\s+(?:on|about|for)\s+(?:the\s+)?([\w'’\- ]+?)(?=\s+(?:and|then|to|in)\b|[,.?!]|$)", re.I),
            re.compile(r"\bthe\s+([\w'’\-]+(?:\s+[\w'’\-]+){0,2})\s+(?:article|page)\b", re.I))


def site_address(goal):
    """Where a goal that names a known site starts: the article it names when the site has a
    search page ("the Coffee article on Wikipedia"), else the site itself; None without a site."""
    from urllib.parse import quote_plus
    site = find_site(goal)
    if site is None:
        return None
    for match in (match for pattern in ARTICLES for match in pattern.finditer(goal)):
        topic = match.group(1).strip()
        if site[0] in SEARCH_URLS and topic.casefold() not in (site[0], 'this', 'that', 'current'):  # not "the Wikipedia article"
            return SEARCH_URLS[site[0]].format(quote_plus(topic))
    return site[1]


def browser_named(text):
    """The browser the request names ('' for a generic browser/web mention), else None."""
    lowered = text.casefold()
    for word, name in BROWSER_WORDS.items():
        if re.search(r'\b'+word+r'\b', lowered):
            return name
    if re.search(r'\b(browser|website|web site|web app|online|in the web)\b', lowered):
        return ''
    return None


def browser_mode(text):
    lowered = text.casefold()
    if re.search(r'\bnew (\w+ )?window\b', lowered):
        return 'window'
    if re.search(r'\bnew (\w+ )?tab\b', lowered):
        return 'tab'
    return 'default'


def web_opening(request):
    """An opening step for 'open <known web app> in <browser>' requests, else None."""
    site, browser = find_site(request), browser_named(request)
    if site is None or browser is None:
        return None
    return {'operation': 'browser_open', 'app_name': browser, 'target': site[1], 'browser_mode': browser_mode(request)}


def site_search(site, rest):
    """The results address for "search for <query>" on a site with a known search page, else None."""
    from urllib.parse import quote_plus
    template = SEARCH_URLS.get(site.casefold().strip())
    match = SEARCH_PHRASE.match(rest.strip().rstrip('.!?'))
    if not template or not match:
        return None
    query = match.group('query').strip(' "\'“”')
    return template.format(quote_plus(query)) if query else None
