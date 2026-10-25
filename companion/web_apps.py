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
    'hacker news': 'https://news.ycombinator.com', 'reddit': 'https://www.reddit.com',
    # Places inside a site that people name: straight there, not the home page (live, v3).
    'github notifications': 'https://github.com/notifications', 'apple support': 'https://support.apple.com',
}
# Where a site really lives once open: Teams redirects teams.microsoft.com to
# teams.cloud.microsoft, so the open tab never matched and every request opened another one
# (live: three Teams tabs in a row).
SITE_ALIASES = {
    'teams.microsoft.com': ('teams.cloud.microsoft', 'teams.live.com'),
    'outlook.office.com': ('outlook.cloud.microsoft', 'outlook.office365.com', 'outlook.live.com'),
    'www.office.com': ('m365.cloud.microsoft', 'www.microsoft365.com'),
    'onedrive.live.com': ('onedrive.cloud.microsoft',),
    'www.wikipedia.org': ('en.wikipedia.org',),  # the portal: an open English article is Wikipedia too
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
    'amazon': 'https://www.amazon.com/s?k={}', 'apple support': 'https://support.apple.com/kb/index?page=search&q={}',
}
SEARCH_PHRASE = re.compile(r'^(?:search|look)(?:\s+(?:it|up|for))*\s+(?P<query>.+?)(?:\s+(?:there|on it))?$', re.I)
BROWSER_WORDS = {'safari': 'Safari', 'chrome': 'Google Chrome', 'edge': 'Microsoft Edge', 'firefox': 'Firefox'}


def find_site(text):
    """(name, url) of the longest known web app named in text, else None."""
    lowered = re.sub(r"['’]s\b", '', text.casefold())  # "Apple's support site" names apple support
    lowered = re.sub(r'\bsupport site\b', 'support', lowered)
    for name in sorted(WEB_APPS, key=len, reverse=True):
        if re.search(r'\b'+re.escape(name)+r'\b', lowered):
            return name, WEB_APPS[name]
    return None


# A written address ("apple.com", "en.wikipedia.org/wiki/Tea"); never the domain of an e-mail address.
DOMAIN = re.compile(r'(?<![@\w.])((?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|edu|gov|co|uk|de|fr|it|ro|es|nl|eu|app|ai|info)(?:/[^\s,]*)?)(?![\w@])', re.I)


def site_mentions(text):
    """(start, end, address) for every site a request names, in order: addresses written out and
    known web apps by name ("teams" inside "microsoft teams" counts once)."""
    lowered = re.sub(r"['’]s\b", lambda m: '\0'*len(m.group()), text.casefold())  # same length, so spans line up
    found = []
    for match in DOMAIN.finditer(text):
        address = match.group(1).rstrip('.')
        found.append((match.start(), match.end(), address if '://' in address else 'https://'+address))
    for name in sorted(WEB_APPS, key=len, reverse=True):
        for match in re.finditer(r'\b'+re.escape(name).replace('\\ ', r'[\s\0]+')+r'\b', lowered):
            if not any(start < match.end() and match.start() < end for start, end, _ in found):
                found.append((match.start(), match.end(), WEB_APPS[name]))
    return sorted(found)


def named_addresses(text):
    """Every site a request names, in the order named, each once."""
    result = []
    for _, _, address in site_mentions(text):
        if address not in result:
            result.append(address)
    return result


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
