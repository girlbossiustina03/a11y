"""Real loopback HTTP transport: streaming assembly, cancellation and disconnects.

These use a local socket server, not doubled transport methods. They do not
exercise a real model; they prove what the client does on the wire."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest
from companion.ollama import OllamaProvider, RequestCancelled
from companion.provider import AIConfig, ProviderError


class Server:
    def __init__(self, chunks, *, delay=0.0, first_delay=0.0, status=200):
        self.disconnected = threading.Event()
        self.bodies = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                outer.bodies.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(status)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.end_headers()
                if status >= 400:
                    self.wfile.write(json.dumps({'error': 'bad grammar private'}).encode())
                    return
                time.sleep(first_delay)
                try:
                    for chunk in chunks:
                        self.wfile.write((json.dumps(chunk)+'\n').encode())
                        self.wfile.flush()
                        time.sleep(delay)
                    # Simulate a generation still in progress, then detect the client leaving.
                    for _ in range(200):
                        time.sleep(0.02)
                        self.wfile.write(b'\n')
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    outer.disconnected.set()

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:%d' % self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def provider(url):
    result = OllamaProvider(AIConfig(base_url=url, model='local-model', timeout=5))
    result.metadata['local-model'] = {'capabilities': ['completion', 'vision']}
    return result


class StreamTransportTests(unittest.TestCase):
    def test_streamed_chunks_assemble_into_one_validated_json_response(self):
        server = Server([{'message': {'content': '{"mode":'}, 'done': False},
                         {'message': {'content': '"inspect"}'}, 'done': False},
                         {'message': {'content': ''}, 'done': True, 'done_reason': 'stop',
                          'prompt_eval_count': 50, 'prompt_eval_duration': 2_000_000}])
        try:
            result = provider(server.url).complete('system', [{'role': 'user', 'content': 'x'}],
                                                   response_schema={'type': 'object'}, max_tokens=40, cancel=threading.Event())
        finally:
            server.close()
        self.assertEqual(result, {'mode': 'inspect'})
        self.assertTrue(server.bodies[0]['stream'])

    def test_cancel_during_prompt_processing_returns_promptly_and_disconnects(self):
        # No bytes arrive for 3 s, as during long image prompt evaluation.
        server = Server([{'message': {'content': '{}'}, 'done': True, 'done_reason': 'stop'}], first_delay=3)
        cancel = threading.Event()
        threading.Timer(0.2, cancel.set).start()
        started = time.monotonic()
        try:
            with self.assertRaises(RequestCancelled):
                provider(server.url).complete('system', [{'role': 'user', 'content': 'x'}],
                                              response_schema={'type': 'object'}, cancel=cancel)
            elapsed = time.monotonic()-started
        finally:
            server.close()
        self.assertLess(elapsed, 1.0)

    def test_cancel_during_generation_closes_the_connection_for_the_server(self):
        server = Server([{'message': {'content': '{"a"'}, 'done': False}], delay=0.01)
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        try:
            with self.assertRaises(RequestCancelled):
                provider(server.url).complete('system', [{'role': 'user', 'content': 'x'}],
                                              response_schema={'type': 'object'}, cancel=cancel)
            self.assertTrue(server.disconnected.wait(3), 'server never observed the disconnect')
        finally:
            server.close()

    def test_already_cancelled_request_never_reaches_the_server(self):
        server = Server([])
        cancel = threading.Event()
        cancel.set()
        try:
            with self.assertRaises(RequestCancelled):
                provider(server.url).complete('s', [{'role': 'user', 'content': 'x'}], response_schema={'type': 'object'}, cancel=cancel)
        finally:
            server.close()
        self.assertEqual(server.bodies, [])

    def test_http_error_body_is_classified_not_echoed(self):
        server = Server([], status=400)
        try:
            with self.assertRaises(ProviderError) as error:
                provider(server.url).request('/api/chat', {'stream': True})
        finally:
            server.close()
        self.assertNotIn('private', str(error.exception))
        self.assertEqual(error.exception.category, 'schema')

    def test_truncated_stream_is_not_treated_as_a_response(self):
        server = Server([{'message': {'content': '{"a":'}, 'done': False}])
        try:
            with self.assertRaisesRegex(ProviderError, 'incomplete|invalid'):
                provider(server.url).request('/api/chat', {'stream': True}, timeout=1)
        finally:
            server.close()


if __name__ == '__main__':
    unittest.main()
