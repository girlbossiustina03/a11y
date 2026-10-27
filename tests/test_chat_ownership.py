import tempfile
import unittest
from unittest.mock import Mock, patch
from companion.models import Identity
from companion.request_plan import preserve_desktop_goal
from companion.service import Companion
from companion.storage import Store
from companion.desktop_context import DesktopContext


class ConversationOwnership(unittest.TestCase):
    def test_reported_greeting_and_correction_never_request_screen_or_movement(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('companion.mail_reader.available',return_value=False), \
             patch('companion.mac_apps.available',return_value=False):
            provider = Mock()
            app = Companion(Store(folder),Identity('test','user'),provider)
            app.desktop_context = DesktopContext(Mock(catalog=Mock(return_value=[])))
            for request in ('hey ally','bro i js said hello you fuck','are you geniuennly restarted?'):
                with self.subTest(request=request):
                    provider.interpret_request.return_value = dict(operation='answer',app_name='',target='',
                        reply='Hello.',referent='companion',acts_on_computer=False)
                    provider.complete_structured.return_value = {'message':'Hello.'}
                    result = app.ask(request)
                    self.assertIsNone(result['desktop_action'])
                    self.assertIsNone(result['target'])
                    self.assertEqual(result['message'],'Hello.')
                    self.assertEqual(app.last_request_plan['operation'],'answer')

    def test_auxiliary_destination_cannot_turn_non_action_answer_into_navigation(self):
        raw = dict(operation='answer',app_name='',target='',reply='Hello.',
                   acts_on_computer=False,referent='destination')
        self.assertEqual(preserve_desktop_goal(raw,'Hello.')['operation'],'answer')

    def test_low_confidence_question_about_companion_is_not_a_web_lookup(self):
        app = object.__new__(Companion)
        plan = dict(operation='answer',referent='companion',acts_on_computer=False,
                    confidence=.1,reply='A conversational reply.')
        with patch('companion.web_lookup.enabled',return_value=True):
            self.assertFalse(app.unsure(plan,'Are you restarting?'))
            self.assertTrue(app.unsure(dict(plan,referent='other'),'What is the capital of France?'))


class EvaluationHistory(unittest.TestCase):
    def test_eval_history_does_not_read_write_or_clear_normal_history(self):
        with tempfile.TemporaryDirectory() as folder:
            identity = Identity('company','user')
            normal = Store(folder)
            normal.add_exchange(identity,'Real question','Real answer')
            evaluation = Store(folder,persist_history=False)
            self.assertEqual(evaluation.history(identity),[])
            evaluation.add_exchange(identity,'Synthetic request','Synthetic answer')
            self.assertEqual(evaluation.history(identity)[0]['content'],'Synthetic request')
            self.assertEqual(normal.history(identity)[0]['content'],'Real question')
            with normal.employee() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0],2)
            evaluation.clear_history(identity)
            self.assertEqual(evaluation.history(identity),[])
            self.assertEqual(len(normal.history(identity)),2)
            self.assertEqual(Store(folder,persist_history=False).history(identity),[])

    def test_eval_history_is_bounded_and_keeps_identity_and_limit_contracts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder,persist_history=False)
            first, second = Identity('company','one'),Identity('company','two')
            for i in range(80):
                store.add_exchange(first,str(i),'answer')
            self.assertEqual(len(store.history(first,1000)),100)
            self.assertEqual(store.history(first,0),[])
            self.assertEqual(store.history(second),[])

    def test_eval_from_env_selects_ephemeral_history_without_changing_profile_storage(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'A11Y_EVAL':'1','A11Y_DATA_DIR':folder}), \
             patch('companion.service.provider_from_env',return_value=Mock()):
            app = Companion.from_env()
            self.assertFalse(app.store.persist_history)
            app.store.save_profile(app.identity,{'name':'test'})
            self.assertEqual(Store(folder).profile(app.identity),{'name':'test'})
