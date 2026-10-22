"""Exercise real HTTP handlers in memory; no listening socket or external service."""
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from server import make_handler
from test_core import CompanionFixture


class InMemorySocket:
    def __init__(self, request):
        self.request = BytesIO(request)
        self.output = bytearray()

    def makefile(self, *args):
        return self.request

    def sendall(self, data):
        self.output.extend(data)


class HTTPTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.handler = make_handler(self.app, 'test-token')

    def request(self, path, data=None, *, headers=None, token='test-token'):
        body = json.dumps(data).encode() if data is not None else b''
        head = {'Host': '127.0.0.1:8765', 'X-A11y-Token': token,
                'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        head.update(headers or {})
        request = f'{"POST" if data is not None else "GET"} {path} HTTP/1.0\r\n'
        request += ''.join(f'{k}: {v}\r\n' for k, v in head.items()) + '\r\n'
        socket = InMemorySocket(request.encode()+body)
        self.handler(socket, ('127.0.0.1', 1), SimpleNamespace(server_port=8765))
        response, payload = bytes(socket.output).split(b'\r\n\r\n', 1)
        return int(response.split(b' ')[1]), response, payload

    def test_http_onboarding_plan_confirm_resume_preferences(self):
        status, _, payload = self.request('/api/ask', {'request': 'Development environment onboarding', 'mode': 'plan'})
        self.assertEqual(status, 200)
        w = json.loads(payload)['workflow']
        status, _, _ = self.request('/api/confirm', {'workflow_id': w['id'], 'step': 0})
        self.assertEqual(status, 200)
        status, _, payload = self.request('/api/state')
        self.assertEqual(json.loads(payload)['workflows'][0]['current_step'], 1)
        status, _, _ = self.request('/api/preferences', {'values': {'input': 'keyboard'}, 'learning_enabled': True})
        self.assertEqual(status, 200)
        self.request('/api/ask', {'request': 'Where am I?', 'workflow_id': w['id']})
        self.assertEqual(self.provider.contexts[-1]['preferences']['input'], 'keyboard')
        self.assertEqual(self.provider.contexts[-1]['workflow']['current_step'], 1)

    def test_api_rejects_missing_token_and_cross_origin(self):
        for headers, token in [({}, ''), ({'Origin': 'https://evil.example'}, 'test-token'),
                               ({'Host': 'evil.example:8765'}, 'test-token'),
                               ({'Sec-Fetch-Site': 'cross-site'}, 'test-token')]:
            status, _, _ = self.request('/api/state', headers=headers, token=token)
            self.assertEqual(status, 403)

    def test_static_allowlist_cannot_expose_keys_databases_or_traverse(self):
        for path in ['/.env', '/.data/company.sqlite3', '/../server.py', '/companion/storage.py']:
            self.assertEqual(self.request(path)[0], 404)

    def test_page_has_token_and_safe_headers(self):
        status, headers, page = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'content="test-token"', page)
        self.assertNotIn(b'__A11Y_SESSION_TOKEN__', page)
        self.assertIn(b'Cache-Control: no-store', headers)
        self.assertIn(b"frame-ancestors 'none'", headers)

    def test_restricted_document_upload_for_employee(self):
        status, _, _ = self.request('/api/documents', {'title': 'test', 'body': 'contents', 'roles': ['employee']})
        self.assertEqual(status, 403)

    def test_invalid_fields_are_errors_not_fake_success(self):
        self.assertEqual(self.request('/api/ask', {'request': ''})[0], 400)
        self.assertEqual(self.request('/api/confirm', {'workflow_id': 'unknown', 'step': 0})[0], 400)
        self.assertEqual(self.request('/api/not-an-operation', {})[0], 404)

