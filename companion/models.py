"""Version 1 contracts. Normalized targets are relative to ONE captured screen."""
from dataclasses import asdict, dataclass
import math
from .input_actions import KEYS


class ValidationError(ValueError):
    pass


def text(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValidationError(f'{name} must be nonempty text (at most {limit} characters).')
    return value.strip()


def keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValidationError('Unexpected or missing fields in structured response.')


@dataclass(frozen=True)
class Identity:
    # Keep the original storage key pair so existing settings and history remain accessible.
    company_id: str
    user_id: str


@dataclass(frozen=True)
class Target:
    label: str
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def parse(cls, value):
        keys(value, ('label', 'x', 'y', 'width', 'height'), ('label', 'x', 'y', 'width', 'height'))
        nums = [value[k] for k in ('x', 'y', 'width', 'height')]
        if any(isinstance(n, bool) or not isinstance(n, (float, int)) or not math.isfinite(n) for n in nums):
            raise ValidationError('Target coordinates must be finite numbers.')
        x, y, w, h = nums
        if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 ):
            raise ValidationError('Target is outside the captured screen.')
        # A partially visible object may extend beyond the frame; clip its visible box.
        return cls(text(value['label'], 'target label', 240), x, y, min(w, 1-x), min(h, 1-y))


def validate_response(value, *, has_screen=False, desktop=None, desktop_snapshot=None):
    keys(value, ('request_kind', 'message', 'target', 'desktop_action'), ('message', 'target'))
    result = {'message': text(value['message'], 'message', 12000), 'target': None}
    request_kind = value.get('request_kind')
    if request_kind is not None and request_kind not in ('move', 'move_object', 'move_geometry', 'highlight', 'answer', 'act', 'press_control', 'launch_app', 'new_window', 'close_window', 'quit_app', 'focus_app', 'click_point', 'browser_search', 'browser_open', 'computer_task', 'inspect_media', 'play_media', 'type_text', 'press_key', 'scroll'):
        raise ValidationError('Invalid request kind.')
    if request_kind in ('move', 'move_object', 'move_geometry') and value['target'] is not None and value.get('desktop_action') is None:
        if not has_screen or desktop is None:
            raise ValidationError('Moving to an observed object requires fresh screen pixels.')
        box = Target.parse(value['target'])
        # The model identifies intent and object. Runtime converts a located box to its center.
        value = dict(value, target=None, desktop_action={
            'type': 'move_to_point', 'basis': 'image', 'label': box.label,
            'x': box.x+box.width/2, 'y': box.y+box.height/2})
    if value['target'] is not None:
        if not has_screen:
            raise ValidationError('Screen guidance requires an explicitly supplied screenshot.')
        result['target'] = asdict(Target.parse(value['target']))
    if value.get('desktop_action') is not None:
        if desktop is None:
            raise ValidationError('Desktop actions require enabled native desktop context.')
        action = value['desktop_action']
        if isinstance(action, dict) and action.get('type') == 'start_task':
            keys(action, ('type', 'goal', 'goal_mode', 'opening', 'looking_at'), ('type', 'goal'))
            if action.get('goal_mode', 'inspect') not in ('inspect', 'draft', 'change'):
                raise ValidationError('Invalid task scope.')
            result['desktop_action'] = dict(action, goal=text(action['goal'], 'task goal', 2000), label='Start computer task')
            if 'looking_at' in action:
                result['desktop_action']['looking_at'] = text(action['looking_at'], 'task context', 300)
        elif isinstance(action, dict) and action.get('type') == 'app_write':
            # A change to Calendar/Reminders/Notes/Shortcuts, built in code from the user's
            # request (mac_apps.prepare) and run only after the user confirms it.
            allowed = {'add_event': ('title', 'start', 'end'), 'add_reminder': ('title', 'due'),
                       'complete_reminder': ('id', 'title'), 'delete_reminder': ('id', 'title'), 'create_note': ('title', 'body'), 'run_shortcut': ('name',)}
            fields = allowed.get(action.get('kind'))
            if fields is None or set(action)-{'remaining_request'} != {'type', 'kind', 'label', *fields}:
                raise ValidationError('Unsupported app change.')
            if 'remaining_request' in action and (not isinstance(action['remaining_request'], str) or len(action['remaining_request']) > 500):
                raise ValidationError('Invalid follow-up for that app change.')  # code's "then …", run after the change
            for key in fields:
                value = action[key]
                if key in ('start', 'end', 'due'):
                    if type(value) is not int or value < 0:
                        raise ValidationError('Invalid time for that app change.')
                elif not isinstance(value, str) or len(value) > (5000 if key == 'body' else 300) or (key != 'body' and not value.strip()):
                    raise ValidationError('Invalid details for that app change.')
            result['desktop_action'] = dict(action, label=text(action['label'], 'action label', 240))
        elif isinstance(action, dict) and action.get('type') == 'wait':
            keys(action, ('type', 'milliseconds'), ('type', 'milliseconds'))
            if type(action['milliseconds']) is not int or action['milliseconds'] not in (250, 500, 1000):
                raise ValidationError('Wait must be 250, 500 or 1000 milliseconds.')
            result['desktop_action'] = dict(action, label='Wait for the interface to update')
        elif action == {'type': 'capture_once'}:
            result['desktop_action'] = {'type': 'capture_once', 'label': 'Preview one screenshot'}
        elif isinstance(action, dict) and action.get('type') == 'click_point':
            keys(action, ('type', 'x', 'y', 'label', 'button', 'click_count'), ('type', 'x', 'y', 'label'))
            if action.get('button', 'left') not in ('left', 'right') or type(action.get('click_count', 1)) is not int or action.get('click_count', 1) not in (1, 2) or action.get('button') == 'right' and action.get('click_count', 1) != 1:
                raise ValidationError('Use a left single/double click or a right single click.')
            if not has_screen:
                raise ValidationError('Clicking a visual target requires a fresh screen image.')
            for coordinate in ('x', 'y'):
                number = action[coordinate]
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number < 1:
                    raise ValidationError('Click coordinates must be finite image fractions from 0 up to 1.')
            result['desktop_action'] = dict(action, label=text(action['label'], 'click label', 240),
                                            confirmation_label=('Right-click' if action.get('button') == 'right' else 'Double-click' if action.get('click_count', 1) == 2 else 'Click')+' “'+action['label']+'”')
        elif isinstance(action, dict) and action.get('type') == 'drag':
            keys(action, ('type', 'x', 'y', 'to_x', 'to_y', 'label'), ('type', 'x', 'y', 'to_x', 'to_y', 'label'))
            if not has_screen:
                raise ValidationError('Dragging requires a fresh screen image.')
            for coordinate in ('x', 'y', 'to_x', 'to_y'):
                number = action[coordinate]
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number < 1:
                    raise ValidationError('Drag coordinates must be finite image fractions from 0 up to 1.')
            result['desktop_action'] = dict(action, label=text(action['label'], 'drag label', 240), confirmation_label=action['label'])
        elif isinstance(action, dict) and action.get('type') == 'browse_url':
            from urllib.parse import urlsplit
            keys(action, ('type', 'bundle_id', 'url', 'label', 'browser_mode', 'window_hint'), ('type', 'bundle_id', 'url', 'label'))
            if action.get('browser_mode', 'default') not in ('default', 'window', 'tab', 'current') or len(str(action.get('window_hint', ''))) > 80:
                raise ValidationError('Invalid browser window mode.')
            url = urlsplit(action['url']) if isinstance(action['url'], str) else None
            if not url or url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or len(action['url']) > 4000:
                raise ValidationError('Browser navigation needs a bounded HTTP(S) URL without credentials.')
            result['desktop_action'] = desktop.authorize_browser(action)
        elif action in ({'type': 'request_screen'}, {'type': 'request_app_access'}):
            result['desktop_action'] = dict(action, label='Enable local screen vision' if action['type'] == 'request_screen' else 'Enable app awareness')
        elif isinstance(action, dict) and set(action) == {'type', 'destination'} and action.get('type') == 'move_companion':
            destinations = {'left_edge': 'left edge', 'right_edge': 'right edge', 'bottom_left': 'bottom left', 'bottom_right': 'bottom right', 'top_left': 'upper left', 'top_right': 'upper right', 'center': 'center'}
            destination = action['destination']
            if not isinstance(destination, str) or destination not in destinations:
                raise ValidationError('Invalid companion destination.')
            if result['target'] is not None:
                raise ValidationError('Companion movement cannot include a screen target.')
            result['desktop_action'] = {'type': 'move_companion', 'destination': destination,
                                        'label': 'Move to '+destinations[destination]}
        elif isinstance(action, dict) and action.get('type') == 'move_to_point':
            keys(action, ('type', 'x', 'y', 'basis', 'label'), ('type', 'x', 'y', 'basis', 'label'))
            for coordinate in ('x', 'y'):
                number = action[coordinate]
                if isinstance(number, bool) or not isinstance(number, (float, int)) or not math.isfinite(number) or not 0 <= number <= 1:
                    raise ValidationError('Movement coordinates must be finite fractions between 0 and 1.')
            if action['basis'] not in ('screen', 'image'):
                raise ValidationError('Invalid movement coordinate basis.')
            if action['basis'] == 'image' and not has_screen:
                raise ValidationError('Moving to a visual object requires a fresh screen image.')
            if result['target'] is not None:
                raise ValidationError('Companion movement cannot include a screen target.')
            result['desktop_action'] = dict(action, label=text(action['label'], 'movement label', 240))
        else:
            try:
                result['desktop_action'] = desktop.authorize_action(action, snapshot=desktop_snapshot)
            except ValueError as error:
                raise ValidationError(str(error)) from error
    action = result.get('desktop_action') or {}
    if request_kind == 'move_object' and action.get('type') != 'request_screen':
        if not has_screen or action.get('type') != 'move_to_point' or action.get('basis') != 'image':
            raise ValidationError('Moving to a named object needs current image coordinates; a corner is not a search action. Request screen vision instead.')
    if request_kind in ('launch_app', 'new_window', 'close_window', 'quit_app', 'focus_app', 'press_control') and action.get('type') not in (request_kind, 'request_app_access'):
        raise ValidationError('The requested operation is '+request_kind+'; '+str(action.get('type'))+' is not an equivalent operation.')
    if request_kind in ('move', 'move_object', 'move_geometry') and action.get('type') not in ('move_companion', 'move_to_point', 'request_screen'):
        raise ValidationError('Movement needs a movement action, a screen request, or a clarification classified as answer.')
    return result


# Ollama constrains generation to this shape; runtime validation still checks access,
# coordinate bounds and the actual native desktop observation.
_TEXT = {'type': 'string'}
RESPONSE_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['request_kind', 'desktop_action', 'message', 'target'],
    'properties': {
        'request_kind': {'enum': ['move_object', 'move_geometry', 'highlight', 'answer', 'press_control', 'launch_app', 'new_window', 'close_window', 'quit_app', 'focus_app', 'click_point', 'browser_search', 'browser_open', 'computer_task', 'inspect_media', 'play_media', 'type_text', 'press_key', 'scroll']},
        'message': _TEXT,
        'target': {'anyOf': [{'type': 'null'}, {'type': 'object', 'additionalProperties': False,
            'required': ['label', 'x', 'y', 'width', 'height'], 'properties': {'label': _TEXT,
            **{k: {'type': 'number', 'minimum': 0, 'maximum': 1} for k in ('x', 'y', 'width', 'height')}}}]},
        'desktop_action': {'anyOf': [{'type': 'null'},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'milliseconds'],
             'properties': {'type': {'const': 'wait'}, 'milliseconds': {'enum': [250, 500, 1000]}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'goal'],
             'properties': {'type': {'const': 'start_task'}, 'goal': _TEXT}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type'],
             'properties': {'type': {'const': 'capture_once'}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'bundle_id', 'url', 'label'],
             'properties': {'type': {'const': 'browse_url'}, 'bundle_id': _TEXT, 'url': _TEXT, 'label': _TEXT, 'browser_mode': {'enum': ['default', 'window', 'tab']}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type'],
             'properties': {'type': {'enum': ['request_screen', 'request_app_access']}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'destination'],
             'properties': {'type': {'const': 'move_companion'},
                'destination': {'enum': ['left_edge', 'right_edge', 'bottom_left', 'bottom_right', 'top_left', 'top_right', 'center']}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'x', 'y', 'basis', 'label'],
             'properties': {'type': {'const': 'move_to_point'}, 'basis': {'enum': ['screen', 'image']},
                'label': _TEXT, 'x': {'type': 'number', 'minimum': 0, 'maximum': 1},
                'y': {'type': 'number', 'minimum': 0, 'maximum': 1}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'bundle_id'],
             'properties': {'type': {'enum': ['focus_app', 'launch_app', 'quit_app', 'new_window']}, 'bundle_id': _TEXT}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'x', 'y', 'label'],
             'properties': {'type': {'const': 'click_point'}, 'label': _TEXT, 'button': {'enum': ['left', 'right']}, 'click_count': {'enum': [1, 2]},
                'x': {'type': 'number', 'minimum': 0, 'exclusiveMaximum': 1},
                'y': {'type': 'number', 'minimum': 0, 'exclusiveMaximum': 1}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'text'],
             'properties': {'type': {'const': 'type_text'}, 'text': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'key'],
             'properties': {'type': {'const': 'press_key'}, 'key': {'enum': list(KEYS)}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'direction'],
             'properties': {'type': {'const': 'scroll'}, 'direction': {'enum': ['up', 'down']}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'query', 'artist'],
             'properties': {'type': {'const': 'play_media'}, 'query': _TEXT, 'artist': _TEXT}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'window_id'],
             'properties': {'type': {'const': 'close_window'}, 'window_id': _TEXT}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'path'],
             'properties': {'type': {'const': 'choose_menu'}, 'path': _TEXT}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'control_id'],
             'properties': {'type': {'enum': ['highlight_control', 'press_control']}, 'control_id': _TEXT}}]}
    }
}

# Decode the intent and action before prose, so an answer cannot anchor an obsolete task.
RESPONSE_SCHEMA['properties'] = {
    key: RESPONSE_SCHEMA['properties'][key]
    for key in ('request_kind', 'desktop_action', 'target', 'message')
}
