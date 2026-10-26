"""Reviewed setup profile and explicit settings."""
from .preferences import Preferences, CHOICES
from .models import text
from .storage import now

FIELDS = (
    ('display_name', 'First things first: what should I call you?', None),
    ('work_role', 'What kind of work do you do? This helps me get to know you.', None),
    ('detail', 'How do you like things explained?',
     (('Keep it short', 'concise'), ('A little context', 'balanced'), ('Walk me through the details', 'detailed'))),
    ('pacing', 'When we work through a task together, what feels better?',
     (('One step at a time', 'one_step'), ('Show the whole plan', 'all_steps'))),
    ('input', 'Would you like me to prioritize keyboard instructions?',
     (('Yes, keyboard first', 'keyboard'), ('No preference', 'any'))),
    ('reduced_motion', 'How much should I move around?',
     (('Keep things still', True), ('Gentle animation is okay', False))),
)


class Introduction:
    def __init__(self, store, identity):
        self.store, self.identity = store, identity

    def get(self):
        return self.store.introduction(self.identity) or {
            'version': 1, 'status': 'new', 'answers': {}, 'saved_at': None}

    def user_details(self):
        """Only reviewed personal details belong in model context, never setup drafts."""
        data = self.get()
        answers = data['answers'] if data['status'] == 'completed' else data.get('approved_details', {})
        return {key: answers[key] for key in ('display_name', 'work_role')
                if isinstance(answers.get(key), str) and answers[key].strip()}

    def draft(self, answers):
        data = self.get()
        data['approved_details'] = self.user_details()
        data.update(status='in_progress', answers=dict(answers))
        self.store.save_introduction(self.identity, data)

    def save(self, answers):
        values = {}
        for key, _, options in FIELDS:
            if key not in answers:
                continue
            value = answers[key]
            if options is None:
                if not value:
                    continue
                value = text(value, key, 80 if key == 'display_name' else 160)
            elif not any(type(value) is type(option) and value == option for _, option in options):
                raise ValueError('Please choose one of the offered answers.')
            values[key] = value
        preferences = Preferences(self.store)
        explicit = preferences.explicit(self.identity)
        explicit.update({k: v for k, v in values.items() if k in CHOICES})
        preferences.set_explicit(self.identity, explicit)
        data = self.get()
        data.update(status='completed', answers=values, saved_at=now())
        self.store.save_introduction(self.identity, data)
        return data

    def summary(self):
        answers = self.get()['answers']
        lines = []
        for key, _, options in FIELDS:
            if key not in answers:
                continue
            value = answers[key]
            friendly = next((label for label, option in options if type(value) is type(option) and value == option), str(value)) if options else value
            lines.append(f'{key.replace("_", " ").capitalize()}: {friendly}')
        return '\n'.join(lines) or 'Use the current defaults. You can change them at any time.'
