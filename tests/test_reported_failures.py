"""Regressions for failures reported from live use.

Model replies and native submission are doubled here. These tests prove the loop's
control flow and validation for each reported failure; they do not prove that a
live model makes the right choice on a real desktop."""
from copy import deepcopy
import time
import unittest
from unittest.mock import Mock
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
        task = ComputerTask('Open Calculator and sum 2+2', automatic=True, goal_mode='inspect')
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
        task = ComputerTask('Open Calculator and sum 2+2', automatic=True, goal_mode='inspect')
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
        task = ComputerTask('Open Calculator and sum 2+2', automatic=True, goal_mode='inspect')
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
        self.assertEqual((step['action']['x'], step['action']['y']), (.05, .21))
        self.assertIn('inspection-only', self.provider.complete_structured.call_args.args[1][-1]['content'])

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
                                      'remaining_request': 'sum 2+2', 'goal_mode': 'inspect'}, 'Open Calculator and sum 2+2')
        self.assertEqual((plan['operation'], plan['goal_mode']), ('computer_task', 'inspect'))


if __name__ == '__main__':
    unittest.main()
