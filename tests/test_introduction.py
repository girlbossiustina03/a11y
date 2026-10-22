import tempfile
import unittest
from companion.adaptation import Adaptation
from companion.models import Identity
from companion.onboarding import Introduction, QUESTIONS
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

    def test_resume_draft_without_applying_preferences(self):
        self.intro.start()
        self.intro.answer('Sam')
        self.intro.answer('Engineer')
        self.intro.answer('detailed')
        restarted = Introduction(Store(self.temp.name), self.identity)
        self.assertEqual(restarted.get()['step'], 3)
        self.assertEqual(restarted.get()['answers']['display_name'], 'Sam')
        self.assertEqual(Adaptation(self.store).effective(self.identity)['detail'], 'balanced')

    def test_review_save_persists_effective_settings_and_completion(self):
        self.intro.start()
        for value in ['Sam', 'Engineer', 'concise', 'one_step', 'keyboard', True, False]:
            self.intro.answer(value)
        self.assertIn('Sam', self.intro.summary())
        self.assertIn('Keep it short', self.intro.summary())
        saved = self.intro.save()
        self.assertEqual(saved['status'], 'completed')
        a = Adaptation(self.store)
        self.assertEqual(a.effective(self.identity)['detail'], 'concise')
        self.assertTrue(a.effective(self.identity)['reduced_motion'])
        self.assertFalse(a.get(self.identity)['learning_enabled'])
        self.assertNotIn('display_name', a.get(self.identity)['explicit'])
        self.assertEqual(self.identity.roles, ('employee',))

    def test_skips_and_back_do_not_require_personal_details(self):
        self.intro.start()
        self.intro.answer(skip=True)
        self.intro.answer(skip=True)
        self.intro.back()
        self.assertEqual(self.intro.get()['step'], 1)
        for _ in range(1, len(QUESTIONS)):
            self.intro.answer(skip=True)
        self.intro.save()
        self.assertNotIn('display_name', self.intro.get()['answers'])

    def test_no_save_before_review_and_validate_choice_types(self):
        self.intro.start()
        with self.assertRaises(ValueError):
            self.intro.save()
        self.intro.answer(skip=True)
        self.intro.answer(skip=True)
        with self.assertRaises(ValueError):
            self.intro.answer('guessed diagnosis')
        self.assertEqual(self.intro.get()['step'], 2)

    def test_profiles_separate_and_restart_keeps_saved_settings_until_review(self):
        self.intro.start()
        for _ in QUESTIONS:
            self.intro.answer(skip=True)
        self.intro.save()
        self.intro.start(restart=True)
        self.assertEqual(self.intro.get()['step'], 0)
        self.assertEqual(Introduction(self.store, Identity('company', 'someone-else')).get()['status'], 'new')


    def test_saved_details_reach_model_after_restart_without_screen_access(self):
        self.intro.start()
        for value in ['Sam', 'Engineer', 'concise', 'one_step', 'keyboard', True, False]:
            self.intro.answer(value)
        self.intro.save()
        provider = RecordingProvider()
        app = Companion(Store(self.temp.name), self.identity, provider)
        app.ask('Describe me')
        context = provider.contexts[-1]
        self.assertEqual(context['user_profile'], {'display_name': 'Sam', 'work_role': 'Engineer'})
        self.assertEqual(context['preferences']['detail'], 'concise')
        self.assertEqual(context['preferences']['input'], 'keyboard')
        self.assertFalse(context['screen_supplied'])
        self.assertIn('refer to the USER', provider.calls[-1][0])
        other = Companion(Store(self.temp.name), Identity('company', 'other'), provider)
        other.ask('Describe me')
        self.assertEqual(provider.contexts[-1]['user_profile'], {})

    def test_draft_details_are_not_sent_and_reediting_keeps_approved_details(self):
        self.intro.start()
        self.intro.answer('Sam')
        self.assertEqual(self.intro.user_details(), {})
        for value in ['Engineer', 'concise', 'one_step', 'keyboard', True, False]:
            self.intro.answer(value)
        self.intro.save()
        self.intro.start(restart=True)
        self.intro.answer('Unreviewed name')
        self.assertEqual(self.intro.user_details()['display_name'], 'Sam')

    def test_preexisting_completed_introduction_needs_no_migration(self):
        self.store.save_introduction(self.identity, {
            'version': 1, 'status': 'completed', 'step': len(QUESTIONS),
            'answers': {'display_name': 'Sam', 'work_role': 'Engineer'}, 'saved_at': 'earlier'})
        self.assertEqual(self.intro.user_details(), {'display_name': 'Sam', 'work_role': 'Engineer'})
