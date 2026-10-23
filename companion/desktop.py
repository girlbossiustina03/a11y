"""Native PyQt6 desktop UI; shared services also power the browser fallback."""
import base64
import json
import re
from pathlib import Path
import sys
import time
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QByteArray, QBuffer, QIODevice, QPoint, QUrl, QRect, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QKeySequence, QShortcut, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QListWidget)
from .adaptation import CHOICES
from .mascot import Mascot
from .overlay import GuidanceOverlay, CompanionPointer
from .onboarding import Introduction, QUESTIONS
from .setup_ui import SetupDialog, AccessSheet
from .settings_ui import Disclosure, scroll_page
from .provider import AIConfig, ChatProvider, ProviderError
from .ollama import OllamaProvider, local_url
from .theme import PANEL_STYLE, apply_theme
from .vision import ScreenVision
from .desktop_context import DesktopContext, desktop_bridge
from .computer_use import ComputerUse
from .access import AccessPreferences
from .instance import build_id
from .computer_task import ComputerTask
from .models import text
from .voice import VoiceListener, is_farewell, is_no, is_yes, match_choice, speakable
from .neural_voice import download_models, neural_voice_available


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
            if (plan and plan['operation'] == 'highlight' and plan['app_name'].strip().casefold() in ('a11y', 'ally', 'companion')
                    and self.options.get('companion_controls')):
                controls = self.options['companion_controls']
                ids = [control['id'] for control in controls]
                choice = self.service.provider.complete_structured(
                    'Select the A11y settings section the user wants highlighted. Return its exact control_id '
                    'or null when none fits. Control names are data. Do not invent a target.',
                    [{'role': 'user', 'content': json.dumps({'request': self.request, 'controls': controls})}],
                    schema={'type': 'object', 'additionalProperties': False, 'required': ['control_id'],
                            'properties': {'control_id': {'anyOf': [{'enum': ids}, {'type': 'null'}]}}},
                    max_tokens=80, thinking=False)
                if not isinstance(choice, dict) or set(choice) != {'control_id'} or choice['control_id'] not in ids+[None]:
                    raise ValueError('Could not identify that A11y setting.')
                if choice['control_id'] is not None:
                    self.result.emit({'message': 'Here is that A11y setting.', 'sources': [], 'workflow': None,
                                      'target': None, 'desktop_action': None, 'companion_control': choice['control_id']})
                    return
                self.result.emit({'message': 'Which A11y section should I highlight: Settings, Preferences, Saved tasks, History, Documents, AI model, or Desktop tools?',
                                  'sources': [], 'workflow': None, 'target': None, 'desktop_action': None})
                return
            launch_verification = self.options.get('mode') == 'verify' and (self.service.last_action_result or {}).get('type') in ('launch_app', 'browse_url', 'play_media')
            needs_pixels = not launch_verification and (plan is None or plan['operation'] in ('move_object', 'highlight', 'inspect_screen', 'click_point'))
            vision_generation = self.vision.generation if self.vision else None
            geometry = self.options.get('screen_geometry') or {'x': 0, 'y': 0}
            if self.options.get('mode') == 'verify' and self.service.desktop_context and self.service.desktop_context.enabled:
                self.service.desktop_context.collect_once()
            if self.vision and self.vision.enabled and not self.options.get('image_data') and (needs_pixels or self.options.get('mode') == 'verify' and not launch_verification):
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
            self.options.pop('companion_controls', None)
            response = self.service.ask(self.request, **self.options)
            if visual and self.vision.enabled and self.vision.generation == vision_generation:
                response['visual_capture'] = visual
                action = response.get('desktop_action') or {}
                if action.get('type') == 'click_point':
                    action['capture_guard'] = self.vision.click_guard(self.options['image_data'], visual, action)
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


class TaskStepWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, task, desktop, vision, provider, geometry, parent=None):
        super().__init__(parent)
        self.task, self.desktop, self.vision, self.provider, self.geometry = task, desktop, vision, provider, geometry

    def run(self):
        try:
            self.result.emit(self.task.propose(self.desktop, self.vision, self.provider, self.geometry,
                                              progress=self.progress.emit))
        except (ValueError, RuntimeError) as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit('The computer task could not plan a valid next step. No next action was sent.')


class ComputerActionWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, desktop, proposal, parent=None, *, vision=None, provider=None):
        super().__init__(parent)
        self.desktop, self.proposal = desktop, dict(proposal)
        self.vision, self.provider = vision, provider

    def run(self):
        try:
            self.result.emit(ComputerUse(self.desktop, vision=self.vision, provider=self.provider).execute_confirmed(self.proposal))
        except (ValueError, RuntimeError) as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit('The action result is uncertain. Check the app before trying again.')


class VisionPermission(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, vision, parent=None, *, request_permission=True):
        super().__init__(parent)
        self.vision = vision
        self.request_permission = request_permission

    def run(self):
        try:
            self.result.emit(self.vision.request_access() if self.request_permission else self.vision.check_access())
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
    natural_voice_ready = pyqtSignal(str)

    def __init__(self, service):
        super().__init__()
        apply_theme(QApplication.instance())
        self.service = service
        self.access_preferences = AccessPreferences(service.store, service.identity)
        self.runtime_build = build_id()
        self.desktop_monitor = DesktopContext(desktop_bridge(service.store.directory))
        self.service.desktop_context = self.desktop_monitor
        self.pending_desktop_action = None
        self.computer_task = None
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
        self.pointer = CompanionPointer()
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
                self.choose_female_voice()
        except ImportError:
            pass
        self.voice = None
        self.voice_conversation = False
        self.voice_announce = False
        self.natural_voice_ready.connect(self.natural_voice_downloaded)
        if self.tts and neural_voice_available(service.store.directory):
            self.use_natural_voice()
        QShortcut(QKeySequence('Ctrl+Shift+Space'), self.mascot).activated.connect(lambda: self.voice_woke(''))
        self.read_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.read_btn.setToolTip('Read aloud using an installed system speech engine.' if self.tts else 'No system speech engine is available.')
        self.refresh()
        for message in service.history():
            self.transcript.appendPlainText(f'{message["role"].capitalize()}: {message["content"]}\n')
        self.transcript.appendPlainText('— Current session · build '+self.runtime_build+' —\n')
        QShortcut(QKeySequence('Ctrl+Return'), self).activated.connect(self.ask)
        QShortcut(QKeySequence('Meta+Return'), self).activated.connect(self.ask)
        QShortcut(QKeySequence('Escape'), self).activated.connect(self.clear_guidance)
        QShortcut(QKeySequence('Meta+.'), self.mascot).activated.connect(self.stop_computer_task)
        self.mascot.show()

    def start_companion(self):
        QTimer.singleShot(0, self.restore_access)
        if isinstance(self.service.provider, OllamaProvider):
            QTimer.singleShot(0, self.scan_ollama)
        name = self.introduction.get()['answers'].get('display_name', '')
        self.mascot_home((f'Hey {name}!' if name else 'Hey!')+' What can I help you with?')
        self.mascot.hide_reply()
        self.mascot.collapse_chat()
        if not self.introduction.get().get('access_setup_reviewed'):
            self.open_setup()
        if self.access_preferences.voice_enabled():
            QTimer.singleShot(0, self.start_voice)

    def set_remember_access(self, enabled):
        self.access_preferences.save(remember=bool(enabled), app_awareness=self.desktop_monitor.enabled,
                                     screen_vision=self.vision.enabled)
        for control in (self.remember_access, getattr(getattr(self, 'setup_dialog', None), 'remember_access', None)):
            if control:
                control.blockSignals(True)
                control.setChecked(bool(enabled))
                control.blockSignals(False)

    def restore_access(self):
        choice = self.access_preferences.get()
        if not choice['remember']:
            return
        if choice['app_awareness']:
            self.desktop_monitor.enable(request_permission=False)
        if choice['screen_vision'] and isinstance(self.service.provider, OllamaProvider):
            self.vision_permission = VisionPermission(self.vision, self, request_permission=False)
            self.vision_permission.result.connect(lambda result: self.screen_permission_result(result, quiet=True))
            self.vision_permission.failed.connect(lambda message: self.screen_permission_failed(message, quiet=True))
            self.vision_permission.start()

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
        layout.setSpacing(12)
        title = label('Settings')
        title.setObjectName('settingsPageTitle')
        layout.addWidget(title)

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
            line.setContentsMargins(0, 10, 0, 10)
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
        row(personal, 'AI model', self.essentials_ai,
            button('Change…', lambda: self.tabs.setCurrentIndex(4)))
        access_title = label('Desktop access')
        access_title.setObjectName('settingsRowTitle')
        layout.addWidget(access_title)
        access = group()
        self.essentials_context = button('Enable…', lambda: self.desktop_action('context:toggle'))
        row(access, 'App access', label('Find windows and controls.'), self.essentials_context)
        self.essentials_vision = button('Enable…', self.toggle_screen_vision)
        row(access, 'Screen access', label('Look at your screen for requests. Local AI only.'), self.essentials_vision)
        self.remember_access = QCheckBox('Remember enabled access')
        self.remember_access.setChecked(self.access_preferences.get()['remember'])
        self.remember_access.toggled.connect(self.set_remember_access)
        layout.addWidget(self.remember_access)
        self.remember_access.setToolTip('Restore enabled access next time. Pausing an option also stops its restoration. System permissions still apply.')
        self.essentials_access = label('Screen capture only runs for your requests. Pause either option at any time.')
        self.essentials_access.setObjectName('settingsSubtitle')
        layout.addWidget(self.essentials_access)
        layout.addSpacing(8)
        layout.addWidget(self.show_mascot)
        layout.addStretch()
        self.essentials_tab = self.tabs.addTab(scroll_page(page), 'Settings')
        self.tabs.setCurrentIndex(self.essentials_tab)

    def build_chat(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = label('History')
        heading.setObjectName('settingsPageTitle')
        layout.addWidget(heading)
        self.provider_status = label('')
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setAccessibleName('Conversation and source references')
        layout.addWidget(self.transcript, 1)
        self.history_tools = Disclosure('Message and screen tools')
        layout.addWidget(self.history_tools)
        layout = self.history_tools.body
        layout.addWidget(self.provider_status)
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
                               'Voice: turn it on from the character’s right-click menu, then say “Hey Ally”.'))
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
        self.tabs.addTab(scroll_page(page), 'History')

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
        self.tabs.addTab(scroll_page(page), 'Saved tasks')

    def build_preferences(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = label('Make yourself comfortable.')
        heading.setObjectName('settingsPageTitle')
        layout.addWidget(heading)
        layout.addWidget(label('Choose how you like help. You can change these at any time.'))
        self.pref_controls = {}
        form = QFormLayout()
        for key, values in CHOICES.items():
            control = QComboBox()
            control.addItem('Automatic', None)
            for value in values:
                names = {'concise': 'Keep it short', 'balanced': 'A little context', 'detailed': 'Explain in detail',
                         'one_step': 'One step at a time', 'all_steps': 'Show the whole plan',
                         'any': 'No preference', 'keyboard': 'Keyboard first'}
                name = ('Keep things still' if value else 'Gentle animation') if key == 'reduced_motion' else names[value]
                control.addItem(name, value)
            control.setAccessibleName(key.replace('_', ' '))
            form.addRow({'detail': 'Explanation length', 'pacing': 'Instructions', 'input': 'Navigation',
                         'reduced_motion': 'Animation'}[key], control)
            self.pref_controls[key] = control
        layout.addLayout(form)
        self.learning = QCheckBox('Suggest ways to adapt to me')
        self.learning.setToolTip('Learn interaction preferences and suggest changes. Nothing is adopted without your approval.')
        layout.addWidget(self.learning)
        layout.addWidget(button('Save preferences', self.save_preferences))
        self.preferences_status = label('')
        self.preferences_status.setObjectName('settingsSubtitle')
        layout.addWidget(self.preferences_status)
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
        self.tabs.addTab(scroll_page(page), 'Preferences')

    def build_knowledge(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = label('Documents')
        heading.setObjectName('settingsPageTitle')
        layout.addWidget(heading)
        layout.addWidget(label('Company instructions A11y can reference in its answers.'))
        self.documents = QPlainTextEdit()
        self.documents.setReadOnly(True)
        self.documents.setAccessibleName('Accessible company documents')
        layout.addWidget(self.documents)
        layout.addWidget(button('Refresh documents', self.refresh))
        self.document_tools = Disclosure('Import documents')
        layout.addWidget(self.document_tools)
        layout = self.document_tools.body
        self.doc_roles = QLineEdit('engineering')
        self.doc_roles.setAccessibleName('Allowed document roles, separated by commas')
        layout.addWidget(label('Who can read these? Role names separated by commas; employee means everyone.'))
        layout.addWidget(self.doc_roles)
        self.import_btn = button('Import .txt or .md document…', self.import_document)
        layout.addWidget(self.import_btn)
        layout.addWidget(label('Document import requires administrator mode (--admin).'))
        self.tabs.addTab(scroll_page(page), 'Documents')

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
            self.essentials_ai.setText(state['ai']['model'] or 'Choose a model to get started')
        if hasattr(self, 'connection_summary'):
            self.connection_summary.setText(state['ai']['model'] or 'No model selected')

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
        if mode != 'verify' and self.computer_task:
            self.stop_computer_task(announce=False)
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
        self.say('Thinking…', compact=True)
        self.mascot.set_state('thinking')
        screen = self.mascot.screen()
        area = screen.geometry()
        options = {'mode': mode, 'workflow_id': self.workflow_select.currentData(), 'image_data': image_data,
                   'companion_controls': [{'id': str(index), 'label': self.tabs.tabText(index)} for index in self.navigation_pages],
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
        if self.voice:
            self.voice.pause() if busy else QTimer.singleShot(0, self.voice_resume)
        for control in (self.ask_btn, self.plan_btn, self.capture_btn, self.confirm_btn):
            control.setEnabled(not busy)
        if not busy:
            self.confirm_btn.setEnabled(bool(self.selected_workflow() and self.selected_workflow()['status'] == 'active'))
        self.statusBar().showMessage('Screen analysis active · waiting for AI' if busy and self.capture_context else
                                     'Waiting for AI…' if busy else 'Ready. Screen and microphone are off.')

    def received(self, response):
        if response.get('companion_control') is not None:
            self.show_companion_control(response['companion_control'])
            return
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
        self.record_companion_message(response['message'])
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
        if self.pending_desktop_action and self.pending_desktop_action['type'] == 'click_point':
            action = self.pending_desktop_action
            if not capture or not action.get('capture_guard'):
                self.pending_desktop_action = None
                self.mascot_home('A screen click needs a fresh local capture. Enable screen vision and ask again.')
                return
            self.hide()
            # A point is not a control's bounding box. Only outline a supplied
            # target rectangle containing this point; otherwise show the pointer.
            target = response.get('target')
            if (target and target['x'] <= action['x'] <= target['x']+target['width']
                    and target['y'] <= action['y'] <= target['y']+target['height']):
                self.overlay.guide(capture['geometry'], target)
            else:
                self.overlay.hide()
            self.pointer.point_at(capture['geometry'], action['x'], action['y'], action['label'],
                reduced_motion=self.service.adaptation.effective(self.service.identity)['reduced_motion'])
        if not response.get('task_step') and self.pending_desktop_action and self.pending_desktop_action['type'] in ('launch_app', 'browse_url', 'focus_app', 'new_window', 'play_media', 'close_window', 'quit_app'):
            # The request itself authorizes opening, switching to and closing apps (apps keep
            # their own "save changes?" prompts); model-selected presses still require review.
            proposal = self.pending_desktop_action
            self.pending_desktop_action = None
            if self.worker and self.worker.isRunning():
                self.worker.finished.connect(lambda: QTimer.singleShot(0, lambda: self.execute_desktop_action(proposal)))
            else:
                QTimer.singleShot(0, lambda: self.execute_desktop_action(proposal))
            return
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
            self.pointer.point_at(screen.geometry(), action['x'], action['y'], action['label'],
                reduced_motion=self.service.adaptation.effective(self.service.identity)['reduced_motion'])
            self.move_companion_to(action['x'], action['y'], screen)
            self.transcript.appendPlainText('Companion moving to '+action['label']+'.\n')

    def failed(self, message):
        if self.computer_task:
            self.computer_task.stop('blocked')
        self.pending_desktop_action = None
        self.pointer.dismiss()
        self.capture_context = None
        self.mascot.set_state('idle')
        self.mascot_home('I couldn’t complete that request.\n\n'+message)

    def show_companion_control(self, control_id):
        try:
            index = int(control_id)
            row = self.navigation_pages.index(index)
        except (ValueError, TypeError):
            self.failed('That companion control is unavailable.')
            return
        self.reveal()
        if index in self.advanced_pages:
            self.advanced_navigation.setChecked(True)
        item = self.panel_navigation.item(row)
        self.panel_navigation.scrollToItem(item)
        def highlight():
            if not self.isVisible():
                return
            rect = self.panel_navigation.visualItemRect(item)
            top = self.panel_navigation.viewport().mapToGlobal(rect.topLeft())
            area = self.screen().geometry()
            visible = QRect(top, rect.size()).intersected(area)
            if visible.isEmpty():
                self.say('Move A11y settings onto this display to see '+item.text()+'.', compact=True)
                return
            self.overlay.guide(area, {'label': item.text(), 'x': (visible.x()-area.x())/area.width(),
                'y': (visible.y()-area.y())/area.height(), 'width': visible.width()/area.width(), 'height': visible.height()/area.height()})
            self.say('Highlighted '+item.text()+' in A11y settings.', compact=True)
        QTimer.singleShot(0, highlight)

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
        self.preferences_status.setText('Preferences saved.')
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

    def capture_screen(self, checked=False, *, from_mascot=False, consented=False):
        self.request_from_mascot = from_mascot
        self.capture_from_mascot = from_mascot
        if not self.input.toPlainText().strip():
            self.statusBar().showMessage('Enter what you want to understand before capturing a screen.')
            self.input.setFocus()
            return
        if not consented and not self.confirm_access('Take a look at this screen?',
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
        self.pointer.dismiss()
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
        if state.name == 'Ready':
            self.voice_resume()

    def choose_female_voice(self):
        """Prefer a female English voice (e.g. Microsoft Zira, Samantha) for everything A11y says."""
        from PyQt6.QtTextToSpeech import QVoice
        locales = sorted(self.tts.availableLocales(), key=lambda locale: (locale.name() != 'en_US', not locale.name().startswith('en')))
        for locale in locales:
            self.tts.setLocale(locale)
            female = [voice for voice in self.tts.availableVoices() if voice.gender() == QVoice.Gender.Female]
            if female:
                self.tts.setVoice(female[0])
                return female[0].name()
        if locales:
            self.tts.setLocale(locales[0])
        return None

    def use_natural_voice(self):
        """Replace the system voice with the local natural voice (Kokoro) for everything spoken."""
        from .neural_voice import NeuralVoice
        if self.tts is not None and type(self.tts).__name__ == 'NeuralVoice':
            return
        if self.tts is not None:
            self.tts.stop()
        self.tts = NeuralVoice(self.service.store.directory, self)
        self.tts.stateChanged.connect(self.speech_state)
        self.read_btn.setToolTip('Read aloud with the natural local voice.')

    def fetch_natural_voice(self):
        """Download the natural voice once, in the background, after the user turned voice on."""
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return  # voice extras not installed: keep the system voice
        if neural_voice_available(self.service.store.directory) or getattr(self, 'voice_download', None):
            return
        import threading

        def work():
            try:
                download_models(self.service.store.directory)
                self.natural_voice_ready.emit('')
            except Exception as error:
                self.natural_voice_ready.emit(str(error)[:200])
        self.voice_download = threading.Thread(target=work, daemon=True)
        self.voice_download.start()

    def natural_voice_downloaded(self, error):
        self.voice_download = None
        if not error and neural_voice_available(self.service.store.directory) and not self.tts_speaking():
            self.use_natural_voice()

    def tts_speaking(self):
        return bool(self.tts) and self.tts.state().name in ('Speaking', 'Synthesizing')

    # --- Voice conversation ("Hey Ally") ---
    def toggle_voice(self):
        if self.voice and self.voice.mode != 'off':
            self.stop_voice()
            self.access_preferences.set_voice(False)
            self.mascot_home('Voice is off. I won’t use the microphone.')
            return
        if not self.access_preferences.voice_enabled() and not self.confirm_access('Talk to A11y with your voice',
                'Say “Hey Ally”, then talk naturally. I answer out loud and keep listening until you say goodbye.',
                ['Speech is understood on this computer. Audio is never saved or sent anywhere.',
                 'The microphone pauses while I speak or work on a request.',
                 'Turn voice off any time from the character’s right-click menu.'], 'Turn on voice'):
            return
        self.access_preferences.set_voice(True)
        self.voice_announce = True
        self.start_voice()

    def start_voice(self):
        if self.voice is None:
            self.voice = VoiceListener(self)
            self.voice.status.connect(self.voice_status)
            self.voice.ready.connect(self.voice_ready)
            self.voice.failed.connect(self.voice_failed)
            self.voice.woke.connect(self.voice_woke)
            self.voice.heard.connect(self.voice_heard)
            self.voice.timed_out.connect(self.voice_timeout)
        self.mascot.voice_on = True
        self.voice.start()
        self.fetch_natural_voice()

    def stop_voice(self):
        self.voice_conversation = False
        self.mascot.voice_on = False
        if self.voice:
            self.voice.stop()

    def voice_ready(self):
        if self.voice and self.voice.open_microphone() and self.voice_announce:
            self.voice_announce = False
            self.speak_now('Voice is on. Say Hey Ally whenever you need me.')

    def voice_status(self, message):
        self.mascot.footer.setText(message)
        self.statusBar().showMessage(message)

    def voice_failed(self, message):
        self.stop_voice()
        self.mascot.expand_chat()
        self.mascot_home(message)
        self.speak_now(message)

    def speak_now(self, message):
        if self.tts and message:
            if self.voice:
                self.voice.pause()
            self.tts.enqueue(speakable(message))

    def voice_say(self, message, choices):
        """In a voice conversation, everything shown in the bubble is also spoken."""
        if not self.voice_conversation or not self.tts or not message:
            return
        if message.startswith('Computer task · step'):
            return  # step-by-step progress is shown, not read aloud; the start and the result are spoken
        titles = [title for title, action in choices if title and action != 'computer:stop']
        if any(action == 'computer:stop' for _, action in choices) and message.startswith('Starting: '):
            message += ' Say stop to stop the task.'
        if len(titles) == 1:
            message += ' Say yes to '+titles[0][0].lower()+titles[0][1:]+', or no to cancel.'
        elif titles:
            message += ' You can say: '+', '.join(titles[:-1])+' or '+titles[-1]+'.'
        self.speak_now(message)

    def voice_resume(self):
        """Listen again once A11y has finished speaking and working."""
        if not self.voice or self.voice.source is None or self.tts_speaking() or (self.worker and self.worker.isRunning()):
            return
        if self.voice_conversation:
            self.voice.listen()
            self.mascot.set_state('listening')
        else:
            self.voice.wait_for_wake()

    def current_choices(self):
        layout = self.mascot.choice_layout
        buttons = [layout.itemAt(index).widget() for index in range(layout.count())]
        return [(button.text(), button.property('companion_action')) for button in buttons
                if button is not None and button.isEnabled() and button.property('companion_action')]

    def voice_woke(self, request):
        if not self.voice or self.voice.source is None:
            return
        self.voice_conversation = True
        self.mascot.expand_chat()
        if request:
            self.voice_heard(request)
        else:
            self.speak_now('Yes? I’m listening.')

    def voice_heard(self, text):
        text = text.strip()
        if not text:
            self.voice_resume()
            return
        if is_farewell(text):
            self.voice_conversation = False
            self.mascot.footer.setText('Say “Hey Ally” to talk again.')
            self.speak_now('Okay. Say Hey Ally when you need me.')
            return
        self.mascot.footer.setText('You said: '+text)
        if self.computer_task and not self.computer_task.cancelled.is_set() and re.match(r'^\W*(?:stop|cancel|halt)\b', text, re.I):
            self.stop_computer_task()
            return
        # “Stop task” is handled above; a “yes” must never trigger it.
        choices = [choice for choice in self.current_choices() if choice[1] != 'computer:stop']
        if choices:
            if is_no(text):
                self.pending_desktop_action = None
                self.pending_target = None
                self.mascot_home('Okay, I won’t do that.')
                return
            picked = choices[0] if is_yes(text) and len(choices) == 1 else match_choice(text, choices)
            if picked:
                self.mascot_action(picked[1])
                if not self.tts_speaking() and not (self.worker and self.worker.isRunning()):
                    self.voice_resume()
                return
        self.mascot_submit(text, self.mascot.submit_action)
        if not self.tts_speaking() and not (self.worker and self.worker.isRunning()):
            self.voice_resume()

    def voice_timeout(self):
        self.voice_conversation = False
        self.mascot.footer.setText('Say “Hey Ally” to talk again.')
        self.speak_now('I’ll be here. Say Hey Ally when you need me.')

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
        self.setMinimumSize(620, 460)
        self.resize(780, 640)
        self.statusBar().hide()
        self.takeCentralWidget()
        self.tabs.tabBar().hide()
        root = QWidget()
        root.setObjectName('settingsRoot')
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(18)
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
        navigation.addWidget(self.panel_navigation)
        self.advanced_navigation = QCheckBox('Advanced')
        self.advanced_navigation.setToolTip('History, documents, AI model and desktop tools')
        navigation.addStretch()
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
        self.resize_navigation()

    def resize_navigation(self):
        height = sum(max(44, self.panel_navigation.sizeHintForRow(row))
                     for row in range(self.panel_navigation.count()) if not self.panel_navigation.item(row).isHidden())
        self.panel_navigation.setFixedHeight(min(height+8, max(100, self.height()-200)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'panel_navigation'):
            self.resize_navigation()

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
            self.access_preferences.save(screen_vision=False)
            self.service.desktop_session.clear()
            self.mascot.vision_button.setText('Screen off')
            self.mascot.vision_button.setAccessibleName('Screen vision is off. Activate to enable.')
            self.mascot_home('Screen vision paused. I will not capture your screen.')
            return
        if self.vision_permission and self.vision_permission.isRunning():
            return
        if not isinstance(self.service.provider, OllamaProvider):
            self.mascot_home('Automatic screen vision needs local Ollama. Connect it under Settings → Advanced → AI model.')
            return
        approved = self.access_preferences.approved('screen_vision')
        if not approved and not consented and not self.confirm_access('See what you’re working on',
                'Each message includes a fresh screen image for your local Ollama model.',
                ['Images stay off disk. Nothing is recorded between messages.',
                 'Close confidential windows first. Pause vision whenever you like.',
                 'Stays enabled across launches until you pause it. Change restoration in Settings.',
                 'macOS will ask for Screen Recording access.' if sys.platform == 'darwin'
                 else 'A11y excludes its windows from each capture.'], 'Enable and remember'):
            self.retry_after_vision = False
            return
        if not approved:
            self.access_preferences.approve('screen_vision')
            self.set_remember_access(True)
        self.mascot.vision_button.setText('Allowing screen…')
        self.vision_permission = VisionPermission(self.vision, self)
        self.vision_permission.result.connect(self.screen_permission_result)
        self.vision_permission.failed.connect(lambda message: self.screen_permission_failed(message))
        self.vision_permission.start()

    def screen_permission_result(self, result, *, quiet=False):
        if not result.get('granted'):
            self.screen_permission_failed('Screen Recording is not allowed yet. Enable the requested Terminal/Python/bridge '
                                          'entry in System Settings → Privacy & Security → Screen & System Audio Recording, '
                                          'then enable screen vision again. Some permission changes require restarting the app.', quiet=quiet)
            return
        self.vision.set_enabled(True)
        self.access_preferences.save(screen_vision=True)
        self.mascot.vision_button.setText('Screen on')
        self.mascot.vision_button.setAccessibleName('Screen vision is on. Each prompt includes a fresh local screen image. Activate to pause.')
        self.mascot.set_screen_vision_indicator(True)
        if quiet:
            return
        if self.retry_after_vision and self.last_user_request:
            request, mode, from_mascot = self.last_user_request
            self.retry_after_vision = False
            self.input.setPlainText(request)
            self.ask(mode=mode, from_mascot=from_mascot)
        else:
            self.mascot_home('Screen access is on.')

    def screen_permission_failed(self, message, *, quiet=False):
        self.retry_after_vision = False
        self.vision.set_enabled(False)
        self.mascot.vision_button.setText('Screen off')
        self.mascot.set_screen_vision_indicator(False)
        if quiet:
            self.essentials_vision.setToolTip(message)
            self.mascot.vision_button.setToolTip(message)
            return
        self.mascot_home(message)

    def build_desktop_context(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = label('Desktop tools')
        heading.setObjectName('settingsPageTitle')
        layout.addWidget(heading)
        layout.addWidget(label('Manage app and screen access in Settings. These tools are for troubleshooting.'))
        layout.addWidget(button('Manage access', lambda: self.tabs.setCurrentIndex(self.essentials_tab)))
        self.desktop_diagnostics = Disclosure('Show desktop details')
        layout.addWidget(self.desktop_diagnostics)
        layout.addStretch()
        layout = self.desktop_diagnostics.body
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
        self.context_tab = self.tabs.addTab(scroll_page(page), 'Desktop tools')
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
            self.essentials_access.setText('Screen capture only runs for your requests. Pause either option at any time.')
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

    def offer_computer_task(self, goal):
        goal = text(goal, 'computer task', 2000)
        self.stop_computer_task(announce=False)
        self.pending_desktop_action = {'type': 'start_task', 'goal': goal, 'label': 'Start computer task'}
        proposal = self.pending_desktop_action
        self.say('Starting: '+goal, [('Stop task', 'computer:stop')], compact=True)
        def begin():
            if self.pending_desktop_action is proposal:
                self.start_computer_task(automatic=True)
        if self.worker and self.worker.isRunning():
            self.worker.finished.connect(lambda: QTimer.singleShot(0, begin))
        else:
            QTimer.singleShot(0, begin)

    def start_computer_task(self, *, automatic=False):
        if self.worker and self.worker.isRunning():
            return
        proposal = self.pending_desktop_action or {}
        if proposal.get('type') != 'start_task':
            return
        if not self.vision.enabled or not self.desktop_monitor.enabled:
            self.say('Enable app awareness and local screen vision in Settings, then try this task again.',
                     [('Settings', 'settings'), ('Try again', 'computer:start:auto' if automatic else 'computer:start:review'), ('Cancel', 'computer:stop')], compact=True)
            return
        self.computer_task = ComputerTask(proposal['goal'], automatic=automatic)
        self.pending_desktop_action = None
        self.next_computer_step()

    def stop_computer_task(self, *, announce=True):
        if self.computer_task:
            self.computer_task.stop()
        self.pending_desktop_action = None
        self.clear_guidance()
        if announce:
            self.say('Computer task stopped. An already-submitted action may still finish; no further steps will run.', compact=True)

    def next_computer_step(self):
        task = self.computer_task
        if not task or task.cancelled.is_set() or task.pending is not None:
            return
        if self.worker and self.worker.isRunning():
            return
        self.pending_desktop_action = None
        self.clear_guidance()
        self.hide()
        self.say(f'Computer task · step {len(task.receipts)+1} of {task.max_steps}\nObserving the screen…', [('Stop task', 'computer:stop')], compact=True)
        self.set_busy(True)
        area = self.mascot.screen().geometry()
        worker = TaskStepWorker(task, self.desktop_monitor, self.vision, self.service.provider,
                                {'x': area.x(), 'y': area.y()}, self)
        self.worker = worker
        worker.progress.connect(lambda message: self.say(
            f'Computer task · step {len(task.receipts)+1} of {task.max_steps}\n{message}',
            [('Stop task', 'computer:stop')], compact=True)
            if self.computer_task is task and not task.cancelled.is_set() else None)
        worker.result.connect(lambda result: self.receive_computer_step(task, result))
        worker.failed.connect(lambda message: self.failed(message) if self.computer_task is task and not task.cancelled.is_set() else None)
        worker.finished.connect(lambda: self.set_busy(False))
        worker.start()

    def receive_computer_step(self, task, step):
        if self.computer_task is not task or task.cancelled.is_set():
            return
        if step['status'] != 'action':
            task.stop(step['status'])
            prefix = 'The model reports completion from the current screen: ' if step['status'] == 'done' else 'Task paused: '
            self.say(prefix+step['message'], compact=True)
            return
        response = {'message': step['message'], 'sources': [], 'workflow': None, 'target': None,
                    'desktop_action': step['action'], 'visual_capture': step['visual_capture'], 'task_step': True}
        self.received(response)
        if self.pending_desktop_action is None:
            task.stop('blocked')
            return
        if not step['review']:
            proposal = self.pending_desktop_action
            def apply():
                if self.computer_task is task and not task.cancelled.is_set() and self.pending_desktop_action is proposal:
                    self.execute_desktop_action(proposal)
            if self.worker and self.worker.isRunning():
                self.worker.finished.connect(lambda: QTimer.singleShot(0, apply))
            else:
                QTimer.singleShot(0, apply)

    def execute_desktop_action(self, proposal):
        if self.worker and self.worker.isRunning():
            return
        task = self.computer_task if self.computer_task and not self.computer_task.cancelled.is_set() else None
        request = self.last_user_request[0] if self.last_user_request else 'Check the action result.'
        self.pending_desktop_action = None
        self.clear_guidance()
        self.hide()
        if task is not None:
            self.say('Executing: '+proposal.get('label', proposal['type']), [('Stop task', 'computer:stop')], compact=True)
        else:
            self.mascot.collapse_chat()
        self.set_busy(True)
        worker = ComputerActionWorker(self.desktop_monitor, proposal, self, vision=self.vision, provider=self.service.provider)
        self.worker = worker
        result = {}
        def submitted(observation):
            result.update(observation)
            self.service.last_action_result = observation
            self.say('Action submitted: '+proposal.get('label', proposal['type'])+'. Checking the result.',
                     [('Stop task', 'computer:stop')] if task else (), compact=True)
        def finished():
            self.set_busy(False)
            self.mascot.show()
            self.mascot.raise_()
            if task is not None:
                if result:
                    task.record(result)
                if not task.cancelled.is_set() and result:
                    QTimer.singleShot(450, self.next_computer_step)
                return
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
                    self.access_preferences.save(app_awareness=False)
                    self.service.desktop_session.clear()
                    self.service.last_action_result = None
                    self.pending_desktop_action = None
                else:
                    approved = self.access_preferences.approved('app_awareness')
                    if not approved and not consented and not self.confirm_access('Help me find my way around',
                            'Let A11y follow your apps, windows and accessible controls.',
                            ['No screenshots, typing or field contents.',
                             'App and control names are shared with your selected AI when you ask for help.',
                             'Stays enabled across launches until you pause it. Change restoration in Settings.'], 'Enable and remember'):
                        return
                    if not approved:
                        self.access_preferences.approve('app_awareness')
                        self.set_remember_access(True)
                    self.desktop_monitor.enable()
                    self.access_preferences.save(app_awareness=True)
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
                if proposed['type'] == 'start_task':
                    self.offer_computer_task(proposed['goal'])
                    return
                if proposed['type'] == 'capture_once':
                    self.pending_desktop_action = None
                    self.input.setPlainText('Describe this captured screen.')
                    self.capture_screen(from_mascot=True, consented=True)
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
                if proposed['type'] in ('focus_app', 'press_control', 'launch_app', 'quit_app', 'new_window', 'close_window', 'browse_url', 'click_point', 'play_media', 'type_text', 'press_key', 'scroll', 'wait'):
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
        heading = label('AI model')
        heading.setObjectName('settingsPageTitle')
        layout.addWidget(heading)
        layout.addWidget(label('Choose an installed Ollama model. Use a vision model for screen tasks.'))
        config = getattr(self.service.provider, 'config', AIConfig())
        self.connection_summary = label(config.model or 'No model selected')
        layout.addWidget(self.connection_summary)
        self.connection_fields = {}
        self.connection_details = Disclosure('Connection details', expanded=not isinstance(self.service.provider, OllamaProvider))
        details = self.connection_details.body
        self.provider_choice = QComboBox()
        self.provider_choice.addItem('Ollama · local model', 'ollama')
        self.provider_choice.addItem('Compatible cloud/API provider', 'compatible')
        self.provider_choice.setCurrentIndex(0 if isinstance(self.service.provider, OllamaProvider) else 1)
        details.addWidget(self.provider_choice)
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
        details.addLayout(form)
        self.local_models = QComboBox()
        self.local_models.setAccessibleName('Installed local Ollama models')
        self.local_models.addItem(config.model or 'Find installed models…', config.model or None)
        self.local_models.currentIndexChanged.connect(self.select_local_model)
        layout.addWidget(self.local_models)
        self.scan_btn = button('Find installed models', self.scan_ollama)
        layout.addWidget(self.scan_btn)
        def apply_model():
            if not self.connection_details.toggle.isChecked():
                self.select_local_model()
            self.connect_provider()
        self.connect_btn = button('Use model', apply_model)
        layout.addWidget(self.connect_btn)
        self.connection_status = label('Changes apply to this session.')
        layout.addWidget(self.connection_status)
        details.addWidget(label('API keys stay in memory. Applying settings does not test the connection.'))
        layout.addWidget(self.connection_details)
        layout.addStretch()
        self.tabs.addTab(scroll_page(page), 'AI model')

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
            self.mascot.footer.setText('Ollama is offline · start ollama serve, then scan in Settings → Advanced → AI model')

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
        if isinstance(self.service.provider, OllamaProvider) and self.service.provider.config.model:
            import threading
            from .request_plan import INTENT_SYSTEM
            from .service import DESKTOP_INSTRUCTIONS, SYSTEM
            threading.Thread(target=self.service.provider.warm_up, args=([INTENT_SYSTEM, SYSTEM+DESKTOP_INSTRUCTIONS],),
                             daemon=True).start()

    def select_local_model(self, index=None):
        model = self.local_models.currentData()
        if model:
            self.provider_choice.setCurrentIndex(0)
            self.connection_fields['base_url'].setText(OllamaProvider().config.base_url)
            self.connection_fields['model'].setText(model)
            self.connection_fields['key'].clear()

    def connect_provider(self):
        self.stop_computer_task(announce=False)
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

    def record_companion_message(self, message):
        if getattr(self, '_last_companion_message', None) != message:
            self.transcript.appendPlainText('A11y: '+message+'\n')
            self._last_companion_message = message

    def say(self, message, choices=(), **options):
        self.record_companion_message(message)
        self.latest_response = message
        self.read_btn.setEnabled(self.tts is not None)
        self.mascot.present(message, choices, **options)
        self.mascot.set_state('idle')
        self.voice_say(message, choices)

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
        elif self.pending_desktop_action and self.pending_desktop_action['type'] == 'start_task':
            self.offer_computer_task(self.pending_desktop_action['goal'])
            return
        elif self.pending_desktop_action:
            choices.append((self.pending_desktop_action.get('confirmation_label', self.pending_desktop_action['label']), 'desktop:apply'))
        if self.computer_task and not self.computer_task.cancelled.is_set():
            choices.append(('Stop task', 'computer:stop'))
        self.say(message or 'What would you like help with?', choices, placeholder='Ask anything…', compact=True)

    def mascot_submit(self, request, action):
        try:
            if action == 'setup':
                if not self.setup_active:
                    return
                self.introduction.answer(request)
                self.show_setup_question()
                return
            if action == 'computer':
                self.offer_computer_task(request)
                return
            self.input.setPlainText(request)
            self.ask(mode='plan' if action == 'plan' else 'assist', from_mascot=True)
        except (ValueError, PermissionError) as e:
            self.mascot.footer.setText(str(e))

    def mascot_action(self, action):
        if action == 'computer:interrupt':
            if self.computer_task and not self.computer_task.cancelled.is_set():
                self.stop_computer_task(announce=False)
                self.mascot.footer.setText('Task stopped while you type. Send your next request when ready.')
            return
        if action == 'computer:stop':
            self.stop_computer_task()
            return
        if action.startswith('computer:start:'):
            self.start_computer_task(automatic=action.endswith(':auto'))
            return
        if action == 'computer:prompt':
            self.stop_computer_task(announce=False)
            self.say('What should I do on your computer?', placeholder='Describe the whole task…', submit_action='computer', compact=True)
            return
        if action == 'reply':
            self.mascot.show_reply()
            return
        if action == 'vision:toggle':
            self.toggle_screen_vision()
            return
        if action == 'voice:toggle':
            self.toggle_voice()
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
        self.stop_computer_task(announce=False)
        self.quitting = True
        self.desktop_monitor.disable()
        self.vision.set_enabled(False)
        self.context_timer.stop()
        self.stop_speech()
        if self.voice:
            self.voice.stop()
            self.voice.executor.shutdown(wait=False, cancel_futures=True)
        self.overlay.close()
        self.pointer.close()
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
