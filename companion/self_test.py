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


CHECKS = [('bundle', check_bundle), ('https', check_https), ('qt', check_qt),
          ('speech', check_speech), ('natural_voice', check_natural_voice)]


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
