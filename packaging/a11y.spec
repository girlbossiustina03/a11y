# PyInstaller spec for the A11y desktop companion (macOS .app, Windows folder build).
# Build with packaging/build_macos.sh or packaging/build_windows.ps1.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
ICONS = ROOT/'packaging'/'icons'
datas = [(str(ROOT/'native'/'DesktopBridge.swift'), 'native'), (str(ROOT/'native'/'ScreenBridge.swift'), 'native'),
         (str(ROOT/'examples'), 'examples'), (str(ROOT/'index.html'), '.'), (str(ROOT/'app.js'), '.'), (str(ROOT/'style.css'), '.')]
binaries = []
# Swift helpers compiled at build time (macOS), so users need no Xcode tools.
helpers = ROOT/'build'/'native-bin'
for name in ('desktop-bridge', 'screen-bridge'):
    if (helpers/name).exists():
        binaries.append((str(helpers/name), 'native/bin'))
hiddenimports = []
# Model-conversion and test tooling A11y never runs at runtime. Importing onnxruntime.quantization
# during the build crashes PyInstaller's isolated child on Windows, so it is left out entirely.
import re
UNUSED = re.compile(r'^onnxruntime\.(quantization|transformers|tools)(\.|$)|(^|\.)tests?(\.|$)')
UNUSED_MODULES = ['onnxruntime.quantization', 'onnxruntime.transformers', 'onnxruntime.tools']
# Optional voice stack: bundled when installed in the build environment.
for package in ('faster_whisper', 'ctranslate2', 'kokoro_onnx', 'onnxruntime', 'espeakng_loader', 'sounddevice', 'tokenizers'):
    try:
        package_datas, package_binaries, package_imports = collect_all(package, filter_submodules=lambda name: not UNUSED.search(name))
    except Exception:
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
if sys.platform == 'win32':
    hiddenimports += ['comtypes', 'comtypes.client', 'winrt.windows.media.ocr', 'winrt.windows.graphics.imaging',
                      'winrt.windows.storage.streams', 'winrt.windows.foundation']

analysis = Analysis([str(ROOT/'a11y_desktop.py')], pathex=[str(ROOT)], binaries=binaries, datas=datas,
                    hiddenimports=hiddenimports, excludes=['tkinter', 'unittest', 'pydoc']+UNUSED_MODULES, noarchive=False)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='A11y', console=False,
          icon=str(ICONS/('A11y.ico' if sys.platform == 'win32' else 'A11y.icns')),
          codesign_identity=None, entitlements_file=None)
collected = COLLECT(exe, analysis.binaries, analysis.datas, name='A11y')

if sys.platform == 'darwin':
    app = BUNDLE(collected, name='A11y.app', icon=str(ICONS/'A11y.icns'), bundle_identifier='com.a11y.companion',
                 info_plist={
                     'CFBundleName': 'A11y', 'CFBundleDisplayName': 'A11y',
                     'CFBundleShortVersionString': '0.9.1', 'CFBundleVersion': '0.9.1',
                     'LSMinimumSystemVersion': '14.0', 'NSHighResolutionCapable': True,
                     'NSMicrophoneUsageDescription': 'A11y listens for “Hey Ally” and your spoken requests when you turn voice on. Audio is processed on this Mac and never saved.',
                     'NSAppleEventsUsageDescription': 'A11y controls Music and Safari only when you ask it to play a song or open a page.',
                     'NSScreenCaptureUsageDescription': 'A11y looks at your screen only when you ask for help with what is on it. Images stay on this Mac.',
                 })
