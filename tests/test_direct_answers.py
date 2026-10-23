"""Questions are answered directly; optional background lookups replace browser searches."""
import unittest
from unittest.mock import Mock, patch
from companion.desktop_context import DesktopContext
from companion.request_plan import preserve_desktop_goal
from companion.web_lookup import lookup_phrase, plain_question
from test_core import CompanionFixture
from test_desktop_context import FakeBridge
from test_request_plan import StagedProvider


class QuestionRoutingTests(unittest.TestCase):
    def test_questions_are_not_browser_searches(self):
        for request in ('where is china', 'Where is China?', 'what is the capital of france', 'how tall is everest?'):
            self.assertTrue(plain_question(request), request)
            plan = preserve_desktop_goal({'operation': 'browser_search', 'app_name': 'Safari', 'target': request}, request)
            self.assertEqual(plan['operation'], 'answer', request)

    def test_explicit_searches_and_opening_still_use_the_browser(self):
        for request in ('search for china in safari', 'google where china is', 'open wikipedia', 'look up china'):
            self.assertFalse(plain_question(request), request)
        self.assertEqual(lookup_phrase('look up the Great Wall of China'), 'the Great Wall of China')
        self.assertEqual(lookup_phrase('search for china'), 'china')
        self.assertIsNone(lookup_phrase('search for china in safari'))
        self.assertIsNone(lookup_phrase('where is china'))


class DirectAnswerServiceTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        bridge = FakeBridge()
        bridge.catalog = Mock(return_value=[{'name': 'Safari', 'bundle_id': 'com.apple.Safari'}])
        self.app.desktop_context = DesktopContext(bridge, clock=lambda: 100)

    def ask(self, request, plan):
        provider = self.app.provider = StagedProvider(plan['operation'])
        provider.interpret_request.return_value = plan
        result = self.app.ask(request)
        provider.complete_structured.assert_not_called()
        return result

    def test_where_is_china_is_answered_by_the_routing_call_without_a_browser(self):
        # Live: the small model routed this to a Safari search.
        result = self.ask('where is china', {'operation': 'browser_search', 'app_name': 'Safari', 'target': 'china',
                                             'reply': 'China is in East Asia, bordering 14 countries.'})
        self.assertIsNone(result['desktop_action'])
        self.assertEqual(result['message'], 'China is in East Asia, bordering 14 countries.')

    def test_company_questions_keep_the_cited_document_path(self):
        provider = self.app.provider = StagedProvider('answer')
        provider.interpret_request.return_value = {'operation': 'answer', 'app_name': '', 'target': '', 'reply': 'guess'}
        provider.complete_structured.return_value = {'request_kind': 'answer', 'message': 'From the docs.', 'source_ids': [],
                                                     'workflow': None, 'target': None, 'desktop_action': None}
        with patch.object(self.app.knowledge, 'retrieve', return_value=[{'id': 'c1', 'document_id': 'd', 'title': 'VPN', 'ordinal': 1, 'content': 'x'}]):
            result = self.app.ask('how do I set up the VPN?')
        self.assertEqual(result['message'], 'From the docs.')

    def test_opt_in_lookup_answers_in_the_background_instead_of_opening_safari(self):
        found = {'title': 'Great Wall of China', 'extract': 'A series of fortifications.', 'url': 'https://en.wikipedia.org/wiki/Great_Wall_of_China'}
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.summary', return_value=found) as summary:
            result = self.ask('look up the great wall of china', {'operation': 'browser_search', 'app_name': '', 'target': 'great wall of china'})
        summary.assert_called_once_with('the great wall of china')
        self.assertIsNone(result['desktop_action'])
        self.assertIn('A series of fortifications.', result['message'])
        self.assertIn('Source: Wikipedia', result['message'])

    def test_lookup_is_off_by_default_and_failure_falls_back_to_the_browser(self):
        with patch('companion.web_lookup.summary') as summary:
            result = self.ask('look up the great wall of china', {'operation': 'browser_search', 'app_name': '', 'target': 'great wall of china'})
        summary.assert_not_called()
        self.assertEqual(result['desktop_action']['type'], 'browse_url')
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.summary', return_value=None):
            result = self.ask('look up the great wall of china', {'operation': 'browser_search', 'app_name': '', 'target': 'great wall of china'})
        self.assertEqual(result['desktop_action']['type'], 'browse_url')


if __name__ == '__main__':
    unittest.main()
