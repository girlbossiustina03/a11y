from io import BytesIO
import json
import unittest
from unittest.mock import patch
import urllib.error
from companion.provider import AIConfig, ChatProvider, NoRedirect, ProviderError


class ProviderTests(unittest.TestCase):
    def config(self, **kwargs):
        return AIConfig(model='configured-model', key='test-key', **kwargs)

    def respond(self, payload):
        return BytesIO(json.dumps(payload).encode())

    def test_transport_sends_model_json_mode_and_multimodal_input(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"message":"hello"}'}}]}
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.return_value = self.respond(response)
            result = ChatProvider(self.config(vision_model='vision-model')).complete(
                'system instructions', [{'role': 'user', 'content': 'request'}], image_data='data:image/png;base64,test')
            args, kwargs = build.return_value.open.call_args
            req = args[0]
            body = json.loads(req.data)
            self.assertEqual(body['model'], 'vision-model')
            self.assertEqual(body['response_format'], {'type': 'json_object'})
            self.assertEqual(body['messages'][1]['content'][1]['type'], 'image_url')
            self.assertEqual(req.get_header('Authorization'), 'Bearer test-key')
            self.assertEqual(kwargs['timeout'], 60)
            self.assertEqual(result['message'], 'hello')

    def test_http_errors_do_not_leak_provider_body(self):
        error = urllib.error.HTTPError('https://provider', 401, 'secret-in-body', {}, BytesIO(b'SECRET'))
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.side_effect = error
            with self.assertRaises(ProviderError) as raised:
                ChatProvider(self.config()).complete('system', [{'role': 'user', 'content': 'hello'}])
            self.assertIn('401', str(raised.exception))
            self.assertNotIn('secret', str(raised.exception).lower())

    def test_invalid_or_truncated_response_fails(self):
        for payload in [[], {}, {'choices': []}, {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]},
                        {'choices': [{'message': {'content': 'not json'}}]}]:
            with self.subTest(payload=payload):
                with patch('urllib.request.build_opener') as build:
                    build.return_value.open.return_value = self.respond(payload)
                    with self.assertRaises(ProviderError):
                        ChatProvider(self.config()).complete('system', [{'role': 'user', 'content': 'hello'}])

    def test_https_required_except_loopback(self):
        for url in ['http://remote.example/v1', 'file:///tmp/provider', 'https://user:password@example.com',
                    'https://example.com/v1?key=secret']:
            with self.assertRaises(ProviderError):
                self.config(base_url=url).validate()
        self.config(base_url='http://127.0.0.1:11434/v1').validate()

    def test_redirects_cannot_forward_sensitive_context(self):
        with self.assertRaises(ProviderError):
            NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://other-host/')

    def test_network_failure_is_actionable(self):
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.side_effect = urllib.error.URLError('network failed')
            with self.assertRaisesRegex(ProviderError, 'connection'):
                ChatProvider(self.config()).complete('system', [{'role': 'user', 'content': 'hi'}])
