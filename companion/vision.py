"""Session consent, local-only request-time screen vision. Never records or saves frames."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from .ollama import OllamaProvider


class ScreenVision:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.binary = self.directory/'screen-bridge'
        self.source = Path(__file__).resolve().parent.parent/'native'/'ScreenBridge.swift'
        self.enabled = False
        self.generation = 0
        self.lock = threading.Lock()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.generation += 1

    def prepare(self):
        if sys.platform != 'darwin':
            raise RuntimeError('Native screen vision currently requires macOS 14 or later.')
        with self.lock:
            if self.binary.exists() and self.binary.stat().st_mtime >= self.source.stat().st_mtime:
                return
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                result = subprocess.run(['xcrun', 'swiftc', '-parse-as-library', '-O', '-module-cache-path',
                    str(self.directory/'swift-cache'), str(self.source), '-o', str(self.binary)],
                    capture_output=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                raise RuntimeError('Screen vision needs Xcode Command Line Tools. Run xcode-select --install.') from None
            if result.returncode:
                raise RuntimeError('Could not build screen vision. Check Xcode Command Line Tools.')

    def call(self, *args):
        if sys.platform == 'win32':
            return self.windows_call(*args)
        self.prepare()
        try:
            result = subprocess.run([str(self.binary), '--exclude-pid', str(os.getpid()), *args],
                                    capture_output=True, timeout=15)
            if len(result.stdout) > 12_000_000:
                raise RuntimeError('Screen image exceeded the size limit.')
            data = json.loads(result.stdout)
            if data.get('error'):
                raise RuntimeError(str(data['error']))
            return data
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise RuntimeError('Screen vision could not capture a frame. Check Screen Recording permission.') from None

    def windows_call(self, *args):
        from .windows_screen import WindowsScreenBridge
        try:
            if not hasattr(self, 'windows_bridge'):
                self.windows_bridge = WindowsScreenBridge()
            data = self.windows_bridge.call(*args)
        except (OSError, AttributeError, ValueError):
            raise RuntimeError('Screen vision could not capture a frame on this version of Windows.') from None
        if data.get('error'):
            raise RuntimeError(str(data['error']))
        return data

    def request_access(self):
        return self.call('--request-access')

    def capture(self, provider, *, x=0, y=0, desktop=None):
        if not self.enabled:
            raise RuntimeError('Screen vision is paused. Enable it from the character’s right-click menu.')
        if not isinstance(provider, OllamaProvider):
            raise RuntimeError('Automatic screen vision is restricted to local Ollama. Use previewed capture for other providers.')
        model = provider.config.vision_model or provider.config.model
        if 'vision' not in provider.model_info(model).get('capabilities', []):
            raise RuntimeError('Choose an installed image-capable Ollama model to use screen vision.')
        if desktop and (desktop.get('status') == 'private_app' or desktop.get('focused_role') == 'secure_input'):
            raise RuntimeError('Screen vision paused for a protected app or password field.')
        generation = self.generation
        data = self.call('--x', str(x), '--y', str(y))
        if not self.enabled or generation != self.generation:
            raise RuntimeError('Screen vision was paused before capture completed. The frame was discarded.')
        if not isinstance(data.get('image_data'), str) or not data['image_data'].startswith('data:image/png;base64,'):
            raise RuntimeError('No screen image was captured. I cannot infer what is visible.')
        data['captured_monotonic'] = time.monotonic()
        return data
