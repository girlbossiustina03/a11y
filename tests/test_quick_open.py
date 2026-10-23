"""'Open X' resolved in code: installed app, known web app/address, then web search."""
import unittest
from unittest.mock import Mock
from companion.desktop_context import DesktopContext
from companion.quick_open import plan
from test_core import CompanionFixture
from test_desktop_context import FakeBridge

CATALOG = [{'name': 'Safari', 'bundle_id': 'com.apple.Safari'}, {'name': 'Calculator', 'bundle_id': 'com.apple.calculator'},
           {'name': 'Stremio', 'bundle_id': 'com.fixture.stremio'}, {'name': 'TextEdit', 'bundle_id': 'com.apple.TextEdit'},
           {'name': 'Microsoft Teams', 'bundle_id': 'com.microsoft.teams2'}]


class QuickOpenTests(unittest.TestCase):
    def test_installed_app_wins_over_the_web(self):
        self.assertEqual(plan('open stremio', CATALOG)['operation'], 'launch_app')
        self.assertEqual(plan('open teams', CATALOG)['app_name'], 'Microsoft Teams')
        self.assertEqual(plan('open notepad and write a summary', CATALOG),
                         {'operation': 'launch_app', 'app_name': 'TextEdit', 'target': '', 'browser_mode': 'default',
                          'remaining_request': 'write a summary'})

    def test_named_browser_opens_the_web_app_with_requested_placement(self):
        result = plan('open up teams in a new safari window YOURSELF, and see if there are any new notifications', CATALOG)
        self.assertEqual(result, {'operation': 'browser_open', 'app_name': 'Safari', 'target': 'https://teams.microsoft.com',
                                  'browser_mode': 'window', 'remaining_request': 'see if there are any new notifications'})
        self.assertEqual(plan('open youtube in a new tab', CATALOG)['browser_mode'], 'tab')

    def test_missing_app_falls_back_to_web_app_address_or_search(self):
        self.assertEqual(plan('open youtube', CATALOG)['target'], 'https://www.youtube.com')
        self.assertEqual(plan('go to github.com/iediot', CATALOG)['target'], 'github.com/iediot')
        self.assertEqual(plan('launch obsidian please', CATALOG), {'operation': 'browser_search', 'app_name': '', 'target': 'obsidian',
                                                                    'browser_mode': 'default', 'remaining_request': ''})

    def test_descriptions_and_local_things_are_left_to_the_model(self):
        for request in ('open the second email', 'open a new safari window', 'open my downloads folder',
                        'open downloads folder', 'what is open', 'open'):
            self.assertIsNone(plan(request, CATALOG), request)

    def test_ambiguous_installed_apps_are_left_to_the_model(self):
        catalog = CATALOG+[{'name': 'Microsoft Teams (work or school)', 'bundle_id': 'other'}, {'name': 'Teams', 'bundle_id': 't'}]
        self.assertIsNone(plan('open microsoft', catalog))


class QuickOpenServiceTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        bridge = FakeBridge()
        bridge.catalog = Mock(return_value=CATALOG)
        bridge.app_state = Mock(return_value={'running': True})
        self.app.desktop_context = DesktopContext(bridge, clock=lambda: 100)
        self.app.provider = Mock()

    def test_open_requests_route_without_any_model_call(self):
        action = self.app.ask('open stremio')['desktop_action']
        self.assertEqual(action['type'], 'launch_app')
        action = self.app.ask('open teams in a new safari window and check my notifications')['desktop_action']
        self.assertEqual(action['type'], 'start_task')
        self.assertEqual(action['opening']['url'], 'https://teams.microsoft.com')
        action = self.app.ask('open spotify')['desktop_action']
        self.assertEqual(action['type'], 'browse_url')
        self.assertIn('duckduckgo.com', action['url'])
        self.app.provider.interpret_request.assert_not_called()
        self.app.provider.complete_structured.assert_not_called()


    def test_bare_verbs_ask_what_instead_of_guessing(self):
        # Reported: a bare "Open." opened google.com.
        for request, reply in (('Open.', 'Open what?'), ('click', 'Click what?'), ('search for', 'What should I search for?')):
            response = self.app.ask(request)
            self.assertEqual(response['message'], reply)
            self.assertIsNone(response['desktop_action'])
        self.app.provider.interpret_request.assert_not_called()

    def test_task_without_an_opening_keeps_the_users_words(self):
        # Reported: "Open up the second last image…" became the verbless goal "the second last image…".
        self.app.provider.interpret_request.return_value = {
            'operation': 'computer_task', 'app_name': '', 'target': 'the second last image you see on this screen',
            'goal_mode': 'change', 'reply': '', 'remaining_request': ''}
        action = self.app.ask('Open up the second last image you see on this screen.')['desktop_action']
        self.assertEqual(action['type'], 'start_task')
        self.assertEqual(action['goal'], 'Open up the second last image you see on this screen.')
        self.assertNotIn('opening', action)

    def test_email_requests_use_the_open_mail_app_instead_of_gmail(self):
        # Reported: with Mail open, "check what my second last email says" opened Gmail in Safari.
        self.app.provider.interpret_request.return_value = {
            'operation': 'computer_task', 'app_name': '', 'target': 'check what my second last email says',
            'goal_mode': 'inspect', 'reply': '', 'remaining_request': 'check what my second last email says',
            'opening': {'operation': 'browser_open', 'app_name': '', 'target': 'gmail', 'browser_mode': 'default'}}
        self.app.desktop_context.bridge.app_state = Mock(side_effect=lambda bundle: {'running': bundle == 'com.apple.mail'})
        action = self.app.ask('Check what my second last email says.')['desktop_action']
        self.assertNotIn('opening', action)
        self.assertEqual(action['goal'], 'Check what my second last email says.')
        self.app.desktop_context.bridge.app_state = Mock(return_value={'running': False})
        action = self.app.ask('Check what my second last email says.')['desktop_action']
        self.assertEqual(action['opening']['url'], 'https://mail.google.com')


    def test_model_cannot_mark_its_own_reply_as_code_computed(self):
        self.app.provider.interpret_request.return_value = {'operation': 'answer', 'app_name': '', 'target': '',
                                                            'reply': 'Trust me.', 'computed': True}
        self.assertNotIn('computed', self.app.prepare_request('what does the handbook say about leave'))


if __name__ == '__main__':
    unittest.main()
