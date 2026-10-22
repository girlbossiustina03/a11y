"""Local, resumable introduction. This is setup UI, not a simulated AI response."""
from .adaptation import Adaptation, CHOICES
from .models import text
from .storage import now

QUESTIONS = (
    ('display_name', 'First things first: what should I call you?', None),
    ('work_role', 'What kind of work do you do? This helps me get to know you; it does not change document access.', None),
    ('detail', 'How do you like things explained?',
     (('Keep it short', 'concise'), ('A little context', 'balanced'), ('Walk me through the details', 'detailed'))),
    ('pacing', 'When we work through a task together, what feels better?',
     (('One step at a time', 'one_step'), ('Show the whole plan', 'all_steps'))),
    ('input', 'Would you like me to prioritize keyboard instructions?',
     (('Yes, keyboard first', 'keyboard'), ('No preference', 'any'))),
    ('reduced_motion', 'How much should I move around?',
     (('Keep things still', True), ('Gentle animation is okay', False))),
    ('learning_enabled', 'May I notice repeated requests about how you like to work and suggest changes? '
     'I will always ask before applying a learned preference.',
     (('Yes, offer suggestions', True), ('No, use only my settings', False))),
)


class Introduction:
    def __init__(self, store, identity):
        self.store, self.identity = store, identity

    def get(self):
        return self.store.introduction(self.identity) or {
            'version': 1, 'status': 'new', 'step': 0, 'answers': {}, 'saved_at': None}

    def user_details(self):
        """Only reviewed personal details belong in model context, never setup drafts."""
        data = self.get()
        answers = data['answers'] if data['status'] == 'completed' else data.get('approved_details', {})
        return {key: answers[key] for key in ('display_name', 'work_role')
                if isinstance(answers.get(key), str) and answers[key].strip()}

    def start(self, *, restart=False):
        data = self.get()
        if restart or data['status'] == 'new':
            data['approved_details'] = self.user_details()
            profile = Adaptation(self.store).get(self.identity)
            answers = dict(profile['explicit'], learning_enabled=profile['learning_enabled'])
            answers.update({k: v for k, v in data['answers'].items() if k in ('display_name', 'work_role')})
            data.update(status='in_progress', step=0, answers=answers)
        self.store.save_introduction(self.identity, data)
        return data

    def answer(self, value=None, *, skip=False):
        data = self.get()
        if data['status'] != 'in_progress' or data['step'] >= len(QUESTIONS):
            raise ValueError('No introduction question is pending.')
        key, _, options = QUESTIONS[data['step']]
        if not skip:
            if options is None:
                value = text(value, key, 80 if key == 'display_name' else 160)
            elif not any(type(value) is type(option) and value == option for _, option in options):
                raise ValueError('Please choose one of the offered answers.')
            data['answers'][key] = value
        data['step'] += 1
        self.store.save_introduction(self.identity, data)
        return data

    def back(self):
        data = self.get()
        if data['status'] != 'in_progress':
            raise ValueError('Start the introduction first.')
        data['step'] = max(0, data['step']-1)
        self.store.save_introduction(self.identity, data)
        return data

    def save(self):
        data = self.get()
        if data['status'] != 'in_progress' or data['step'] != len(QUESTIONS):
            raise ValueError('Review the introduction before saving.')
        answers = data['answers']
        adaptation = Adaptation(self.store)
        profile = adaptation.get(self.identity)
        explicit = dict(profile['explicit'])
        explicit.update({k: v for k, v in answers.items() if k in CHOICES})
        adaptation.set_explicit(self.identity, explicit, answers.get('learning_enabled', profile['learning_enabled']))
        data.update(status='completed', saved_at=now())
        self.store.save_introduction(self.identity, data)
        return data

    def summary(self):
        answers = self.get()['answers']
        lines = []
        for key, _, options in QUESTIONS:
            if key not in answers:
                continue
            value = answers[key]
            friendly = next((label for label, option in options if type(value) is type(option) and value == option), str(value)) if options else value
            lines.append(f'{key.replace("_", " ").capitalize()}: {friendly}')
        return '\n'.join(lines) or 'Use the current defaults. You can change them at any time.'
