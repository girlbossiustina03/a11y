from companion.ollama import OllamaProvider
"""Run with python3 -m unittest discover -s tests -v. No credentials/network/Qt required."""
import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
os.environ.setdefault('A11Y_ROUTES', '0')  # nor read routes a live run remembered
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from companion.preferences import Preferences
from companion.models import Identity, Target, ValidationError, validate_response
from companion.provider import ProviderError
from companion.service import Companion
from companion.storage import Store


class RecordingProvider:
    """Explicit test double, never shipped as an app provider or a demo mode."""
    def __init__(self):
        self.contexts = []
        self.calls = []
        self.invalid = None
        self.error = None

    def complete(self, system, messages, *, image_data=None):
        self.calls.append((system, deepcopy(messages), image_data))
        context = json.loads(messages[-2]['content'])
        self.contexts.append(context)
        if self.error:
            raise self.error
        if self.invalid is not None:
            return self.invalid
        target = {'label': 'Open Extensions in the left sidebar', 'x': .02, 'y': .15, 'width': .04, 'height': .07} if image_data else None
        return {'message': 'Here is some help.', 'target': target}


class CompanionFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.employee = Identity('company', 'engineer')
        self.admin = Identity('company', 'admin-user')
        self.provider = RecordingProvider()
        self.app = Companion(self.store, self.employee, self.provider)
        self.admin_app = Companion(self.store, self.admin, self.provider)
    def tearDown(self):
        self.temp.cleanup()


class CoreTests(CompanionFixture, unittest.TestCase):
    def test_injected_actions_rejected(self):
        self.provider.invalid = {'message': 'Hello', 'target': None, 'shell': 'rm -rf anything'}
        with self.assertRaises(ValidationError):
            validate_response(self.provider.invalid)
        result = self.app.ask('help')
        self.assertIsNone(result['desktop_action'])
        self.assertEqual(self.store.history(self.employee), [])

    def test_provider_failure_does_not_advance_or_record_preferences(self):
        history = self.store.history(self.employee)
        self.provider.error = ProviderError('Unavailable')
        with self.assertRaises(ProviderError):
            self.app.ask('shorter answers')
        self.assertEqual(history, self.store.history(self.employee))
        self.assertEqual(self.app.preferences.explicit(self.employee), {})

    def test_image_analysis_never_persists_image_or_reply(self):
        self.app.ask('What is this control?', image_data='data:image/png;base64,TEST_ONLY')
        self.assertEqual(self.store.history(self.employee), [])
        for file in Path(self.temp.name).iterdir():
            self.assertNotIn(b'TEST_ONLY', file.read_bytes())
            self.assertNotIn(b'Here is some help', file.read_bytes())

    def test_target_requires_image(self):
        self.provider.invalid = {'message': 'Click', 'target': {'label': 'Button', 'x': .1, 'y': .2, 'width': .3, 'height': .1}}
        result = self.app.ask('Help')  # no screen image: the target is dropped, never shown
        self.assertIsNone(result['target'])
        self.assertIsNone(result['desktop_action'])

    def test_no_silent_demo_fallback_without_config(self):
        from companion.provider import AIConfig
        app = Companion(self.store, self.employee, OllamaProvider(AIConfig()))
        self.assertFalse(app.state()['ai']['ready'])
        with self.assertRaises(ProviderError):
            app.ask('Hello')


class ContractTests(unittest.TestCase):
    def test_invalid_target_bounds_and_types(self):
        valid = {'label': 'Open settings', 'x': .2, 'y': .3, 'width': .1, 'height': .1}
        Target.parse(valid)
        for patch in [{'x': -1}, {'width': 0}, {'width': 1.1}, {'height': float('nan')},
                      {'x': True}, {'label': ''}, {'execute': 'anything'}]:
            with self.subTest(patch=patch):
                with self.assertRaises(ValidationError):
                    Target.parse(dict(valid, **patch))

    def test_output_schema_requires_all_fields(self):
        for value in [None, [], {'message': 'Hello'}]:
            with self.assertRaises(ValidationError):
                validate_response(value)


if __name__ == '__main__':
    unittest.main()
