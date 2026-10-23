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
BROWSER_WORDS = {'safari': 'Safari', 'chrome': 'Google Chrome', 'edge': 'Microsoft Edge', 'firefox': 'Firefox'}


def find_site(text):
    """(name, url) of the longest known web app named in text, else None."""
    lowered = text.casefold()
    for name in sorted(WEB_APPS, key=len, reverse=True):
        if re.search(r'\b'+re.escape(name)+r'\b', lowered):
            return name, WEB_APPS[name]
    return None


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
