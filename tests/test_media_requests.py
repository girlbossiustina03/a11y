"""Compound goals and playback are grounded in native evidence, not process names."""
import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
os.environ.setdefault('A11Y_ROUTES', '0')  # nor read routes a live run remembered
import unittest
from unittest.mock import Mock
from companion.desktop_context import DesktopContext
from test_core import CompanionFixture
from test_desktop_context import FakeBridge
from test_request_plan import StagedProvider


class MediaRequestTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        bridge = self.bridge = FakeBridge()
        bridge.catalog = Mock(return_value=[{'name': 'Music', 'bundle_id': 'com.apple.Music'}])
        bridge.media_state = Mock(return_value={'player_state': 'paused', 'track': {'name': 'Last Christmas', 'artist': 'Wham!', 'id': 'ABC'}})
        bridge.app_state = Mock(return_value={'running': True})
        self.app.desktop_context = DesktopContext(bridge, clock=lambda: 100)

    def test_compound_music_request_does_not_disappear_into_launch(self):
        provider = self.app.provider = StagedProvider('play_media', 'Music', 'Last Christmas')
        result = self.app.ask('open music and play last christmas')
        self.assertEqual(result['desktop_action']['type'], 'play_media')
        self.assertEqual(result['desktop_action']['query'], 'Last Christmas')
        self.assertNotIn('is running', result['message'])
        provider.complete_structured.assert_not_called()

    def test_what_is_playing_reads_actual_state_without_llm_guess_or_screenshot(self):
        provider = self.app.provider = StagedProvider('inspect_media', '', '')
        result = self.app.ask('what is playing')
        self.assertIn('paused', result['message'])
        self.assertNotIn('is playing', result['message'])
        self.bridge.media_state.assert_called_once()
        provider.complete_structured.assert_not_called()
        self.assertIsNone(result['desktop_action'])

    def test_play_verification_checks_current_id_and_state(self):
        provider = self.app.provider = StagedProvider('play_media', 'Music', 'Last Christmas')
        self.app.last_action_result = {'type': 'play_media', 'native_result': {'play_submitted': True, 'requested_id': 'ABC'}}
        self.assertIn('not confirmed', self.app.ask('play it', mode='verify')['message'])
        self.bridge.media_state.return_value['player_state'] = 'playing'
        self.assertIn('playing Last Christmas by Wham!', self.app.ask('play it', mode='verify')['message'])
        self.bridge.media_state.return_value['track']['id'] = 'OTHER'
        self.assertIn('not confirmed', self.app.ask('play it', mode='verify')['message'])
        provider.complete_structured.assert_not_called()

    def test_other_player_is_not_silently_replaced_with_music(self):
        self.app.provider = StagedProvider('play_media', 'Spotify', 'Last Christmas')
        result = self.app.ask('play Last Christmas in Spotify')
        self.assertIsNone(result['desktop_action'])
        self.assertIn('have not', result['message'])

    def test_general_goal_proposes_task_mode_not_just_first_app(self):
        goal = 'Open Safari, find a video about accessibility and play it'
        self.app.provider = StagedProvider('computer_task', 'Safari', goal)
        result = self.app.ask(goal)
        self.assertEqual(result['desktop_action']['type'], 'start_task')
        self.assertEqual(result['desktop_action']['goal'], goal)

    def test_teams_requests_with_remaining_work_enter_loop_before_opening(self):
        goal = 'open teams in a new safari window and look if I have any tasks to do'
        for operation in ('new_window', 'browser_search', 'browser_open'):
            self.app.provider = StagedProvider(operation, 'Safari', 'teams')
            self.app.provider.interpret_request.return_value['remaining_request'] = 'look if I have any tasks to do'
            result = self.app.ask(goal)
            self.assertEqual(result['desktop_action']['type'], 'start_task')
            self.assertEqual(result['desktop_action']['goal'], goal)
            self.assertNotIn('this part has not', result['message'])

    def test_app_shortcuts_with_followup_work_enter_the_general_loop(self):
        for app, goal, remainder in (
                ('Calculator', 'open the macos calculator app and in it sum 2 + 2', 'in it sum 2 + 2'),
                ('Notepad', 'open up notepad and in it write a summary of little prince', 'write a summary of little prince'),
                ('Preview', 'open Preview and rotate my image', 'rotate my image')):
            self.app.provider = StagedProvider('launch_app', app)
            self.app.provider.interpret_request.return_value['remaining_request'] = remainder
            result = self.app.ask(goal)
            self.assertEqual(result['desktop_action']['type'], 'start_task')
            self.assertEqual(result['desktop_action']['goal'], goal)

    def test_direct_click_requests_enter_the_observe_act_verify_loop(self):
        for operation in ('click_point', 'press_control'):
            self.app.provider = StagedProvider(operation, 'System Settings', 'Battery')
            goal = 'click on the Battery setting yourself'
            result = self.app.ask(goal)
            self.assertEqual(result['desktop_action']['type'], 'start_task')
            self.assertEqual(result['desktop_action']['goal'], goal)
            self.assertNotIn('Confirm below', result['message'])

    def test_old_partial_receipts_still_report_unexecuted_work(self):
        self.app.provider = StagedProvider('launch_app', 'Music')
        self.app.last_action_result = {'type': 'launch_app', 'bundle_id': 'com.apple.Music', 'label': 'Open Music',
                                      'remaining_request': 'Play Last Christmas'}
        result = self.app.ask('verify', mode='verify')
        self.assertIn('Still pending: Play Last Christmas', result['message'])
