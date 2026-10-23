"""'Get A11y ready' window: installs Ollama and the local models after an explicit choice."""
import threading
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout
from . import installer
from .theme import PANEL_STYLE


class StatusWorker(QObject):
    """Checks Ollama and the models on a daemon thread, so closing a window or quitting
    never has to wait for (or abort on) a slow local HTTP check."""
    result = pyqtSignal(object)

    def __init__(self, models=None, parent=None):
        super().__init__(parent)
        self.models = models

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        value = installer.status()
        if self.models and all(self.models):
            present = installer.installed_models() if value['ollama_running'] else set()
            value.update(text_model=self.models[0], vision_model=self.models[1],
                         text_ready=installer.has_model(self.models[0], present),
                         vision_ready=installer.has_model(self.models[1], present))
        value['ready'] = value['ollama_running'] and value['text_ready'] and value['vision_ready']
        try:
            self.result.emit(value)
        except RuntimeError:  # the window was closed while checking
            pass


class SetupWorker(QThread):
    progress = pyqtSignal(str, float)
    finished_ok = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(self, models, parent=None):
        super().__init__(parent)
        self.models = models
        self.cancel = threading.Event()

    def run(self):
        try:
            text, vision = installer.prepare_everything(
                lambda message, fraction: self.progress.emit(message, -1.0 if fraction is None else float(fraction)),
                self.cancel, self.models)
            self.finished_ok.emit(text, vision)
        except installer.SetupError as error:
            self.failed.emit(str(error))


class ReadinessDialog(QDialog):
    """Shows what is missing and installs it only when the user presses Set up."""

    def __init__(self, owner, status):
        super().__init__(owner)
        self.owner, self.status, self.worker = owner, status, None
        self.setWindowTitle('Get A11y ready')
        self.setMinimumWidth(460)
        self.setStyleSheet(PANEL_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(14)
        title = QLabel('Get A11y ready')
        title.setObjectName('settingsPageTitle')
        layout.addWidget(title)
        intro = QLabel('A11y runs its AI on this computer with Ollama, so your screen and words stay here. '
                       'Setup downloads what is missing. Nothing is installed until you choose Set up.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        rows = [('Ollama (local AI runtime, from ollama.com)', status['ollama_running'] or status['ollama_installed']),
                ('Language model: '+status['text_model'], status['text_ready']),
                ('Vision model: '+status['vision_model'], status['vision_ready'])]
        for text, done in rows:
            row = QLabel(('✓  ' if done else '○  ')+text)
            row.setAccessibleName(text+(' is ready' if done else ' will be installed'))
            layout.addWidget(row)
        note = QLabel('Models are a few gigabytes in total; the first download can take several minutes.')
        note.setObjectName('detailLabel')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.message = QLabel('')
        self.message.setWordWrap(True)
        self.message.setAccessibleName('Setup progress')
        layout.addWidget(self.message)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.later = QPushButton('Not now')
        self.later.clicked.connect(self.close_or_cancel)
        self.start = QPushButton('Set up')
        self.start.setDefault(True)
        self.start.clicked.connect(self.begin)
        buttons.addWidget(self.later)
        buttons.addWidget(self.start)
        layout.addLayout(buttons)
        if not status.get('supported'):
            self.start.setEnabled(False)
            self.message.setText('Automatic setup supports macOS and Windows. Install Ollama from ollama.com, then run '
                                 'ollama pull '+status['text_model']+' and ollama pull '+status['vision_model']+'.')

    def begin(self):
        self.start.setEnabled(False)
        self.later.setText('Cancel')
        self.bar.show()
        self.worker = SetupWorker((self.status['text_model'], self.status['vision_model']), self)
        self.worker.progress.connect(self.show_progress)
        self.worker.finished_ok.connect(self.done_ok)
        self.worker.failed.connect(self.done_failed)
        self.worker.start()

    def show_progress(self, message, fraction):
        self.message.setText(message)
        if fraction < 0:
            self.bar.setRange(0, 0)  # busy indicator
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(fraction*1000))

    def done_ok(self, text, vision):
        self.owner.models_ready(text, vision)
        self.message.setText('A11y is ready.')
        self.accept()

    def done_failed(self, message):
        self.bar.hide()
        self.message.setText(message)
        self.start.setEnabled(True)
        self.start.setText('Try again')
        self.later.setText('Not now')

    def close_or_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.message.setText('Stopping after the current step…')
            return
        self.reject()
