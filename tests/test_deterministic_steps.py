"""Steps that no longer need a model call: opening a named app/site, waiting for a
page to settle, and moving the companion to a named edge or corner."""
import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
os.environ.setdefault('A11Y_ROUTES', '0')  # nor read routes a live run remembered
from copy import deepcopy
import time
import unittest
from unittest.mock import Mock, patch
from companion.computer_task import ComputerTask, text_pass_enabled
from companion.desktop_context import DesktopContext
from companion.request_plan import preserve_desktop_goal
from companion.service import geometric_destination
from test_core import CompanionFixture
from test_desktop_context import FakeBridge
from test_request_plan import StagedProvider

SAFARI = {'name': 'Safari', 'bundle_id': 'com.apple.Safari'}
CALCULATOR = {'name': 'Calculator', 'bundle_id': 'com.apple.calculator'}


class OpeningServiceTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()
        self.bridge.catalog = Mock(return_value=[SAFARI, CALCULATOR])
        self.app.desktop_context = DesktopContext(self.bridge, clock=lambda: 100)

    def start(self, plan, request):
        provider = self.app.provider = StagedProvider(plan['operation'], plan.get('app_name', ''), plan.get('target', ''))
        provider.interpret_request.return_value = plan
        result = self.app.ask(request)
        provider.complete_structured.assert_not_called()
        return result['desktop_action']

    def test_teams_goal_opens_the_site_in_the_requested_window_without_a_model_step(self):
        action = self.start({'operation': 'browser_open', 'app_name': 'Safari', 'target': 'https://teams.microsoft.com',
                             'browser_mode': 'window', 'remaining_request': 'see if there are new tasks for me', 'goal_mode': 'inspect'},
                            'open teams in a new safari window and see if there are any new tasks for me')
        self.assertEqual(action['type'], 'start_task')
        self.assertEqual(action['goal'], 'open teams in a new safari window and see if there are any new tasks for me')
        self.assertEqual(action['opening']['type'], 'browse_url')
        self.assertEqual(action['opening']['url'], 'https://teams.microsoft.com')
        self.assertEqual(action['opening']['browser_mode'], 'window')

    def test_calculator_goal_launches_the_catalog_app_first(self):
        action = self.start({'operation': 'launch_app', 'app_name': 'Calculator', 'target': '', 'remaining_request': 'sum 2+2'},
                            'open calculator and sum 2+2')
        self.assertEqual(action['opening'], {'type': 'launch_app', 'bundle_id': 'com.apple.calculator', 'label': 'Open Calculator'})

    def test_a_bare_unknown_name_is_searched_not_turned_into_a_guessed_address(self):
        action = self.start({'operation': 'browser_open', 'app_name': 'Safari', 'target': 'intranet',
                             'browser_mode': 'window', 'remaining_request': 'check tasks'}, 'open intranet in safari and check tasks')
        self.assertEqual(action['type'], 'start_task')
        self.assertEqual(action['opening']['url'], 'https://duckduckgo.com/?q=intranet')

    def test_known_web_app_name_opens_its_address_even_when_the_model_gave_a_bare_name(self):
        # Live: qwen3:4b returned target "teams" or skipped the opening entirely.
        for plan in ({'operation': 'browser_open', 'app_name': 'Safari', 'target': 'teams', 'browser_mode': 'window',
                      'remaining_request': 'check notifications'},
                     {'operation': 'computer_task', 'app_name': '', 'target': 'x'}):
            action = self.start(plan, 'open up teams in a new safari window YOURSELF, and see if there are any new notifications')
            self.assertEqual(action['opening']['url'], 'https://teams.microsoft.com')
            self.assertEqual(action['opening']['browser_mode'], 'window')

    def test_without_a_browser_named_teams_means_the_installed_app(self):
        self.bridge.catalog.return_value.append({'name': 'Microsoft Teams', 'bundle_id': 'com.microsoft.teams2'})
        action = self.start({'operation': 'computer_task', 'app_name': '', 'target': 'x'}, 'open teams and check my tasks')
        self.assertEqual(action['opening']['bundle_id'], 'com.microsoft.teams2')

    def test_left_of_the_screen_moves_without_a_second_model_call(self):
        action = self.start({'operation': 'move_geometry', 'app_name': '', 'target': 'left of the screen'}, 'move to the left of the screen')
        self.assertEqual(action, {'type': 'move_companion', 'destination': 'left_edge', 'label': 'Move to left edge'})


class GeometryTests(unittest.TestCase):
    def test_named_edges_and_corners_map_without_ambiguity(self):
        cases = {'move to the left of the screen': 'left_edge', 'go to the upper right corner': 'top_right',
                 'bottom left please': 'bottom_left', 'move to the middle': 'center', 'right side': 'right_edge'}
        for phrase, destination in cases.items():
            self.assertEqual(geometric_destination(phrase), destination, phrase)
        for phrase in ('move up a bit', 'from left to right', 'top', 'somewhere nice'):
            self.assertIsNone(geometric_destination(phrase), phrase)


class OpeningTaskTests(unittest.TestCase):
    def setUp(self):
        bridge = FakeBridge()
        bridge.value['installed_apps'] = [SAFARI]
        self.desktop = DesktopContext(bridge, clock=lambda: 100)
        self.desktop.enabled = True
        self.frames = []
        self.vision = Mock(enabled=True, generation=0)
        def capture(*args, **kwargs):
            regions = self.frames.pop(0) if self.frames else [{'text': t, 'x': .1, 'y': .2+.1*i, 'width': .1, 'height': .05} for i, t in enumerate(('Activity', 'Chat', 'Teams'))]
            return {'image_data': 'data:image/png;base64,x', 'display_id': 1, 'text_regions': regions,
                    'screen': {'x': 0, 'y': 0, 'width': 1000, 'height': 700}, 'captured_monotonic': time.monotonic()}
        self.vision.capture.side_effect = capture
        self.provider = Mock()
        self.provider.complete_structured.return_value = {'status': 'action', 'message': 'Open Activity.', 'risk': 'navigation',
            'action': {'type': 'click_point', 'x': .12, 'y': .12, 'label': 'Activity'}}

    def test_opening_is_offered_once_before_any_model_step(self):
        opening = {'type': 'browse_url', 'bundle_id': 'com.apple.Safari', 'url': 'https://teams.microsoft.com', 'label': 'Open Teams', 'browser_mode': 'window'}
        task = ComputerTask('open teams and check tasks', automatic=True, goal_mode='inspect', opening=opening)
        step = task.take_opening()
        self.assertEqual(step['action'], opening)
        self.assertFalse(step['review'])
        self.assertIsNone(task.take_opening())
        self.provider.complete_structured.assert_not_called()

    def test_after_navigation_the_screen_is_watched_until_it_settles(self):
        loading = [{'text': 'Loading', 'x': .4, 'y': .4, 'width': .1, 'height': .05}]
        ready = [{'text': t, 'x': .1, 'y': .2+.1*i, 'width': .1, 'height': .05} for i, t in enumerate(('Activity', 'Chat', 'Teams'))]
        self.frames = [loading, loading, ready, ready]
        task = ComputerTask('open teams and check tasks', automatic=True, goal_mode='inspect')
        task.record({'type': 'browse_url', 'label': 'Open Teams', 'status': 'submitted'})
        with patch('companion.computer_task.time.sleep'):
            task.propose(self.desktop, self.vision, self.provider, {'x': 0, 'y': 0})
        self.assertEqual(self.vision.capture.call_count, 4)
        self.assertIn('Activity', self.provider.complete_structured.call_args.args[1][1]['content'])
        self.assertIn('settle_ms', task.timings[-1])
        task.record({'type': 'click_point', 'label': 'Activity', 'status': 'submitted'})
        self.vision.capture.reset_mock()
        task.propose(self.desktop, self.vision, self.provider, {'x': 0, 'y': 0})
        self.assertEqual(self.vision.capture.call_count, 1)

    def test_stop_while_settling_sends_nothing(self):
        task = ComputerTask('open teams and check tasks', automatic=True, goal_mode='inspect')
        task.record({'type': 'browse_url', 'status': 'submitted'})
        with patch('companion.computer_task.time.sleep', side_effect=lambda seconds: task.stop()):
            with self.assertRaisesRegex(ValueError, 'stopped'):
                task.propose(self.desktop, self.vision, self.provider, {'x': 0, 'y': 0})
        self.provider.complete_structured.assert_not_called()

    def test_text_only_pass_is_opt_in(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(text_pass_enabled())
        with patch.dict('os.environ', {'A11Y_TEXT_PASS': '1'}):
            self.assertTrue(text_pass_enabled())


class PlanTests(unittest.TestCase):
    def test_shortcut_with_follow_up_keeps_the_opening(self):
        plan = preserve_desktop_goal({'operation': 'browser_open', 'app_name': 'Safari', 'target': 'https://teams.microsoft.com',
                                      'browser_mode': 'window', 'remaining_request': 'check tasks'}, 'open teams in safari and check tasks')
        self.assertEqual(plan['operation'], 'computer_task')
        self.assertEqual(plan['opening'], {'operation': 'browser_open', 'app_name': 'Safari',
                                           'target': 'https://teams.microsoft.com', 'browser_mode': 'window'})


class CompactObservationTests(unittest.TestCase):
    def test_ocr_lines_and_controls_are_short_strings_with_click_ready_centers(self):
        from companion.computer_task import compact_regions, compact_desktop
        self.assertEqual(compact_regions([{'text': 'Activity', 'x': .02, 'y': .2, 'width': .06, 'height': .02}]), ['Activity|0.050,0.210'])
        desktop = compact_desktop({'status': 'available', 'app': {'name': 'Safari', 'bundle_id': 'com.apple.Safari', 'pid': 3},
            'window': {'title': 'Teams', 'bounds': {'x': 0, 'y': 0, 'width': 10, 'height': 10}},
            'controls': [{'id': 'control-0', 'role': 'AXButton', 'label': 'Activity', 'enabled': True,
                          'bounds': {'x': 10.4, 'y': 20, 'width': 30, 'height': 40}}],
            'available_apps': [{'name': 'Safari', 'bundle_id': 'com.apple.Safari'}]})
        self.assertEqual(desktop, {'status': 'available', 'app': 'Safari (com.apple.Safari)', 'window': 'Teams',
                                   'controls': ['control-0|button|Activity|10,20,30,40'], 'running_apps': ['Safari=com.apple.Safari']})


if __name__ == '__main__':
    unittest.main()
