import json
import unittest
from unittest.mock import patch
from io import BytesIO
from companion.ollama import OllamaProvider, local_url, provider_from_env
from companion.provider import AIConfig, ProviderError


class OllamaTests(unittest.TestCase):
    def provider(self):
        return OllamaProvider(AIConfig(base_url='http://127.0.0.1:11434', model='local-model'))

    def test_local_chat_calls_native_api_and_retains_real_conversation(self):
        provider = self.provider()
        with patch.object(provider, 'request') as request:
            request.side_effect = [
                {'capabilities': ['completion']},
                {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                    'message': 'A model-generated answer', 'source_ids': [], 'workflow': None, 'target': None})}}]
            result = provider.complete('system', [{'role': 'user', 'content': 'Earlier question'},
                {'role': 'assistant', 'content': 'Earlier reply'}, {'role': 'user', 'content': 'Follow up'}])
            args = request.call_args.args
            self.assertEqual(args[0], '/api/chat')
            self.assertEqual(args[1]['messages'][1]['content'], 'Earlier question')
            self.assertEqual(args[1]['format']['type'], 'object')
            self.assertIn('desktop_action', args[1]['format']['properties'])
            self.assertTrue(args[1]['stream'])
            self.assertEqual(result['message'], 'A model-generated answer')

    def test_discovery_excludes_embedding_and_cloud_models(self):
        provider = self.provider()
        with patch.object(provider, 'request') as request:
            request.side_effect = [
                {'models': [{'name': 'embed'}, {'name': 'chat'}, {'name': 'hosted:cloud'}]},
                {'capabilities': ['embedding']}, {'capabilities': ['completion', 'vision']}]
            self.assertEqual(provider.list_models(), [{'name': 'chat', 'vision': True}])

    def test_browser_coverage_recovers_work_omitted_by_first_interpretation(self):
        provider = self.provider()
        goal = 'open teams in a new safari window and look if i have any tasks i need to be doing'
        first = {'operation': 'browser_open', 'app_name': 'Safari', 'target': 'https://teams.microsoft.com',
                 'browser_mode': 'window', 'remaining_request': ''}
        with patch.object(provider, 'complete', side_effect=[first, {'requires_followup_actions': True}]) as complete:
            plan = provider.interpret_request(goal)
        self.assertEqual(plan['operation'], 'computer_task')
        self.assertEqual(plan['target'], goal)
        self.assertIn(goal, complete.call_args.args[1][0]['content'])
        self.assertEqual(plan['browser_mode'], 'window')

    def test_browser_coverage_keeps_simple_navigation_and_rejects_invalid_checks(self):
        provider = self.provider()
        first = {'operation': 'browser_open', 'app_name': 'Safari', 'target': 'https://youtube.com',
                 'browser_mode': 'window', 'remaining_request': ''}
        with patch.object(provider, 'complete', side_effect=[first, {'requires_followup_actions': False}]):
            self.assertEqual(provider.interpret_request('open youtube')['operation'], 'browser_open')
        for invalid in ({}, {'requires_followup_actions': 'false'}, {'requires_followup_actions': False, 'action': 'click'}):
            with patch.object(provider, 'complete', side_effect=[first, invalid]):
                with self.assertRaisesRegex(ProviderError, 'No action was sent'):
                    provider.interpret_request('open youtube')

    def test_generic_app_coverage_recovers_omitted_followup_work(self):
        provider = self.provider()
        for goal in ('open Calculator and sum 2 + 2', 'open Notepad and write a summary of The Little Prince',
                     'open Preview and rotate the image', 'open my drawing app and draw a circle'):
            first = {'operation': 'launch_app', 'app_name': 'Requested app', 'target': '', 'remaining_request': ''}
            with patch.object(provider, 'complete', side_effect=[first, {'requires_followup_actions': True}]):
                plan = provider.interpret_request(goal)
            self.assertEqual(plan['operation'], 'computer_task')
            self.assertEqual(plan['target'], goal)

    def test_task_scope_classification_is_small_text_only_and_validated(self):
        provider = self.provider()
        with patch.object(provider, 'complete', return_value={'mode': 'inspect'}) as complete:
            self.assertEqual(provider.classify_task_goal('check Teams activity'), 'inspect')
        self.assertEqual(complete.call_args.kwargs['max_tokens'], 80)
        self.assertNotIn('image_data', complete.call_args.kwargs)
        with patch.object(provider, 'complete', return_value={'mode': 'anything'}):
            with self.assertRaises(ProviderError):
                provider.classify_task_goal('check Teams activity')

    def test_text_model_cannot_silently_accept_screen_capture(self):
        provider = self.provider()
        with patch.object(provider, 'request', return_value={'capabilities': ['completion']}):
            with self.assertRaisesRegex(ProviderError, 'cannot read images'):
                provider.complete('system', [{'role': 'user', 'content': 'Screen'}], image_data='data:image/png;base64,abc')

    def test_vision_uses_base64_images_field(self):
        provider = self.provider()
        with patch.object(provider, 'request') as request:
            request.side_effect = [{'capabilities': ['completion', 'vision']},
                                   {'done': True, 'message': {'content': '{}'}}]
            provider.complete('system', [{'role': 'user', 'content': 'Screen'}], image_data='data:image/png;base64,abc')
            self.assertEqual(request.call_args.args[1]['messages'][-1]['images'], ['abc'])

    def test_context_and_thinking_are_configurable_for_model_comparison(self):
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion']}
        with patch.dict('os.environ', {'A11Y_OLLAMA_CONTEXT': '16384', 'A11Y_OLLAMA_THINKING': 'false'}), patch.object(provider, 'request', return_value={'done': True, 'message': {'content': '{}'}}) as request:
            provider.complete('system', [{'role': 'user', 'content': 'Move left'}])
        body = request.call_args.args[1]
        self.assertEqual(body['options']['num_ctx'], 16384)
        self.assertIs(body['think'], False)
        self.assertIn('request_kind', body['format']['required'])
        self.assertEqual(list(body['format']['properties'])[0], 'request_kind')

    def test_incomplete_and_invalid_model_output_is_rejected(self):
        for result in [{'done': False}, {'done': True, 'done_reason': 'length'},
                       {'done': True, 'message': {'content': 'not json'}}]:
            provider = self.provider()
            provider.metadata['local-model'] = {'capabilities': ['completion']}
            with patch.object(provider, 'request', return_value=result):
                with self.assertRaises(ProviderError):
                    provider.complete('system', [{'role': 'user', 'content': 'Question'}])

    def test_desktop_step_budget_disables_supported_thinking_and_retains_message_bound(self):
        from companion.computer_task import SCHEMA
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion', 'vision', 'thinking']}
        with patch.dict('os.environ', {'A11Y_OLLAMA_THINKING': 'default'}), patch.object(provider, 'request', return_value={'done': True, 'message': {'content': '{}'}}) as request:
            provider.complete_structured('system', [{'role': 'user', 'content': 'Screen'}], schema=SCHEMA,
                                         image_data='data:image/png;base64,abc', max_tokens=1200, thinking=False)
        body = request.call_args.args[1]
        self.assertIs(body['think'], False)
        self.assertEqual(body['options']['num_predict'], 1200)
        action_step, terminal_step = body['format']['anyOf']
        self.assertEqual(action_step['properties']['message']['maxLength'], 256)
        self.assertEqual(action_step['properties']['status'], {'const': 'action'})
        self.assertFalse(any(variant.get('type') == 'null' for variant in action_step['properties']['action']['anyOf']))
        self.assertEqual(terminal_step['properties']['action'], {'type': 'null'})

    def test_explicit_thinking_override_is_respected(self):
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion', 'thinking']}
        with patch.dict('os.environ', {'A11Y_OLLAMA_THINKING': 'true'}), patch.object(provider, 'request', return_value={'done': True, 'message': {'content': '{}'}}) as request:
            provider.complete('system', [{'role': 'user', 'content': 'Screen'}], thinking=False)
        self.assertIs(request.call_args.args[1]['think'], True)

    def test_token_exhaustion_is_not_reported_as_a_long_user_request(self):
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion']}
        with patch.object(provider, 'request', return_value={'done': True, 'done_reason': 'length', 'message': {'content': '{"action":'}}) as request:
            with self.assertRaisesRegex(ProviderError, 'long answer'):
                provider.complete('system', [{'role': 'user', 'content': 'Screen'}], max_tokens=700)
        # One longer retry, then a plain-language error (no action is ever sent).
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.args[1]['options']['num_predict'], 2100)

    def test_truncated_answer_gets_one_longer_try(self):
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion']}
        replies = [{'done': True, 'done_reason': 'length', 'message': {'content': '{"a":'}},
                   {'done': True, 'done_reason': 'stop', 'message': {'content': '{"a": 1}'}}]
        with patch.object(provider, 'request', side_effect=replies):
            self.assertEqual(provider.complete('system', [{'role': 'user', 'content': 'x'}], max_tokens=700), {'a': 1})

    def test_warm_up_sends_one_request_per_prompt(self):
        # A user's Ollama log showed every warm-up prompt sent twice: the one-token reply was
        # retried as if the model had rambled.
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion']}
        with patch.object(provider, 'request', return_value={'done': True, 'done_reason': 'length', 'message': {'content': '{'}}) as request:
            provider.warm_up(['first system', 'second system'])
        self.assertEqual(request.call_count, 2)

    def test_timing_logs_backend_costs_without_private_content(self):
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion', 'vision']}
        response = {'done': True, 'done_reason': 'length', 'total_duration': 82_759_000_000,
                    'prompt_eval_duration': 9_326_000_000, 'eval_duration': 73_432_000_000,
                    'eval_count': 3000, 'prompt_eval_count': 6031,
                    'message': {'content': 'private-response', 'thinking': 'private-thought'}}
        with patch.object(provider, 'request', return_value=response), patch('builtins.print') as output:
            with self.assertRaises(ProviderError):
                provider.complete('private-system', [{'role': 'user', 'content': 'private-screen'}],
                                  image_data='data:image/png;base64,private-image')
        logged = '\n'.join(call.args[0] for call in output.call_args_list)
        self.assertNotIn('private-', logged)
        record = json.loads(output.call_args_list[-1].args[0].removeprefix('A11y timing '))
        self.assertEqual(record['eval_ms'], 73432)
        self.assertEqual(record['prompt_eval_ms'], 9326)
        self.assertEqual(record['eval_count'], 3000)
        self.assertTrue(record['truncated'])

    def test_timing_failure_logs_do_not_echo_provider_errors(self):
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion']}
        with patch.object(provider, 'request', side_effect=ProviderError('private-error')), patch('builtins.print') as output:
            with self.assertRaises(ProviderError):
                provider.complete('private-system', [{'role': 'user', 'content': 'private-input'}])
        logged = '\n'.join(call.args[0] for call in output.call_args_list)
        self.assertIn('ollama.failed', logged)
        self.assertNotIn('private-', logged)

    def test_no_remote_endpoint_or_cloud_forwarding(self):
        for endpoint in ['http://remote.example:11434', 'https://ollama.com', 'file:///tmp/ollama']:
            with self.assertRaises(ProviderError):
                local_url(endpoint)
        provider = self.provider()
        with patch.object(provider, 'request', return_value={'remote_host': 'https://ollama.com'}):
            with self.assertRaises(ProviderError):
                provider.model_info('hosted')

    def test_transport_calls_loopback_without_authentication_or_proxy(self):
        provider = self.provider()
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.return_value = BytesIO(b'{"models": []}')
            self.assertEqual(provider.request('/api/tags'), {'models': []})
            req = build.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url, 'http://127.0.0.1:11434/api/tags')
            self.assertIsNone(req.get_header('Authorization'))

    def test_http_400_is_classified_without_echoing_private_error_body(self):
        from urllib.error import HTTPError
        from companion.ollama import OllamaRequestError
        provider = self.provider()
        for detail, category in [('failed to parse grammar secret-in-body', 'schema'),
                                 ('invalid image secret-in-body', 'vision'),
                                 ('bad request secret-in-body', 'request')]:
            error = HTTPError('http://127.0.0.1:11434/api/chat', 400, 'Bad request', {}, BytesIO(json.dumps({'error': detail}).encode()))
            with patch('urllib.request.build_opener') as build:
                build.return_value.open.side_effect = error
                with self.assertRaises(OllamaRequestError) as result:
                    provider.request('/api/chat', {})
            self.assertEqual(result.exception.category, category)
            self.assertNotIn('secret-in-body', str(result.exception))
            self.assertNotIn('ollama list', str(result.exception))
            self.assertTrue(error.fp.closed)

    def test_schema_grammar_rejection_retries_json_once_and_caches_per_schema(self):
        from copy import deepcopy
        from companion.ollama import OllamaRequestError
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion', 'vision']}
        formats = []
        def request(path, body):
            formats.append(deepcopy(body))
            if len(formats) == 1:
                raise OllamaRequestError(400, 'schema')
            return {'done': True, 'message': {'content': '{"message":"ok"}'}}
        schema = {'type': 'object', 'properties': {'message': {'type': 'string', 'maxLength': 2000}}, 'required': ['message']}
        with patch.object(provider, 'request', side_effect=request):
            provider.complete_structured('system', [{'role': 'user', 'content': 'Screen'}], schema=schema, image_data='data:image/png;base64,abc')
            provider.complete_structured('system', [{'role': 'user', 'content': 'Next screen'}], schema=schema, image_data='data:image/png;base64,def')
        self.assertIsInstance(formats[0]['format'], dict)
        self.assertNotIn('maxLength', formats[0]['format']['properties']['message'])
        self.assertEqual([item['format'] for item in formats[1:]], ['json', 'json'])
        self.assertEqual(formats[1]['messages'][-1]['images'], ['abc'])
        self.assertIn('2000', formats[1]['messages'][0]['content'])
        self.assertEqual(schema['properties']['message']['maxLength'], 2000)

    def test_non_schema_errors_and_second_rejection_are_not_retried(self):
        from companion.ollama import OllamaRequestError
        provider = self.provider()
        provider.metadata['local-model'] = {'capabilities': ['completion']}
        for code, category in [(400, 'vision'), (400, 'thinking'), (404, 'missing'), (500, 'memory')]:
            with patch.object(provider, 'request', side_effect=OllamaRequestError(code, category)) as request:
                with self.assertRaises(OllamaRequestError):
                    provider.complete('system', [{'role': 'user', 'content': 'Question'}])
                request.assert_called_once()
        with patch.object(provider, 'request', side_effect=OllamaRequestError(400, 'schema')) as request:
            with self.assertRaises(OllamaRequestError):
                provider.complete('system', [{'role': 'user', 'content': 'Question'}])
            self.assertEqual(request.call_count, 2)

    def test_default_provider_is_ollama_and_explicit_cloud_still_supported(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsInstance(provider_from_env(), OllamaProvider)
