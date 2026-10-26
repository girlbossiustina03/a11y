"""Explicit interaction settings. Existing profile records stay intact."""
CHOICES = {'detail': ('concise', 'balanced', 'detailed'),
           'pacing': ('one_step', 'all_steps'),
           'input': ('any', 'keyboard'),
           'reduced_motion': (False, True)}
DEFAULTS = {'detail': 'balanced', 'pacing': 'one_step', 'input': 'any', 'reduced_motion': False}


class Preferences:
    def __init__(self, store):
        self.store = store

    def explicit(self, identity):
        values = (self.store.profile(identity) or {}).get('explicit', {})
        return {k: v for k, v in values.items() if k in CHOICES and
                any(type(v) is type(option) and v == option for option in CHOICES[k])}

    def effective(self, identity):
        return dict(DEFAULTS, **self.explicit(identity))

    def set_explicit(self, identity, values):
        if not isinstance(values, dict) or set(values) - set(CHOICES):
            raise ValueError('Invalid preference settings.')
        for key, value in values.items():
            if not any(type(value) is type(option) and value == option for option in CHOICES[key]):
                raise ValueError(f'Invalid {key} preference.')
        def update(profile):
            profile['explicit'] = dict(values)
        self.store.mutate_profile(identity, dict, update)
