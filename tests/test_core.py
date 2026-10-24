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
from companion.adaptation import Adaptation
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
        ids = [s['id'] for s in context['sources']]
        workflow = None
        if context['mode'] == 'plan':
            workflow = {'title': 'Development environment setup', 'steps': [
                {'instruction': 'Review SSH keys in your browser.', 'application': 'Browser',
                 'keyboard_hint': '', 'source_ids': ids[:1]},
                {'instruction': 'Open the Extensions view in Visual Studio Code.', 'application': 'Visual Studio Code',
                 'keyboard_hint': 'Command+Shift+X on macOS.', 'source_ids': ids[:1]}]}
        target = {'label': 'Open Extensions in the left sidebar', 'x': .02, 'y': .15, 'width': .04, 'height': .07} if image_data else None
        return {'message': 'Follow the company onboarding instructions.', 'source_ids': ids[:1],
                'workflow': workflow, 'target': target}


class CompanionFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.employee = Identity('company', 'engineer', ('employee', 'engineering'))
        self.admin = Identity('company', 'admin-user', ('admin', 'engineering', 'employee'))
        self.provider = RecordingProvider()
        self.app = Companion(self.store, self.employee, self.provider)
        self.admin_app = Companion(self.store, self.admin, self.provider)
        self.example = Path('examples/onboarding.md').read_text()
        self.document_id = self.admin_app.knowledge.ingest(self.admin, 'Engineering onboarding', self.example, ['engineering'])

    def tearDown(self):
        self.temp.cleanup()

    def plan(self):
        return self.app.ask('Help me set up my development environment', mode='plan')['workflow']


class CoreTests(CompanionFixture, unittest.TestCase):
    def test_complete_onboarding_resume_and_adapt_across_restart(self):
        workflow = self.plan()
        self.assertEqual(workflow['current_step'], 0)
        self.assertTrue(workflow['sources'])
        self.store.confirm_step(self.employee, workflow['id'], 0)
        restarted = Companion(Store(self.temp.name), self.employee, self.provider)
        saved = restarted.state()['workflows'][0]
        self.assertEqual(saved['current_step'], 1)
        restarted.ask('Where did I leave off?', workflow_id=workflow['id'])
        self.assertEqual(self.provider.contexts[-1]['workflow']['current_step'], 1)
        restarted.ask('Please give shorter answers')
        restarted.ask('Shorter answers please')
        self.assertEqual(restarted.state()['effective']['detail'], 'balanced')
        restarted.adaptation.decide(self.employee, 'detail:concise', True)
        restarted.ask('Explain this step', workflow_id=workflow['id'])
        self.assertEqual(self.provider.contexts[-1]['preferences']['detail'], 'concise')
        done = restarted.store.confirm_step(self.employee, workflow['id'], 1)
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(len(done['confirmations']), 2)
        self.assertTrue(all(c['by'] == 'user' for c in done['confirmations']))

    def test_retrieval_filters_roles_and_tenant_before_model_call(self):
        self.admin_app.knowledge.ingest(self.admin, 'Private engineering onboarding', 'SECRET board environment onboarding budget', ['board'])
        other_admin = Identity('other-company', 'admin', ('admin',))
        self.admin_app.knowledge.ingest(other_admin, 'Other onboarding', 'OTHER_SECRET environment onboarding', ['engineering'])
        self.app.ask('Company environment onboarding')
        prompt = json.dumps(self.provider.contexts[-1])
        self.assertNotIn('SECRET', prompt)
        self.assertNotIn('Private engineering', prompt)
        self.assertIn('Engineering onboarding', prompt)

    def test_revoked_role_hides_dependent_tasks_and_history(self):
        w = self.plan()
        restricted = Companion(self.store, Identity('company', 'engineer', ('employee',)), self.provider)
        self.assertEqual(restricted.state()['workflows'], [])
        self.assertEqual(restricted.state()['unavailable_tasks'], 1)
        self.assertEqual(restricted.history(), [])
        with self.assertRaises(PermissionError):
            restricted.ask('Continue', workflow_id=w['id'])
        with self.assertRaises(PermissionError):
            restricted.confirm_step(w['id'], 0)
        restricted.ask('Hello')
        self.assertEqual(len(self.provider.calls[-1][1]), 2)
        self.assertEqual(self.provider.contexts[-1]['sources'], [])

    def test_deleted_source_hides_dependent_tasks_and_history(self):
        self.plan()
        self.admin_app.knowledge.delete(self.admin, self.document_id)
        self.assertEqual(self.app.state()['workflows'], [])
        self.assertEqual(self.app.history(), [])

    def test_empty_query_does_not_retrieve_every_document(self):
        self.assertEqual(self.app.knowledge.retrieve(self.employee, 'the to of'), [])

    def test_unrelated_query_has_no_fake_source(self):
        self.assertEqual(self.app.knowledge.retrieve(self.employee, 'astrophysics'), [])

    def test_document_ingestion_requires_admin(self):
        with self.assertRaises(PermissionError):
            self.app.knowledge.ingest(self.employee, 'Private', 'contents', ['employee'])

    def test_delete_cascades_chunks(self):
        self.admin_app.knowledge.delete(self.admin, self.document_id)
        self.assertEqual(self.app.knowledge.retrieve(self.employee, 'onboarding'), [])
        with self.store.company() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM chunks').fetchone()[0], 0)

    def test_workflows_and_profiles_separate_employees(self):
        w = self.plan()
        other = Identity('company', 'someone-else', self.employee.roles)
        self.assertEqual(self.store.workflows(other), [])
        with self.assertRaises(ValueError):
            self.store.workflow(other, w['id'])
        with self.assertRaises(ValueError):
            self.store.confirm_step(other, w['id'], 0)
        self.app.adaptation.set_explicit(self.employee, {'detail': 'detailed'}, True)
        self.assertEqual(self.app.adaptation.effective(other)['detail'], 'balanced')

    def test_replayed_confirmation_cannot_skip(self):
        w = self.plan()
        self.store.confirm_step(self.employee, w['id'], 0)
        with self.assertRaises(ValueError):
            self.store.confirm_step(self.employee, w['id'], 0)
        with self.assertRaises(ValueError):
            self.store.confirm_step(self.employee, w['id'], True)
        self.assertEqual(self.store.workflow(self.employee, w['id'])['current_step'], 1)

    def test_no_confirmation_after_completion(self):
        w = self.plan()
        self.store.confirm_step(self.employee, w['id'], 0)
        self.store.confirm_step(self.employee, w['id'], 1)
        with self.assertRaises(ValueError):
            self.store.confirm_step(self.employee, w['id'], 2)

    def test_answer_cannot_replace_or_complete_workflow(self):
        w = self.plan()
        self.app.ask('I think I finished all of it', workflow_id=w['id'])
        self.assertEqual(self.store.workflow(self.employee, w['id'])['current_step'], 0)
        self.provider.invalid = {'message': 'Done', 'source_ids': [], 'workflow': {'title': 'Overwrite', 'steps': []}, 'target': None}
        # An invalid workflow is never saved: at most the words are shown, with nothing attached.
        result = self.app.ask('Continue')
        self.assertIsNone(result['workflow'])
        self.assertEqual(len(self.store.workflows(self.employee)), 1)
        self.assertEqual(self.store.workflow(self.employee, w['id'])['current_step'], 0)

    def test_fabricated_source_rejects_whole_response(self):
        self.provider.invalid = {'message': 'Claim', 'source_ids': ['made-up-source'], 'workflow': None, 'target': None}
        with self.assertRaises(ValidationError):
            self.app.ask('onboarding')
        self.assertEqual(self.store.history(self.employee), [])
        self.assertEqual(self.store.workflows(self.employee), [])

    def test_injected_actions_rejected(self):
        self.provider.invalid = {'message': 'Hello', 'source_ids': [], 'workflow': None, 'target': None, 'shell': 'rm -rf anything'}
        with self.assertRaises(ValidationError):
            self.app.ask('onboarding')

    def test_provider_failure_does_not_advance_or_record_preferences(self):
        w = self.plan()
        history = self.store.history(self.employee)
        self.provider.error = ProviderError('Unavailable')
        with self.assertRaises(ProviderError):
            self.app.ask('shorter answers', workflow_id=w['id'])
        self.assertEqual(history, self.store.history(self.employee))
        self.assertEqual(self.store.workflow(self.employee, w['id'])['current_step'], 0)
        self.assertEqual(self.app.adaptation.get(self.employee)['observed'], {})

    def test_image_analysis_never_persists_image_or_reply(self):
        self.app.ask('What is this control?', image_data='data:image/png;base64,TEST_ONLY')
        self.assertEqual(self.store.history(self.employee), [])
        self.assertEqual(self.store.workflows(self.employee), [])
        for file in Path(self.temp.name).iterdir():
            self.assertNotIn(b'TEST_ONLY', file.read_bytes())
            self.assertNotIn(b'Follow the company', file.read_bytes())

    def test_target_requires_image(self):
        self.provider.invalid = {'message': 'Click', 'source_ids': [], 'workflow': None,
            'target': {'label': 'Button', 'x': .1, 'y': .2, 'width': .3, 'height': .1}}
        result = self.app.ask('Help')  # no screen image: the target is dropped, never shown
        self.assertIsNone(result['target'])
        self.assertIsNone(result['desktop_action'])

    def test_profile_only_changes_with_approval(self):
        a = self.app.adaptation
        a.observe(self.employee, 'shorter please')
        self.assertEqual(a.get(self.employee)['suggestions'], {})
        a.observe(self.employee, 'shorter please')
        self.assertIn('detail:concise', a.get(self.employee)['suggestions'])
        self.assertEqual(a.effective(self.employee)['detail'], 'balanced')
        a.decide(self.employee, 'detail:concise', True)
        self.assertEqual(a.effective(self.employee)['detail'], 'concise')

    def test_explicit_overrides_approved_and_disable_uses_defaults(self):
        a = self.app.adaptation
        a.observe(self.employee, 'shorter')
        a.observe(self.employee, 'shorter')
        a.decide(self.employee, 'detail:concise', True)
        a.set_explicit(self.employee, {'detail': 'detailed'}, True)
        self.assertEqual(a.effective(self.employee)['detail'], 'detailed')
        a.set_explicit(self.employee, {}, False)
        self.assertEqual(a.effective(self.employee)['detail'], 'balanced')
        before = a.get(self.employee)
        a.observe(self.employee, 'keyboard shortcuts')
        self.assertEqual(before, a.get(self.employee))

    def test_dismiss_and_reset(self):
        a = self.app.adaptation
        for _ in range(2):
            a.observe(self.employee, 'one step at a time')
        a.decide(self.employee, 'pacing:one_step', False)
        a.observe(self.employee, 'one step at a time')
        self.assertEqual(a.get(self.employee)['suggestions'], {})
        a.set_explicit(self.employee, {'input': 'keyboard'}, True)
        a.reset_learned(self.employee)
        self.assertEqual(a.get(self.employee)['observed'], {})
        self.assertEqual(a.effective(self.employee)['input'], 'keyboard')

    def test_no_diagnosis_inference(self):
        self.app.adaptation.observe(self.employee, 'I have ADHD and struggle at work')
        self.assertEqual(self.app.adaptation.get(self.employee)['observed'], {})

    def test_reject_invalid_preference_values(self):
        a = self.app.adaptation
        for values, enabled in [({'diagnosis': 'guess'}, True), ({'detail': 'very short'}, True),
                                ({'reduced_motion': 1}, True), ({}, 'yes')]:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    a.set_explicit(self.employee, values, enabled)

    def test_no_silent_demo_fallback_without_config(self):
        from companion.provider import AIConfig, ChatProvider
        app = Companion(self.store, self.employee, ChatProvider(AIConfig()))
        self.assertFalse(app.state()['ai']['ready'])
        with self.assertRaises(ProviderError):
            app.ask('Plan onboarding', mode='plan')
        self.assertEqual(app.state()['workflows'], [])

    def test_company_step_requires_citation(self):
        plan = self.plan()
        plan['steps'][0]['source_ids'] = []
        self.provider.invalid = {'message': 'Plan', 'source_ids': [], 'workflow':
                                {'title': plan['title'], 'steps': plan['steps']}, 'target': None}
        with self.assertRaises(ValidationError):
            self.app.ask('development environment onboarding', mode='plan')


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
                validate_response(value, set())


if __name__ == '__main__':
    unittest.main()
