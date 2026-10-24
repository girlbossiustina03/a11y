"""Library near-matches, artist splitting, Apple Music fallback, and clock answers."""
import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
import datetime
import unittest
from unittest.mock import Mock
from companion.arithmetic import clock_answer
from companion.computer_use import ComputerUse
from companion.desktop_context import DesktopContext
from companion.media import base_title, near_match, split_artist
from companion.request_plan import preserve_desktop_goal
from test_core import CompanionFixture
from test_desktop_context import FakeBridge
from test_request_plan import StagedProvider

NOT_FOUND = {'submitted': True, 'outcome': 'not_found', 'play_submitted': False, 'candidates': [
    {'name': 'Far Away (feat. A$AP Rocky)', 'artist': 'Yebba'}, {'name': 'Far Away From Home', 'artist': 'Groove Armada'}]}


class TitleTests(unittest.TestCase):
    def test_credits_and_version_tags_are_ignored_for_matching(self):
        self.assertEqual(base_title('Far Away (feat. A$AP Rocky)'), 'far away')
        self.assertEqual(base_title('Last Christmas - Remastered 2017'), 'last christmas')
        self.assertEqual(base_title('Hey Baby (Drop It to the Floor) [feat. T-Pain]'), 'hey baby drop it to the floor')
        self.assertEqual(near_match(NOT_FOUND, 'far away'), ('Far Away (feat. A$AP Rocky)', 'Yebba'))
        self.assertIsNone(near_match(NOT_FOUND, 'far'))
        self.assertIsNone(near_match(NOT_FOUND, 'far away', 'Someone Else'))

    def test_artist_is_split_from_the_title(self):
        self.assertEqual(split_artist('Last Christmas by wham'), ('Last Christmas', 'wham'))
        self.assertEqual(split_artist('Stand by Me', 'Ben E. King'), ('Stand by Me', 'Ben E. King'))


class MusicServiceTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()
        self.bridge.catalog = Mock(return_value=[{'name': 'Music', 'bundle_id': 'com.apple.Music'}])
        self.bridge.media_state = Mock(return_value={'player_state': 'paused', 'track': {'name': 'x', 'artist': 'y', 'id': '1'}})
        self.bridge.app_state = Mock(return_value={'running': True})
        self.app.desktop_context = DesktopContext(self.bridge, clock=lambda: 100)

    def test_far_away_plays_the_single_featured_version(self):
        played = {'submitted': True, 'outcome': 'play_submitted', 'play_submitted': True, 'requested_id': 'Y1',
                  'player_state': 'playing', 'track': {'name': 'Far Away (feat. A$AP Rocky)', 'artist': 'Yebba', 'id': 'Y1'}}
        self.bridge.application_action = Mock(side_effect=[NOT_FOUND, played])
        receipt = ComputerUse(self.app.desktop_context).execute_confirmed({'type': 'play_media', 'query': 'far away', 'artist': ''})
        retry = self.bridge.application_action.call_args_list[1].args[0]
        self.assertEqual((retry['query'], retry['artist']), ('Far Away (feat. A$AP Rocky)', 'Yebba'))
        self.assertTrue(receipt['native_result']['play_submitted'])

    def test_play_by_artist_is_split_and_not_reported_as_pending(self):
        provider = self.app.provider = StagedProvider('play_media', 'Music', 'Last Christmas')
        provider.interpret_request.return_value = {'operation': 'play_media', 'app_name': 'Music', 'target': 'Last Christmas',
                                                   'remaining_request': 'by wham'}
        result = self.app.ask('open up music and play last christmas by wham')
        self.assertEqual((result['desktop_action']['query'], result['desktop_action']['artist']), ('Last Christmas', 'wham'))
        self.assertNotIn('pending', result['message'])

    def test_full_title_is_tried_before_splitting_off_an_artist(self):
        found = {'submitted': True, 'outcome': 'play_submitted', 'play_submitted': True}
        self.bridge.application_action = Mock(return_value=found)
        ComputerUse(self.app.desktop_context).execute_confirmed({'type': 'play_media', 'query': 'Stand by Me', 'artist': ''})
        self.assertEqual(self.bridge.application_action.call_count, 1)  # "Stand by Me" stays one title
        self.bridge.application_action = Mock(side_effect=[dict(NOT_FOUND, candidates=[]), found])
        ComputerUse(self.app.desktop_context).execute_confirmed({'type': 'play_media', 'query': 'Last Christmas by Wham', 'artist': ''})
        retry = self.bridge.application_action.call_args_list[1].args[0]
        self.assertEqual((retry['query'], retry['artist']), ('Last Christmas', 'Wham'))

    def test_missing_song_opens_apple_music_search_and_starts_playing_the_top_result(self):
        self.bridge.application_action = Mock(side_effect=[dict(NOT_FOUND, candidates=[]), {'submitted': True}])
        self.app.last_action_result = ComputerUse(self.app.desktop_context).execute_confirmed(
            {'type': 'play_media', 'query': 'Last Christmas', 'artist': 'Wham'})
        result = self.app.ask('Check the action result.', mode='verify')
        search = self.bridge.application_action.call_args_list[1].args[0]
        self.assertEqual(search, {'type': 'music_search', 'query': 'Last Christmas Wham'})
        self.assertEqual(result['desktop_action']['type'], 'start_task')
        self.assertNotIn('confirm', result['desktop_action'])
        self.assertIn('opened Apple Music search', result['message'])


class ClockTests(CompanionFixture, unittest.TestCase):
    def test_time_and_date_come_from_the_clock(self):
        now = datetime.datetime(2026, 10, 23, 16, 5)
        self.assertEqual(clock_answer('what time is it?????', now), 'It’s 4:05 PM.')
        self.assertEqual(clock_answer("what's the date", now), 'Today is Friday, 23 October 2026.')
        self.assertIsNone(clock_answer('what is playing', now))

    def test_time_question_needs_no_model_and_never_reads_music(self):
        self.app.desktop_context = DesktopContext(FakeBridge(), clock=lambda: 100)
        self.app.provider = Mock()
        self.assertTrue(self.app.ask('what time is it')['message'].startswith('It’s '))
        self.app.provider.interpret_request.assert_not_called()

    def test_media_inspection_only_for_music_questions(self):
        plan = preserve_desktop_goal({'operation': 'inspect_media', 'app_name': '', 'target': ''}, 'what time is it')
        self.assertEqual(plan['operation'], 'answer')
        plan = preserve_desktop_goal({'operation': 'inspect_media', 'app_name': '', 'target': ''}, "what's playing")
        self.assertEqual(plan['operation'], 'inspect_media')


if __name__ == '__main__':
    unittest.main()
