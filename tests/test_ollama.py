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
            self.assertFalse(args[1]['stream'])
            self.assertEqual(result['message'], 'A model-generated answer')

    def test_discovery_excludes_embedding_and_cloud_models(self):
        provider = self.provider()
        with patch.object(provider, 'request') as request:
            request.side_effect = [
                {'models': [{'name': 'embed'}, {'name': 'chat'}, {'name': 'hosted:cloud'}]},
                {'capabilities': ['embedding']}, {'capabilities': ['completion', 'vision']}]
            self.assertEqual(provider.list_models(), [{'name': 'chat', 'vision': True}])

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
