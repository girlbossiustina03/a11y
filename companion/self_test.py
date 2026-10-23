"""Packaged-app self-check: `A11y --self-test result.json`.

CI runs this inside the built .app/.exe before a release is published, so problems that only
exist in the packaged app (missing certificates, libraries PyInstaller left out, a wrong Qt
call signature, missing native helpers) fail the build instead of reaching users. It uses the
same code paths as setup and voice, and downloads only the small tiny.en speech model."""
import importlib.util
import json
import sys
import time
import traceback
import urllib.request

from . import paths


def check_https():
    from .installer import DOWNLOADS
    from .neural_voice import MODEL_URL, VOICES_FILE
    urls = ['https://huggingface.co']
    if sys.platform in DOWNLOADS:
        urls.append(DOWNLOADS[sys.platform])
    if importlib.util.find_spec('kokoro_onnx'):
        urls.append(MODEL_URL+VOICES_FILE)
    for url in urls:
        with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=30) as response:
            if response.status >= 400:
                raise RuntimeError(url+' answered '+str(response.status))
    return ', '.join(urls)


def check_speech():
    if not importlib.util.find_spec('faster_whisper'):
        return 'skipped: speech recognition is not part of this build'
    import numpy as np
    from faster_whisper import WhisperModel
    from .voice import WAKE_MODEL, vad_available
    model = WhisperModel(WAKE_MODEL, device='cpu', compute_type='int8', cpu_threads=2)
    segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language='en', beam_size=1,
                                   vad_filter=vad_available())
    list(segments)
    return 'tiny.en loaded and transcribed (speech filter '+('on' if vad_available() else 'off')+')'


def check_natural_voice():
    if not importlib.util.find_spec('kokoro_onnx'):
        return 'skipped: the natural voice is not part of this build (system voice is used)'
    import onnxruntime  # noqa: F401
    import espeakng_loader
    from pathlib import Path
    for path in (espeakng_loader.get_library_path(), espeakng_loader.get_data_path()):
        if not Path(path).exists():
            raise RuntimeError('missing espeak-ng file: '+str(path))
    from kokoro_onnx.tokenizer import Tokenizer
    phonemes = Tokenizer().phonemize('Hello there', 'en-us')
    if not phonemes:
        raise RuntimeError('espeak-ng produced no phonemes')
    return 'onnxruntime, espeak-ng and phonemizer work ('+phonemes[:20]+')'


def check_qt():
    from PyQt6.QtCore import QCoreApplication, QMicrophonePermission  # noqa: F401
    from PyQt6.QtMultimedia import QMediaDevices  # noqa: F401
    signature = QCoreApplication.requestPermission.__doc__ or ''
    if 'handler' not in signature or 'context' in signature:
        raise RuntimeError('unexpected requestPermission signature: '+signature[:200])
    return 'Qt multimedia and the permission API are available'


def check_bundle():
    found = []
    if sys.platform == 'darwin':
        for name in ('desktop-bridge', 'screen-bridge'):
            if paths.bundled_helper(name) is None:
                raise RuntimeError('native helper missing: '+name)
            found.append(name)
        import plistlib
        from pathlib import Path
        info = Path(sys.executable).resolve().parent.parent/'Info.plist'
        keys = plistlib.loads(info.read_bytes())
        for key in ('NSMicrophoneUsageDescription', 'NSScreenCaptureUsageDescription', 'NSAppleEventsUsageDescription'):
            if not keys.get(key):
                raise RuntimeError('Info.plist lacks '+key)
        found.append('Info.plist privacy descriptions')
    stamp = paths.resource_dir()/'build-id.txt'
    if not paths.frozen():
        return ', '.join(found+['source checkout (no build stamp)'])
    if not stamp.is_file():
        raise RuntimeError('build-id.txt missing')
    found.append('build '+stamp.read_text().strip())
    return ', '.join(found)


def check_claude():
    """One structured request through the bundled Anthropic SDK to a local stand-in server."""
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from .claude import MODEL, ClaudeProvider
    from .provider import AIConfig
    events = [('message_start', {'type': 'message_start', 'message': {'id': 'msg_test', 'type': 'message', 'role': 'assistant',
                  'model': MODEL, 'content': [], 'stop_reason': None, 'stop_sequence': None,
                  'usage': {'input_tokens': 1, 'output_tokens': 1}}}),
              ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
              ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': '{"message": "ok"}'}}),
              ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
              ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': 3}}),
              ('message_stop', {'type': 'message_stop'})]
    payload = ''.join(f'event: {name}\ndata: {json.dumps(data)}\n\n' for name, data in events).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ['NO_PROXY'] = ','.join(filter(None, [os.environ.get('NO_PROXY'), '127.0.0.1']))
    try:
        provider = ClaudeProvider(AIConfig(base_url=f'http://127.0.0.1:{server.server_address[1]}', model=MODEL, key='self-test', timeout=20))
        schema = {'type': 'object', 'additionalProperties': False, 'required': ['message'], 'properties': {'message': {'type': 'string'}}}
        result = provider.complete('Self-test.', [{'role': 'user', 'content': 'ping'}], response_schema=schema)
    finally:
        server.shutdown()
        server.server_close()
    if result != {'message': 'ok'}:
        raise RuntimeError('unexpected reply: '+repr(result)[:200])
    import anthropic
    return 'anthropic '+anthropic.__version__+' streamed a structured reply'


CHECKS = [('bundle', check_bundle), ('https', check_https), ('qt', check_qt),
          ('speech', check_speech), ('natural_voice', check_natural_voice), ('claude', check_claude)]


def run(output):
    results, ok = [], True
    for name, check in CHECKS:
        started = time.monotonic()
        try:
            detail, passed = check(), True
        except Exception as error:
            detail, passed = type(error).__name__+': '+str(error)[:400]+'\n'+traceback.format_exc()[-1500:], False
        ok = ok and passed
        results.append({'check': name, 'ok': passed, 'detail': detail, 'seconds': round(time.monotonic()-started, 1)})
    text = json.dumps({'ok': ok, 'frozen': paths.frozen(), 'platform': sys.platform, 'results': results}, indent=2)
    with open(output, 'w', encoding='utf-8') as handle:
        handle.write(text)
    print(text, flush=True)
    return 0 if ok else 1
