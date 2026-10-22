"""Bounded input primitives. Execution is bound to the observed window/focused field."""
INPUT_TYPES = ('type_text', 'press_key', 'scroll')
KEYS = ('enter', 'tab', 'escape', 'space', 'backspace', 'left', 'right', 'up', 'down',
        'cmd_l', 'cmd_f', 'cmd_t', 'cmd_n', 'cmd_w', 'cmd_a', 'cmd_r')
BLOCKED = {'com.apple.Terminal', 'com.googlecode.iterm2', 'dev.warp.Warp-Stable',
           'com.apple.Passwords', 'com.apple.keychainaccess', 'com.1password.1password', 'com.bitwarden.desktop'}


def authorize_input(action, context):
    kind = action.get('type')
    field = {'type_text': 'text', 'press_key': 'key', 'scroll': 'direction'}.get(kind)
    if not field or set(action) != {'type', field}:
        raise ValueError('Unsupported input fields.')
    if not context.get('enabled') or context.get('status') not in ('available', 'companion_focused') or context.get('age_seconds', 999) > 10:
        raise ValueError('Input needs fresh app awareness. Focus the destination app and ask again.')
    app, window = context.get('app', {}), context.get('window', {})
    if not app.get('bundle_id') or not window.get('bounds') or app['bundle_id'] in BLOCKED:
        raise ValueError('Input is unavailable for that application. Shell and protected-app input is disabled.')
    if context.get('focused_role') == 'secure_input':
        raise ValueError('Input is blocked while a password field is focused.')
    value = action[field]
    if kind == 'type_text':
        if not isinstance(value, str) or not value.strip() or len(value) > 2000 or any(ord(c) < 32 for c in value):
            raise ValueError('Type one line of text, at most 2000 characters. Enter is a separate action.')
        if context.get('focused_role') not in ('AXTextField', 'AXTextArea', 'AXComboBox') or not context.get('focused_bounds'):
            raise ValueError('Focus a non-password text field before requesting text entry.')
        label = 'Type “'+value[:100]+('…' if len(value) > 100 else '')+'” in '+app.get('name', 'the app')
    elif kind == 'press_key':
        if value not in KEYS:
            raise ValueError('Unsupported keyboard command. Use a named navigation key or supported Command shortcut.')
        label = 'Press '+value.replace('cmd_', '⌘+').title()+' in '+app.get('name', 'the app')
    else:
        if value not in ('up', 'down'):
            raise ValueError('Scroll direction must be up or down.')
        label = 'Scroll '+value+' in '+app.get('name', 'the app')
    return dict(action, label=label, confirmation_label=label, bundle_id=app['bundle_id'],
                window_title=window.get('title', ''), bounds=window['bounds'],
                focused_role=context.get('focused_role', ''), focused_bounds=context.get('focused_bounds'))
