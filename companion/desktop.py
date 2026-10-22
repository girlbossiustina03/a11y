"""Native PyQt6 desktop UI; shared services also power the browser fallback."""
import base64
import json
from pathlib import Path
import time
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QByteArray, QBuffer, QIODevice, QPoint, QUrl, QRect, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QKeySequence, QShortcut, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QListWidget)
from .adaptation import CHOICES
from .mascot import Mascot
from .overlay import GuidanceOverlay
from .onboarding import Introduction, QUESTIONS
from .setup_ui import SetupDialog, AccessSheet
from .provider import AIConfig, ChatProvider, ProviderError
from .ollama import OllamaProvider, local_url
from .theme import PANEL_STYLE, apply_theme
from .vision import ScreenVision
from .desktop_context import DesktopContext, MacDesktopBridge
from .computer_use import ComputerUse


class RequestWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, service, request, options, parent=None, vision=None):
        super().__init__(parent)
        self.service, self.request, self.options = service, request, options
        self.vision = vision

    def run(self):
        try:
            visual = None
            plan = ({'operation': 'plan', 'app_name': '', 'target': self.request[:500]} if self.options.get('mode') == 'plan'
                    else self.service.prepare_request(self.request) if self.options.get('mode') != 'verify' else None)
            if plan is not None:
                self.options['request_plan'] = plan
            needs_pixels = plan is None or plan['operation'] in ('move_object', 'highlight', 'inspect_screen')
            vision_generation = self.vision.generation if self.vision else None
            geometry = self.options.get('screen_geometry') or {'x': 0, 'y': 0}
            if self.options.get('mode') == 'verify' and self.service.desktop_context and self.service.desktop_context.enabled:
                self.service.desktop_context.collect_once()
            if self.vision and self.vision.enabled and not self.options.get('image_data') and (needs_pixels or self.options.get('mode') == 'verify'):
                desktop = self.service.desktop_context.context() if self.service.desktop_context else None
                try:
                    visual = self.vision.capture(self.service.provider, x=geometry['x'], y=geometry['y'], desktop=desktop)
                    self.options['image_data'] = visual.pop('image_data')
                    self.options['visual_context'] = visual
                except RuntimeError as error:
                    if self.options.get('mode') != 'verify':
                        raise
                    # An approved action may already be submitted. Verify only what
                    # fresh metadata establishes; never resubmit because vision failed.
                    self.options['visual_context'] = {'status': 'unavailable', 'reason': str(error)}
            response = self.service.ask(self.request, **self.options)
            if visual and self.vision.enabled and self.vision.generation == vision_generation:
                response['visual_capture'] = visual
            elif visual:
                self.service.desktop_session.clear()
                response['target'] = None
                response['desktop_action'] = None
            self.result.emit(response)
        except (ValueError, RuntimeError, PermissionError) as e:
            self.failed.emit(str(e))
        except Exception:
            self.failed.emit('The request could not be completed. Your confirmed progress is saved.')
        finally:
            self.options.clear()  # release transient image data


class ComputerActionWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, desktop, proposal, parent=None):
        super().__init__(parent)
        self.desktop, self.proposal = desktop, dict(proposal)

    def run(self):
        try:
            self.result.emit(ComputerUse(self.desktop).execute_confirmed(self.proposal))
        except (ValueError, RuntimeError) as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit('The action result is uncertain. Check the app before trying again.')


class VisionPermission(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, vision, parent=None):
        super().__init__(parent)
        self.vision = vision

    def run(self):
        try:
            self.result.emit(self.vision.request_access())
        except RuntimeError as e:
            self.failed.emit(str(e))


class OllamaDiscovery(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        try:
            provider = OllamaProvider()
            self.result.emit((provider, provider.list_models()))
        except (ValueError, RuntimeError) as e:
            self.failed.emit(str(e))


def label(value):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def button(value, action):
    widget = QPushButton(value)
    widget.clicked.connect(action)
    return widget


class CompanionWindow(QMainWindow):
    def __init__(self, service):
        super().__init__()
        apply_theme(QApplication.instance())
        self.service = service
        self.desktop_monitor = DesktopContext(MacDesktopBridge(service.store.directory))
        self.service.desktop_context = self.desktop_monitor
        self.pending_desktop_action = None
        self.vision = ScreenVision(service.store.directory)
        self.vision_permission = None
        self.last_user_request = None
        self.retry_after_vision = False
        self.move_animation = None
        self.worker = None
        self.discovery = None
        self.capture_context = None
        self.pending_target = None
        self.introduction = Introduction(service.store, service.identity)
        self.setup_active = False
        self.request_from_mascot = False
        self.quitting = False
        self.setWindowTitle('A11y · Your workplace, at your pace')
        self.resize(760, 740)
        self.mascot = Mascot()
        self.mascot.opened.connect(self.reveal)
        self.mascot.submitted.connect(self.mascot_submit)
        self.mascot.action_requested.connect(self.mascot_action)
        self.overlay = GuidanceOverlay()
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.build_chat()
        self.build_workflow()
        self.build_preferences()
        self.build_knowledge()
        self.build_connection()
        self.build_desktop_context()
        self.build_essentials()
        self.build_panel_shell()
        self.context_timer = QTimer(self)
        self.context_timer.timeout.connect(self.refresh_desktop_context)
        self.context_timer.start(1000)
        self.statusBar().showMessage('Ready. Screen and microphone are off.')
        self.setStyleSheet(PANEL_STYLE)
        self.tts = None
        try:
            from PyQt6.QtTextToSpeech import QTextToSpeech
            engines = [engine for engine in QTextToSpeech.availableEngines() if engine != 'mock']
            if engines:
                self.tts = QTextToSpeech(engines[0], self)
                self.tts.stateChanged.connect(self.speech_state)
        except ImportError:
            pass
        self.read_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.read_btn.setToolTip('Read aloud using an installed system speech engine.' if self.tts else 'No system speech engine is available.')
        self.refresh()
        for message in service.history():
            self.transcript.appendPlainText(f'{message["role"].capitalize()}: {message["content"]}\n')
        QShortcut(QKeySequence('Ctrl+Return'), self).activated.connect(self.ask)
        QShortcut(QKeySequence('Meta+Return'), self).activated.connect(self.ask)
        QShortcut(QKeySequence('Escape'), self).activated.connect(self.clear_guidance)
        self.mascot.show()

    def start_companion(self):
        if isinstance(self.service.provider, OllamaProvider):
            QTimer.singleShot(0, self.scan_ollama)
        name = self.introduction.get()['answers'].get('display_name', '')
        self.mascot_home((f'Hey {name}!' if name else 'Hey!')+' What can I help you with?')
        self.mascot.hide_reply()
        self.mascot.fit_on_screen()
        if not self.introduction.get().get('access_setup_reviewed'):
            self.open_setup()

    def open_setup(self):
        if getattr(self, 'setup_dialog', None) and self.setup_dialog.isVisible():
            self.setup_dialog.raise_()
            return
        self.setup_dialog = SetupDialog(self)
        self.setup_dialog.show()
        self.setup_dialog.raise_()
        self.setup_dialog.activateWindow()

    def build_essentials(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        title = label('Settings')
        title.setObjectName('settingsPageTitle')
        layout.addWidget(title)
        subtitle = label('A little help, configured your way.')
        subtitle.setObjectName('settingsSubtitle')
        layout.addWidget(subtitle)

        def group():
            surface = QFrame()
            surface.setObjectName('settingsGroup')
            rows = QVBoxLayout(surface)
            rows.setContentsMargins(16, 6, 16, 6)
            rows.setSpacing(0)
            layout.addWidget(surface)
            return rows

        def row(rows, title, detail, control):
            if rows.count():
                line = QFrame()
                line.setObjectName('settingsDivider')
                line.setFixedHeight(1)
                rows.addWidget(line)
            line = QHBoxLayout()
            line.setContentsMargins(0, 14, 0, 14)
            line.setSpacing(18)
            text = QVBoxLayout()
            text.setSpacing(5)
            heading = label(title)
            heading.setObjectName('settingsRowTitle')
            text.addWidget(heading)
            detail.setObjectName('settingsSubtitle')
            text.addWidget(detail)
            line.addLayout(text, 1)
            control.setFixedWidth(116)
            line.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
            rows.addLayout(line)

        personal = group()
        self.essentials_identity = label('')
        row(personal, 'Personalization', self.essentials_identity,
            button('Personalize…', self.open_setup))
        self.essentials_ai = label('')
        row(personal, 'Intelligence', self.essentials_ai,
            button('Choose…', lambda: self.tabs.setCurrentIndex(4)))
        access_title = label('Desktop access')
        access_title.setObjectName('settingsRowTitle')
        layout.addWidget(access_title)
        access = group()
        self.essentials_context = button('Enable…', lambda: self.desktop_action('context:toggle'))
        row(access, 'App awareness', label('Understand app names, windows and accessible controls.'), self.essentials_context)
        self.essentials_vision = button('Enable…', self.toggle_screen_vision)
        row(access, 'Screen vision', label('Take a fresh look when you send a message. Local Ollama only.'), self.essentials_vision)
        self.essentials_access = label('Both options are optional and last for this session.')
        self.essentials_access.setObjectName('settingsSubtitle')
        layout.addWidget(self.essentials_access)
        layout.addSpacing(8)
        layout.addWidget(self.show_mascot)
        layout.addStretch()
        self.essentials_tab = self.tabs.addTab(page, 'Settings')
        self.tabs.setCurrentIndex(self.essentials_tab)

    def build_chat(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label('A11y · Your workplace, at your pace'))
        self.provider_status = label('')
        layout.addWidget(self.provider_status)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setAccessibleName('Conversation and source references')
        layout.addWidget(self.transcript, 1)
        self.input = QPlainTextEdit()
        self.input.setAccessibleName('Your request')
        self.input.setPlaceholderText('Help me set up my company development environment…')
        self.input.setMaximumHeight(90)
        layout.addWidget(self.input)
        row = QHBoxLayout()
        self.ask_btn = button('Send · Ctrl+Enter', self.ask)
        self.plan_btn = button('Create workflow', lambda: self.ask(mode='plan'))
        self.read_btn = button('Read latest response', self.read_response)
        row.addWidget(self.ask_btn)
        row.addWidget(self.plan_btn)
        row.addWidget(self.read_btn)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.screens = QComboBox()
        self.screens.setAccessibleName('Screen to capture')
        for screen in QApplication.screens():
            self.screens.addItem(screen.name(), screen)
        row.addWidget(self.screens)
        self.capture_btn = button('Capture screen once…', self.capture_screen)
        row.addWidget(self.capture_btn)
        layout.addLayout(row)
        layout.addWidget(label('Screen analysis is optional. A preview requires approval before upload. '
                               'Native voice input is not available in this pass; the browser UI offers optional speech input.'))
        row = QHBoxLayout()
        self.highlight_btn = button('Show desktop highlight (minimize panel)', self.show_guidance)
        self.highlight_btn.setEnabled(False)
        row.addWidget(self.highlight_btn)
        row.addWidget(button('Dismiss highlight · Esc', self.clear_guidance))
        self.stop_btn = button('Stop speech', self.stop_speech)
        row.addWidget(self.stop_btn)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.show_mascot = QCheckBox('Show desktop mascot')
        self.show_mascot.setChecked(True)
        self.show_mascot.toggled.connect(self.mascot.setVisible)
        row.addWidget(self.show_mascot)
        row.addWidget(button('Clear saved conversation', self.clear_history))
        layout.addLayout(row)
        self.latest_response = ''
        self.tabs.addTab(page, 'Conversation')

    def build_workflow(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.workflow_select = QComboBox()
        self.workflow_select.setAccessibleName('Saved workflow')
        self.workflow_select.currentIndexChanged.connect(self.render_workflow)
        layout.addWidget(self.workflow_select)
        self.workflow_text = QPlainTextEdit()
        self.workflow_text.setReadOnly(True)
        self.workflow_text.setAccessibleName('Workflow progress and instructions')
        layout.addWidget(self.workflow_text)
        self.confirm_btn = button('I completed this step', self.confirm_step)
        layout.addWidget(self.confirm_btn)
        self.resume_btn = button('Resume in conversation', self.resume)
        layout.addWidget(self.resume_btn)
        layout.addWidget(label('Progress is saved after every confirmation. Only you can mark a step complete. '
                               'App controls can be pressed only after you approve an observed control. Task completion still requires your confirmation.'))
        self.tabs.addTab(page, 'Saved tasks')

    def build_preferences(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = label('Make yourself comfortable.')
        heading.setObjectName('settingsPageTitle')
        layout.addWidget(heading)
        layout.addWidget(label('Choose how A11y works with you. Explicit settings override approved adaptations. '
                               '“Use approved/default” removes your explicit override.'))
        self.pref_controls = {}
        form = QFormLayout()
        for key, values in CHOICES.items():
            control = QComboBox()
            control.addItem('Use approved/default', None)
            for value in values:
                names = {'concise': 'Keep it short', 'balanced': 'A little context', 'detailed': 'Explain in detail',
                         'one_step': 'One step at a time', 'all_steps': 'Show the whole plan',
                         'any': 'No preference', 'keyboard': 'Keyboard first'}
                name = ('Keep things still' if value else 'Gentle animation') if key == 'reduced_motion' else names[value]
                control.addItem(name, value)
            control.setAccessibleName(key.replace('_', ' '))
            form.addRow(key.replace('_', ' ').capitalize(), control)
            self.pref_controls[key] = control
        layout.addLayout(form)
        self.learning = QCheckBox('Allow behavior suggestions and approved adaptations')
        layout.addWidget(self.learning)
        layout.addWidget(button('Save preferences', self.save_preferences))
        self.profile_view = QPlainTextEdit()
        self.profile_view.setReadOnly(True)
        self.profile_view.setAccessibleName('Explicit preferences, observations and approved adaptations')
        self.inspect_profile = inspect_profile = button('Inspect learned preferences', lambda: self.profile_view.setVisible(not self.profile_view.isVisible()))
        layout.addWidget(inspect_profile)
        self.profile_view.hide()
        layout.addWidget(self.profile_view)
        self.suggestions = QComboBox()
        self.suggestions.setAccessibleName('Pending behavior suggestion')
        layout.addWidget(self.suggestions)
        row = QHBoxLayout()
        self.approve_btn = button('Approve suggestion', lambda: self.decide_preference(True))
        self.dismiss_btn = button('Dismiss suggestion', lambda: self.decide_preference(False))
        row.addWidget(self.approve_btn)
        row.addWidget(self.dismiss_btn)
        layout.addLayout(row)
        self.reset_learning_button = button('Reset learned preferences (keep explicit settings)', self.reset_preferences)
        layout.addWidget(self.reset_learning_button)
        layout.addStretch()
        self.tabs.addTab(page, 'Preferences')

    def build_knowledge(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label('Company knowledge · text and Markdown documents\n'
                               'A local administrator imports approved company instructions. '
                               'Retrieved excerpts are sent to the configured AI provider when you ask a question.'))
        self.documents = QPlainTextEdit()
        self.documents.setReadOnly(True)
        self.documents.setAccessibleName('Accessible company documents')
        layout.addWidget(self.documents)
        self.doc_roles = QLineEdit('engineering')
        self.doc_roles.setAccessibleName('Allowed document roles, separated by commas')
        layout.addWidget(label('Allowed roles (employee means all employees):'))
        layout.addWidget(self.doc_roles)
        self.import_btn = button('Import .txt or .md document…', self.import_document)
        layout.addWidget(self.import_btn)
        layout.addWidget(button('Refresh company knowledge', self.refresh))
        layout.addWidget(label('Launch with --admin to manage documents in this single-machine prototype. '
                               'This is not a multi-user company admin service.'))
        self.tabs.addTab(page, 'Company knowledge')

    def selected_workflow(self):
        workflow_id = self.workflow_select.currentData()
        return next((w for w in self.saved_workflows if w['id'] == workflow_id), None)

    def refresh(self, workflow_id=None):
        state = self.service.state()
        self.saved_workflows = state['workflows']
        self.unavailable_tasks = state['unavailable_tasks']
        previous = workflow_id or self.workflow_select.currentData()
        self.workflow_select.blockSignals(True)
        self.workflow_select.clear()
        for workflow in self.saved_workflows:
            self.workflow_select.addItem(workflow['title']+' · '+workflow['status'], workflow['id'])
        index = self.workflow_select.findData(previous)
        if index >= 0:
            self.workflow_select.setCurrentIndex(index)
        self.workflow_select.blockSignals(False)
        self.render_workflow()
        self.provider_status.setText(f'AI: {state["ai"]["model"] or "not configured"} · {state["ai"]["endpoint"]}\n'
                                     + (state['ai']['message'] or 'Requests include your conversation, preferences and relevant company excerpts.'))
        self.documents.setPlainText('\n\n'.join(f'{d["title"]}\nRoles: {", ".join(d["roles"])}' for d in state['documents']) or 'No accessible documents. Ask an administrator to import onboarding instructions.')
        self.import_btn.setEnabled(state['admin'])
        for key, control in self.pref_controls.items():
            value = state['profile']['explicit'].get(key)
            control.setCurrentIndex(control.findData(value))
        self.learning.setChecked(state['profile']['learning_enabled'])
        self.profile_view.setPlainText(json.dumps({'effective': state['effective'], **state['profile']}, indent=2))
        self.suggestions.clear()
        for signal, suggestion in state['profile']['suggestions'].items():
            self.suggestions.addItem(f'{suggestion["key"]}: {suggestion["value"]} — {suggestion["reason"]}', signal)
        pending = bool(state['profile']['suggestions'])
        self.approve_btn.setEnabled(pending)
        self.dismiss_btn.setEnabled(pending)
        self.suggestions.setVisible(pending)
        self.approve_btn.setVisible(pending)
        self.dismiss_btn.setVisible(pending)
        self.mascot.set_reduced_motion(state['effective']['reduced_motion'])
        if hasattr(self, 'essentials_identity'):
            details = self.introduction.user_details()
            self.essentials_identity.setText(' · '.join(details.values()) or 'Your name, role and preferred way to work.')
            self.essentials_ai.setText((state['ai']['model'] or 'Choose a local model to get started')+'\n'+('Needs connection setup' if state['ai']['message'] else 'Connection configured'))

    def render_workflow(self):
        self.clear_guidance()
        w = self.selected_workflow()
        self.confirm_btn.setEnabled(bool(w and w['status'] == 'active'))
        self.resume_btn.setEnabled(bool(w))
        if not w:
            self.workflow_text.setPlainText(('Some saved tasks are hidden because their company sources are no longer accessible.\n' if self.unavailable_tasks else '')+'No accessible saved tasks yet. Import onboarding instructions, then create a workflow from the Conversation tab.')
            return
        current = w['current_step']
        lines = [w['title'], f'{current} of {len(w["steps"])} steps confirmed · {w["status"]}', '']
        prefs = self.service.adaptation.effective(self.service.identity)
        visible = range(current, min(current+1, len(w['steps']))) if prefs['pacing'] == 'one_step' else range(len(w['steps']))
        for i in visible:
            step = w['steps'][i]
            lines.append(f'{i+1}. {step["instruction"]}')
            if step['application']:
                lines.append('Application: '+step['application'])
            if step['keyboard_hint']:
                lines.append('Keyboard: '+step['keyboard_hint'])
            lines.append('Sources: '+', '.join(step['source_ids']))
            lines.append('')
        for source in w.get('sources', []):
            lines.append(f'Source [{source["id"]}]: {source["title"]} · section {source["ordinal"]}\n{source["content"]}\n')
        self.workflow_text.setPlainText('\n'.join(lines))

    def ask(self, checked=False, *, mode='answer', image_data=None, from_mascot=False):
        if self.worker and self.worker.isRunning():
            return
        request = self.input.toPlainText().strip()
        if not request:
            self.input.setFocus()
            self.statusBar().showMessage('Enter a request first.')
            return
        self.request_from_mascot = from_mascot
        self.last_user_request = (request, mode, from_mascot)
        self.pending_desktop_action = None
        self.clear_guidance(keep_capture=bool(image_data))
        self.transcript.appendPlainText('Checking the action result against a fresh observation…\n' if mode == 'verify' else 'You: '+request+'\n')
        self.set_busy(True)
        self.mascot.set_state('thinking', 'Thinking with your instructions and company knowledge…')
        screen = self.mascot.screen()
        area = screen.geometry()
        options = {'mode': mode, 'workflow_id': self.workflow_select.currentData(), 'image_data': image_data,
                   'screen_geometry': {'x': area.x(), 'y': area.y(), 'width': area.width(), 'height': area.height(),
                       'usable': {'x': screen.availableGeometry().x(), 'y': screen.availableGeometry().y(),
                                  'width': screen.availableGeometry().width(), 'height': screen.availableGeometry().height()}}}
        self.worker = RequestWorker(self.service, request, options, self, vision=self.vision)
        self.worker.result.connect(self.received)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.worker.start()

    def set_busy(self, busy):
        self.mascot.set_busy(busy)
        for control in (self.ask_btn, self.plan_btn, self.capture_btn, self.confirm_btn):
            control.setEnabled(not busy)
        if not busy:
            self.confirm_btn.setEnabled(bool(self.selected_workflow() and self.selected_workflow()['status'] == 'active'))
        self.statusBar().showMessage('Screen analysis active · waiting for AI' if busy and self.capture_context else
                                     'Waiting for AI…' if busy else 'Ready. Screen and microphone are off.')

    def received(self, response):
        capture = self.capture_context
        visual = response.get('visual_capture')
        if visual:
            bounds = visual['screen']
            geometry = QRect(int(bounds['x']), int(bounds['y']), int(bounds['width']), int(bounds['height']))
            screen = next((s for s in QApplication.screens() if s.geometry() == geometry), None)
            if screen:
                capture = {'screen': screen, 'geometry': geometry, 'time': visual['captured_monotonic'],
                           'workflow': self.workflow_select.currentData()}
        self.latest_response = response['message']
        self.read_btn.setEnabled(self.tts is not None)
        self.transcript.appendPlainText('A11y: '+response['message']+'\n')
        for source in response['sources']:
            self.transcript.appendPlainText(f'[{source["id"]}] {source["title"]} · section {source["ordinal"]}\n{source["content"]}\n')
        workflow_id = response['workflow']['id'] if response['workflow'] else None
        self.refresh(workflow_id)
        self.mascot.set_state('guiding' if response['target'] else 'idle', response['message'])
        if response['target'] and capture and time.monotonic()-capture['time'] < 90:
            self.latest_response += '\nSuggested target: '+response['target']['label']
            self.pending_target = (response['target'], capture)
            self.highlight_btn.setEnabled(True)
            self.transcript.appendPlainText('Suggested target: '+response['target']['label']+'\nReview the current screen before showing the highlight.\n')
        self.capture_context = None
        if response['workflow']:
            self.tabs.setCurrentIndex(1)
        self.pending_desktop_action = response.get('desktop_action')
        self.mascot_home(response['message'], sources=response['sources'])
        if self.pending_desktop_action and self.pending_desktop_action['type'] == 'move_companion':
            destination = self.pending_desktop_action['destination']
            self.pending_desktop_action = None
            self.move_companion(destination)
            self.transcript.appendPlainText('Companion moving to '+destination.replace('_', ' ')+'.\n')
        elif self.pending_desktop_action and self.pending_desktop_action['type'] == 'move_to_point':
            action = self.pending_desktop_action
            self.pending_desktop_action = None
            if action['basis'] == 'image':
                if not capture or time.monotonic()-capture['time'] >= 90 or capture['screen'].geometry() != capture['geometry']:
                    self.mascot_home('That screen observation expired. Ask again for a fresh look before I move.')
                    return
                screen = capture['screen']
            else:
                screen = self.mascot.screen()
            self.move_companion_to(action['x'], action['y'], screen)
            self.transcript.appendPlainText('Companion moving to '+action['label']+'.\n')

    def failed(self, message):
        self.transcript.appendPlainText('Request failed: '+message+'\n')
        self.capture_context = None
        self.mascot.set_state('idle')
        self.mascot_home('I couldn’t complete that request. Your task progress is saved.\n\n'+message)

    def confirm_step(self):
        w = self.selected_workflow()
        if not w:
            return
        try:
            self.service.confirm_step(w['id'], w['current_step'])
            self.refresh(w['id'])
            current = self.selected_workflow()
            if current and current['status'] == 'active':
                step = current['steps'][current['current_step']]
                next_message = f'Progress saved. Step {current["current_step"]+1}: '+step['instruction']
                if step['keyboard_hint']:
                    next_message += '\n'+step['keyboard_hint']
            else:
                next_message = 'All steps are confirmed. Your task is complete!'
            self.mascot_home(next_message)
            self.mascot.set_state('celebrate')
            QTimer.singleShot(1600, lambda: self.mascot.set_state('idle'))
        except (ValueError, PermissionError) as e:
            self.statusBar().showMessage(str(e))
            self.refresh()

    def resume(self):
        w = self.selected_workflow()
        if not w:
            return
        self.tabs.setCurrentIndex(0)
        current = w['current_step']
        self.transcript.appendPlainText(f'Resumed: {w["title"]}. {current}/{len(w["steps"])} steps confirmed.\n'
                                       + ('Next: '+w['steps'][current]['instruction'] if w['status'] == 'active' else 'All steps confirmed.')+'\n')
        self.input.setFocus()
        self.mascot_home(('Next: '+w['steps'][current]['instruction']) if w['status'] == 'active' else 'All steps are confirmed.')

    def save_preferences(self):
        values = {k: c.currentData() for k, c in self.pref_controls.items() if c.currentData() is not None}
        self.service.adaptation.set_explicit(self.service.identity, values, self.learning.isChecked())
        self.refresh()
        self.statusBar().showMessage('Preferences saved and applied to future replies and current guidance.')
        if not self.setup_active:
            self.mascot_home('Got it. I’ll use your updated preferences.')

    def decide_preference(self, approve):
        signal = self.suggestions.currentData()
        if signal:
            self.service.adaptation.decide(self.service.identity, signal, approve)
            self.refresh()

    def reset_preferences(self):
        self.service.adaptation.reset_learned(self.service.identity)
        self.refresh()

    def import_document(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import company instructions', '', 'Text documents (*.md *.txt)')
        if not path:
            return
        try:
            if Path(path).stat().st_size > 480000:
                raise ValueError('Document is too large. Maximum is 120,000 text characters.')
            body = Path(path).read_text(encoding='utf-8')
            self.service.knowledge.ingest(self.service.identity, Path(path).name, body,
                                         [r.strip() for r in self.doc_roles.text().split(',') if r.strip()])
            self.refresh()
        except (ValueError, OSError, PermissionError) as e:
            QMessageBox.warning(self, 'Import failed', str(e))

    def capture_screen(self, checked=False, *, from_mascot=False):
        self.request_from_mascot = from_mascot
        self.capture_from_mascot = from_mascot
        if not self.input.toPlainText().strip():
            self.statusBar().showMessage('Enter what you want to understand before capturing a screen.')
            self.input.setFocus()
            return
        if not self.confirm_access('Take a look at this screen?',
                'Capture the selected display once, then review it before sending.',
                ['Close confidential windows and password fields first.',
                 'Nothing is sent until you approve the preview. The image is not saved.'], 'Show preview'):
            return
        self.clear_guidance()
        self.hide()
        self.mascot.hide()
        QTimer.singleShot(350, self.take_capture)

    def take_capture(self):
        screen = self.screens.currentData()
        if screen not in QApplication.screens():
            self.reveal()
            self.statusBar().showMessage('Selected display is unavailable. Restart to refresh displays.')
            return
        pixmap = screen.grabWindow(0)
        captured_at = time.monotonic()
        geometry = screen.geometry()
        if not getattr(self, 'capture_from_mascot', False):
            self.reveal()
        self.mascot.setVisible(self.show_mascot.isChecked())
        if pixmap.isNull():
            QMessageBox.warning(self, 'Screen capture unavailable',
                                'Screen capture was denied or is unsupported. Grant OS screen-recording '
                                'permission if desired, then try again. Text interaction still works.')
            return
        pixmap = pixmap.scaled(1600, 1200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(1)
        preview = QDialog(self)
        preview.setWindowTitle('Review screenshot before sending')
        layout = QVBoxLayout(preview)
        layout.addWidget(label('Check that no passwords or confidential information are visible. '
                               'Cancel and recapture if needed. Sending transmits this image to:\n'
                               +getattr(getattr(self.service.provider, 'config', None), 'base_url', 'the configured provider')))
        image = QLabel()
        image.setPixmap(pixmap.scaled(680, 460, Qt.AspectRatioMode.KeepAspectRatio))
        image.setAccessibleName('Screen preview. Cancel if you cannot confirm this screen is safe to share.')
        layout.addWidget(image)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Send this screenshot once')
        buttons.accepted.connect(preview.accept)
        buttons.rejected.connect(preview.reject)
        layout.addWidget(buttons)
        if preview.exec() != QDialog.DialogCode.Accepted:
            return
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, 'PNG')
        buffer.close()
        self.capture_context = {'screen': screen, 'geometry': geometry, 'time': captured_at,
                                'workflow': self.workflow_select.currentData()}
        self.ask(image_data='data:image/png;base64,'+base64.b64encode(bytes(data)).decode('ascii'),
                 from_mascot=getattr(self, 'capture_from_mascot', False))

    def show_guidance(self):
        if not self.pending_target:
            return
        target, capture = self.pending_target
        if (time.monotonic()-capture['time'] >= 90 or capture['screen'] not in QApplication.screens()
                or capture['screen'].geometry() != capture['geometry']
                or capture['workflow'] != self.workflow_select.currentData()):
            self.clear_guidance()
            self.statusBar().showMessage('Screen context expired or changed. Capture a fresh screenshot.')
            return
        self.overlay.guide(capture['geometry'], target)
        self.mascot.collapse_chat()
        if self.show_mascot.isChecked() and not self.service.adaptation.effective(self.service.identity)['reduced_motion']:
            area = capture['geometry']
            target_x = area.x()+int(target['x']*area.width())
            target_y = area.y()+int(target['y']*area.height())
            beside = target_x-self.mascot.width()-18
            if beside < area.left():
                beside = target_x+int(target['width']*area.width())+18
            x = max(area.left(), min(beside, area.right()-self.mascot.width()))
            y = max(area.top(), min(target_y, area.bottom()-self.mascot.height()))
            self.mascot.move(x, y)
        self.showMinimized()
        self.statusBar().showMessage('Suggested target: '+target['label']+' · expires in 10 seconds. Esc dismisses from this window.')

    def clear_guidance(self, checked=False, *, keep_capture=False):
        self.overlay.hide()
        self.pending_target = None
        if hasattr(self, 'highlight_btn'):
            self.highlight_btn.setEnabled(False)
        if not keep_capture:
            self.capture_context = None

    def read_response(self):
        if self.tts and self.latest_response:
            self.tts.say(self.latest_response)

    def speech_state(self, state):
        speaking = state.name == 'Speaking'
        self.stop_btn.setEnabled(speaking)
        self.mascot.set_state('speaking' if speaking else 'idle')

    def stop_speech(self):
        if self.tts:
            self.tts.stop()

    def clear_history(self):
        self.service.store.clear_history(self.service.identity)
        self.transcript.clear()
        self.latest_response = ''
        self.read_btn.setEnabled(False)

    def reveal(self):
        self.mascot.collapse_chat()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def build_panel_shell(self):
        # Preserve the existing page interfaces/indices; replace only the navigation shell.
        self.setWindowTitle('A11y · Companion settings')
        self.resize(800, 680)
        self.takeCentralWidget()
        self.tabs.tabBar().hide()
        root = QWidget()
        root.setObjectName('settingsRoot')
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 22, 24, 16)
        outer.setSpacing(22)
        header = QHBoxLayout()
        brand = QVBoxLayout()
        heading = label('A11y')
        heading.setObjectName('settingsBrand')
        brand.addWidget(heading)
        subtitle = label('A little help, your way.')
        subtitle.setObjectName('settingsSubtitle')
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
        back = button('Back to desktop', self.hide)
        back.setObjectName('backToDesktop')
        header.addWidget(back)
        outer.addLayout(header)
        content = QHBoxLayout()
        content.setSpacing(20)
        self.panel_navigation = QListWidget()
        self.panel_navigation.setObjectName('settingsNavigation')
        self.panel_navigation.setAccessibleName('Companion settings sections')
        self.panel_navigation.setFixedWidth(166)
        self.navigation_pages = [self.essentials_tab, 2, 1, 0, 3, 4, 5]
        for index in self.navigation_pages:
            self.panel_navigation.addItem(self.tabs.tabText(index))
        self.panel_navigation.setCurrentRow(self.navigation_pages.index(self.tabs.currentIndex()))
        self.panel_navigation.currentRowChanged.connect(
            lambda row: self.tabs.setCurrentIndex(self.navigation_pages[row]) if row >= 0 else None)
        self.tabs.currentChanged.connect(
            lambda index: self.panel_navigation.setCurrentRow(self.navigation_pages.index(index)))
        navigation = QVBoxLayout()
        navigation.addWidget(self.panel_navigation, 1)
        self.advanced_navigation = QCheckBox('Advanced')
        self.advanced_navigation.setToolTip('Conversation history, company documents, AI connection and desktop diagnostics')
        navigation.addWidget(self.advanced_navigation)
        content.addLayout(navigation)
        self.advanced_pages = {0, 3, 4, 5}
        self.advanced_navigation.toggled.connect(self.update_navigation)
        self.tabs.currentChanged.connect(self.ensure_page_visible)
        self.update_navigation(False)
        surface = QFrame()
        surface.setObjectName('settingsSurface')
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(18, 18, 18, 18)
        surface_layout.addWidget(self.tabs)
        content.addWidget(surface, 1)
        outer.addLayout(content, 1)
        self.setCentralWidget(root)

    def update_navigation(self, advanced):
        self.inspect_profile.setVisible(advanced)
        self.reset_learning_button.setVisible(advanced)
        if not advanced:
            self.profile_view.hide()
        if not advanced and self.tabs.currentIndex() in self.advanced_pages:
            self.tabs.setCurrentIndex(self.essentials_tab)
        for index in self.advanced_pages:
            self.panel_navigation.item(self.navigation_pages.index(index)).setHidden(not advanced)

    def ensure_page_visible(self, index):
        if index in self.advanced_pages and not self.advanced_navigation.isChecked():
            self.advanced_navigation.setChecked(True)

    def move_companion(self, destination):
        self.mascot.collapse_chat()
        area = self.mascot.screen().availableGeometry()
        left, right = area.left()+16, area.right()-self.mascot.width()-16
        top, bottom = area.top()+16, area.bottom()-self.mascot.height()-16
        positions = {'left_edge': QPoint(left, max(top, min(self.mascot.y(), bottom))),
                     'right_edge': QPoint(right, max(top, min(self.mascot.y(), bottom))),
                     'bottom_left': QPoint(left, bottom), 'bottom_right': QPoint(right, bottom),
                     'top_left': QPoint(left, top), 'top_right': QPoint(right, top),
                     'center': QPoint((left+right)//2, (top+bottom)//2)}
        if destination not in positions:
            raise ValueError('Unknown companion destination.')
        self.animate_companion_to(positions[destination])

    def move_companion_to(self, x, y, screen):
        self.mascot.collapse_chat()
        full = screen.geometry()
        usable = screen.availableGeometry()
        # The AI chooses a point. Native code maps image fractions and clamps the character.
        left = full.x()+round(x*full.width())-self.mascot.width()//2
        top = full.y()+round(y*full.height())-self.mascot.height()//2
        position = QPoint(max(usable.left()+16, min(left, usable.right()-self.mascot.width()-16)),
                          max(usable.top()+16, min(top, usable.bottom()-self.mascot.height()-16)))
        self.animate_companion_to(position)

    def animate_companion_to(self, position):
        if self.move_animation:
            self.move_animation.stop()
        if self.service.adaptation.effective(self.service.identity)['reduced_motion']:
            self.mascot.move(position)
        else:
            self.move_animation = QPropertyAnimation(self.mascot, b'pos', self)
            self.move_animation.setDuration(450)
            self.move_animation.setStartValue(self.mascot.pos())
            self.move_animation.setEndValue(position)
            self.move_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self.move_animation.start()

    def confirm_access(self, title, explanation, details, action):
        return AccessSheet(self, title, explanation, details, action).exec() == QDialog.DialogCode.Accepted

    def toggle_screen_vision(self, checked=False, *, consented=False):
        if self.vision.enabled:
            self.retry_after_vision = False
            self.vision.set_enabled(False)
            self.service.desktop_session.clear()
            self.mascot.vision_button.setText('Screen off')
            self.mascot.vision_button.setAccessibleName('Screen vision is off. Activate to enable.')
            self.mascot_home('Screen vision paused. I will not capture your screen.')
            return
        if self.vision_permission and self.vision_permission.isRunning():
            return
        if not isinstance(self.service.provider, OllamaProvider):
            self.mascot_home('Automatic screen vision needs local Ollama. Connect it under Settings → AI connection.')
            return
        if not consented and not self.confirm_access('See what you’re working on',
                'Each message includes a fresh screen image for your local Ollama model.',
                ['Images stay off disk. Nothing is recorded between messages.',
                 'Close confidential windows first. Pause vision whenever you like.',
                 'macOS will ask for Screen Recording access.'], 'Enable screen vision'):
            self.retry_after_vision = False
            return
        self.mascot.vision_button.setText('Allowing screen…')
        self.vision_permission = VisionPermission(self.vision, self)
        self.vision_permission.result.connect(self.screen_permission_result)
        self.vision_permission.failed.connect(lambda message: self.screen_permission_failed(message))
        self.vision_permission.start()

    def screen_permission_result(self, result):
        if not result.get('granted'):
            self.screen_permission_failed('Screen Recording is not allowed yet. Enable the requested Terminal/Python/bridge '
                                          'entry in System Settings → Privacy & Security → Screen & System Audio Recording, '
                                          'then enable screen vision again. Some permission changes require restarting the app.')
            return
        self.vision.set_enabled(True)
        self.mascot.vision_button.setText('Screen on')
        self.mascot.vision_button.setAccessibleName('Screen vision is on. Each prompt includes a fresh local screen image. Activate to pause.')
        if self.retry_after_vision and self.last_user_request:
            request, mode, from_mascot = self.last_user_request
            self.retry_after_vision = False
            self.input.setPlainText(request)
            self.ask(mode=mode, from_mascot=from_mascot)
        else:
            self.mascot_home('Screen vision is on. Ask what’s on your screen, or what to do next. Each message gets a fresh look.')

    def screen_permission_failed(self, message):
        self.retry_after_vision = False
        self.vision.set_enabled(False)
        self.mascot.vision_button.setText('Screen off')
        self.mascot_home(message)

    def build_desktop_context(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label('Desktop awareness'))
        layout.addWidget(label('Enable for this session to follow your active application, window title and '
                               'accessible button/control names. No screenshots, text-field values, selected text, '
                               'clipboard, or keystrokes are collected. Context stays in memory. Relevant metadata '
                               'is included when you ask the selected AI provider a question.'))
        self.context_toggle = button('Enable desktop context…', lambda: self.desktop_action('context:toggle'))
        layout.addWidget(self.context_toggle)
        layout.addWidget(button('Open macOS Accessibility settings', lambda: QDesktopServices.openUrl(
            QUrl('x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'))))
        self.context_status = label('Desktop context is off.')
        layout.addWidget(self.context_status)
        self.context_view = QPlainTextEdit()
        self.context_view.setReadOnly(True)
        self.context_view.setAccessibleName('Current desktop metadata sent with AI requests')
        layout.addWidget(self.context_view)
        self.running_apps = QComboBox()
        self.running_apps.setAccessibleName('Running application to switch to')
        layout.addWidget(self.running_apps)
        self.switch_app_btn = button('Switch to selected application', lambda: self.desktop_action('desktop:switch'))
        layout.addWidget(self.switch_app_btn)
        self.observed_controls = QComboBox()
        self.observed_controls.setAccessibleName('Observed accessible control to highlight')
        layout.addWidget(self.observed_controls)
        self.control_highlight_btn = button('Highlight selected control', lambda: self.desktop_action('desktop:highlight'))
        layout.addWidget(self.control_highlight_btn)
        layout.addWidget(label('macOS may ask you to enable Terminal, Python, or desktop-bridge under Privacy & Security → Accessibility. '
                               'App identity can work without that permission; control names and window details require it. '
                               'Some applications expose limited accessibility metadata.'))
        self.context_tab = self.tabs.addTab(page, 'Desktop access')
        self.refresh_desktop_context()

    def refresh_desktop_context(self):
        self.mascot.set_screen_vision_indicator(self.vision.enabled)
        context = self.desktop_monitor.context()
        enabled = context.get('enabled', False)
        app = context.get('app', {}).get('name', '')
        if not enabled:
            title = 'Desktop context off · Enable'
            description = 'Desktop context is off. Enable it to share app/window/control metadata with your chosen model.'
        elif context.get('status') == 'unavailable':
            title = 'Desktop access · Setting up'
            description = context.get('reason', 'Desktop metadata unavailable.')
        elif context.get('status') == 'private_app':
            title = 'Desktop context paused · Private app'
            description = 'A protected app is active. No window/control metadata is collected.'
        else:
            title = 'Context on'+(' · '+app if app else ' · Waiting for an app')
            description = ('Last external app: ' if context.get('companion_focused') else 'Active app: ')+ (app or 'not yet observed')
            if context.get('window', {}).get('title'):
                description += '\nWindow: '+context['window']['title']
            if context.get('accessibility') == 'permission_required':
                description += '\nGrant macOS Accessibility access for window details and controls.'
            elif context.get('controls_stale'):
                description += '\nControl positions expired. Focus the target app briefly to refresh them.'
            else:
                description += f'\n{len(context.get("controls", []))} accessible controls observed. No screenshots.'
        self.mascot.context_button.setText(title)
        self.mascot.context_button.setToolTip(description)
        self.context_toggle.setText('Pause desktop context' if enabled else 'Enable desktop context…')
        self.context_status.setText(description)
        if hasattr(self, 'essentials_access'):
            self.essentials_access.setText(description)
            self.essentials_context.setText('Pause' if enabled else 'Enable…')
            self.essentials_vision.setText('Pause' if self.vision.enabled else 'Enable…')
        self.context_view.setPlainText(json.dumps(context, indent=2, ensure_ascii=False))
        for combo, records, identity, label_key in (
                (self.running_apps, context.get('available_apps', []), 'bundle_id', 'name'),
                (self.observed_controls, context.get('controls', []), 'id', 'label')):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for record in records:
                combo.addItem(record[label_key][:85], record[identity])
            index = combo.findData(previous)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.switch_app_btn.setEnabled(bool(self.running_apps.count()))
        self.control_highlight_btn.setEnabled(bool(self.observed_controls.count()))

    def execute_desktop_action(self, proposal):
        if self.worker and self.worker.isRunning():
            return
        request = self.last_user_request[0] if self.last_user_request else 'Check the action result.'
        self.pending_desktop_action = None
        self.clear_guidance()
        self.hide()
        self.mascot.collapse_chat()
        self.set_busy(True)
        worker = ComputerActionWorker(self.desktop_monitor, proposal, self)
        self.worker = worker
        result = {}
        def submitted(observation):
            result.update(observation)
            self.service.last_action_result = observation
            self.transcript.appendPlainText('Action submitted: '+proposal.get('label', proposal['type'])+'. Checking the result.\n')
        def finished():
            self.set_busy(False)
            if result:
                self.mascot.expand_chat()
                self.input.setPlainText(request)
                self.ask(mode='verify', from_mascot=True)
        worker.result.connect(submitted)
        worker.failed.connect(self.failed)
        worker.finished.connect(finished)
        worker.start()

    def desktop_action(self, action, *, consented=False):
        try:
            if action == 'context:toggle':
                if self.desktop_monitor.enabled:
                    self.desktop_monitor.disable()
                    self.service.desktop_session.clear()
                    self.service.last_action_result = None
                    self.pending_desktop_action = None
                else:
                    if not consented and not self.confirm_access('Help me find my way around',
                            'Let A11y follow your apps, windows and accessible controls.',
                            ['No screenshots, typing or field contents.',
                             'App and control names are shared with your selected AI when you ask for help.',
                             'Access lasts this session. You can pause it at any time.'], 'Enable app awareness'):
                        return
                    self.desktop_monitor.enable()
                    self.mascot.footer.setText('Focus the app you want help with for a moment; I’ll follow it.')
                self.refresh_desktop_context()
            elif action == 'context:details':
                self.tabs.setCurrentIndex(self.context_tab)
                self.reveal()
            elif action == 'desktop:switch':
                bundle = self.running_apps.currentData()
                if bundle:
                    self.desktop_monitor.activate(bundle)
                    self.hide()
                    self.mascot.footer.setText('Application switched. Desktop context will follow it.')
            elif action in ('desktop:highlight', 'desktop:apply'):
                proposed = self.pending_desktop_action if action == 'desktop:apply' else {
                    'type': 'highlight_control', 'control_id': self.observed_controls.currentData()}
                if not proposed:
                    return
                if proposed['type'] == 'request_app_access':
                    if not self.desktop_monitor.enabled:
                        self.desktop_action('context:toggle')
                    elif self.desktop_monitor.context().get('accessibility') == 'permission_required':
                        QDesktopServices.openUrl(QUrl('x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'))
                    self.mascot_home('App awareness is setting up. macOS Accessibility access is needed to inspect and close windows. Once allowed, ask me again.' if self.desktop_monitor.enabled else 'App awareness is off. You can enable it from Settings when you want to use app controls.')
                    return
                if proposed['type'] == 'request_screen':
                    if self.vision.enabled:
                        self.mascot_home('Screen vision is already on. Each new message includes a fresh image. Ask me what you want to inspect.')
                        return
                    self.retry_after_vision = True
                    self.toggle_screen_vision()
                    return
                if proposed['type'] == 'move_companion':
                    self.move_companion(proposed['destination'])
                    return
                if proposed['type'] in ('focus_app', 'press_control', 'launch_app', 'quit_app', 'new_window', 'close_window'):
                    self.execute_desktop_action(proposed)
                    return
                current = self.desktop_monitor.authorize_action({'type': 'highlight_control', 'control_id': proposed['control_id']})
                if proposed.get('observation_id') and proposed['observation_id'] != current['observation_id']:
                    raise ValueError('The window changed. Ask for fresh guidance before highlighting.')
                rect = current['bounds']
                screen = QApplication.screenAt(QPoint(int(rect['x']+rect['width']/2), int(rect['y']+rect['height']/2)))
                if screen is None:
                    raise ValueError('The control is outside the connected displays.')
                area = screen.geometry()
                x = max(0, (rect['x']-area.x())/area.width())
                y = max(0, (rect['y']-area.y())/area.height())
                width = min(rect['width']/area.width(), 1-x)
                height = min(rect['height']/area.height(), 1-y)
                self.overlay.guide(area, {'label': current['label'], 'x': x, 'y': y, 'width': width, 'height': height})
                self.mascot.collapse_chat()
                if not self.service.adaptation.effective(self.service.identity)['reduced_motion']:
                    beside = int(rect['x'])-self.mascot.width()-18
                    if beside < area.left():
                        beside = int(rect['x']+rect['width'])+18
                    self.mascot.move(max(area.left(), min(beside, area.right()-self.mascot.width())),
                                     max(area.top(), min(int(rect['y']), area.bottom()-self.mascot.height())))
                self.mascot.set_state('guiding')
                self.hide()
                self.mascot.footer.setText('Highlighted: '+current['label']+' · expires in 10 seconds')
        except (ValueError, RuntimeError) as e:
            self.mascot_home(str(e))
            self.mascot.expand_chat()
            self.context_status.setText(str(e))

    def build_connection(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label('Connect your AI provider for chat, planning and screen explanations. '
                               'The introduction, preferences and saved progress work without a connection.'))
        config = getattr(self.service.provider, 'config', AIConfig())
        self.connection_fields = {}
        self.provider_choice = QComboBox()
        self.provider_choice.addItem('Ollama · local model', 'ollama')
        self.provider_choice.addItem('Compatible cloud/API provider', 'compatible')
        self.provider_choice.setCurrentIndex(0 if isinstance(self.service.provider, OllamaProvider) else 1)
        layout.addWidget(self.provider_choice)
        form = QFormLayout()
        for key, title, value in [('base_url', 'API base URL', config.base_url),
                                  ('model', 'Chat model', config.model),
                                  ('vision_model', 'Vision model (optional)', config.vision_model),
                                  ('key', 'API key (session only)', '')]:
            field = QLineEdit(value)
            field.setAccessibleName(title)
            if key == 'key':
                field.setEchoMode(QLineEdit.EchoMode.Password)
                field.setPlaceholderText('Leave blank to keep the key for the same endpoint')
            form.addRow(title, field)
            self.connection_fields[key] = field
        layout.addLayout(form)
        self.local_models = QComboBox()
        self.local_models.setAccessibleName('Installed local Ollama models')
        self.local_models.currentIndexChanged.connect(self.select_local_model)
        layout.addWidget(self.local_models)
        self.scan_btn = button('Find local Ollama models', self.scan_ollama)
        layout.addWidget(self.scan_btn)
        self.connect_btn = button('Use this connection for this session', self.connect_provider)
        layout.addWidget(self.connect_btn)
        self.connection_status = label('Keys entered here are held in memory and are not written to disk. '
                                       'This checks configuration; the next AI request tests connectivity.')
        layout.addWidget(self.connection_status)
        layout.addStretch()
        self.tabs.addTab(page, 'AI connection')

    def scan_ollama(self):
        if self.discovery and self.discovery.isRunning():
            return
        self.scan_btn.setEnabled(False)
        self.connection_status.setText('Checking local Ollama and installed models…')
        self.discovery = OllamaDiscovery(self)
        self.discovery.result.connect(self.ollama_discovered)
        self.discovery.failed.connect(self.ollama_unavailable)
        self.discovery.finished.connect(lambda: self.scan_btn.setEnabled(True))
        self.discovery.start()

    def ollama_unavailable(self, message):
        self.connection_status.setText(message)
        if isinstance(self.service.provider, OllamaProvider):
            self.mascot.footer.setText('Ollama is offline · start ollama serve, then scan in Settings → AI connection')

    def ollama_discovered(self, result):
        provider, models = result
        self.local_models.blockSignals(True)
        self.local_models.clear()
        for model in models:
            self.local_models.addItem(model['name']+(' · vision' if model['vision'] else ''), model['name'])
        self.local_models.blockSignals(False)
        if not models:
            self.connection_status.setText('Ollama is running, but no local chat models are installed. Download a model with ollama pull <model>, then scan again.')
            return
        self.connection_status.setText(f'Ollama is running. Found {len(models)} local chat model(s).')
        if isinstance(self.service.provider, OllamaProvider) and not self.service.provider.config.model:
            self.select_local_model()
            self.connect_provider()

    def select_local_model(self, index=None):
        model = self.local_models.currentData()
        if model:
            self.provider_choice.setCurrentIndex(0)
            self.connection_fields['base_url'].setText(OllamaProvider().config.base_url)
            self.connection_fields['model'].setText(model)
            self.connection_fields['key'].clear()

    def connect_provider(self):
        if self.worker and self.worker.isRunning():
            self.connection_status.setText('Wait for the current request to finish before changing provider.')
            return
        values = {key: field.text().strip() for key, field in self.connection_fields.items()}
        old = getattr(self.service.provider, 'config', AIConfig())
        if not values['key'] and values['base_url'].rstrip('/') == old.base_url.rstrip('/'):
            values['key'] = old.key
        try:
            config = AIConfig(**values)
            if self.provider_choice.currentData() == 'ollama':
                local_url(config.base_url)
                if not config.model:
                    raise ProviderError('Choose an installed local model first.')
            else:
                config.validate()
        except ProviderError as e:
            self.connection_status.setText(str(e))
            return
        self.service.provider = OllamaProvider(AIConfig(base_url=config.base_url, model=config.model, vision_model=config.vision_model, timeout=120)) if self.provider_choice.currentData() == 'ollama' else ChatProvider(config)
        self.connection_fields['key'].clear()
        self.connection_status.setText('Connection settings applied for this session. Ask me a question to test the provider.')
        self.refresh()
        if not self.setup_active:
            self.mascot_home('Connection settings are ready. What would you like to work on?')

    def say(self, message, choices=(), **options):
        self.latest_response = message
        self.read_btn.setEnabled(self.tts is not None)
        self.mascot.present(message, choices, **options)
        self.mascot.set_state('idle')

    def show_setup_question(self):
        data = self.introduction.get()
        if data['step'] == len(QUESTIONS):
            self.say('Here’s what I’ve learned about how you want to work:\n\n'+self.introduction.summary()+
                     '\n\nSave these settings? Working preferences are included with future AI requests. '
                     'Your saved name, work role and preferences help personalize replies and are sent to your configured AI provider. Ollama runs locally. You can edit them by restarting this introduction.',
                     [('Save my preferences', 'setup:save'), ('Go back', 'setup:back'), ('Finish later', 'setup:later')],
                     stage='Your choices · review before saving')
            return
        key, question, options = QUESTIONS[data['step']]
        choices = []
        if options:
            choices.extend((title, 'setup:choice:'+json.dumps(value)) for title, value in options)
        choices.append(('Skip this question', 'setup:skip'))
        if data['step']:
            choices.append(('Go back', 'setup:back'))
        choices.append(('Finish later', 'setup:later'))
        name = data['answers'].get('display_name')
        prefix = f'Nice to meet you, {name}!\n\n' if key == 'work_role' and name else ''
        self.say(prefix+question, choices,
                 placeholder=('Your name (optional)' if key == 'display_name' else 'Your role, e.g. software engineer (optional)') if not options else None,
                 value=data['answers'].get(key, '') if not options else '', submit_action='setup',
                 stage=f'Getting to know you · {data["step"]+1} of {len(QUESTIONS)} · optional')

    def mascot_home(self, message=None, *, sources=()):
        self.setup_active = False
        choices = []
        if self.pending_target:
            choices.append(('Show me where', 'guide'))
        elif self.pending_desktop_action:
            choices.append((self.pending_desktop_action.get('confirmation_label', self.pending_desktop_action['label']), 'desktop:apply'))
        self.say(message or 'What would you like help with?', choices, placeholder='Ask anything…', compact=True)

    def mascot_submit(self, request, action):
        try:
            if action == 'setup':
                if not self.setup_active:
                    return
                self.introduction.answer(request)
                self.show_setup_question()
                return
            self.input.setPlainText(request)
            self.ask(mode='plan' if action == 'plan' else 'assist', from_mascot=True)
        except (ValueError, PermissionError) as e:
            self.mascot.footer.setText(str(e))

    def mascot_action(self, action):
        if action == 'reply':
            self.mascot.show_reply()
            return
        if action == 'vision:toggle':
            self.toggle_screen_vision()
            return
        if action == 'guide':
            self.show_guidance()
            return
        if action in ('talk', 'tasks', 'setup:restart', 'setup:start') or action.startswith('task:'):
            self.mascot.expand_chat()
        if action.startswith('context:') or action.startswith('desktop:'):
            self.desktop_action(action)
            return
        if self.worker and self.worker.isRunning() and action not in ('settings', 'history', 'read', 'stop_speech', 'quit'):
            self.mascot.footer.setText('Let me finish this request before we change tasks.')
            return
        try:
            if action == 'quit':
                self.request_quit()
            elif action in ('settings', 'history'):
                self.tabs.setCurrentIndex(0 if action == 'history' else self.essentials_tab)
                self.reveal()
            elif action == 'read':
                if self.tts:
                    self.read_response()
                else:
                    self.mascot.footer.setText('No system voice is available. All instructions are shown as text.')
            elif action == 'stop_speech':
                self.stop_speech()
            elif action == 'talk':
                if self.setup_active:
                    self.show_setup_question() if self.introduction.get()['status'] == 'in_progress' else self.start_companion()
                else:
                    self.mascot_home()
            elif action == 'tasks':
                workflows = self.service.state()['workflows']
                choices = [(w['title'][:64]+' · '+w['status'], 'task:'+w['id']) for w in workflows]
                self.say('Choose where we should pick up. Your last confirmed step is saved.' if workflows else
                         'No saved tasks yet. Tell me what you want to do, then choose “Make a plan from my reply”.',
                         choices+[('Back to our conversation', 'talk')])
            elif action.startswith('task:'):
                self.refresh(action[5:])
                self.mascot_home('Let’s pick up where we left off.')
            elif action == 'confirm':
                self.confirm_step()
            elif action == 'highlight':
                self.show_guidance()
            elif action in ('plan', 'screen'):
                request = self.mascot.input.text().strip()
                if not request and action == 'screen':
                    request = 'Help me with the current step on this screen.' if self.selected_workflow() else 'Explain this screen and the available controls.'
                if not request:
                    self.mascot_home('Describe the task in the prompt, then ask me to make a plan.')
                    self.mascot.expand_chat()
                    self.mascot.input.setFocus()
                    return
                self.input.setPlainText(request)
                if action == 'plan':
                    self.ask(mode='plan', from_mascot=True)
                else:
                    current_screen = self.mascot.screen()
                    index = self.screens.findData(current_screen)
                    if index >= 0:
                        self.screens.setCurrentIndex(index)
                    self.capture_screen(from_mascot=True)
            elif action.startswith('adapt:'):
                _, decision, signal = action.split(':', 2)
                self.service.adaptation.decide(self.service.identity, signal, decision == 'yes')
                self.refresh()
                self.mascot_home('Got it. Your preference choice is saved.')
            elif action == 'setup:wizard':
                self.open_setup()
            elif action in ('setup:start', 'setup:restart'):
                self.introduction.start(restart=action == 'setup:restart')
                self.setup_active = True
                self.show_setup_question()
            elif action == 'setup:later':
                self.mascot_home('No rush. You can restart our introduction from Companion menu whenever you like.')
            elif action == 'setup:back':
                self.introduction.back()
                self.show_setup_question()
            elif action == 'setup:skip':
                self.introduction.answer(skip=True)
                self.show_setup_question()
            elif action.startswith('setup:choice:'):
                self.introduction.answer(json.loads(action[len('setup:choice:'):]))
                self.show_setup_question()
            elif action == 'setup:save':
                data = self.introduction.save()
                self.refresh()
                name = data['answers'].get('display_name', '')
                self.mascot_home((f'We’re all set, {name}!' if name else 'We’re all set!')+
                                 ' I’ve saved your choices. You can talk to me right here. What are we working on first?')
        except (ValueError, PermissionError) as e:
            self.mascot.footer.setText(str(e))

    def request_quit(self):
        if (self.worker and self.worker.isRunning()) or (self.discovery and self.discovery.isRunning()) or (self.vision_permission and self.vision_permission.isRunning()):
            self.mascot.footer.setText('I’m still waiting for the current request. Please quit after it finishes.')
            return
        self.quitting = True
        self.desktop_monitor.disable()
        self.vision.set_enabled(False)
        self.context_timer.stop()
        self.stop_speech()
        self.overlay.close()
        self.mascot.close()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if getattr(self, 'setup_dialog', None):
            self.setup_dialog.close()
        if self.quitting:
            event.accept()
        else:
            self.hide()
            event.ignore()
