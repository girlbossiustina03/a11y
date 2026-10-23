"""Natural local voice (Kokoro, open weights) with the QTextToSpeech methods A11y uses.

Speech is generated on this computer sentence by sentence; the first sentence starts
playing while the rest are still being generated. Text and audio never leave the
computer. When the package or model files are missing, A11y keeps the system voice.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import threading

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, pyqtSignal

MODEL_FILE, VOICES_FILE = 'kokoro-v1.0.onnx', 'voices-v1.0.bin'
MODEL_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
DEFAULT_VOICE = 'af_heart'          # warm, natural US English female voice
SAMPLE_RATE = 24000


def split_sentences(text, limit=280):
    """Short chunks so playback starts quickly; long sentences are split at commas."""
    chunks = []
    for sentence in re.split(r'(?<=[.!?…])\s+|\n+', text.strip()):
        sentence = sentence.strip()
        while len(sentence) > limit:
            cut = sentence.rfind(',', 0, limit)
            cut = cut+1 if cut > limit//3 else limit
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


def model_directory(data_directory):
    return Path(os.getenv('A11Y_TTS_DIR') or Path(data_directory)/'tts')


def neural_voice_available(data_directory):
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        return False
    folder = model_directory(data_directory)
    return (folder/MODEL_FILE).is_file() and (folder/VOICES_FILE).is_file()


def download_models(data_directory, progress=None):
    """Fetch the open model files once (about 340 MB), from setup or after voice is turned on.
    progress(fraction or None) is called while downloading."""
    import urllib.request
    folder = model_directory(data_directory)
    folder.mkdir(parents=True, exist_ok=True)
    for name in (VOICES_FILE, MODEL_FILE):
        target = folder/name
        if not target.is_file():
            partial = target.with_suffix(target.suffix+'.part')
            hook = None
            if progress:
                def hook(blocks, size, total):
                    progress(min(1.0, blocks*size/total) if total > 0 else None)
            urllib.request.urlretrieve(MODEL_URL+name, partial, hook)
            partial.replace(target)


class _State:
    def __init__(self, name):
        self.name = name


class NeuralVoice(QObject):
    stateChanged = pyqtSignal(object)
    _chunk_ready = pyqtSignal(int, bytes)
    _chunk_failed = pyqtSignal(int, str)

    def __init__(self, data_directory, parent=None, *, voice=None, speed=None):
        super().__init__(parent)
        folder = model_directory(data_directory)
        self.model_path, self.voices_path = folder/MODEL_FILE, folder/VOICES_FILE
        self.voice = voice or os.getenv('A11Y_VOICE', DEFAULT_VOICE)
        self.speed = float(speed or os.getenv('A11Y_VOICE_SPEED', '1.0'))
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.engine = None
        self.lock = threading.Lock()
        self.generation = 0
        self.pending = 0          # chunks still being generated
        self.queue = []           # generated audio waiting to play
        self.sink = self.buffer = None
        self.current = 'Ready'
        self.failed_message = ''
        self._chunk_ready.connect(self._queue_audio)
        self._chunk_failed.connect(self._failed)
        self.executor.submit(self._engine)   # load in the background so the first reply is quick

    # --- QTextToSpeech-compatible surface used by the companion ---
    def state(self):
        return _State(self.current)

    def say(self, text):
        self.stop()
        self.enqueue(text)

    def enqueue(self, text):
        chunks = split_sentences(text)
        if not chunks:
            return
        self.pending += len(chunks)
        self._set_state('Synthesizing' if self.current == 'Ready' else self.current)
        generation = self.generation
        for chunk in chunks:
            self.executor.submit(self._synthesize, chunk, generation)

    def stop(self):
        self.generation += 1
        self.pending = 0
        self.queue.clear()
        if self.sink is not None:
            self.sink.stop()
        self._set_state('Ready')

    # --- Generation (worker thread) ---
    def _engine(self):
        with self.lock:
            if self.engine is None:
                from kokoro_onnx import Kokoro
                self.engine = Kokoro(str(self.model_path), str(self.voices_path))
            return self.engine

    def _synthesize(self, text, generation):
        if generation != self.generation:
            return
        try:
            import numpy as np
            samples, rate = self._engine().create(text, voice=self.voice, speed=self.speed,
                                                  lang='en-gb' if self.voice.startswith('b') else 'en-us')
            if rate != SAMPLE_RATE:
                samples = np.interp(np.arange(0, len(samples), rate/SAMPLE_RATE), np.arange(len(samples)), samples)
            pcm = (np.clip(samples, -1, 1)*32767).astype(np.int16).tobytes()
            self._chunk_ready.emit(generation, pcm)
        except Exception as error:
            self._chunk_failed.emit(generation, str(error)[:200])

    # --- Playback (GUI thread) ---
    def _ensure_sink(self):
        if self.sink is None:
            from PyQt6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
            audio_format = QAudioFormat()
            audio_format.setSampleRate(SAMPLE_RATE)
            audio_format.setChannelCount(1)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            self.sink = QAudioSink(QMediaDevices.defaultAudioOutput(), audio_format, self)
            self.sink.stateChanged.connect(self._sink_state)

    def _queue_audio(self, generation, pcm):
        if generation != self.generation:
            return
        self.pending = max(0, self.pending-1)
        self.queue.append(pcm)
        if self.current != 'Speaking':
            self._play_next()

    def _failed(self, generation, message):
        if generation != self.generation:
            return
        self.failed_message = message
        self.pending = max(0, self.pending-1)
        if not self.pending and not self.queue and self.current != 'Speaking':
            self._set_state('Ready')

    def _play_next(self):
        if not self.queue:
            self._set_state('Synthesizing' if self.pending else 'Ready')
            return
        self._ensure_sink()
        self.buffer = QBuffer(self)
        self.buffer.setData(QByteArray(self.queue.pop(0)))
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._set_state('Speaking')
        self.sink.start(self.buffer)

    def _sink_state(self, state):
        from PyQt6.QtMultimedia import QAudio
        if state == QAudio.State.IdleState and self.current == 'Speaking':
            self.sink.stop()
            self._play_next()

    def _set_state(self, name):
        if name != self.current:
            self.current = name
            self.stateChanged.emit(_State(name))
