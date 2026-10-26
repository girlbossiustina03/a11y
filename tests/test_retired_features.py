"""Retired surfaces stay unavailable without deleting existing local records."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from companion.models import Identity, RESPONSE_SCHEMA, ValidationError, validate_response
from companion.preferences import Preferences
from companion.provider import ProviderError
from companion.ollama import OllamaProvider, provider_from_env
from companion.request_plan import INTENT_SCHEMA, validate_plan
from companion.service import Companion
from companion.storage import Store


class RetirementTests(unittest.TestCase):
    def test_local_default_ignores_remote_credentials_and_retired_saved_selection(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'unused', 'A11Y_AI_KEY': 'unused',
                'A11Y_AI_BASE_URL': 'https://unused.invalid', 'A11Y_AI_PROVIDER': ''}), \
                patch('companion.paths.saved_ai_settings', return_value={'provider': 'compatible'}):
            self.assertIsInstance(provider_from_env(), OllamaProvider)
        with patch.dict('os.environ', {'A11Y_AI_PROVIDER': 'compatible'}), self.assertRaises(ProviderError):
            provider_from_env()

    def test_retired_operations_and_response_fields_are_rejected(self):
        self.assertNotIn('plan', json.dumps(INTENT_SCHEMA))
        self.assertNotIn('workflow', RESPONSE_SCHEMA['properties'])
        self.assertNotIn('source_ids', RESPONSE_SCHEMA['properties'])
        with self.assertRaises(ValidationError):
            validate_plan({'operation': 'plan', 'app_name': '', 'target': ''})
        for extra in ({'workflow': None}, {'source_ids': []}, {'request_kind': 'plan'}):
            with self.assertRaises(ValidationError):
                validate_response(dict(message='Hello', target=None, **extra))
        with self.assertRaises(ValueError):
            Companion(None, None, object()).ask('Hello', mode='plan')

    def test_legacy_files_and_records_stay_intact_and_private(self):
        with tempfile.TemporaryDirectory() as folder:
            identity = Identity('company', 'employee')
            store = Store(folder)
            company = Path(folder)/'company.sqlite3'
            company.write_bytes(b'legacy document database left untouched')
            profile = {'explicit': {'input': 'keyboard'}, 'approved': {'reduced_motion': {'value': True}},
                       'observed': {'detail:concise': 9}, 'suggestions': {'old': 'value'}}
            store.save_profile(identity, profile)
            with store.employee() as db:
                db.execute('CREATE TABLE workflows (id TEXT, owner TEXT, data TEXT, updated_at TEXT)')
                db.execute('INSERT INTO workflows VALUES (?,?,?,?)', ('old', store.owner(identity), 'legacy task', 'earlier'))
                db.execute('INSERT INTO messages(owner,role,content,created_at,source_documents) VALUES (?,?,?,?,?)',
                           (store.owner(identity), 'assistant', 'Private old answer', 'earlier', '["restricted"]'))
            restarted = Store(folder)
            self.assertEqual(company.read_bytes(), b'legacy document database left untouched')
            self.assertEqual(restarted.history(identity), [])
            prefs = Preferences(restarted)
            self.assertFalse(prefs.effective(identity)['reduced_motion'])
            prefs.set_explicit(identity, {'input': 'keyboard', 'reduced_motion': True})
            saved = restarted.profile(identity)
            self.assertEqual(saved['approved'], profile['approved'])
            self.assertEqual(saved['observed'], profile['observed'])
            self.assertTrue(Preferences(Store(folder)).effective(identity)['reduced_motion'])
            self.assertEqual(prefs.effective(Identity('company', 'other'))['input'], 'any')
            with restarted.employee() as db:
                self.assertEqual(db.execute('SELECT data FROM workflows').fetchone()['data'], 'legacy task')
                self.assertEqual(db.execute('SELECT content FROM messages').fetchone()['content'], 'Private old answer')
            restarted.add_exchange(identity, 'Hello', 'Hi')
            self.assertEqual(len(restarted.history(identity)), 2)

    def test_explicit_preferences_validate_types(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs = Preferences(Store(folder))
            identity = Identity('company', 'employee')
            for values in ({'reduced_motion': 1}, {'detail': 'unknown'}, {'diagnosis': 'guess'}):
                with self.assertRaises(ValueError):
                    prefs.set_explicit(identity, values)

    def test_repeated_requests_never_change_settings(self):
        from test_core import RecordingProvider
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            identity = Identity('company', 'employee')
            app = Companion(store, identity, RecordingProvider())
            app.preferences.set_explicit(identity, {'input': 'keyboard', 'detail': 'detailed'})
            before = store.profile(identity)
            app.ask('Please give shorter answers')
            app.ask('Shorter answers please')
            self.assertEqual(store.profile(identity), before)
            self.assertEqual(app.preferences.effective(identity)['detail'], 'detailed')
