"""Behavior contracts for movement and one confirmed computer action.

These use explicit model/native doubles. See scripts/evaluate_movement.py for live
Ollama interpretation checks; unit tests do not claim to measure model intelligence.
"""
import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
os.environ.setdefault('A11Y_ROUTES', '0')  # nor read routes a live run remembered
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from companion.computer_use import ComputerUse
from companion.desktop_context import DesktopContext
from companion.models import Target, ValidationError, validate_response
from test_core import CompanionFixture
from test_desktop_context import FakeBridge, SAMPLE


def response(**values):
    return dict({'request_kind': 'move', 'message': 'I’ll move there.', 'source_ids': [],
                 'workflow': None, 'target': None, 'desktop_action': None}, **values)


class MovementContracts(unittest.TestCase):
    def test_objects_become_movement_instead_of_review_only_highlights(self):
        for name, box in [
            ('menu-bar date and time', (.95, .0, .08, .04)),
            ('Fastfetch Apple logo in bottom Terminal', (.72, .70, .12, .15)),
            ('GET and POST output in upper Terminal', (.15, .12, .30, .06)),
        ]:
            with self.subTest(destination=name):
                raw = response(target=dict(zip(('x', 'y', 'width', 'height'), box), label=name))
                result = validate_response(raw, set(), has_screen=True, desktop=object())
                self.assertIsNone(result['target'])
                action = result['desktop_action']
                self.assertEqual(action['type'], 'move_to_point')
                self.assertEqual(action['basis'], 'image')
                self.assertAlmostEqual(action['x'], box[0]+min(box[2], 1-box[0])/2)
                self.assertAlmostEqual(action['y'], box[1]+min(box[3], 1-box[1])/2)

    def test_highlight_request_remains_a_highlight(self):
        result = validate_response(response(request_kind='highlight',
            target={'label': 'Clock', 'x': .95, 'y': 0, 'width': .08, 'height': .04}),
            set(), has_screen=True)
        self.assertIsNone(result.get('desktop_action'))
        self.assertAlmostEqual(result['target']['width'], .05)

    def test_edges_clip_but_wrong_units_and_offscreen_origins_do_not(self):
        box = {'label': 'Clock', 'x': .97, 'y': .98, 'width': .08, 'height': .06}
        target = Target.parse(box)
        self.assertAlmostEqual(target.x+target.width, 1)
        self.assertAlmostEqual(target.y+target.height, 1)
        for change in [{'x': 990}, {'x': 1.1}, {'y': -1}, {'width': float('nan')}]:
            with self.assertRaises(ValidationError):
                Target.parse(dict(box, **change))

    def test_named_object_without_pixels_cannot_become_a_pretend_corner_search(self):
        with self.assertRaisesRegex(ValidationError, 'corner is not a search action'):
            validate_response(response(request_kind='move_object', desktop_action={'type': 'move_companion', 'destination': 'top_left'}), set(), desktop=object())
        result = validate_response(response(request_kind='move_object', desktop_action={'type': 'request_screen'}), set(), desktop=object())
        self.assertEqual(result['desktop_action']['type'], 'request_screen')

    def test_movement_without_action_cannot_claim_to_execute(self):
        with self.assertRaisesRegex(ValidationError, 'Movement needs'):
            validate_response(response(), set(), desktop=object())

    def test_visual_movement_without_pixels_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_response(response(target={'label': 'Logo', 'x': .5, 'y': .5, 'width': .1, 'height': .1}),
                              set(), desktop=object())


class ComputerServiceTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()
        self.monitor = self.app.desktop_context = DesktopContext(self.bridge, clock=lambda: 100)
        self.monitor.enabled = True
        self.monitor.collect_once()

    def test_invalid_model_geometry_gets_one_correction_with_same_image(self):
        outputs = [response(target={'label': 'Clock', 'x': 980, 'y': 5, 'width': 50, 'height': 15}),
                   response(desktop_action={'type': 'move_to_point', 'basis': 'image', 'x': .97, 'y': .02, 'label': 'Clock'})]
        with patch.object(self.provider, 'complete', side_effect=outputs) as model:
            result = self.app.ask('move to the date and time', image_data='data:image/png;base64,TEST_FRAME')
        self.assertEqual(model.call_count, 2)
        for call in model.call_args_list:
            self.assertEqual(call.kwargs['image_data'], 'data:image/png;base64,TEST_FRAME')
            self.assertEqual(call.args[1][-1]['content'], 'move to the date and time')
        self.assertIn('correction', json.loads(model.call_args_list[-1].args[1][-2]['content']))
        self.assertEqual(result['desktop_action']['type'], 'move_to_point')
        self.assertEqual(self.store.history(self.employee), [])

    def test_failed_correction_never_saves_or_executes_action(self):
        with patch.object(self.provider, 'complete', return_value=response()) as model:
            result = self.app.ask('move to the clock')
        self.assertIsNone(result['desktop_action'])
        self.assertIsNone(result['target'])
        self.assertEqual(model.call_count, 2)
        self.assertEqual(list(self.app.desktop_session), [])
        self.assertEqual(self.store.workflows(self.employee), [])

    def test_press_proposal_has_exact_control_and_app_for_confirmation(self):
        raw = response(request_kind='act', desktop_action={'type': 'press_control', 'control_id': 'control-0'})
        self.provider.invalid = raw
        result = self.app.ask('Press New Folder')
        action = result['desktop_action']
        self.assertEqual(action['bundle_id'], 'com.apple.finder')
        self.assertEqual(action['label'], 'New Folder')
        self.assertEqual(action['confirmation_label'], 'Press “New Folder” in Finder')
        self.assertEqual(action['bounds'], SAMPLE['controls'][0]['bounds'])

    def test_confirmed_press_is_submitted_then_observed_not_completed(self):
        proposal = self.monitor.authorize_action({'type': 'press_control', 'control_id': 'control-0'})
        self.bridge.press = lambda action: {'submitted': True}
        result = ComputerUse(self.monitor).execute_confirmed(proposal)
        self.assertEqual(result['status'], 'submitted')
        self.assertFalse(result['task_completed'])
        self.assertIn('after', result)

    def test_changed_or_paused_observation_cannot_execute_press(self):
        proposal = self.monitor.authorize_action({'type': 'press_control', 'control_id': 'control-0'})
        self.bridge.press = unittest.mock.Mock(return_value={'submitted': True})
        self.bridge.value['controls'][0]['label'] = 'Different action'
        self.monitor.collect_once()
        with self.assertRaises(ValueError):
            ComputerUse(self.monitor).execute_confirmed(proposal)
        self.bridge.press.assert_not_called()
        self.monitor.disable()
        with self.assertRaises(ValueError):
            ComputerUse(self.monitor).execute_confirmed(proposal)
        self.bridge.press.assert_not_called()

    def test_pausing_during_submission_drops_observation_and_stops_verification(self):
        proposal = self.monitor.authorize_action({'type': 'press_control', 'control_id': 'control-0'})
        def paused(action):
            self.monitor.disable()
            return {'submitted': True}
        self.bridge.press = paused
        with self.assertRaisesRegex(RuntimeError, 'app awareness was paused'):
            ComputerUse(self.monitor).execute_confirmed(proposal)

    def test_uncertain_native_press_is_never_retried(self):
        proposal = self.monitor.authorize_action({'type': 'press_control', 'control_id': 'control-0'})
        self.bridge.press = unittest.mock.Mock(side_effect=RuntimeError('Uncertain press result'))
        with self.assertRaises(RuntimeError):
            ComputerUse(self.monitor).execute_confirmed(proposal)
        self.bridge.press.assert_called_once()

    def test_verification_cannot_chain_another_action(self):
        self.app.last_action_result = {'type': 'press_control', 'status': 'submitted', 'task_completed': False}
        outputs = [response(request_kind='act', desktop_action={'type': 'press_control', 'control_id': 'control-0'}),
                   response(request_kind='answer', message='The window is unchanged; I cannot verify completion.')]
        with patch.object(self.provider, 'complete', side_effect=outputs) as model:
            result = self.app.ask('Press New Folder', mode='verify')
        self.assertEqual(model.call_count, 2)
        self.assertIsNone(result['desktop_action'])
        context = json.loads(model.call_args_list[0].args[1][-2]['content'])
        self.assertEqual(context['last_action_result']['status'], 'submitted')


class AppActionTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()
        self.bridge.value['available_apps'] = [
            {'name': 'Terminal', 'bundle_id': 'com.apple.Terminal'},
            {'name': 'Finder', 'bundle_id': 'com.apple.finder'}]
        self.bridge.value['installed_apps'] = self.bridge.value['available_apps']+[
            {'name': 'Stremio', 'bundle_id': 'com.stremio.test'}]
        self.bridge.value['app_windows'] = [
            {'window_id': 'com.apple.Terminal:0', 'bundle_id': 'com.apple.Terminal', 'name': 'Terminal',
             'title': 'API requests', 'bounds': {'x': 40, 'y': 60, 'width': 640, 'height': 300}, 'can_close': True},
            {'window_id': 'com.apple.Terminal:1', 'bundle_id': 'com.apple.Terminal', 'name': 'Terminal',
             'title': 'zsh', 'bounds': {'x': 650, 'y': 410, 'width': 500, 'height': 330}, 'can_close': True}]
        self.monitor = DesktopContext(self.bridge, clock=lambda: 100)
        self.monitor.enabled = True
        self.monitor.collect_once()
        self.bridge.application_action = unittest.mock.Mock(return_value={'submitted': True})

    def test_model_cannot_substitute_focus_for_open_new_window_or_quit(self):
        for requested in ('launch_app', 'new_window', 'quit_app', 'close_window'):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValidationError, 'not an equivalent operation'):
                validate_response(response(request_kind=requested, desktop_action={'type': 'focus_app', 'bundle_id': 'com.apple.Terminal'}), set(), desktop=self.monitor)

    def test_installed_app_launch_is_distinct_from_running_app_focus(self):
        action = self.monitor.authorize_action({'type': 'launch_app', 'bundle_id': 'com.stremio.test'})
        self.assertEqual(action['label'], 'Open Stremio')
        with self.assertRaises(ValueError):
            self.monitor.authorize_action({'type': 'focus_app', 'bundle_id': 'com.stremio.test'})
        ComputerUse(self.monitor).execute_confirmed(action)
        self.bridge.application_action.assert_called_once_with(action)

    def test_new_terminal_window_is_a_separate_confirmed_action(self):
        action = self.monitor.authorize_action({'type': 'new_window', 'bundle_id': 'com.apple.Terminal'})
        self.assertEqual(action['label'], 'Open a new window in Terminal')
        ComputerUse(self.monitor).execute_confirmed(action)
        self.bridge.application_action.assert_called_once_with(action)
        with self.assertRaises(ValueError):
            self.monitor.authorize_action({'type': 'new_window', 'bundle_id': 'com.apple.finder'})

    def test_close_one_window_never_quits_the_app_or_selects_focused_window(self):
        action = self.monitor.authorize_action({'type': 'close_window', 'window_id': 'com.apple.Terminal:1'})
        self.assertEqual(action['window_title'], 'zsh')
        self.assertEqual(action['bounds']['x'], 650)
        ComputerUse(self.monitor).execute_confirmed(action)
        sent = self.bridge.application_action.call_args.args[0]
        self.assertEqual(sent['type'], 'close_window')
        self.assertEqual(sent['window_id'], 'com.apple.Terminal:1')

    def test_window_change_or_disabled_access_prevents_execution(self):
        action = self.monitor.authorize_action({'type': 'close_window', 'window_id': 'com.apple.Terminal:1'})
        self.bridge.value['app_windows'][1]['title'] = 'Different zsh session'
        self.monitor.collect_once()
        with self.assertRaises(ValueError):
            ComputerUse(self.monitor).execute_confirmed(action)
        self.bridge.application_action.assert_not_called()
        self.monitor.disable()
        with self.assertRaises(ValueError):
            ComputerUse(self.monitor).execute_confirmed(action)

    def test_quit_is_graceful_and_targets_one_observed_running_app(self):
        action = self.monitor.authorize_action({'type': 'quit_app', 'bundle_id': 'com.apple.Terminal'})
        ComputerUse(self.monitor).execute_confirmed(action)
        self.assertEqual(self.bridge.application_action.call_args.args[0]['type'], 'quit_app')
        with self.assertRaises(ValueError):
            self.monitor.authorize_action({'type': 'quit_app', 'bundle_id': 'not-observed'})

    def test_windows_keep_updating_when_companion_has_focus(self):
        windows = self.bridge.value['app_windows']
        self.bridge.value = {'status': 'companion_focused', 'app_windows': windows, 'installed_apps': []}
        self.monitor.collect_once()
        self.assertEqual(self.monitor.context()['app_windows'][1]['title'], 'zsh')
