"""Consent-based behavior profile. No inferred health or demographic attributes."""
from copy import deepcopy
from .storage import now

CHOICES = {'detail': ('concise', 'balanced', 'detailed'),
           'pacing': ('one_step', 'all_steps'),
           'input': ('any', 'keyboard'),
           'reduced_motion': (False, True)}
DEFAULTS = {'detail': 'balanced', 'pacing': 'one_step', 'input': 'any', 'reduced_motion': False}
# These are requests about interface behavior, not disability classifications.
SIGNALS = [('detail', 'concise', ('shorter', 'more concise', 'less detail', 'mai scurt')),
           ('detail', 'detailed', ('more detail', 'explain in detail', 'mai detaliat')),
           ('pacing', 'one_step', ('one step at a time', 'one at a time', 'pas cu pas')),
           ('input', 'keyboard', ('keyboard instructions', 'keyboard shortcuts', 'prefer the keyboard'))]


class Adaptation:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def default_profile():
        return {'version': 1, 'learning_enabled': True, 'explicit': {}, 'approved': {},
                'observed': {}, 'suggestions': {}, 'dismissed': []}

    def get(self, identity):
        return self.store.profile(identity) or self.default_profile()

    def change(self, identity, operation):
        return self.store.mutate_profile(identity, self.default_profile, operation)

    def effective(self, identity):
        p = self.get(identity)
        result = dict(DEFAULTS)
        if p['learning_enabled']:
            result.update({k: v['value'] for k, v in p['approved'].items()})
        result.update(p['explicit'])
        return result

    def set_explicit(self, identity, values, learning_enabled):
        if not isinstance(values, dict) or set(values) - set(CHOICES) or type(learning_enabled) is not bool:
            raise ValueError('Invalid preference settings.')
        for k, v in values.items():
            if not any(type(v) is type(option) and v == option for option in CHOICES[k]):
                raise ValueError(f'Invalid {k} preference.')
        def update(p):
            p['explicit'] = deepcopy(values)
            p['learning_enabled'] = learning_enabled
        return self.change(identity, update)

    def observe(self, identity, request):
        lowered = request.casefold()
        def update(p):
            if not p['learning_enabled']:
                return
            for key, value, phrases in SIGNALS:
                if not any(phrase in lowered for phrase in phrases):
                    continue
                signal = f'{key}:{value}'
                p['observed'][signal] = p['observed'].get(signal, 0) + 1
                if (p['observed'][signal] >= 2 and signal not in p['dismissed']
                        and key not in p['explicit'] and p['approved'].get(key, {}).get('value') != value):
                    p['suggestions'][signal] = {'key': key, 'value': value,
                        'reason': f'You requested this style {p["observed"][signal]} times. Apply it to future tasks?'}
        self.change(identity, update)

    def decide(self, identity, signal, approve):
        if type(approve) is not bool:
            raise ValueError('Approval must be explicit.')
        def update(p):
            if signal not in p['suggestions']:
                raise ValueError('This suggestion is no longer pending.')
            suggestion = p['suggestions'].pop(signal)
            if approve:
                p['approved'][suggestion['key']] = {'value': suggestion['value'], 'approved_at': now()}
            else:
                p['dismissed'].append(signal)
        return self.change(identity, update)

    def reset_learned(self, identity):
        def update(p):
            p.update(approved={}, observed={}, suggestions={}, dismissed=[])
        return self.change(identity, update)
