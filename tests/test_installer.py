"""First-run setup: model choice, Ollama pulls, verified installs, saved settings, packaged paths."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from companion import installer, paths


class PullServer:
    def __init__(self, lines):
        outer = self
        self.bodies = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                outer.bodies.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                for line in lines:
                    self.wfile.write((json.dumps(line)+'\n').encode())

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:%d' % self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class InstallerTests(unittest.TestCase):
    def test_models_follow_memory(self):
        self.assertEqual(installer.recommended_models(24), ('qwen3:4b-instruct', 'qwen3-vl:4b-instruct'))
        self.assertEqual(installer.recommended_models(8), ('qwen3:1.7b', 'qwen3-vl:2b-instruct'))

    def test_pull_reports_progress_over_the_real_ollama_api_shape(self):
        server = PullServer([{'status': 'pulling manifest'}, {'status': 'downloading', 'total': 100, 'completed': 40},
                             {'status': 'downloading', 'total': 100, 'completed': 100}, {'status': 'success'}])
        seen = []
        try:
            with mock.patch.object(installer, 'OLLAMA', server.url):
                installer.pull_model('qwen3:4b-instruct', lambda message, fraction: seen.append(fraction))
        finally:
            server.close()
        self.assertEqual(server.bodies, [{'model': 'qwen3:4b-instruct', 'stream': True}])
        self.assertEqual([value for value in seen if value is not None], [0.4, 1.0])

    def test_pull_errors_are_reported(self):
        server = PullServer([{'error': 'model not found'}])
        try:
            with mock.patch.object(installer, 'OLLAMA', server.url), self.assertRaisesRegex(installer.SetupError, 'not found'):
                installer.pull_model('missing', lambda *a: None)
        finally:
            server.close()

    def test_everything_installs_only_what_is_missing(self):
        calls = []
        with mock.patch.object(installer, 'ollama_running', return_value=False), \
                mock.patch.object(installer, 'ollama_app', return_value=None), \
                mock.patch.object(installer, 'install_ollama', side_effect=lambda *a: calls.append('install')), \
                mock.patch.object(installer, 'installed_models', return_value={'qwen3:4b-instruct'}), \
                mock.patch.object(installer, 'pull_model', side_effect=lambda name, *a: calls.append(name)):
            result = installer.prepare_everything(lambda *a: None, models=('qwen3:4b-instruct', 'qwen3-vl:4b-instruct'))
        self.assertEqual(calls, ['install', 'qwen3-vl:4b-instruct'])
        self.assertEqual(result, ('qwen3:4b-instruct', 'qwen3-vl:4b-instruct'))

    def test_unverified_windows_installer_is_never_run(self):
        ran = []
        def run(args, **kwargs):
            ran.append(args[0])
            return mock.Mock(stdout='NotSigned\n', returncode=0)
        with mock.patch.object(installer.sys, 'platform', 'win32'), mock.patch.object(installer, 'download'), \
                mock.patch.object(installer.subprocess, 'run', side_effect=run), \
                self.assertRaisesRegex(installer.SetupError, 'could not be verified'):
            installer.install_ollama(lambda *a: None)
        self.assertEqual(ran, ['powershell.exe'])  # only the signature check

    def test_unverified_macos_download_is_never_installed(self):
        ran = []
        def run(args, **kwargs):
            ran.append(args[0])
            return mock.Mock(returncode=1)
        def fake_download(url, destination, *a):
            import zipfile
            with zipfile.ZipFile(destination, 'w') as bundle:
                bundle.writestr('Ollama.app/Contents/MacOS/Ollama', 'x')
        with mock.patch.object(installer.sys, 'platform', 'darwin'), mock.patch.object(installer, 'download', side_effect=fake_download), \
                mock.patch.object(installer.subprocess, 'run', side_effect=run), \
                self.assertRaisesRegex(installer.SetupError, 'could not be verified'):
            installer.install_ollama(lambda *a: None)
        self.assertEqual(ran, ['codesign'])  # never copied into Applications


class PathTests(unittest.TestCase):
    def test_packaged_app_uses_the_platform_data_folder(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(paths, 'frozen', return_value=True), \
                mock.patch.object(paths.sys, 'platform', 'darwin'):
            self.assertEqual(paths.data_dir(), Path.home()/'Library'/'Application Support'/'A11y')
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(paths, 'frozen', return_value=False):
            self.assertEqual(paths.data_dir(), Path('.data'))
        with mock.patch.dict(os.environ, {'A11Y_DATA_DIR': '/x'}):
            self.assertEqual(paths.data_dir(), Path('/x'))

    def test_saved_models_are_used_unless_the_environment_overrides(self):
        from companion.ollama import OllamaProvider
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'A11Y_DATA_DIR': directory}, clear=False):
            os.environ.pop('A11Y_AI_MODEL', None)
            os.environ.pop('A11Y_VISION_MODEL', None)
            paths.save_ai_settings(model='qwen3:4b-instruct', vision_model='qwen3-vl:4b-instruct', other='ignored')
            provider = OllamaProvider()
            self.assertEqual((provider.config.model, provider.config.vision_model), ('qwen3:4b-instruct', 'qwen3-vl:4b-instruct'))
            with mock.patch.dict(os.environ, {'A11Y_AI_MODEL': 'override'}):
                self.assertEqual(OllamaProvider().config.model, 'override')
            self.assertNotIn('other', json.loads((Path(directory)/'ai.json').read_text()))

    def test_bundled_helpers_skip_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory)/'native'/'bin'/'desktop-bridge'
            helper.parent.mkdir(parents=True)
            helper.write_text('#!/bin/sh\n')
            helper.chmod(0o755)
            with mock.patch.object(paths, 'resource_dir', return_value=Path(directory)):
                from companion.desktop_context import MacDesktopBridge
                bridge = MacDesktopBridge(directory)
                self.assertEqual(bridge.binary, helper)
                with mock.patch.object(paths.sys, 'platform', 'darwin'), mock.patch('subprocess.run') as run:
                    import companion.desktop_context as module
                    with mock.patch.object(module.sys, 'platform', 'darwin'):
                        bridge.prepare()
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
