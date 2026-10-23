"""Local voice conversation: "Hey Ally" wake phrase, speech-to-text and turn taking.

Audio never leaves the computer and is never written to disk. The microphone stream is
split into utterances by an energy detector; only utterances are transcribed, with
faster-whisper (tiny.en to spot the wake phrase, small.en for requests). Transcripts go
through exactly the same path as typed text.
"""
from concurrent.futures import ThreadPoolExecutor
import re
import subprocess
import sys
import threading
import time
from . import paths

SAMPLE_RATE = 16000
FRAME = 480                      # 30 ms
WAKE_MODEL, SPEECH_MODEL = 'tiny.en', 'small.en'
CONVERSATION_TIMEOUT = 30        # seconds without speech before waiting for "Hey Ally" again

_NAME = r'(?:ally|allie|alley|ali|alli|aly|ally\'s|alle|ellie|elly|allee|a11y)'
_WAKE = re.compile(r'^\W*(?:(?:hey|hi|hay|okay|ok|hello)\W+)' + _NAME + r'\b\W*(.*)$', re.IGNORECASE | re.DOTALL)
_FAREWELL = re.compile(r'^\W*(?:(?:ok(?:ay)?|thanks?|thank you)\W+)*(?:good ?bye|bye(?: bye)?|bye ally|stop listening|'
                       r'that\'?s all|that is all|go to sleep|we\'?re done|i\'?m done)\b', re.IGNORECASE)
_YES = re.compile(r'^\W*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|confirm(?:ed)?|do it|go ahead|please do|correct|right)\b'
                  r'(?:\W+(?:please|do it|go ahead|confirm))*\W*$', re.IGNORECASE)
_NO = re.compile(r'^\W*(?:no|nope|nah|cancel|don\'?t|do not|stop|never mind|nevermind|wait)\b', re.IGNORECASE)


def words(text):
    return re.findall(r"[a-z0-9']+", text.casefold())


def wake_split(text):
    """Return the request after "Hey Ally" ('' when there is none), or None without the wake phrase."""
    match = _WAKE.match(text.strip())
    return None if match is None else match.group(1).strip(' .,!?')


def is_farewell(text):
    return bool(_FAREWELL.match(text))


def is_yes(text):
    return bool(_YES.match(text))


def is_no(text):
    return bool(_NO.match(text))


def match_choice(text, choices):
    """Pick the offered choice the user named. choices: [(title, action)]; None when unclear."""
    spoken = set(words(text))
    if not spoken:
        return None
    scored = []
    for title, action in choices:
        title_words = set(words(title))-{'the', 'a', 'an', 'to', 'my', 'me', 'this', 'that'}
        if title_words and title_words <= spoken | {'open', 'close', 'show'}:
            scored.append((len(title_words), title, action))
    ordinals = {'first': 0, 'one': 0, 'second': 1, 'two': 1, 'third': 2, 'three': 2}
    for word, index in ordinals.items():
        if word in spoken and index < len(choices) and not scored:
            return choices[index]
    if not scored:
        return None
    scored.sort(reverse=True)
    best = [item for item in scored if item[0] == scored[0][0]]
    return (best[0][1], best[0][2]) if len(best) == 1 else None


def speakable(message):
    """Text for the voice: no markdown symbols, citations or URLs read character by character."""
    text = re.sub(r'https?://\S+', 'a link', message)
    text = re.sub(r'\[[^\]]*\]', '', text)
    text = re.sub(r'[*_#`>|]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


class Segmenter:
    """Energy-based utterance detector with an adaptive noise floor (int16 mono, 16 kHz)."""
    def __init__(self, *, end_silence=0.8, max_seconds=15, min_seconds=0.35):
        self.end_frames = int(end_silence*SAMPLE_RATE/FRAME)
        self.max_frames = int(max_seconds*SAMPLE_RATE/FRAME)
        self.min_frames = int(min_seconds*SAMPLE_RATE/FRAME)
        self.noise = 300.0
        self.reset()

    def reset(self):
        import numpy as np
        self.pending = np.zeros(0, dtype=np.int16)
        self.preroll, self.frames = [], []
        self.loud = self.quiet = 0
        self.active = False

    def feed(self, samples):
        """Add int16 samples; return a list of finished utterances as float32 arrays."""
        import numpy as np
        finished = []
        data = np.concatenate([self.pending, samples])
        usable = len(data)//FRAME*FRAME
        self.pending = data[usable:]
        for start in range(0, usable, FRAME):
            frame = data[start:start+FRAME]
            rms = float(np.sqrt(np.mean(frame.astype(np.float32)**2)))
            if not self.active:
                self.preroll = (self.preroll+[frame])[-10:]
                self.loud = self.loud+1 if rms > max(3*self.noise, 400) else 0
                if self.loud >= 3:
                    self.active, self.frames, self.quiet = True, list(self.preroll), 0
                else:
                    self.noise = min(3000.0, max(50.0, 0.95*self.noise+0.05*rms))
                continue
            self.frames.append(frame)
            self.quiet = self.quiet+1 if rms < max(2*self.noise, 300) else 0
            if self.quiet >= self.end_frames or len(self.frames) >= self.max_frames:
                if len(self.frames)-self.quiet >= self.min_frames:
                    finished.append(np.concatenate(self.frames).astype(np.float32)/32768)
                self.active, self.preroll, self.frames, self.loud = False, [], [], 0
        return finished


class Transcriber:
    """faster-whisper models, loaded once in the background and reused."""
    def __init__(self):
        self.models = {}
        self.lock = threading.Lock()

    def model(self, name):
        with self.lock:
            if name not in self.models:
                import os
                # Model files are cached by Hugging Face Hub; copies instead of symlinks are fine on Windows.
                os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
                from faster_whisper import WhisperModel
                self.models[name] = WhisperModel(name, device='cpu', compute_type='int8', cpu_threads=4)
            return self.models[name]

    def transcribe(self, audio, name, *, prompt=None):
        segments, _ = self.model(name).transcribe(audio, language='en', beam_size=1 if name == WAKE_MODEL else 5,
                                                  initial_prompt=prompt, condition_on_previous_text=False,
                                                  vad_filter=name != WAKE_MODEL)
        return ''.join(segment.text for segment in segments).strip()


def voice_available():
    try:
        import faster_whisper  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


try:
    from PyQt6.QtCore import QObject, QTimer, pyqtSignal
except ImportError:  # pure helpers above stay importable without Qt
    QObject = object


class VoiceListener(QObject):
    """Microphone → utterances → text. Modes: off, wake (waiting for "Hey Ally"), conversation, paused."""
    if QObject is not object:
        status = pyqtSignal(str)
        woke = pyqtSignal(str)          # request spoken together with the wake phrase ('' if none)
        heard = pyqtSignal(str)         # a conversation utterance
        timed_out = pyqtSignal()
        failed = pyqtSignal(str)
        ready = pyqtSignal()

    def __init__(self, parent=None, *, transcriber=None):
        super().__init__(parent)
        self.transcriber = transcriber or Transcriber()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.segmenter = Segmenter()
        self.mode = 'off'
        self.capturing = False
        self.busy = False
        self.generation = 0
        self.source = self.device = None
        self.heard_signal = False
        self.last_speech = time.monotonic()
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.check_idle)

    def start(self):
        if self.mode != 'off':
            return
        if not voice_available():
            self.failed.emit('Voice needs the speech package. Install it with: pip install -r requirements-voice.txt')
            return
        self.mode = 'loading'
        self.status.emit('Getting my ears ready… (the first time downloads the speech models)')
        self.executor.submit(self._load)

    def _load(self):
        try:
            self.transcriber.model(WAKE_MODEL)
            self.transcriber.model(SPEECH_MODEL)
        except Exception as error:  # download or runtime problem; reported in the UI
            self.failed.emit('The speech models could not be loaded: '+str(error)[:200])
            return
        self.ready.emit()

    def microphone_permission(self):
        """'granted', 'denied' or 'asking'. macOS only answers apps that ask first: without the
        request it hands an unapproved app silence instead of an error. Elsewhere Qt reports granted."""
        from PyQt6.QtCore import QCoreApplication, QMicrophonePermission, Qt
        app = QCoreApplication.instance()
        if app is None or sys.platform != 'darwin':
            return 'granted'
        permission = QMicrophonePermission()
        state = app.checkPermission(permission)
        if state == Qt.PermissionStatus.Granted:
            return 'granted'
        if state == Qt.PermissionStatus.Undetermined:
            app.requestPermission(permission, self, self.permission_answered)
            self.status.emit('Allow microphone access so I can hear you.')
            return 'asking'
        # Running from source, Python has no usage description, so Qt says denied without asking;
        # macOS then attributes the microphone to the terminal app, which asks on its own.
        return 'denied' if paths.frozen() else 'granted'

    def permission_answered(self, permission):
        from PyQt6.QtCore import Qt
        if permission.status() == Qt.PermissionStatus.Granted:
            self.open_microphone()
        else:
            self.microphone_denied()

    def microphone_denied(self):
        self.mode = 'off'
        self.failed.emit('Microphone access is off for A11y. Turn it on in System Settings → Privacy & Security → '
                         'Microphone, then turn voice on again.')
        if sys.platform == 'darwin':
            subprocess.Popen(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone'])

    def open_microphone(self):
        """Called on the GUI thread once the models are ready."""
        from PyQt6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        permission = self.microphone_permission()
        if permission == 'asking':
            return True
        if permission == 'denied':
            self.microphone_denied()
            return False
        device = QMediaDevices.defaultAudioInput()
        audio_format = QAudioFormat()
        audio_format.setSampleRate(SAMPLE_RATE)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if device.isNull() or not device.isFormatSupported(audio_format):
            self.mode = 'off'
            self.failed.emit('No usable microphone was found. Check that one is connected and enabled.')
            return False
        self.source = QAudioSource(device, audio_format, self)
        self.heard_signal = False
        self.device = self.source.start()
        self.device.readyRead.connect(self.read_audio)
        self.idle_timer.start(1000)
        QTimer.singleShot(2500, self.check_microphone)
        self.wait_for_wake()
        return True

    def check_microphone(self):
        from PyQt6.QtMultimedia import QAudio
        if self.source is None:
            return
        # A blocked microphone shows up as an error on Windows and as pure digital silence on macOS.
        if self.source.error() != QAudio.Error.NoError or not self.heard_signal:
            self.stop()
            self.failed.emit('The microphone is blocked. On Windows allow it in Settings → Privacy & security → '
                             'Microphone → "Let desktop apps access your microphone". On macOS turn on A11y in '
                             'System Settings → Privacy & Security → Microphone.')

    def stop(self):
        self.generation += 1
        self.mode = 'off'
        self.capturing = False
        self.idle_timer.stop()
        if self.source is not None:
            self.source.stop()
            self.source = self.device = None
        self.status.emit('Voice is off.')

    def wait_for_wake(self):
        if self.source is None:
            return
        self.mode, self.capturing = 'wake', True
        self.segmenter = Segmenter(end_silence=0.6, max_seconds=12)
        self.status.emit('Say “Hey Ally” to talk to me.')

    def listen(self):
        """Take the next conversation turn."""
        if self.source is None:
            return
        self.mode, self.capturing = 'conversation', True
        self.segmenter = Segmenter(end_silence=0.9, max_seconds=20)
        self.last_speech = time.monotonic()
        self.status.emit('Listening…')

    def pause(self):
        """Ignore the microphone, e.g. while A11y speaks or works on a request."""
        self.capturing = False
        self.generation += 1

    def check_idle(self):
        if self.mode == 'conversation' and self.capturing and not self.busy and not self.segmenter.active \
                and time.monotonic()-self.last_speech > CONVERSATION_TIMEOUT:
            self.pause()
            self.timed_out.emit()

    def read_audio(self):
        import numpy as np
        if self.device is None:
            return
        data = bytes(self.device.readAll())
        if data and not self.heard_signal and data.strip(b'\x00'):
            self.heard_signal = True
        if not self.capturing or self.busy or not data:
            return
        samples = np.frombuffer(data[:len(data)//2*2], dtype=np.int16)
        if self.segmenter.active:
            self.last_speech = time.monotonic()
        for utterance in self.segmenter.feed(samples):
            if self.mode == 'conversation':
                self.capturing = False   # one turn at a time; the app resumes listening after replying
            self.busy = True
            self.status.emit('Understanding…' if self.mode == 'conversation' else 'Say “Hey Ally” to talk to me.')
            self.executor.submit(self._transcribe, utterance, self.mode, self.generation)

    def _transcribe(self, audio, mode, generation):
        try:
            if mode == 'wake':
                quick = self.transcriber.transcribe(audio, WAKE_MODEL, prompt='Hey Ally.')
                rest = wake_split(quick)
                if rest is None or generation != self.generation:
                    return
                if len(words(rest)) >= 2:
                    # The request came with the wake phrase: transcribe it accurately.
                    full = self.transcriber.transcribe(audio, SPEECH_MODEL, prompt='Hey Ally.')
                    accurate = wake_split(full)
                    rest = accurate if accurate is not None else rest
                self.woke.emit(rest)
            else:
                text = self.transcriber.transcribe(audio, SPEECH_MODEL)
                if generation != self.generation:
                    return
                if words(text):
                    self.heard.emit(text)
                else:
                    self.heard.emit('')   # noise: the app simply listens again
        except Exception as error:
            self.failed.emit('I could not understand that audio: '+str(error)[:200])
        finally:
            self.busy = False
