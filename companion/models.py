"""Version 1 contracts. Normalized targets are relative to ONE captured screen."""
from dataclasses import asdict, dataclass
import math


class ValidationError(ValueError):
    pass


def text(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValidationError(f'{name} must be nonempty text (at most {limit} characters).')
    return value.strip()


def keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValidationError('Unexpected or missing fields in structured response.')


def source_ids(value, allowed):
    if not isinstance(value, list) or len(value) > 12 or any(
        not isinstance(s, str) or s not in allowed for s in value
    ):
        raise ValidationError('The model cited a source outside the retrieved documents.')
    return list(dict.fromkeys(value))


@dataclass(frozen=True)
class Identity:
    company_id: str
    user_id: str
    roles: tuple[str, ...] = ('employee',)


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
        if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x+w <= 1.000001 and y+h <= 1.000001):
            raise ValidationError('Target is outside the captured screen.')
        return cls(text(value['label'], 'target label', 240), x, y, w, h)


def validate_response(value, allowed_sources, *, planning=False, has_screen=False, desktop=None, desktop_snapshot=None):
    keys(value, ('message', 'source_ids', 'workflow', 'target', 'desktop_action'), ('message', 'source_ids', 'workflow', 'target'))
    result = {'message': text(value['message'], 'message', 12000),
              'source_ids': source_ids(value['source_ids'], allowed_sources),
              'workflow': None, 'target': None}
    if value['workflow'] is not None:
        if not planning:
            raise ValidationError('Workflow creation requires an explicit planning request.')
        w = value['workflow']
        keys(w, ('title', 'steps'), ('title', 'steps'))
        if not isinstance(w['steps'], list) or not 1 <= len(w['steps']) <= 20:
            raise ValidationError('A workflow must contain 1 to 20 steps.')
        steps = []
        for step in w['steps']:
            keys(step, ('instruction', 'application', 'keyboard_hint', 'source_ids'),
                 ('instruction', 'application', 'keyboard_hint', 'source_ids'))
            parsed = {'instruction': text(step['instruction'], 'instruction', 3000),
                      'source_ids': source_ids(step['source_ids'], allowed_sources)}
            for k in ('application', 'keyboard_hint'):
                if not isinstance(step[k], str) or len(step[k]) > 600:
                    raise ValidationError(f'Invalid {k}.')
                parsed[k] = step[k].strip()
            if allowed_sources and not parsed['source_ids']:
                raise ValidationError('Each company workflow step must cite a retrieved source.')
            steps.append(parsed)
        result['workflow'] = {'title': text(w['title'], 'workflow title', 200), 'steps': steps}
    elif planning:
        # A provider can ask a clarification rather than invent a plan.
        pass
    if value['target'] is not None:
        if not has_screen:
            raise ValidationError('Screen guidance requires an explicitly supplied screenshot.')
        result['target'] = asdict(Target.parse(value['target']))
    if value.get('desktop_action') is not None:
        if desktop is None:
            raise ValidationError('Desktop actions require enabled native desktop context.')
        action = value['desktop_action']
        if action == {'type': 'request_screen'}:
            result['desktop_action'] = {'type': 'request_screen', 'label': 'Enable local screen vision'}
        elif isinstance(action, dict) and set(action) == {'type', 'destination'} and action.get('type') == 'move_companion':
            destinations = {'left_edge': 'left edge', 'right_edge': 'right edge', 'bottom_left': 'bottom left', 'bottom_right': 'bottom right'}
            destination = action['destination']
            if not isinstance(destination, str) or destination not in destinations:
                raise ValidationError('Invalid companion destination.')
            result['desktop_action'] = {'type': 'move_companion', 'destination': destination,
                                        'label': 'Move to '+destinations[destination]}
        else:
            result['desktop_action'] = desktop.authorize_action(action, snapshot=desktop_snapshot)
    return result


# Ollama constrains generation to this shape; runtime validation still checks access,
# citations, coordinate bounds and the actual native desktop observation.
_TEXT = {'type': 'string'}
_IDS = {'type': 'array', 'items': _TEXT, 'maxItems': 12}
_STEP = {'type': 'object', 'additionalProperties': False,
         'properties': {'instruction': _TEXT, 'application': _TEXT, 'keyboard_hint': _TEXT, 'source_ids': _IDS},
         'required': ['instruction', 'application', 'keyboard_hint', 'source_ids']}
RESPONSE_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['message', 'source_ids', 'workflow', 'target'],
    'properties': {
        'message': _TEXT, 'source_ids': _IDS,
        'workflow': {'anyOf': [{'type': 'null'}, {'type': 'object', 'additionalProperties': False,
            'required': ['title', 'steps'], 'properties': {'title': _TEXT,
            'steps': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': _STEP}}}]},
        'target': {'anyOf': [{'type': 'null'}, {'type': 'object', 'additionalProperties': False,
            'required': ['label', 'x', 'y', 'width', 'height'], 'properties': {'label': _TEXT,
            **{k: {'type': 'number', 'minimum': 0, 'maximum': 1} for k in ('x', 'y', 'width', 'height')}}}]},
        'desktop_action': {'anyOf': [{'type': 'null'},
            {'type': 'object', 'additionalProperties': False, 'required': ['type'],
             'properties': {'type': {'const': 'request_screen'}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'destination'],
             'properties': {'type': {'const': 'move_companion'},
                'destination': {'enum': ['left_edge', 'right_edge', 'bottom_left', 'bottom_right']}}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'bundle_id'],
             'properties': {'type': {'const': 'focus_app'}, 'bundle_id': _TEXT}},
            {'type': 'object', 'additionalProperties': False, 'required': ['type', 'control_id'],
             'properties': {'type': {'const': 'highlight_control'}, 'control_id': _TEXT}}]}
    }
}
