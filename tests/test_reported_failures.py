"""Regressions for failures reported from live use.

Model replies and native submission are doubled here. These tests prove the loop's
control flow and validation for each reported failure; they do not prove that a
live model makes the right choice on a real desktop."""
from copy import deepcopy
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
        self.assertIsNone(task.view_step(desktop, {'controls': []}, self.REGIONS, {}, 'img', vision))  # only once
        other = ComputerTask('read my last email', automatic=True, goal_mode='inspect')
        self.assertIsNone(other.view_step(desktop, {'controls': []}, self.REGIONS, {}, 'img', vision))
