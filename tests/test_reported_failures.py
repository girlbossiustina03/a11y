"""Regressions for failures reported from live use.

Model replies and native submission are doubled here. These tests prove the loop's
control flow and validation for each reported failure; they do not prove that a
live model makes the right choice on a real desktop."""
from copy import deepcopy
import json
import time
import unittest
from unittest.mock import Mock, patch
from companion.computer_task import ComputerTask, SYSTEM, TEXT_PASS, IMAGE_PASS
from companion.desktop_context import DesktopContext
from companion.request_plan import preserve_desktop_goal, highlight_only
from test_desktop_context import FakeBridge, SAMPLE


def region(text, x, y, width=.08, height=.03):
    return {'text': text, 'x': x, 'y': y, 'width': width, 'height': height}


CALCULATOR = {'status': 'available', 'platform': 'macOS', 'accessibility': 'granted',
    'app': {'name': 'Calculator', 'bundle_id': 'com.apple.calculator', 'pid': 7},
    'window': {'title': 'Calculator', 'bounds': {'x': 0, 'y': 0, 'width': 1000, 'height': 700}},
    'available_apps': [{'name': 'Calculator', 'bundle_id': 'com.apple.calculator'}],
    'installed_apps': [{'name': 'Calculator', 'bundle_id': 'com.apple.calculator'}],
    'controls': [{'id': 'control-%d' % index, 'label': label, 'role': 'AXButton', 'enabled': True,
                  'bounds': {'x': 100+index*40, 'y': 300, 'width': 36, 'height': 36}}
                 for index, label in enumerate(['2', 'Add', 'Equals', 'Clear'])]}
TEAMS_REGIONS = [region('Activity', .02, .2), region('Chat', .02, .3), region('Teams', .02, .4),
                 region('Post in channel', .5, .9, .12), region('Assignments', .02, .5)]


class Harness(unittest.TestCase):
    snapshot = CALCULATOR
    regions = []

    def setUp(self):
        bridge = FakeBridge()
        bridge.value = deepcopy(self.snapshot)
        self.desktop = DesktopContext(bridge, clock=lambda: 100)
        self.desktop.enabled = True
        self.vision = Mock(enabled=True, generation=0)
        self.vision.capture.side_effect = lambda *args, **kwargs: {
            'image_data': 'data:image/png;base64,synthetic', 'display_id': 7, 'text_regions': deepcopy(self.regions),
            'screen': {'x': 0, 'y': 0, 'width': 1000, 'height': 700}, 'captured_monotonic': time.monotonic()}
        self.vision.click_guard.return_value = {'region_hash': 'synthetic'}
        self.provider = Mock()

    def propose(self, task):
        return task.propose(self.desktop, self.vision, self.provider, {'x': 0, 'y': 0})


class StopsAfterLaunchTests(Harness):
    def test_calculator_arithmetic_continues_after_a_premature_done(self):
        task = ComputerTask('Open Calculator and compute (2+2)*3', automatic=True, goal_mode='inspect')
        task.record({'type': 'launch_app', 'label': 'Open Calculator', 'status': 'submitted'})
        self.provider.complete_structured.side_effect = [
            {'status': 'done', 'message': 'Calculator is open.', 'risk': 'navigation', 'action': None},
            {'status': 'action', 'message': 'Press 2.', 'risk': 'navigation',
             'action': {'type': 'press_control', 'control_id': 'control-0'}}]
        step = self.propose(task)
        self.assertEqual(step['status'], 'action')
        self.assertEqual(step['action']['label'], '2')
        self.assertFalse(step['review'])
        recheck = self.provider.complete_structured.call_args_list[1]
        self.assertIn('only opening', recheck.args[1][-1]['content'])
        self.assertIsNotNone(recheck.kwargs['image_data'])

    def test_launch_uses_catalog_names_in_the_prompt_and_resolves_the_id(self):
        self.desktop.bridge.catalog = Mock(return_value=CALCULATOR['installed_apps'])
        task = ComputerTask('Open Calculator and compute (2+2)*3', automatic=True, goal_mode='inspect')
        self.provider.complete_structured.return_value = {'status': 'action', 'message': 'Open Calculator.', 'risk': 'navigation',
            'action': {'type': 'launch_app', 'bundle_id': 'Calculator'}}
        step = self.propose(task)
        self.assertEqual(step['action']['bundle_id'], 'com.apple.calculator')
        self.assertFalse(step['review'])
        prompt = self.provider.complete_structured.call_args.args[1][0]['content']
        self.assertIn('"installed_apps":["Calculator"]', prompt)
        self.provider.complete_structured.return_value = {'status': 'action', 'message': 'Open it.', 'risk': 'navigation',
            'action': {'type': 'launch_app', 'bundle_id': 'Nonexistent Tool'}}
        with self.assertRaises(Exception):
            self.propose(ComputerTask('Open a tool', goal_mode='inspect'))

    def test_done_after_real_work_is_not_second_guessed(self):
        task = ComputerTask('Open Calculator and compute (2+2)*3', automatic=True, goal_mode='inspect')
        for kind in ('launch_app', 'press_control', 'press_control', 'press_control', 'press_control'):
            task.record({'type': kind, 'status': 'submitted'})
        self.provider.complete_structured.return_value = {'status': 'done', 'message': 'The display shows 4.', 'risk': 'navigation', 'action': None}
        self.assertEqual(self.propose(task)['status'], 'done')
        self.assertEqual(self.provider.complete_structured.call_count, 1)

    def test_notepad_drafting_continues_to_the_editor_after_launch(self):
        self.desktop.bridge.value['controls'] = []
        task = ComputerTask('Open Notepad and write a summary of my day', automatic=True, goal_mode='draft')
        task.record({'type': 'launch_app', 'label': 'Open TextEdit', 'status': 'submitted'})
        self.provider.complete_structured.side_effect = [
            {'status': 'done', 'message': 'TextEdit opened.', 'risk': 'navigation', 'action': None},
            {'status': 'action', 'message': 'Choose New Document.', 'risk': 'navigation',
             'action': {'type': 'click_point', 'x': .3, 'y': .8, 'label': 'New Document'}}]
        step = self.propose(task)
        self.assertEqual(step['action']['type'], 'click_point')
        self.assertIn('capture_guard', step['action'])


class TeamsInspectionTests(Harness):
    regions = TEAMS_REGIONS

    def test_post_in_channel_under_a_model_point_is_rejected_for_inspection(self):
        self.desktop.bridge.value['controls'] = []
        task = ComputerTask('Open Teams and check whether I have tasks', automatic=True, goal_mode='inspect')
        self.provider.complete_structured.side_effect = [
            # The label claims Activity, but the point lies on OCR text "Post in channel".
            {'status': 'action', 'message': 'Check activity.', 'risk': 'navigation',
             'action': {'type': 'click_point', 'x': .55, 'y': .91, 'label': 'Activity'}},
            {'status': 'action', 'message': 'Open Activity.', 'risk': 'navigation',
             'action': {'type': 'click_point', 'x': .05, 'y': .21, 'label': 'Activity'}}]
        step = self.propose(task)
        # The click now snaps onto the OCR text "Activity" instead of being rejected and retried.
        self.assertEqual((step['action']['x'], step['action']['y']), (.06, .215))
        self.assertEqual(self.provider.complete_structured.call_count, 1)

    def test_a_point_on_post_in_channel_without_a_matching_label_is_still_rejected(self):
        self.desktop.bridge.value['controls'] = []
        task = ComputerTask('Open Teams and check whether I have tasks', automatic=True, goal_mode='inspect')
        self.provider.complete_structured.side_effect = [
            {'status': 'action', 'message': 'Check the feed.', 'risk': 'navigation',
             'action': {'type': 'click_point', 'x': .55, 'y': .91, 'label': 'Feed'}},
            {'status': 'action', 'message': 'Open Activity.', 'risk': 'navigation',
             'action': {'type': 'click_point', 'x': .05, 'y': .21, 'label': 'Activity'}}]
        self.propose(task)
        self.assertIn('inspection-only', self.provider.complete_structured.call_args.args[1][-1]['content'])

    @patch.dict('os.environ', {'A11Y_TEXT_PASS': '1'})  # the text pass is opt-in
    def test_text_and_image_passes_share_the_cacheable_prefix(self):
        task = ComputerTask('Open Teams and check whether I have tasks', automatic=True, goal_mode='inspect')
        self.provider.complete_structured.side_effect = [
            {'status': 'needs_vision', 'message': 'Need the icon.', 'risk': 'navigation', 'action': None},
            {'status': 'action', 'message': 'Open Activity.', 'risk': 'navigation',
             'action': {'type': 'click_point', 'x': .05, 'y': .21, 'label': 'Activity'}}]
        self.propose(task)
        text, image = self.provider.complete_structured.call_args_list
        self.assertEqual(text.args[0], SYSTEM)
        self.assertEqual(image.args[0], SYSTEM)
        self.assertEqual(text.args[1][:-1], image.args[1][:-1])
        self.assertIn(TEXT_PASS, text.args[1][-1]['content'])
        self.assertIn(IMAGE_PASS, image.args[1][-1]['content'])
        self.assertIsNone(text.kwargs['image_data'])
        self.assertIs(text.kwargs['cancel'], task.cancelled)

    def test_scope_from_the_intent_call_avoids_a_classifier_call(self):
        class Provider:
            classified = 0
            def classify_task_goal(self, goal):
                Provider.classified += 1
                return 'inspect'
            def complete_structured(self, *args, **kwargs):
                return {'status': 'done', 'message': 'Assignments shows 0 tasks.', 'risk': 'navigation', 'action': None}
        task = ComputerTask('check tasks', goal_mode='inspect')
        task.receipts.append({'type': 'press_control'})
        task.propose(self.desktop, self.vision, Provider(), {'x': 0, 'y': 0})
        self.assertEqual(Provider.classified, 0)
        legacy = ComputerTask('check tasks')
        legacy.receipts.append({'type': 'press_control'})
        legacy.propose(self.desktop, self.vision, Provider(), {'x': 0, 'y': 0})
        self.assertEqual(Provider.classified, 1)

    @patch.dict('os.environ', {'A11Y_TEXT_PASS': '1'})  # the text pass is opt-in
    def test_step_timing_is_recorded_without_screen_content(self):
        task = ComputerTask('check tasks', goal_mode='inspect')
        task.receipts.append({'type': 'press_control'})
        self.provider.complete_structured.return_value = {'status': 'done', 'message': 'Private Teams text', 'risk': 'navigation', 'action': None}
        self.propose(task)
        stage = task.timings[-1]
        self.assertEqual(stage['text_regions'], 5)
        self.assertEqual([call['mode'] for call in stage['model']], ['text'])
        self.assertNotIn('Private', repr(stage))


class StopDuringInferenceTests(Harness):
    def test_stop_reaches_the_in_flight_model_request_and_no_action_is_proposed(self):
        import threading
        from companion.ollama import RequestCancelled
        task = ComputerTask('Open Teams and check tasks', automatic=True, goal_mode='inspect')
        class SlowProvider:
            def complete_structured(self, *args, cancel=None, **kwargs):
                # Stands in for the streaming transport, which closes its socket on cancel.
                if cancel.wait(10):
                    raise RequestCancelled()
                return {'status': 'action', 'message': 'late', 'risk': 'navigation',
                        'action': {'type': 'scroll', 'direction': 'down'}}
        outcome = []
        def run():
            try:
                outcome.append(task.propose(self.desktop, self.vision, SlowProvider(), {'x': 0, 'y': 0}))
            except RuntimeError as error:
                outcome.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        time.sleep(0.1)
        started = time.monotonic()
        task.stop()
        worker.join(2)
        self.assertLess(time.monotonic()-started, 1)
        self.assertIsInstance(outcome[0], RequestCancelled)
        self.assertIsNone(task.pending)


class LiveTeamsLogTests(Harness):
    """From a live macOS log: 10 slow steps, each text pass then image pass, six
    identical Activity clicks, and a separate Safari launch before navigating."""
    regions = TEAMS_REGIONS
    activity = {'status': 'action', 'message': 'Activity has a badge.', 'risk': 'navigation',
                'action': {'type': 'click_point', 'x': .05, 'y': .21, 'label': 'Activity section with notification badge'}}

    def setUp(self):
        super().setUp()
        self.desktop.bridge.value['controls'] = []

    @patch.dict('os.environ', {'A11Y_TEXT_PASS': '1'})  # the text pass is opt-in
    def test_text_pass_is_skipped_for_an_app_after_it_failed_once(self):
        task = ComputerTask('Open Teams and check tasks', automatic=True, goal_mode='inspect')
        need = {'status': 'needs_vision', 'message': 'Need pixels.', 'risk': 'navigation', 'action': None}
        self.provider.complete_structured.side_effect = [need, self.activity, self.activity]
        self.propose(task)
        task.record({'type': 'click_point', 'label': 'Something else', 'status': 'submitted'})
        self.propose(task)
        modes = [call.kwargs['image_data'] is not None for call in self.provider.complete_structured.call_args_list]
        self.assertEqual(modes, [False, True, True])

    def test_third_identical_click_is_corrected_and_then_stopped(self):
        task = ComputerTask('Open Teams and check tasks', automatic=True, goal_mode='inspect')
        for _ in range(2):
            task.record({'type': 'click_point', 'label': 'Activity section with notification badge', 'status': 'submitted'})
        done = {'status': 'done', 'message': 'Activity lists 2 assignments due Friday.', 'risk': 'navigation', 'action': None}
        self.provider.complete_structured.side_effect = [self.activity, done]
        self.assertEqual(self.propose(task)['status'], 'done')
        self.assertIn('already ran twice', self.provider.complete_structured.call_args.args[1][-1]['content'])
        self.provider.complete_structured.side_effect = [self.activity, self.activity]
        step = self.propose(task)
        self.assertEqual(step['status'], 'needs_user')
        self.assertIsNone(task.pending)

    def test_digit_presses_may_repeat(self):
        task = ComputerTask('compute 22+1', goal_mode='inspect')
        for _ in range(2):
            task.record({'type': 'press_control', 'label': '2', 'status': 'submitted'})
        self.assertEqual(task.repeats({'type': 'press_control', 'label': '2'}), 0)

    def test_launching_the_browser_for_a_known_web_app_becomes_the_navigation(self):
        safari = [{'name': 'Safari', 'bundle_id': 'com.apple.Safari'}]
        self.desktop.bridge.value['installed_apps'] = safari
        self.desktop.bridge.catalog = Mock(return_value=safari)
        task = ComputerTask('open teams in a new safari window and check tasks', automatic=True, goal_mode='inspect')
        self.provider.complete_structured.return_value = {'status': 'action', 'message': 'Launch Safari.', 'risk': 'navigation',
                                                         'action': {'type': 'launch_app', 'bundle_id': 'Safari'}}
        step = self.propose(task)
        self.assertEqual((step['action']['type'], step['action']['url'], step['action']['browser_mode']),
                         ('browse_url', 'https://teams.microsoft.com', 'window'))
        self.assertFalse(step['review'])
        self.assertEqual(self.provider.complete_structured.call_count, 1)

    def test_browser_is_not_launched_as_a_separate_step_for_other_sites(self):
        safari = [{'name': 'Safari', 'bundle_id': 'com.apple.Safari'}]
        self.desktop.bridge.value['installed_apps'] = safari
        self.desktop.bridge.catalog = Mock(return_value=safari)
        task = ComputerTask('open the company portal in safari and check tasks', automatic=True, goal_mode='inspect')
        browse = {'status': 'action', 'message': 'Open portal.', 'risk': 'navigation',
                  'action': {'type': 'browse_url', 'bundle_id': 'com.apple.Safari', 'url': 'https://portal.example.com/',
                             'browser_mode': 'default', 'label': 'Open portal'}}
        self.provider.complete_structured.side_effect = [
            {'status': 'action', 'message': 'Launch Safari.', 'risk': 'navigation', 'action': {'type': 'launch_app', 'bundle_id': 'Safari'}}, browse]
        step = self.propose(task)
        self.assertEqual(step['action']['type'], 'browse_url')
        self.assertIn('browse_url opens the browser itself', self.provider.complete_structured.call_args.args[1][-1]['content'])


class PendingTextTests(unittest.TestCase):
    def test_conversation_is_never_reported_as_pending_work(self):
        plan = preserve_desktop_goal({'operation': 'answer', 'app_name': '', 'target': '', 'remaining_request': 'yo wyd'}, 'yo wyd')
        self.assertEqual(plan['remaining_request'], '')
        plan = preserve_desktop_goal({'operation': 'launch_app', 'app_name': 'Teams', 'target': '', 'remaining_request': 'check my tasks'},
                                     'open teams and check my tasks')
        self.assertEqual(plan['operation'], 'computer_task')


class ThinEvidenceTests(Harness):
    regions = [region('OK', .5, .5)]

    def test_one_ocr_fragment_without_controls_goes_straight_to_the_image(self):
        self.desktop.bridge.value['controls'] = []
        task = ComputerTask('Click the gear icon', automatic=True, goal_mode='inspect')
        self.provider.complete_structured.return_value = {'status': 'action', 'message': 'Click gear.', 'risk': 'navigation',
            'action': {'type': 'click_point', 'x': .9, 'y': .1, 'label': 'Gear'}}
        self.propose(task)
        self.assertEqual(self.provider.complete_structured.call_count, 1)
        self.assertIsNotNone(self.provider.complete_structured.call_args.kwargs['image_data'])


class HighlightOnlyTests(unittest.TestCase):
    def test_mark_or_show_where_never_becomes_an_activating_operation(self):
        for request, operation in [("Mark where the left terminal's close button is", 'close_window'),
                                   ('Show me where the Send button is', 'click_point'),
                                   ('where is the Post in channel button?', 'computer_task'),
                                   ('Highlight the Desktop tools section', 'press_control')]:
            plan = preserve_desktop_goal({'operation': operation, 'app_name': '', 'target': 'x'}, request)
            self.assertEqual(plan['operation'], 'highlight', request)

    def test_explicit_activation_after_locating_is_not_downgraded(self):
        self.assertFalse(highlight_only('Show me where Send is and click it'))
        plan = preserve_desktop_goal({'operation': 'click_point', 'app_name': '', 'target': 'x'}, 'Find the Help link and then click it')
        self.assertEqual(plan['operation'], 'computer_task')
        plan = preserve_desktop_goal({'operation': 'launch_app', 'app_name': 'Calculator', 'target': '',
                                      'remaining_request': 'sum 2+2', 'goal_mode': 'inspect'}, 'Open Calculator and compute (2+2)*3')
        self.assertEqual((plan['operation'], plan['goal_mode']), ('computer_task', 'inspect'))


if __name__ == '__main__':
    unittest.main()


class ClickGroundingTests(unittest.TestCase):
    """Teams 'click Activity' missed twice, then failed on a 0–1000 coordinate."""
    REGIONS = [{'text': 'Activity', 'x': .010, 'y': .200, 'width': .030, 'height': .015},
               {'text': 'Chat', 'x': .015, 'y': .260, 'width': .020, 'height': .015},
               {'text': 'Turn on desktop notifications', 'x': .40, 'y': .05, 'width': .20, 'height': .02},
               {'text': 'Activity', 'x': .30, 'y': .10, 'width': .05, 'height': .02}]

    def test_click_snaps_to_the_named_ocr_text_nearest_the_models_guess(self):
        from companion.computer_task import snap_click
        snapped = snap_click({'type': 'click_point', 'x': .05, 'y': .23, 'label': 'Activity icon'}, self.REGIONS)
        self.assertEqual((snapped['x'], snapped['y']), (.025, .2075))
        header = snap_click({'type': 'click_point', 'x': .33, 'y': .12, 'label': 'Activity'}, self.REGIONS)
        self.assertEqual((header['x'], header['y']), (.325, .11))

    def test_unmatched_label_keeps_the_models_point(self):
        from companion.computer_task import snap_click
        action = {'type': 'click_point', 'x': .5, 'y': .5, 'label': 'Calendar icon'}
        self.assertEqual(snap_click(action, self.REGIONS), action)

    def test_accessible_control_bounds_are_used_too(self):
        from companion.computer_task import snap_click
        snapped = snap_click({'type': 'click_point', 'x': .5, 'y': .5, 'label': 'Calls button'}, [],
                             [{'label': 'Calls', 'bounds': {'x': 100, 'y': 300, 'width': 40, 'height': 40}}],
                             {'x': 0, 'y': 0, 'width': 1000, 'height': 1000})
        self.assertEqual((snapped['x'], snapped['y']), (.12, .32))

    def test_qwen_grid_coordinates_are_accepted(self):
        from companion.computer_task import normalize_click
        self.assertEqual(normalize_click({'x': 25, 'y': 207.5})['x'], .025)
        self.assertEqual(normalize_click({'x': .5, 'y': 1.0}), {'x': .5, 'y': .999})
        self.assertEqual(normalize_click({'x': .5, 'y': .4}), {'x': .5, 'y': .4})
        self.assertEqual(normalize_click({'x': 2000, 'y': 5})['x'], 2000)  # still rejected later
        self.assertEqual(normalize_click({'x': 500, 'y': .3})['x'], 500)

    def test_inspect_goal_can_click_activity_next_to_a_notifications_banner(self):
        from companion.computer_task import validate_step
        desktop = DesktopContext(FakeBridge())
        step = validate_step({'status': 'action', 'message': 'Opening Activity.', 'risk': 'navigation',
                              'action': {'type': 'click_point', 'x': 480, 'y': 62, 'label': 'Activity'}},
                             desktop, {'controls': []}, goal_mode='inspect', text_regions=self.REGIONS)
        self.assertEqual((step['action']['x'], step['action']['y']), (.325, .11))


class NotificationViewTests(unittest.TestCase):
    """Reported: 'any new notifications on Teams?' read the current feed instead of opening Activity."""
    REGIONS = [{'text': 'Post in channel', 'x': .40, 'y': .90, 'width': .1, 'height': .02},
               {'text': 'Activity', 'x': .30, 'y': .10, 'width': .05, 'height': .02},
               {'text': 'Activity', 'x': .010, 'y': .200, 'width': .030, 'height': .015}]

    def test_notification_goal_opens_the_rail_activity_view_first_in_code(self):
        vision = Mock()
        vision.click_guard.return_value = {'guard': True}
        desktop = DesktopContext(FakeBridge())
        task = ComputerTask('are there any new notifications on the teams page', automatic=True, goal_mode='inspect')
        step = task.view_step(desktop, {'controls': []}, self.REGIONS, {'screen': {'x': 0, 'y': 0, 'width': 1000, 'height': 1000}}, 'img', vision)
        self.assertEqual(step['action']['type'], 'click_point')
        self.assertEqual((step['action']['x'], step['action']['y']), (.025, .2075))  # the left rail, not the page header
        # A click refused before it ran (the screen changed) is proposed again (live: the retry
        # went to the model, which invented control IDs); once it ran, never again.
        self.assertEqual(task.view_step(desktop, {'controls': []}, self.REGIONS, {}, 'img', vision)['action']['label'], 'Activity')
        task.record({'type': 'click_point', 'label': 'Activity', 'status': 'submitted'})
        self.assertIsNone(task.view_step(desktop, {'controls': []}, self.REGIONS, {}, 'img', vision))
        other = ComputerTask('read my last email', automatic=True, goal_mode='inspect')
        self.assertIsNone(other.view_step(desktop, {'controls': []}, self.REGIONS, {}, 'img', vision))


@unittest.skipUnless(__import__('sys').platform == 'darwin', 'Qt raises activate the app only on macOS')
class FocusTests(unittest.TestCase):
    """Live evaluation: after "Microsoft Teams." opened Teams in Safari, A11y itself was the
    frontmost app. On macOS Qt's raise_() of the mascot activated the whole process, taking
    keyboard focus from the app being worked in after every action."""

    def test_launcher_keeps_raising_the_mascot_from_activating_a11y(self):
        import os
        import sys
        import tempfile
        import a11y_desktop
        seen = {}

        class Stop(Exception):
            pass

        def application(*args):
            seen['raise_process'] = os.environ.get('QT_MAC_SET_RAISE_PROCESS')
            raise Stop()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'A11Y_DATA_DIR': directory}), \
                patch.object(sys, 'argv', ['a11y_desktop.py']), patch.object(sys, 'excepthook', sys.excepthook), \
                patch('PyQt6.QtWidgets.QApplication', application), patch('companion.instance.DesktopInstance'):
            os.environ.pop('QT_MAC_SET_RAISE_PROCESS', None)
            with self.assertRaises(Stop):
                a11y_desktop.main()
        self.assertEqual(seen['raise_process'], '0')


class LiveRoutingTests(unittest.TestCase):
    """Live evaluation (scripts/live_eval.py) on qwen3:4b-instruct, wording as typed."""

    def setUp(self):
        import tempfile
        from companion.models import Identity
        from companion.service import Companion
        from companion.storage import Store
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        bridge = FakeBridge()
        bridge.catalog = Mock(return_value=[{'name': 'Safari', 'bundle_id': 'com.apple.Safari'},
                                            {'name': 'Photos', 'bundle_id': 'com.apple.Photos'}])
        bridge.calendar_events = Mock(return_value=[])
        bridge.app_state = Mock(return_value={'running': False})
        self.provider = Mock()
        self.app = Companion(Store(self.temp.name), Identity('company', 'employee'), self.provider)
        self.app.desktop_context = DesktopContext(bridge, clock=lambda: 100)
        for patcher in (patch('companion.mac_apps.available', return_value=True), patch('companion.mail_reader.available', return_value=True),
                        patch('companion.mail_reader.newest', side_effect=AssertionError('Mail must not be read'))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def route(self, operation, target='', **extra):
        self.provider.interpret_request.return_value = dict({'operation': operation, 'app_name': '', 'target': target, 'reply': '',
                                                             'browser_mode': 'default', 'remaining_request': ''}, **extra)

    def test_notifications_on_teams_are_looked_for_in_teams_not_calendar_or_mail(self):
        # Routed to read_calendar three times in a row, and to read_mail in another session.
        for operation, target in (('read_calendar', 'today'), ('read_mail', ''), ('read_mail', '1')):
            self.route(operation, target)
            response = self.app.ask('check if I have new notifications on Teams')
            self.assertEqual(response['desktop_action']['type'], 'start_task')
            self.assertEqual(response['desktop_action']['goal'], 'check if I have new notifications on Teams')
        self.app.desktop_context.bridge.calendar_events.assert_not_called()
        self.route('read_mail', '1')
        self.assertEqual(self.app.ask('any new messages in Slack?')['desktop_action']['type'], 'start_task')

    def test_built_in_reads_still_answer_when_they_name_their_own_app(self):
        self.route('read_calendar', 'tomorrow')
        response = self.app.ask("what's on my calendar tomorrow")
        self.assertTrue(response['full_text'])
        self.app.desktop_context.bridge.calendar_events.assert_called_once()
        self.route('read_notes', 'trip on Photos')
        with patch('companion.mac_apps.read_notes', return_value='Your note.') as notes:
            self.assertEqual(self.app.ask('read my note trip on Photos')['message'], 'Your note.')
        notes.assert_called_once()

    def test_earlier_requests_are_sent_only_to_resolve_a_reference(self):
        # After two calendar questions the same model read the calendar for a Teams question.
        for request in ('read my second last email', "what's on my calendar tomorrow"):
            self.app.desktop_session.append({'role': 'user', 'content': request, 'source_documents': []})
        self.route('computer_task', 'check if I have new notifications on Teams')
        self.app.prepare_request('check if I have new notifications on Teams')
        self.assertEqual(self.provider.interpret_request.call_args.args[1], [])
        self.app.prepare_request('do that again')
        self.assertEqual(self.provider.interpret_request.call_args.args[1], ['read my second last email', "what's on my calendar tomorrow"])

    def test_a_reminder_keeps_its_title_when_the_time_has_its_own_field(self):
        # Packed as "title | time" the model wrote only "6 PM" and the reminder lost its title.
        self.route('add_reminder', 'call mom', when='2026-10-23T18:00')
        action = self.app.ask('remind me to call mom at 6')['desktop_action']
        self.assertEqual((action['kind'], action['title']), ('add_reminder', 'call mom'))
        self.assertIn('18:00', action['label'])
        self.route('add_event', 'Dentist | 30', when='2026-10-24T15:00')
        action = self.app.ask('dentist tomorrow at 3 for half an hour')['desktop_action']
        self.assertEqual(action['end']-action['start'], 30*60)

    def test_youtube_search_is_one_navigation_without_a_model(self):
        # The task opened YouTube, then clicked Safari's New Tab and address bar (live).
        response = self.app.ask('open youtube and search for lo-fi')
        self.assertEqual(response['desktop_action']['type'], 'browse_url')
        self.assertEqual(response['desktop_action']['url'], 'https://www.youtube.com/results?search_query=lo-fi')
        self.provider.interpret_request.assert_not_called()
        plan = self.app.prepare_request('open youtube and search for rock and roll')
        self.assertEqual(plan['operation'], 'computer_task')  # unclear where the query ends: the task decides


class DeterministicSamplingTests(unittest.TestCase):
    """At temperature 0.2 the same request was routed three different ways in one session."""

    def test_every_local_model_call_is_greedy_with_a_fixed_seed(self):
        from companion.ollama import OllamaProvider
        from companion.provider import AIConfig
        provider = OllamaProvider(AIConfig(base_url='http://127.0.0.1:11434', model='m', vision_model='', timeout=5))
        provider.metadata['m'] = {'capabilities': ['completion']}
        sent = []
        def request(path, body=None, **kwargs):
            sent.append(json.loads(json.dumps(body)))
            return {'done': True, 'done_reason': 'stop', 'message': {'content': '{"a": 1}'}}
        provider.request = request
        provider.complete('system', [{'role': 'user', 'content': 'x'}], response_schema={'type': 'object'})
        provider.complete('system', [{'role': 'user', 'content': 'x'}], response_schema={'type': 'object'})
        self.assertEqual([(body['options']['temperature'], body['options']['seed']) for body in sent], [(0, 7), (0, 7)])


class CodeClickTests(Harness):
    """"click on Chat" in Teams took five model calls and ~20 s for one click (live)."""
    snapshot = dict(CALCULATOR, controls=[], app={'name': 'Safari', 'bundle_id': 'com.apple.Safari', 'pid': 7})
    regions = TEAMS_REGIONS

    def test_one_labelled_target_is_clicked_in_code_and_the_task_ends_after_it(self):
        task = ComputerTask('click on Chat', automatic=True)
        step = self.propose(task)
        self.provider.complete_structured.assert_not_called()
        self.provider.classify_task_goal.assert_not_called()
        self.assertEqual((step['action']['type'], step['action']['label']), ('click_point', 'Chat'))
        self.assertEqual((step['action']['x'], step['action']['y']), (.06, .315))
        self.assertFalse(step['review'])
        task.record({'type': 'click_point', 'label': 'Chat', 'status': 'submitted'})
        self.regions = TEAMS_REGIONS+[region('Recent chats', .2, .1)]
        self.assertEqual(self.propose(task), {'status': 'done', 'action': None, 'message': 'Clicked Chat.'})
        self.provider.complete_structured.assert_not_called()

    def test_a_click_refused_before_it_ran_is_proposed_again(self):
        task = ComputerTask('click on Chat', automatic=True)
        self.propose(task)
        task.pending = None  # the guard refused it: no receipt
        step = self.propose(task)
        self.assertEqual(step['action']['label'], 'Chat')
        self.provider.complete_structured.assert_not_called()

    def test_an_unchanged_screen_after_the_click_is_reported(self):
        task = ComputerTask('click on Chat', automatic=True)
        self.propose(task)
        task.record({'type': 'click_point', 'label': 'Chat', 'status': 'submitted'})
        with patch('companion.computer_task.time.sleep'):
            result = self.propose(task)
        self.assertEqual(result['status'], 'needs_user')
        self.assertIn('nothing on the screen changed', result['message'])

    def test_an_accessible_control_is_pressed_and_sensitive_labels_still_need_review(self):
        self.desktop.bridge.value['controls'] = [{'id': 'control-0', 'label': 'Send', 'role': 'AXButton', 'enabled': True,
                                                  'bounds': {'x': 900, 'y': 600, 'width': 60, 'height': 30}}]
        step = self.propose(ComputerTask('click Send', automatic=True))
        self.assertEqual(step['action']['type'], 'press_control')
        self.assertTrue(step['review'])

    def test_several_or_no_matches_are_left_to_the_model(self):
        self.regions = TEAMS_REGIONS+[region('Chat', .5, .1)]
        self.provider.classify_task_goal = None
        self.provider.complete_structured.return_value = {'status': 'needs_user', 'message': 'Which Chat?', 'risk': 'navigation', 'action': None}
        self.propose(ComputerTask('click on Chat', automatic=True, goal_mode='inspect'))
        self.provider.complete_structured.assert_called()
        self.provider.complete_structured.reset_mock()
        self.propose(ComputerTask('click the first email in Mail', automatic=True, goal_mode='inspect'))
        self.provider.complete_structured.assert_called()


class ListRowTests(Harness):
    """"click the first email in Mail": the model clicked the window title "All Inboxes – 17.865
    messages" twice, then said done (live, three runs out of three)."""
    snapshot = dict(CALCULATOR, controls=[], app={'name': 'Mail', 'bundle_id': 'com.apple.mail', 'pid': 7},
                    window={'title': 'All Inboxes', 'bounds': {'x': 0, 'y': 0, 'width': 1000, 'height': 700}},
                    lists=[{'role': 'AXOutline', 'label': 'mailboxes', 'bounds': {'x': 0, 'y': 80, 'width': 200, 'height': 600},
                            'rows': [{'x': 0, 'y': 85 + 24*i, 'width': 200, 'height': 24} for i in range(5)]},
                           {'role': 'AXTable', 'label': 'messages', 'bounds': {'x': 200, 'y': 80, 'width': 300, 'height': 99999},
                            'rows': [{'x': 200, 'y': 90 + 80*i, 'width': 300, 'height': 80} for i in range(12)]}])
    regions = [region('All Inboxes – 17.865 messages', .3, .02, .3)]

    def test_the_first_row_of_the_message_list_is_clicked_in_code(self):
        task = ComputerTask('click the first email in Mail', automatic=True)
        step = self.propose(task)
        self.provider.complete_structured.assert_not_called()
        self.assertEqual(step['action']['type'], 'click_point')
        self.assertEqual((step['action']['x'], step['action']['y']), (.35, round(130/700, 4)))  # the messages table, row 1
        self.assertEqual(step['action']['label'], 'First email')
        task.record({'type': 'click_point', 'label': 'First email', 'status': 'submitted'})
        self.assertEqual(self.propose(task), {'status': 'done', 'action': None, 'message': 'Clicked the first email.'})

    def test_rows_outside_the_window_and_other_apps_are_not_used(self):
        task = ComputerTask('double-click the tenth message', automatic=True, goal_mode='inspect')
        self.desktop.bridge.value['window']['bounds']['height'] = 500  # rows 6+ are below the window
        self.provider.complete_structured.return_value = {'status': 'needs_user', 'message': 'Not visible.', 'risk': 'navigation', 'action': None}
        self.propose(task)
        self.provider.complete_structured.assert_called()
        self.provider.complete_structured.reset_mock()
        self.desktop.bridge.value['app'] = {'name': 'Safari', 'bundle_id': 'com.apple.Safari', 'pid': 7}
        self.propose(ComputerTask('click the first email in Mail', automatic=True, goal_mode='inspect'))
        self.provider.complete_structured.assert_called()  # Mail is not in front: the model opens it first

    def test_list_rows_stay_out_of_model_prompts(self):
        from companion.computer_task import compact_desktop
        self.assertNotIn('lists', compact_desktop(self.snapshot))


class ReviewFindingTests(LiveRoutingTests):
    """Edge cases of the live-evaluation fixes, found in review."""

    def test_a_past_reminder_time_moves_to_the_next_occurrence(self):
        # At 18:59 "remind me to call mom at 6" was proposed for today 18:00 (live).
        from datetime import datetime
        from companion.service import upcoming
        now = datetime(2026, 10, 23, 18, 59)
        self.assertEqual(upcoming('2026-10-23T18:00', 'call mom at 6', now), '2026-10-24T18:00')
        self.assertEqual(upcoming('2026-10-23T06:00', 'call mom at 6', now), '2026-10-24T06:00')
        self.assertEqual(upcoming('2026-10-23T09:00', 'call mom at 9', datetime(2026, 10, 23, 10, 0)), '2026-10-23T21:00')
        self.assertEqual(upcoming('2026-10-23T09:00', 'call mom at 9am', datetime(2026, 10, 23, 10, 0)), '2026-10-24T09:00')
        self.assertEqual(upcoming('2026-10-24T15:00', 'dentist tomorrow at 3', now), '2026-10-24T15:00')
        self.assertEqual(upcoming('2026-10-23T09:00', 'dentist today at 9am', now), '2026-10-23T09:00')  # as said
        self.assertEqual(upcoming('2026-10-22T18:59', 'call mom at 18:59', now), '2026-10-22T18:59')  # no crash at one day

    def test_follow_ups_without_a_pronoun_still_get_the_earlier_request(self):
        self.app.desktop_session.append({'role': 'user', 'content': "what's on my calendar today", 'source_documents': []})
        self.route('read_calendar', 'tomorrow')
        self.app.prepare_request('what about tomorrow?')
        self.assertEqual(self.provider.interpret_request.call_args.args[1], ["what's on my calendar today"])

    def test_vendor_names_and_the_mail_shortcut_respect_another_named_app(self):
        self.app.desktop_context.bridge.catalog.return_value.append({'name': 'Microsoft To Do', 'bundle_id': 'com.microsoft.to-do-mac'})
        self.route('read_reminders', 'all')
        self.assertEqual(self.app.ask('read my tasks in To Do')['desktop_action']['type'], 'start_task')
        self.route('read_mail', '1')
        self.assertEqual(self.app.ask('In Outlook, read my latest email')['desktop_action']['type'], 'start_task')

    def test_a_site_search_with_more_after_a_comma_is_not_one_query(self):
        plan = self.app.prepare_request('open youtube and search for cats, click the first result')
        self.assertEqual(plan['operation'], 'computer_task')


class CodeClickReviewTests(Harness):
    snapshot = dict(CALCULATOR, controls=[], app={'name': 'Mail', 'bundle_id': 'com.apple.mail', 'pid': 7},
                    lists=ListRowTests.snapshot['lists'])
    regions = [region('OK', .5, .5), region('Cancel', .6, .5)]

    def test_a_confirming_label_waits_for_the_user(self):
        # "OK" can confirm a deletion; the code click must not press it unreviewed.
        self.assertTrue(self.propose(ComputerTask('click OK', automatic=True))['review'])

    def test_a_click_that_changes_only_pixels_counts_as_done(self):
        task = ComputerTask('click Cancel', automatic=True)
        self.propose(task)
        task.record({'type': 'click_point', 'label': 'Cancel', 'status': 'submitted'})
        self.vision.click_guard.return_value = {'region_hash': 'changed'}
        self.assertEqual(self.propose(task)['status'], 'done')

    def test_the_noun_chooses_the_list(self):
        step = self.propose(ComputerTask('click the first mailbox in Mail', automatic=True))
        self.assertEqual(step['action']['x'], .1)  # the mailboxes outline, not the messages table


class ScreenDescriptionTests(LiveRoutingTests):
    """"What's on my screen" evaluated ~9,000 prompt tokens (6-8 s) with the full chat prompt (live)."""

    def test_a_short_prompt_and_compact_observation_describe_the_screen(self):
        from companion.service import SCREEN_SCHEMA, SCREEN_SYSTEM
        self.route('inspect_screen')
        self.provider.complete_structured.return_value = {'message': 'Mail is open with your inbox.'}
        self.app.desktop_context.enabled = True
        self.app.desktop_context.collect_once()
        response = self.app.ask("what's on my screen", mode='assist', image_data='data:image/png;base64,FRAME',
                                visual_context={'windows': [{'app': 'Mail', 'title': 'Inbox'}]})
        self.assertEqual(response['message'], 'Mail is open with your inbox.')
        self.assertIsNone(response['desktop_action'])
        system, messages = self.provider.complete_structured.call_args.args
        self.assertEqual(system, SCREEN_SYSTEM)
        self.assertEqual(self.provider.complete_structured.call_args.kwargs['schema'], SCREEN_SCHEMA)
        self.assertEqual(self.provider.complete_structured.call_args.kwargs['image_data'], 'data:image/png;base64,FRAME')
        observation = json.loads(messages[-2]['content'])
        # A follow-up gets the earlier turn, never one built from company documents no longer allowed.
        self.app.desktop_session.extend([{'role': 'user', 'content': 'what is in the handbook', 'source_documents': ['revoked-doc']},
                                         {'role': 'assistant', 'content': 'Secret policy text.', 'source_documents': ['revoked-doc']}])
        self.app.ask('what does that say on my screen', mode='assist', image_data='data:image/png;base64,FRAME', visual_context={})
        self.assertNotIn('Secret policy text.', json.dumps(self.provider.complete_structured.call_args.args[1]))
        self.assertEqual(observation['visible_windows'], ['Mail — Inbox'])
        self.assertNotIn('installed_apps', messages[-2]['content'])
        self.assertLess(len(system)+len(messages[-2]['content']), 3000)


class InspectionAnswerTests(Harness):
    """Teams Activity was open; the model twice proposed a Safari toolbar button as a change and
    the task ended "I could not find a safe next step" (live)."""
    regions = TEAMS_REGIONS

    def test_an_inspection_ends_with_what_the_screen_shows_and_no_action(self):
        task = ComputerTask('check if I have new notifications on Teams', automatic=True, goal_mode='inspect')
        task.record({'type': 'click_point', 'label': 'Activity', 'status': 'submitted'})
        change = {'status': 'action', 'message': 'Press it.', 'risk': 'change', 'action': {'type': 'press_control', 'control_id': 'control-0'}}
        self.provider.complete_structured.side_effect = [change, change,
            {'status': 'done', 'message': 'Ana mentioned you in General.', 'risk': 'navigation', 'action': None}]
        step = self.propose(task)
        self.assertEqual(step, {'status': 'done', 'message': 'Ana mentioned you in General.', 'action': None})
        report = self.provider.complete_structured.call_args
        self.assertEqual(report.kwargs['schema']['properties']['action'], {'type': 'null'})

    def test_other_goals_still_stop_with_nothing_done(self):
        task = ComputerTask('open Teams and post hello', automatic=True, goal_mode='change')
        task.record({'type': 'click_point', 'label': 'Activity', 'status': 'submitted'})
        bad = {'status': 'action', 'message': 'Press it.', 'risk': 'navigation', 'action': {'type': 'press_control', 'control_id': 'missing'}}
        self.provider.complete_structured.side_effect = [bad, bad]
        with self.assertRaises(Exception):
            self.propose(task)
        self.assertEqual(self.provider.complete_structured.call_count, 2)
