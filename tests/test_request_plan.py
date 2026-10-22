"""Tests the staged planner boundary; model semantic quality has separate live evaluators."""
import json
import unittest
from unittest.mock import Mock, patch
from companion.request_plan import response_schema, validate_plan
from companion.computer_use import ComputerUse
from companion.desktop_context import DesktopContext
from companion.models import ValidationError
from companion.ollama import OllamaProvider
from companion.provider import AIConfig
from test_core import CompanionFixture
from test_desktop_context import FakeBridge


class StagedProvider:
    def __init__(self, operation, app_name='Terminal', target=''):
        self.interpret_request = Mock(return_value={'operation': operation, 'app_name': app_name, 'target': target})
        self.complete_structured = Mock()
        self.complete = Mock(side_effect=AssertionError('Actions must not use unrestricted chat output.'))


class RequestPlanningTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()
        self.bridge.catalog = Mock(return_value=[{'name': 'Terminal', 'bundle_id': 'com.apple.Terminal'},
                                                {'name': 'Stremio', 'bundle_id': 'com.fixture.stremio'}])
        self.bridge.application_action = Mock(return_value={'submitted': True})
        self.bridge.app_state = Mock(return_value={'bundle_id': 'com.fixture.stremio', 'running': True})
        self.monitor = self.app.desktop_context = DesktopContext(self.bridge, clock=lambda: 100)

    def test_open_stremio_with_awareness_off_does_not_focus_or_launch_terminal(self):
        provider = self.app.provider = StagedProvider('launch_app', 'Stremio')
        self.app.desktop_session.append({'role': 'assistant', 'content': 'Move toward Terminal to open another app.', 'source_documents': []})
        self.bridge.sample = Mock(side_effect=AssertionError('Launch must not read the desktop.'))
        result = self.app.ask('open up stremio please')
        self.assertEqual(result['desktop_action']['type'], 'launch_app')
        self.assertEqual(result['desktop_action']['bundle_id'], 'com.fixture.stremio')
        self.assertIn('Ready to open Stremio', result['message'])
        provider.complete.assert_not_called()
        provider.complete_structured.assert_not_called()
        self.assertEqual(provider.interpret_request.call_args.args[1], [])
        receipt = ComputerUse(self.monitor).execute_confirmed(result['desktop_action'])
        self.assertTrue(receipt['application_state']['running'])
        self.assertFalse(self.monitor.enabled)
        self.bridge.sample.assert_not_called()

    def test_unknown_app_never_falls_back_to_terminal(self):
        provider = self.app.provider = StagedProvider('launch_app', 'MissingApp')
        result = self.app.ask('open MissingApp')
        self.assertIsNone(result['desktop_action'])
        self.assertIn('exact application name', result['message'])
        provider.complete_structured.assert_not_called()
        self.bridge.application_action.assert_not_called()

    def test_close_without_access_requests_app_metadata_not_movement_or_pixels(self):
        provider = self.app.provider = StagedProvider('close_window')
        result = self.app.ask('close the lower right terminal please')
        self.assertEqual(result['desktop_action']['type'], 'request_app_access')
        provider.complete_structured.assert_not_called()

    def test_object_without_pixels_never_uses_a_corner_search(self):
        provider = self.app.provider = StagedProvider('move_object', '', 'ally name on Terminal title')
        result = self.app.ask('move to the ally name on the left terminal title')
        self.assertEqual(result['desktop_action']['type'], 'request_screen')
        provider.complete_structured.assert_not_called()

    def test_wrong_operation_is_rejected_independently_of_model_self_classification(self):
        provider = self.app.provider = StagedProvider('close_window')
        self.bridge.value['app_windows'] = [{'window_id': 'com.apple.Terminal:1', 'name': 'Terminal',
            'bundle_id': 'com.apple.Terminal', 'title': 'zsh', 'can_close': True,
            'bounds': {'x': 650, 'y': 410, 'width': 500, 'height': 300}}]
        self.monitor.enabled = True
        self.monitor.collect_once()
        base = {'message': 'Proposed operation.', 'source_ids': [], 'workflow': None, 'target': None}
        provider.complete_structured.side_effect = [
            dict(base, request_kind='move_geometry', desktop_action={'type': 'move_companion', 'destination': 'bottom_right'}),
            dict(base, request_kind='close_window', desktop_action={'type': 'close_window', 'window_id': 'com.apple.Terminal:1'})]
        result = self.app.ask('close the lower right terminal please')
        self.assertEqual(provider.complete_structured.call_count, 2)
        self.assertEqual(result['desktop_action']['type'], 'close_window')
        self.assertIn('Confirm below', result['message'])
        first = provider.complete_structured.call_args_list[0]
        context = json.loads(first.args[1][-2]['content'])
        self.assertNotIn('history', context)
        self.assertEqual(context['request_plan']['operation'], 'close_window')
        variants = first.kwargs['schema']['properties']['desktop_action']['anyOf']
        types = [value for entry in variants if 'properties' in entry for value in entry['properties']['type'].get('enum', [])]
        self.assertNotIn('move_companion', types)
        self.assertNotIn('launch_app', types)

    def test_verification_schema_has_no_action_field_or_original_instruction(self):
        provider = self.app.provider = StagedProvider('launch_app', 'Stremio')
        self.app.last_action_result = {'type': 'launch_app', 'application_state': {'running': True}, 'task_completed': False}
        provider.complete_structured.return_value = {'message': 'Stremio is running. Its window contents are not available.'}
        result = self.app.ask('open Stremio', mode='verify')
        provider.interpret_request.assert_not_called()
        call = provider.complete_structured.call_args
        self.assertEqual(list(call.kwargs['schema']['properties']), ['message'])
        payload = json.loads(call.args[1][0]['content'])
        self.assertNotIn('request', payload)
        self.assertNotIn('history', payload)
        self.assertIsNone(result['desktop_action'])
        self.assertIn('Stremio is running', result['message'])

    def test_malformed_verification_cannot_issue_actions(self):
        provider = self.app.provider = StagedProvider('answer')
        provider.complete_structured.return_value = {'message': 'Opening Terminal', 'desktop_action': {'type': 'launch_app', 'bundle_id': 'com.apple.Terminal'}}
        with self.assertRaises(ValidationError):
            self.app.ask('open Stremio', mode='verify')
        self.bridge.application_action.assert_not_called()


class IntentTransportTests(unittest.TestCase):
    def test_intent_call_uses_small_schema_and_no_screen_or_assistant_history(self):
        provider = OllamaProvider(AIConfig(base_url='http://127.0.0.1:11434', model='test'))
        provider.metadata['test'] = {'capabilities': ['completion', 'thinking']}
        with patch.object(provider, 'request', return_value={'done': True, 'message': {'content': json.dumps({'operation': 'launch_app', 'app_name': 'Stremio', 'target': ''})}}) as request:
            plan = provider.interpret_request('open up stremio please', ['close Terminal'])
        body = request.call_args.args[1]
        self.assertFalse(body['think'])
        self.assertEqual(body['options']['num_predict'], 400)
        self.assertEqual(body['format']['required'], ['operation', 'app_name', 'target'])
        self.assertNotIn('images', body['messages'][-1])
        self.assertEqual(plan['app_name'], 'Stremio')

    def test_object_schema_cannot_emit_geometric_movement(self):
        schema = response_schema({'operation': 'move_object'})
        variants = schema['properties']['desktop_action']['anyOf']
        for entry in variants:
            if 'properties' in entry:
                types = entry['properties']['type']['enum']
                self.assertNotIn('move_companion', types)
                if 'move_to_point' in types:
                    self.assertEqual(entry['properties']['basis'], {'const': 'image'})

    def test_bad_interpretation_is_rejected_before_grounding(self):
        for plan in [None, {'operation': 'run_shell', 'app_name': 'Terminal', 'target': 'anything'},
                     {'operation': 'launch_app', 'app_name': 123, 'target': ''}]:
            with self.assertRaises(ValidationError):
                validate_plan(plan)
