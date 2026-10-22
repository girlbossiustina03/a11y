"""One confirmed desktop action followed by observation; never an open-ended executor."""
from copy import deepcopy


class ComputerUse:
    def __init__(self, desktop):
        self.desktop = desktop

    def execute_confirmed(self, proposal):
        generation = self.desktop.generation
        before = self.desktop.context()
        kind = proposal.get('type')
        if kind == 'press_control':
            self.desktop.press(proposal)
        elif kind in ('launch_app', 'quit_app', 'new_window', 'close_window'):
            self.desktop.application_action(proposal)
        elif kind == 'focus_app':
            self.desktop.activate(proposal['bundle_id'])
            self.desktop.collect_once()
        else:
            raise ValueError('That desktop action is not supported by the confirmed executor.')
        if (kind != 'launch_app' and not self.desktop.enabled) or self.desktop.generation != generation:
            raise RuntimeError('The action may have been submitted, but app awareness was paused. Check the app before trying again.')
        after = self.desktop.context()
        return {'type': kind, 'label': proposal.get('label', ''), 'status': 'submitted',
                'before': self.summary(before, proposal.get('bundle_id')), 'after': self.summary(after, proposal.get('bundle_id')),
                'verification': 'Observe the result; API acceptance does not prove task completion.',
                'application_state': self.desktop.app_state(proposal['bundle_id']) if proposal.get('bundle_id') else {},
                'task_completed': False}

    @staticmethod
    def summary(observation, bundle_id=None):
        # Full fresh controls are already in desktop_context; do not triple their
        # prompt footprint or overwhelm a local model with duplicate observations.
        windows = [item for item in observation.get('app_windows', []) if bundle_id is None or item['bundle_id'] == bundle_id]
        return {'window_count': len(windows), 'windows': [{key: deepcopy(item.get(key)) for key in ('window_id', 'title', 'bounds')} for item in windows[:8]],
                **{key: deepcopy(observation.get(key)) for key in ('app', 'window')},
                'control_labels': [item['label'] for item in observation.get('controls', [])[:15]]}
