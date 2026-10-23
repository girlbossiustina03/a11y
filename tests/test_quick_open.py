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


if __name__ == '__main__':
    unittest.main()
