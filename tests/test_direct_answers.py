"""Questions are answered directly; optional background lookups replace browser searches."""
import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
os.environ.setdefault('A11Y_ROUTES', '0')  # nor read routes a live run remembered
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


    def test_weather_is_answered_in_code_without_opening_anything(self):
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), \
                patch('companion.weather.forecast', return_value={'place': 'Paris', 'sentence': 'Tomorrow in Paris: rain, 10° to 17°C.'}) as forecast:
            result = self.ask('will it rain in Paris tomorrow?', {'operation': 'weather', 'app_name': '', 'target': 'Paris', 'when': 'tomorrow'})
        forecast.assert_called_once_with('Paris', 'tomorrow')
        self.assertIsNone(result['desktop_action'])
        self.assertEqual(result['message'], 'Tomorrow in Paris: rain, 10° to 17°C.')
        # No place named: the saved home place, else this Mac's time-zone city.
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.weather.home_place', return_value='Bucharest'), \
                patch('companion.weather.forecast', return_value={'place': 'Bucharest', 'sentence': '10°C and cloudy in Bucharest.'}) as forecast:
            self.ask('what is the weather like?', {'operation': 'weather', 'app_name': '', 'target': '', 'when': ''})
        forecast.assert_called_once_with('Bucharest', 'now')
        # Reported: the router put "today" where the place goes and it was geocoded to a town called Todaya.
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.weather.home_place', return_value='Bucharest'), \
                patch('companion.weather.forecast', return_value={'place': 'Bucharest', 'sentence': '10°C in Bucharest.'}) as forecast:
            self.ask('will it be foggy today?', {'operation': 'weather', 'app_name': '', 'target': 'today', 'when': ''})
        forecast.assert_called_once_with('Bucharest', 'now')

    def test_reported_two_cities_are_compared(self):
        # Live (v3): "is it warmer in Lima or Nairobi right now?" got Lima's weather only.
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), \
                patch('companion.weather.compare', return_value='Lima is warmer: 24°C, against 19°C in Nairobi.') as compare:
            result = self.ask('is it warmer in Lima or Nairobi right now?', {'operation': 'weather', 'app_name': '', 'target': 'Lima'})
        compare.assert_called_once_with(['Lima', 'Nairobi'])
        self.assertIn('Lima is warmer', result['message'])

    def test_reported_a_lookup_then_carries_on_with_the_rest(self):
        # Live (v3): the population was found, "write it in a new TextEdit document" was dropped.
        found = ('5.6 million', {'title': 'Norway', 'extract': '', 'url': ''})
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.answer', return_value=found):
            result = self.ask('look up the population of Norway and write it in a new TextEdit document',
                              {'operation': 'look_up', 'app_name': '', 'target': 'population of Norway',
                               'remaining_request': 'write it in a new TextEdit document'})
        self.assertEqual(result['desktop_action']['type'], 'start_task')
        self.assertEqual(result['desktop_action']['goal'], 'write "5.6 million" in a new TextEdit document')  # the text itself
        self.assertNotIn('Still pending', result['message'])

    def test_changing_facts_are_looked_up_in_the_background(self):
        found = ('Austria won with "Wasted Love" by JJ.', {'title': 'Eurovision Song Contest 2025', 'extract': '', 'url': ''})
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.answer', return_value=found) as lookup:
            result = self.ask('who won Eurovision 2025?', {'operation': 'look_up', 'app_name': '', 'target': 'Eurovision 2025 winner'})
        lookup.assert_called_once()
        self.assertIsNone(result['desktop_action'])
        self.assertIn('Wasted Love', result['message'])
        self.assertIn('Source: Wikipedia, Eurovision Song Contest 2025', result['message'])
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.answer', return_value=None), \
                patch.object(self.app, 'converse', return_value=None):
            result = self.ask('who won Eurovision 2025?', {'operation': 'look_up', 'app_name': '', 'target': 'Eurovision 2025 winner'})
        self.assertIsNone(result['desktop_action'])                 # never a browser unasked
        self.assertIn('search for', result['message'])
        # Reported: "the speed of light in km per second" got "I couldn't find that online": the model's own answer.
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.answer', return_value=None), \
                patch.object(self.app, 'converse', return_value='About 299,792 km per second.'):
            result = self.ask('find out the speed of light in km per second', {'operation': 'look_up', 'app_name': '', 'target': 'speed of light'})
        self.assertEqual(result['message'], 'About 299,792 km per second.')
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '0'}), patch('companion.web_lookup.answer') as lookup:
            result = self.ask('who won Eurovision 2025?', {'operation': 'look_up', 'app_name': '', 'target': 'Eurovision 2025 winner'})
        lookup.assert_not_called()
        self.assertIn('turned off', result['message'])

    def test_an_unsure_answer_is_checked_online_and_a_sure_one_is_not(self):
        found = ('Florin Talpeș is the CEO of Bitdefender.', {'title': 'Bitdefender', 'extract': '', 'url': ''})
        plan = {'operation': 'answer', 'app_name': '', 'target': '', 'reply': 'Bitdefender has no public CEO.'}
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.answer', return_value=found) as lookup:
            unsure = self.ask('who is the CEO of Bitdefender?', dict(plan, confidence=0.28))
            # A sure reply is written with the conversation in mind, as before, and not looked up.
            provider = self.app.provider = StagedProvider('answer')
            provider.interpret_request.return_value = dict(plan, confidence=0.97)
            provider.complete_structured.return_value = {'message': 'Bitdefender has no public CEO.'}
            sure = self.app.ask('who is the CEO of Bitdefender?')
        self.assertEqual(lookup.call_count, 1)
        self.assertIn('Florin Talpeș', unsure['message'])
        self.assertEqual(sure['message'], 'Bitdefender has no public CEO.')
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.answer', return_value=None):
            kept = self.ask('who is the CEO of Bitdefender?', dict(plan, confidence=0.28))
        self.assertEqual(kept['message'], 'Bitdefender has no public CEO.')  # nothing better online

    def test_asking_to_search_still_opens_the_browser(self):
        with patch.dict('os.environ', {'A11Y_WEB_ANSWERS': '1'}), patch('companion.web_lookup.answer') as lookup:
            result = self.ask('search for romeo and juliet', {'operation': 'browser_search', 'app_name': '', 'target': 'romeo and juliet'})
        lookup.assert_not_called()
        self.assertEqual(result['desktop_action']['type'], 'browse_url')


class ReplyQualityTests(unittest.TestCase):
    def test_markdown_is_removed_from_replies(self):
        from companion.service import plain_text
        self.assertEqual(plain_text('## First day\n\n1. **Arrive on time** -- greet your team.\n- Ask `questions`'),
                         'First day\n\n1. Arrive on time – greet your team.\n• Ask questions')


class InspectionChangeTests(unittest.TestCase):
    def test_turning_on_notifications_is_a_change_not_inspection(self):
        # Live: "see if I have notifications" clicked "Turn on desktop notifications".
        from companion.computer_task import needs_review
        self.assertTrue(needs_review({'type': 'click_point', 'label': 'Turn on desktop notifications'}, 'navigation'))
        self.assertFalse(needs_review({'type': 'click_point', 'label': 'Activity'}, 'navigation'))


if __name__ == '__main__':
    unittest.main()
