"""Loopback-only, single-employee browser fallback. No third-party dependencies."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlparse
from companion.service import Companion

ROOT = Path(__file__).resolve().parent


def make_handler(service, token):
    mutation_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # URLs and request bodies must not become employee activity logs.

        def allowed(self, api=False):
            expected = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') not in (expected, f'localhost:{self.server.server_port}'):
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://{expected}', f'http://localhost:{self.server.server_port}'):
                return False
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return False
            return not api or secrets.compare_digest(self.headers.get('X-A11y-Token', ''), token)

        def send(self, status, value, content_type='application/json; charset=utf-8'):
            data = json.dumps(value).encode() if content_type.startswith('application/json') else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if not self.allowed(api=path.startswith('/api/')):
                return self.send(403, {'error': 'Local origin and session token required.'})
            if path == '/api/state':
                return self.send(200, service.state())
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/index.html': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path not in files:
                return self.send(404, {'error': 'Not found.'})
            name, content_type = files[path]
            data = (ROOT / name).read_bytes()
            if name == 'index.html':
                data = data.replace(b'__A11Y_SESSION_TOKEN__', token.encode())
            self.send(200, data, content_type)

        def do_POST(self):
            if not self.allowed(api=True):
                return self.send(403, {'error': 'Local origin and session token required.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 500000:
                    return self.send(413, {'error': 'Request size must be between 1 and 500,000 bytes.'})
                if self.headers.get_content_type() != 'application/json':
                    return self.send(415, {'error': 'JSON required.'})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('JSON object required.')
                path = urlparse(self.path).path
                with mutation_lock:
                    if path == '/api/ask':
                        result = service.ask(data.get('request'), mode=data.get('mode', 'answer'),
                                             workflow_id=data.get('workflow_id'))
                    elif path == '/api/confirm':
                        result = service.confirm_step(data.get('workflow_id'), data.get('step'))
                    elif path == '/api/preferences':
                        result = service.adaptation.set_explicit(service.identity, data.get('values'), data.get('learning_enabled'))
                    elif path == '/api/adapt':
                        result = service.adaptation.decide(service.identity, data.get('signal'), data.get('approve'))
                    elif path == '/api/reset-learned':
                        result = service.adaptation.reset_learned(service.identity)
                    elif path == '/api/clear-history':
                        service.store.clear_history(service.identity)
                        result = {'ok': True}
                    elif path == '/api/documents':
                        result = {'id': service.knowledge.ingest(service.identity, data.get('title'),
                                                               data.get('body'), data.get('roles'))}
                    elif path == '/api/delete-document':
                        service.knowledge.delete(service.identity, data.get('id'))
                        result = {'ok': True}
                    else:
                        return self.send(404, {'error': 'Unknown operation.'})
                self.send(200, result)
            except PermissionError as e:
                self.send(403, {'error': str(e)})
            except (ValueError, TypeError) as e:
                self.send(400, {'error': str(e)})
            except RuntimeError as e:
                self.send(502, {'error': str(e)})
            except Exception:
                self.send(500, {'error': 'The operation failed. Confirmed progress is saved.'})

    return Handler


def make_server(service, port=8765):
    handler = make_handler(service, secrets.token_urlsafe(32))
    server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description='A11y local browser companion')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--admin', action='store_true', help='Allow local company document management')
    args = parser.parse_args()
    try:
        server = make_server(Companion.from_env(admin=args.admin), args.port)
    except OSError as e:
        raise SystemExit(f'Cannot listen on 127.0.0.1:{args.port}: {e}. Try another --port or run outside a restricted environment.')
    print(f'A11y is ready at http://127.0.0.1:{server.server_port} (local single-employee session).', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
