"""Resolve platform names to observed installed apps; never manufacture a bundle ID."""
def normalized(value):
    return ''.join(character for character in value.casefold() if character.isalnum())


# Platform vocabulary, independent of LLM command interpretation.
ALIASES = {
    'settings': ('System Settings', 'System Preferences'),
    'macsettings': ('System Settings', 'System Preferences'),
    'macossettings': ('System Settings', 'System Preferences'),
    'preferences': ('System Settings', 'System Preferences'),
    'macssettings': ('System Settings', 'System Preferences'),
    'systempreferences': ('System Settings', 'System Preferences'),
    'systemsettings': ('System Settings', 'System Preferences'),
    'notepad': ('TextEdit',),
    'texteditor': ('TextEdit',),
    'macnotes': ('Notes',),
    'macosnotes': ('Notes',),
    'browser': ('Safari',),
}


def resolve_app(name, catalog):
    wanted = normalized(name)
    exact = [app for app in catalog if normalized(app['name']) == wanted]
    if exact:
        return exact
    aliases = {normalized(alias) for alias in ALIASES.get(wanted, ())}
    known_ids = {'systemsettings': 'com.apple.systempreferences', 'systempreferences': 'com.apple.systempreferences', 'textedit': 'com.apple.TextEdit', 'notes': 'com.apple.Notes', 'safari': 'com.apple.Safari'}
    bundle_ids = {known_ids[alias] for alias in aliases if alias in known_ids}
    return [app for app in catalog if normalized(app['name']) in aliases or app['bundle_id'] in bundle_ids]
