"""Guided first-run setup; OS permissions are requested only by explicit buttons."""
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                            QLineEdit, QComboBox, QPushButton, QCheckBox, QFormLayout, QStackedWidget)
from .onboarding import QUESTIONS
from .theme import panel_style


def description(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    return widget


class SetupDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('Welcome to A11y')
        self.setMinimumWidth(480)
        self.resize(530, 570)
        self.setStyleSheet(panel_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(18)
        self.progress = description('')
        layout.addWidget(self.progress)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.fields = {}
        self.add_page('Hi, I’m A11y.', 'Let’s make your desktop feel more like yours. '
                      'I’ll learn how you want help, then walk you through optional access. '
                      'You can skip personal details and keep every permission off.')
        page = self.add_page('A little about you', 'These details help personalize replies. '
                             'Saved answers are shared with your configured AI provider; Ollama runs locally.')
        form = QFormLayout()
        answers = owner.introduction.get()['answers']
        for key, prompt in [('display_name', 'What should I call you?'), ('work_role', 'What kind of work do you do?')]:
            field = QLineEdit(answers.get(key, ''))
            field.setMaxLength(80 if key == 'display_name' else 160)
            field.setPlaceholderText('Optional')
            field.setAccessibleName(prompt)
            form.addRow(prompt, field)
            self.fields[key] = field
        page.insertLayout(2, form)
        page = self.add_page('How should I help?', 'Choose what feels comfortable. '
                             'You can change any of this later. I won’t infer a disability or diagnosis.')
        form = QFormLayout()
        effective = owner.service.adaptation.effective(owner.service.identity)
        defaults = dict(effective, learning_enabled=owner.service.adaptation.get(owner.service.identity)['learning_enabled'])
        names = {'detail': 'Explanations', 'pacing': 'Task guidance', 'input': 'Navigation',
                 'reduced_motion': 'Movement', 'learning_enabled': 'Learn from feedback'}
        for key, _, options in QUESTIONS[2:]:
            field = QComboBox()
            for title, value in options:
                field.addItem(title, value)
            field.setCurrentIndex(max(0, field.findData(defaults[key])))
            field.setAccessibleName(names[key])
            form.addRow(names[key], field)
            self.fields[key] = field
        page.insertLayout(2, form)
        page = self.add_page('Let me understand your desktop', 'Both options are optional and can be paused at any time. '
                             'Enabling access remembers it until paused; use the restoration checkbox for session-only access. '
                             'macOS may ask for permission. Closing setup never grants access.')
        page.insertWidget(2, description('App awareness · Reads app names, window positions and accessible controls. '
                              'No screenshots or field values. Shared with your selected AI only when you ask.'))
        self.context_button = QPushButton('Enable app awareness…')
        self.context_button.clicked.connect(lambda: owner.desktop_action('context:toggle', consented=True))
        page.insertWidget(3, self.context_button)
        page.insertWidget(4, description('Screen vision · A fresh image with each message, sent only to local Ollama. '
                              'No continuous recording or saved images. Requires Screen Recording permission and a vision model.'))
        self.vision_button = QPushButton('Enable screen vision…')
        self.vision_button.clicked.connect(lambda: owner.toggle_screen_vision(consented=True))
        page.insertWidget(5, self.vision_button)
        self.remember_access = QCheckBox('Restore enabled access when I reopen A11y')
        self.remember_access.setChecked(owner.access_preferences.get()['remember'])
        self.remember_access.toggled.connect(owner.set_remember_access)
        page.insertWidget(6, self.remember_access)
        self.access_status = description('')
        page.insertWidget(7, self.access_status)
        page.insertWidget(8, description('Voice · Optional. Turn on voice from the character’s right-click menu, then say “Hey Ally” '
                              'and talk naturally. Speech is understood on this computer and never saved.'))
        page = self.add_page('You’re ready.', 'Click the character to talk. Enter sends; Shift+Enter adds a line. '
                             'Right-click the character for more actions. You stay in control of each task step.')
        self.summary = description('')
        page.insertWidget(2, self.summary)
        row = QHBoxLayout()
        self.later = QPushButton('Finish later')
        self.later.clicked.connect(self.reject)
        row.addWidget(self.later)
        row.addStretch()
        self.back = QPushButton('Back')
        self.back.clicked.connect(lambda: self.show_page(self.pages.currentIndex()-1))
        row.addWidget(self.back)
        self.next = QPushButton('Get started')
        self.next.setObjectName('setupPrimary')
        self.next.setDefault(True)
        self.next.clicked.connect(self.advance)
        row.addWidget(self.next)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_access)
        self.timer.start(500)
        self.show_page(0)

    def reject(self):
        self.timer.stop()
        super().reject()

    def accept(self):
        self.timer.stop()
        super().accept()

    def add_page(self, title, text):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        heading = description(title)
        heading.setObjectName('settingsPageTitle')
        layout.addWidget(heading)
        layout.addWidget(description(text))
        layout.addStretch()
        self.pages.addWidget(page)
        return layout

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.progress.setText(f'Set up your companion · {index+1} of {self.pages.count()}')
        self.back.setVisible(index > 0)
        self.next.setText('Get started' if index == 0 else 'Save and continue' if index == 2 else 'Finish' if index == 4 else 'Continue')
        self.update_access()

    def advance(self):
        index = self.pages.currentIndex()
        if index == 1:
            intro = self.owner.introduction
            intro.start(restart=True)
            for key in ('display_name', 'work_role'):
                value = self.fields[key].text().strip()
                intro.answer(value, skip=not value)
        if index == 2:
            intro = self.owner.introduction
            intro.start(restart=True)
            for key, _, options in QUESTIONS:
                field = self.fields[key]
                value = field.currentData() if options else field.text().strip()
                intro.answer(value, skip=not options and not value)
            intro.save()
            self.owner.refresh()
        if index == 4:
            data = self.owner.introduction.get()
            data['access_setup_reviewed'] = True
            self.owner.service.store.save_introduction(self.owner.service.identity, data)
            self.owner.mascot_home('We’re ready. What would you like help with first?')
            self.accept()
        else:
            self.show_page(index+1)

    def update_access(self):
        context = self.owner.desktop_monitor.context()
        self.context_button.setText('Pause app awareness' if self.owner.desktop_monitor.enabled else 'Enable app awareness…')
        self.vision_button.setText('Pause screen vision' if self.owner.vision.enabled else 'Enable screen vision…')
        pending = self.owner.vision_permission and self.owner.vision_permission.isRunning()
        self.vision_button.setEnabled(not pending)
        app_state = 'Off'
        if context.get('enabled'):
            app_state = 'Permission needed' if context.get('accessibility') == 'permission_required' else {'available': 'On', 'companion_focused': 'On', 'private_app': 'Paused for private app', 'stale': 'Waiting for an app'}.get(context.get('status'), 'Starting or waiting for access')
        status = f'App awareness: {app_state} · Screen vision: '+('On' if self.owner.vision.enabled else 'Requesting permission…' if pending else 'Off')
        self.access_status.setText(status+'\nRestoration is opt-in. Pausing access also pauses it for future launches; OS permissions still apply.')
        self.summary.setText('Your saved details and preferences:\n'+self.owner.introduction.summary()+'\n\n'+status)


class AccessSheet(QDialog):
    """Short, consistently styled access explanation outside the guided setup."""
    def __init__(self, parent, title, explanation, details, action):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(440)
        self.setStyleSheet(panel_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)
        heading = description(title)
        heading.setObjectName('settingsPageTitle')
        layout.addWidget(heading)
        layout.addWidget(description(explanation))
        for detail in details:
            layout.addWidget(description(detail))
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton('Not now')
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)
        row.addWidget(cancel)
        enable = QPushButton(action)
        enable.setObjectName('setupPrimary')
        enable.setAutoDefault(False)
        enable.clicked.connect(self.accept)
        row.addWidget(enable)
        layout.addLayout(row)
        self.adjustSize()
