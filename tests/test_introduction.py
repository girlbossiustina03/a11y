import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')
os.environ.setdefault('A11Y_ROUTES', '0')
import tempfile
import unittest
from companion.preferences import Preferences
from companion.models import Identity
from companion.onboarding import Introduction
from companion.storage import Store
from companion.service import Companion
from test_core import RecordingProvider


class IntroductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.identity = Identity('company', 'employee')
        self.intro = Introduction(self.store, self.identity)

    def tearDown(self):
        self.temp.cleanup()

    def test_drafts_do_not_apply_settings_or_disclose_details(self):
        self.intro.draft({'display_name': 'Sam', 'detail': 'concise'})
        restarted = Introduction(Store(self.temp.name), self.identity)
        self.assertEqual(restarted.get()['answers']['display_name'], 'Sam')
        self.assertEqual(restarted.user_details(), {})
        self.assertEqual(Preferences(self.store).effective(self.identity)['detail'], 'balanced')

    def test_reviewed_details_and_explicit_settings_survive_restart(self):
        self.intro.save({'display_name': 'Sam', 'work_role': 'Engineer', 'detail': 'concise',
                         'input': 'keyboard', 'reduced_motion': True})
        app = Companion(Store(self.temp.name), self.identity, RecordingProvider())
        app.ask('Describe me')
        context = app.provider.contexts[-1]
        self.assertEqual(context['user_profile'], {'display_name': 'Sam', 'work_role': 'Engineer'})
        self.assertEqual(context['preferences']['detail'], 'concise')
        self.assertEqual(context['preferences']['input'], 'keyboard')
        self.assertFalse(context['screen_supplied'])
        self.assertTrue(app.preferences.effective(self.identity)['reduced_motion'])
        self.assertIn('Keep it short', self.intro.summary())
        self.assertEqual(Introduction(self.store, Identity('company', 'other')).user_details(), {})
        self.intro.draft({'display_name': 'Unreviewed'})
        self.assertEqual(self.intro.user_details()['display_name'], 'Sam')

    def test_optional_details_and_choice_validation(self):
        self.intro.save({})
        self.assertEqual(self.intro.user_details(), {})
        for answers in ({'detail': 'guess'}, {'reduced_motion': 1}, {'display_name': 'x'*81}):
            with self.assertRaises(ValueError):
                self.intro.save(answers)
        self.assertEqual(self.intro.user_details(), {})

    def test_preexisting_completed_profile_needs_no_migration(self):
        self.store.save_introduction(self.identity, {'version': 1, 'status': 'completed', 'step': 7,
            'answers': {'display_name': 'Sam', 'work_role': 'Engineer'}, 'saved_at': 'earlier'})
        self.assertEqual(self.intro.user_details(), {'display_name': 'Sam', 'work_role': 'Engineer'})
