"""First-run readiness: Ollama and the local models, installed with the user's consent.

Everything here is plain code (no model calls). Downloads come only from ollama.com
over HTTPS, and installers are checked for a valid code signature before use.
Nothing is installed without an explicit choice in the setup window."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

OLLAMA = 'http://127.0.0.1:11434'
DOWNLOADS = {'darwin': 'https://ollama.com/download/Ollama-darwin.zip',
             'win32': 'https://ollama.com/download/OllamaSetup.exe'}


class SetupError(RuntimeError):
    pass


def memory_gb():
    try:
        if sys.platform == 'darwin':
            return int(subprocess.run(['sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, timeout=5).stdout)/2**30
        if sys.platform == 'win32':
            class Status(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                            ('available', ctypes.c_ulonglong), ('page_total', ctypes.c_ulonglong), ('page_free', ctypes.c_ulonglong),
                            ('virtual_total', ctypes.c_ulonglong), ('virtual_free', ctypes.c_ulonglong), ('extended', ctypes.c_ulonglong)]
            status = Status(length=ctypes.sizeof(Status))
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.total/2**30
        return os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')/2**30
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return 0


def recommended_models(memory=None):
    """(text model, vision model). Measured live on an M5 Pro: the 4B pair answers chat in ~0.7 s
    and runs task steps in ~3–5 s; smaller machines get the 2B vision model."""
    memory = memory_gb() if memory is None else memory
    if memory and memory < 15:
        return 'qwen3:1.7b', 'qwen3-vl:2b-instruct'
    return 'qwen3:4b-instruct', 'qwen3-vl:4b-instruct'


def request(path, body=None, timeout=5):
    req = urllib.request.Request(OLLAMA+path, None if body is None else json.dumps(body).encode(),
                                 {'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback only
    return opener.open(req, timeout=timeout)


def ollama_running():
    try:
        with request('/api/version', timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def installed_models():
    try:
        with request('/api/tags', timeout=5) as response:
            return {item.get('name', '') for item in json.loads(response.read()).get('models', [])}
    except (OSError, ValueError):
        return set()


def has_model(name, models):
    return name in models or (':' not in name and name+':latest' in models)


def ollama_app():
    """The installed Ollama app or executable, or None."""
    if sys.platform == 'darwin':
        for path in (Path('/Applications/Ollama.app'), Path.home()/'Applications'/'Ollama.app'):
            if path.exists():
                return path
    elif sys.platform == 'win32':
        path = Path(os.getenv('LOCALAPPDATA', ''))/'Programs'/'Ollama'/'ollama app.exe'
        if path.exists():
            return path
    found = shutil.which('ollama')
    return Path(found) if found else None


def status():
    running = ollama_running()
    models = installed_models() if running else set()
    text, vision = recommended_models()
    return {'ollama_installed': running or ollama_app() is not None, 'ollama_running': running,
            'text_model': text, 'vision_model': vision,
            'text_ready': has_model(text, models), 'vision_ready': has_model(vision, models),
            'supported': sys.platform in DOWNLOADS}


def download(url, destination, progress, cancel=None):
    with urllib.request.urlopen(url, timeout=30) as response:
        total = int(response.headers.get('Content-Length') or 0)
        done = 0
        with open(destination, 'wb') as handle:
            while True:
                if cancel is not None and cancel.is_set():
                    raise SetupError('Setup was cancelled.')
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                progress('Downloading Ollama…', done/total if total else None)


def install_ollama(progress, cancel=None):
    """Download Ollama from ollama.com, verify its signature, install and start it."""
    if sys.platform not in DOWNLOADS:
        raise SetupError('Install Ollama from https://ollama.com/download on this system.')
    work = Path(tempfile.mkdtemp(prefix='a11y-setup-'))
    try:
        if sys.platform == 'darwin':
            archive = work/'Ollama-darwin.zip'
            download(DOWNLOADS['darwin'], archive, progress, cancel)
            progress('Checking the download…', None)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(work)
            app = work/'Ollama.app'
            # ditto/unzip keep exec bits; zipfile does not, so restore them for the binaries.
            for binary in (app/'Contents'/'MacOS').glob('*') if app.exists() else []:
                binary.chmod(0o755)
            for binary in (app/'Contents'/'Resources').glob('ollama*'):
                binary.chmod(0o755)
            check = subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], capture_output=True, timeout=120)
            if not app.exists() or check.returncode:
                raise SetupError('The Ollama download could not be verified, so it was not installed.')
            target = Path('/Applications') if os.access('/Applications', os.W_OK) else Path.home()/'Applications'
            target.mkdir(exist_ok=True)
            destination = target/'Ollama.app'
            if destination.exists():
                shutil.rmtree(destination)
            progress('Installing Ollama…', None)
            subprocess.run(['ditto', str(app), str(destination)], check=True, timeout=300)
        else:
            installer = work/'OllamaSetup.exe'
            download(DOWNLOADS['win32'], installer, progress, cancel)
            progress('Checking the download…', None)
            signature = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                '(Get-AuthenticodeSignature -LiteralPath $args[0]).Status', str(installer)],
                capture_output=True, text=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if signature.stdout.strip() != 'Valid':
                raise SetupError('The Ollama installer signature could not be verified, so it was not run.')
            progress('Installing Ollama…', None)
            subprocess.run([str(installer), '/VERYSILENT', '/NORESTART', '/SUPPRESSMSGBOXES'], check=True, timeout=900)
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        raise SetupError('Ollama could not be installed: '+str(error)[:200]) from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    start_ollama(progress)


def start_ollama(progress=lambda *a: None, wait=60):
    if ollama_running():
        return
    app = ollama_app()
    if app is None:
        raise SetupError('Ollama is not installed.')
    progress('Starting Ollama…', None)
    if sys.platform == 'darwin' and app.suffix == '.app':
        subprocess.Popen(['open', '-g', str(app)])
    elif sys.platform == 'win32' and app.name.endswith('app.exe'):
        subprocess.Popen([str(app)], creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
    else:
        subprocess.Popen([str(app), 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    deadline = time.monotonic()+wait
    while time.monotonic() < deadline:
        if ollama_running():
            return
        time.sleep(1)
    raise SetupError('Ollama did not start. Open the Ollama app, then try again.')


def pull_model(name, progress, cancel=None):
    """Download one model through Ollama's own API, reporting progress."""
    try:
        with request('/api/pull', {'model': name, 'stream': True}, timeout=3600) as response:
            for line in response:
                if cancel is not None and cancel.is_set():
                    raise SetupError('Setup was cancelled.')
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get('error'):
                    raise SetupError('Could not download '+name+': '+str(event['error'])[:200])
                total, done = event.get('total'), event.get('completed')
                progress('Downloading '+name+'…', done/total if total and done is not None else None)
    except (OSError, ValueError) as error:
        raise SetupError('Could not download '+name+': '+str(error)[:200]) from None


def voice_status(data_directory):
    """What spoken conversation needs, as shipped in this build: Whisper speech recognition
    and, where bundled, the natural Kokoro voice. Packages missing from the build are not
    'missing downloads' (the app then uses the system voice), so they are reported as unsupported."""
    import importlib.util
    from . import voice, neural_voice
    speech_supported = importlib.util.find_spec('faster_whisper') is not None
    natural_supported = importlib.util.find_spec('kokoro_onnx') is not None
    speech_ready = True
    if speech_supported:
        try:
            with voice.WHISPER_IMPORT:
                from faster_whisper.utils import download_model
            for name in (voice.WAKE_MODEL, voice.SPEECH_MODEL):
                download_model(name, local_files_only=True)
        except Exception:  # not cached yet (or the cache is unreadable)
            speech_ready = False
    return {'speech_supported': speech_supported, 'speech_ready': speech_ready,
            'natural_supported': natural_supported,
            'natural_ready': not natural_supported or neural_voice.neural_voice_available(data_directory)}


def prepare_voice(progress, cancel=None, data_directory=None):
    """Download the speech recognition models and the natural voice, if this build has them."""
    from . import voice, neural_voice
    state = voice_status(data_directory)
    if state['speech_supported'] and not state['speech_ready']:
        with voice.WHISPER_IMPORT:
            from faster_whisper.utils import download_model
        for name in (voice.WAKE_MODEL, voice.SPEECH_MODEL):
            if cancel is not None and cancel.is_set():
                raise SetupError('Setup was cancelled.')
            progress('Downloading speech recognition ('+name+')…', None)
            try:
                download_model(name)
            except Exception as error:
                raise SetupError('Could not download the speech model '+name+': '+str(error)[:200]) from None
    if state['natural_supported'] and not state['natural_ready'] and data_directory is not None:
        if cancel is not None and cancel.is_set():
            raise SetupError('Setup was cancelled.')
        progress('Downloading the natural voice…', None)
        def report(fraction):
            if cancel is not None and cancel.is_set():
                raise SetupError('Setup was cancelled.')
            progress('Downloading the natural voice…', fraction)
        try:
            neural_voice.download_models(data_directory, report)
        except SetupError:
            raise
        except Exception as error:
            raise SetupError('Could not download the natural voice: '+str(error)[:200]) from None


def prepare_everything(progress, cancel=None, models=None, data_directory=None):
    """Install/start Ollama, pull the recommended models and fetch the voice models. Returns (text, vision)."""
    text, vision = models or recommended_models()
    if not ollama_running():
        if ollama_app() is None:
            install_ollama(progress, cancel)
        else:
            start_ollama(progress)
    present = installed_models()
    for name in dict.fromkeys((text, vision)):
        if not has_model(name, present):
            pull_model(name, progress, cancel)
    prepare_voice(progress, cancel, data_directory)
    progress('Ready.', 1.0)
    return text, vision
