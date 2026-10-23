"""Claude transport against a local fake Messages API (the real SSE event format)."""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from companion import claude
from companion.claude import ClaudeProvider, wire_schema
from companion.computer_task import schema_for
from companion.models import RESPONSE_SCHEMA
from companion.ollama import RequestCancelled, provider_from_env
from companion.provider import AIConfig, ProviderError
from companion.request_plan import INTENT_SCHEMA


def sse(text, stop='end_turn'):
    events = [('message_start', {'type': 'message_start', 'message': {
                  'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'model': claude.MODEL, 'content': [],
                  'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 12, 'output_tokens': 1}}}),
              ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
              ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}}),
              ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
              ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': stop, 'stop_sequence': None},
                                 'usage': {'output_tokens': 7}}),
              ('message_stop', {'type': 'message_stop'})]
    return ''.join(f'event: {name}\ndata: {json.dumps(data)}\n\n' for name, data in events).encode()


class FakeAnthropic:
    """Answers queued replies: (status, body bytes) or a callable(handler)."""
    def __init__(self):
        self.requests, self.replies = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append({'path': self.path, 'headers': dict(self.headers), 'body': body})
                reply = owner.replies.pop(0)
                if callable(reply):
                    return reply(self)
                status, payload = reply
                self.send_response(status)
                self.send_header('Content-Type', 'text/event-stream' if status == 200 else 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def error(status, kind, message):
    return status, json.dumps({'type': 'error', 'error': {'type': kind, 'message': message}}).encode()


class ClaudeTransport(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'})
        self.env.start()
        self.fake = FakeAnthropic()
        self.provider = ClaudeProvider(AIConfig(base_url=self.fake.url, model=claude.MODEL, key='sk-test', timeout=10))
        self.provider._client = self.provider.client().with_options(max_retries=0)

    def tearDown(self):
        self.fake.close()
        self.env.stop()

    def test_structured_answer_and_request_shape(self):
        reply = {'request_kind': 'answer', 'desktop_action': None, 'target': None, 'message': 'Hi.', 'source_ids': [], 'workflow': None}
        self.fake.replies.append((200, sse(json.dumps(reply))))
        result = self.provider.complete_structured('SYSTEM', [{'role': 'assistant', 'content': 'old'},
                                                              {'role': 'user', 'content': 'hello'}], schema=RESPONSE_SCHEMA)
        self.assertEqual(result, reply)
        sent = self.fake.requests[0]
        body = sent['body']
        self.assertTrue(sent['path'].startswith('/v1/messages'))
        self.assertIn('sk-test', sent['headers'].get('Authorization', '')+sent['headers'].get('X-Api-Key', ''))
        self.assertIn(claude.FALLBACK_BETA, sent['headers'].get('anthropic-beta', ''))
        self.assertEqual(body['model'], 'claude-sonnet-5-5')
        self.assertEqual(body['fallbacks'], 'default')
        self.assertTrue(body['stream'])
        self.assertNotIn('temperature', body)
        self.assertEqual(body['system'][0]['cache_control'], {'type': 'ephemeral'})
        # A leading assistant turn is dropped: Claude conversations start with the user.
        self.assertEqual(body['messages'], [{'role': 'user', 'content': 'hello'}])
        self.assertEqual(body['output_config']['effort'], 'low')
        self.assertEqual(body['output_config']['format']['type'], 'json_schema')
        text = json.dumps(body['output_config']['format']['schema'])
        for unsupported in ('maxLength', 'minLength', 'maximum', 'minimum', 'maxItems'):
            self.assertNotIn(unsupported, text)

    def test_task_step_schema_is_wrapped_and_unwrapped_with_the_screenshot(self):
        step = {'status': 'action', 'message': 'Clicking Chat.', 'risk': 'navigation',
                'action': {'type': 'click_point', 'label': 'Chat', 'x': 0.1, 'y': 0.2}}
        self.fake.replies.append((200, sse(json.dumps({'result': step}))))
        result = self.provider.complete_structured('TASK', [{'role': 'user', 'content': 'observation'}],
                                                   schema=schema_for('Darwin', False), max_tokens=1200, thinking=False,
                                                   image_data='data:image/png;base64,iVBORw0KGgo=')
        self.assertEqual(result, step)
        body = self.fake.requests[0]['body']
        schema = body['output_config']['format']['schema']
        self.assertEqual((schema['type'], schema['required']), ('object', ['result']))
        self.assertIn('anyOf', schema['properties']['result'])
        image, text = body['messages'][-1]['content']
        self.assertEqual(image['source'], {'type': 'base64', 'media_type': 'image/png', 'data': 'iVBORw0KGgo='})
        self.assertEqual(text, {'type': 'text', 'text': 'observation'})
        self.assertEqual(body['output_config']['effort'], 'medium')  # looking at the screen gets more thought

    def test_routing_uses_the_shared_planner(self):
        plan = {'operation': 'launch_app', 'app_name': 'Microsoft Teams', 'target': '', 'browser_mode': 'default',
                'remaining_request': '', 'goal_mode': 'inspect', 'reply': ''}
        self.fake.replies += [(200, sse(json.dumps(plan))), (200, sse(json.dumps({'requires_followup_actions': False})))]
        result = self.provider.interpret_request('Microsoft Teams.')
        self.assertEqual(result['operation'], 'launch_app')
        first = self.fake.requests[0]['body']
        self.assertEqual(first['output_config']['format']['schema']['properties']['operation'], INTENT_SCHEMA['properties']['operation'])

    def test_refusal_and_truncation_never_become_actions(self):
        self.fake.replies.append((200, sse('', stop='refusal')))
        with self.assertRaisesRegex(ProviderError, 'declined'):
            self.provider.complete('S', [{'role': 'user', 'content': 'x'}])
        self.fake.replies.append((200, sse('{"message": "', stop='max_tokens')))
        with self.assertRaisesRegex(ProviderError, 'long answer'):
            self.provider.complete('S', [{'role': 'user', 'content': 'x'}])

    def test_errors_are_plain_and_never_echo_the_body(self):
        cases = [(error(401, 'authentication_error', 'secret prompt text'), 'API key'),
                 (error(429, 'rate_limit_error', 'secret prompt text'), 'rate limited'),
                 (error(529, 'overloaded_error', 'secret prompt text'), 'HTTP 529')]
        for reply, expected in cases:
            self.fake.replies.append(reply)
            with self.assertRaises(ProviderError) as caught:
                self.provider.complete('S', [{'role': 'user', 'content': 'x'}])
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn('secret', str(caught.exception))

    def test_schema_rejection_falls_back_to_json_instructions_once(self):
        self.fake.replies += [error(400, 'invalid_request_error', 'output_config.format.schema: too complex'),
                              (200, sse('{"message": "ok"}'))]
        schema = {'type': 'object', 'additionalProperties': False, 'required': ['message'],
                  'properties': {'message': {'type': 'string'}}}
        self.assertEqual(self.provider.complete('S', [{'role': 'user', 'content': 'x'}], response_schema=schema), {'message': 'ok'})
        retry = self.fake.requests[1]['body']
        self.assertNotIn('format', retry['output_config'])
        self.assertIn('Return ONLY a JSON object', retry['system'][0]['text'])
        # The schema is remembered: the next request goes straight to JSON instructions.
        self.fake.replies.append((200, sse('{"message": "again"}')))
        self.provider.complete('S', [{'role': 'user', 'content': 'y'}], response_schema=schema)
        self.assertNotIn('format', self.fake.requests[2]['body']['output_config'])

    def test_other_bad_requests_do_not_retry(self):
        self.fake.replies.append(error(400, 'invalid_request_error', 'messages: something else'))
        with self.assertRaisesRegex(ProviderError, 'HTTP 400'):
            self.provider.complete('S', [{'role': 'user', 'content': 'x'}])
        self.assertEqual(len(self.fake.requests), 1)

    def test_stop_closes_a_slow_answer(self):
        cancel = threading.Event()
        release = threading.Event()

        def slow(handler):
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/event-stream')
            handler.end_headers()
            payload = sse('{"message": "late"}')
            handler.wfile.write(payload[:200])
            handler.wfile.flush()
            release.wait(5)
        self.fake.replies.append(slow)
        threading.Timer(0.3, cancel.set).start()
        try:
            with self.assertRaises(RequestCancelled):
                self.provider.complete('S', [{'role': 'user', 'content': 'x'}], cancel=cancel)
        finally:
            release.set()

    def test_missing_key_explains_where_to_add_it(self):
        provider = ClaudeProvider(AIConfig(base_url=self.fake.url, model=claude.MODEL, key=''))
        with self.assertRaisesRegex(ProviderError, 'Anthropic API key'):
            provider.complete('S', [{'role': 'user', 'content': 'x'}])
        self.assertEqual(self.fake.requests, [])


class ClaudeHelpers(unittest.TestCase):
    def test_wire_schema_closes_objects_and_drops_bounds(self):
        schema = wire_schema({'type': 'object', 'properties': {'n': {'type': 'number', 'minimum': 0, 'maximum': 1},
                                                               'ids': {'type': 'array', 'maxItems': 0},
                                                               'steps': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'properties': {}}}}})
        self.assertEqual(schema['additionalProperties'], False)
        self.assertEqual(schema['properties']['n'], {'type': 'number'})
        self.assertEqual(schema['properties']['ids'], {'type': 'array', 'items': {'type': 'string'}})
        self.assertEqual(schema['properties']['steps']['minItems'], 1)
        self.assertEqual(schema['properties']['steps']['items']['additionalProperties'], False)

    def test_key_is_saved_privately_and_forgotten(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'A11Y_DATA_DIR': folder}, clear=False):
            os.environ.pop('ANTHROPIC_API_KEY', None)
            claude.save_key('sk-saved ')
            self.assertEqual(claude.saved_key(), 'sk-saved')
            if os.name == 'posix':
                self.assertEqual(os.stat(claude.key_path()).st_mode & 0o777, 0o600)
            with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-env'}):
                self.assertEqual(claude.saved_key(), 'sk-env')
            claude.save_key('')
            self.assertEqual(claude.saved_key(), '')

    def test_provider_choice_comes_from_settings_unless_the_environment_says_otherwise(self):
        from companion.paths import save_ai_settings
        from companion.ollama import OllamaProvider
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'A11Y_DATA_DIR': folder}):
            for name in ('A11Y_AI_PROVIDER', 'A11Y_AI_BASE_URL', 'A11Y_AI_KEY', 'OPENAI_API_KEY'):
                os.environ.pop(name, None)
            self.assertIsInstance(provider_from_env(), OllamaProvider)
            save_ai_settings(provider='claude')
            self.assertIsInstance(provider_from_env(), ClaudeProvider)
            with patch.dict(os.environ, {'A11Y_AI_PROVIDER': 'ollama'}):
                self.assertIsInstance(provider_from_env(), OllamaProvider)


if __name__ == '__main__':
    unittest.main()
