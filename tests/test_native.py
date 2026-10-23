"""Actual Qt widget/controller tests, rendered offscreen; no desktop capture or AI network calls."""
import importlib.util
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtCore import Qt, QPoint
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QPushButton
    from companion.desktop import CompanionWindow
    from companion.models import Identity
    from companion.service import Companion
    from companion.storage import Store
    from test_core import RecordingProvider


@unittest.skipUnless(HAS_QT, 'Install requirements.txt to run native Qt checks')
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = RecordingProvider()
        self.service = Companion(Store(self.temp.name), Identity('company', 'employee'), self.provider)
        self.window = CompanionWindow(self.service)
        self.window.start_companion()
        self.qt.processEvents()
        # Most widget tests exercise a user-opened conversation, not startup.
        self.window.mascot.character.click()
        self.qt.processEvents()

    def tearDown(self):
        if self.window.worker:
            self.window.worker.wait(2000)
        self.window.desktop_monitor.disable()
        self.window.context_timer.stop()
        self.window.mascot.close()
        self.window.overlay.close()
        self.window.pointer.close()
        self.window.quitting = True
        self.window.close()
        self.window.deleteLater()
        self.qt.processEvents()
        self.temp.cleanup()

    def choose(self, action):
        for i in range(self.window.mascot.choice_layout.count()):
            btn = self.window.mascot.choice_layout.itemAt(i).widget()
            if btn.property('companion_action') == action:
                QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
                self.qt.processEvents()
                return
        self.fail('Missing mascot action: '+action)

    def test_mascot_stays_visible_when_mac_app_deactivates(self):
        self.assertTrue(self.window.mascot.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(self.window.mascot.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow))

    def test_context_menu_has_transparent_corners_and_keyboard_actions(self):
        from companion.mascot import RoundedMenu
        menu = RoundedMenu(self.window.mascot)
        menu.addAction('Talk to me')
        menu.addAction('Settings…')
        menu.show()
        self.qt.processEvents()
        image = menu.grab().toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(image.width()-1, image.height()-1).alpha(), 0)
        self.assertEqual(image.pixelColor(15, 15).alpha(), 255)
        menu.setActiveAction(menu.actions()[0])
        QTest.keyClick(menu, Qt.Key.Key_Down)
        self.assertEqual(menu.activeAction(), menu.actions()[1])
        menu.close()

    def test_opening_actions_execute_without_an_extra_confirmation_button(self):
        for kind in ('launch_app', 'browse_url', 'focus_app', 'new_window'):
            action = {'type': kind, 'bundle_id': 'com.apple.Safari', 'label': 'Open Safari'}
            response = {'message': 'Open Safari…', 'sources': [], 'workflow': None,
                        'target': None, 'desktop_action': action}
            with patch.object(self.window, 'execute_desktop_action') as execute:
                self.window.received(response)
                self.qt.processEvents()
                execute.assert_called_once_with(action)
            self.assertIsNone(self.window.pending_desktop_action)

    def test_closing_runs_at_once_but_model_selected_presses_wait(self):
        # The user asked for app open/close/quit without a confirmation step.
        action = {'type': 'close_window', 'window_id': 'test:0', 'label': 'Close window'}
        with patch.object(self.window, 'execute_desktop_action') as execute:
            self.window.received({'message': 'Close window…', 'sources': [], 'workflow': None,
                                  'target': None, 'desktop_action': action})
            self.qt.processEvents()
            execute.assert_called_once_with(action)
        press = {'type': 'press_control', 'control_id': 'control-0', 'label': 'Delete'}
        with patch.object(self.window, 'execute_desktop_action') as execute:
            self.window.received({'message': 'Ready to press Delete. Confirm below.', 'sources': [], 'workflow': None,
                                  'target': None, 'desktop_action': press})
            self.qt.processEvents()
            execute.assert_not_called()
        self.assertEqual(self.window.pending_desktop_action, press)

    def test_visual_click_only_outlines_an_actual_target_rectangle(self):
        area = self.window.mascot.screen().geometry()
        frame = {'screen': {'x': area.x(), 'y': area.y(), 'width': area.width(), 'height': area.height()},
                 'captured_monotonic': time.monotonic()}
        response = {'message': 'Click Battery.', 'sources': [], 'workflow': None, 'target': None,
                    'visual_capture': frame, 'task_step': True,
                    'desktop_action': {'type': 'click_point', 'x': .4, 'y': .5, 'label': 'Battery',
                                       'capture_guard': {'synthetic': True}}}
        with patch.object(self.window.overlay, 'guide') as guide:
            self.window.received(response)
            guide.assert_not_called()
            self.assertTrue(self.window.pointer.isVisible())
            target = {'label': 'Battery', 'x': .3, 'y': .4, 'width': .2, 'height': .2}
            self.window.received(dict(response, target=target))
            guide.assert_called_once_with(area, target)

    def test_remember_access_checkbox_is_explicit_and_pause_is_persisted(self):
        self.assertFalse(self.window.remember_access.isChecked())
        self.window.desktop_monitor.enabled = True
        self.window.vision.set_enabled(True)
        self.window.remember_access.setChecked(True)
        self.assertTrue(self.window.access_preferences.get()['screen_vision'])
        self.window.toggle_screen_vision()
        self.assertFalse(self.window.access_preferences.get()['screen_vision'])
        self.window.desktop_action('context:toggle')
        self.assertFalse(self.window.access_preferences.get()['app_awareness'])
        self.window.remember_access.setChecked(False)
        self.assertFalse(self.window.access_preferences.get()['remember'])

    def test_first_app_enable_remembers_and_pause_reenable_does_not_reprompt(self):
        def enable(**kwargs):
            self.window.desktop_monitor.enabled = True
        with patch.object(self.window, 'confirm_access', return_value=True) as consent, patch.object(self.window.desktop_monitor, 'enable', side_effect=enable):
            self.window.desktop_action('context:toggle')
            self.assertEqual(self.window.access_preferences.get(), {'remember': True, 'app_awareness': True, 'screen_vision': False})
            self.assertTrue(self.window.access_preferences.approved('app_awareness'))
            self.window.desktop_action('context:toggle')
            self.assertFalse(self.window.access_preferences.get()['app_awareness'])
            self.window.desktop_action('context:toggle')
            consent.assert_called_once()

    def test_declining_first_enable_does_not_remember_or_enable_anything(self):
        with patch.object(self.window, 'confirm_access', return_value=False), patch.object(self.window.desktop_monitor, 'enable') as enable:
            self.window.desktop_action('context:toggle')
            enable.assert_not_called()
        self.assertFalse(self.window.access_preferences.get()['remember'])
        self.assertFalse(self.window.access_preferences.approved('app_awareness'))

    def test_previous_consent_respects_explicit_session_only_choice(self):
        self.window.access_preferences.approve('app_awareness')
        self.window.access_preferences.save(remember=False)
        with patch.object(self.window, 'confirm_access') as consent, patch.object(self.window.desktop_monitor, 'enable'):
            self.window.desktop_action('context:toggle')
            consent.assert_not_called()
        self.assertFalse(self.window.access_preferences.get()['remember'])

    def test_startup_restoration_preflights_permissions_without_os_prompt(self):
        self.window.access_preferences.save(remember=True, app_awareness=True, screen_vision=True)
        from companion.ollama import OllamaProvider
        self.window.service.provider = OllamaProvider()
        with patch.object(self.window.desktop_monitor, 'enable') as enable, patch('companion.desktop.VisionPermission') as permission:
            self.window.restore_access()
            enable.assert_called_once_with(request_permission=False)
            self.assertFalse(permission.call_args.kwargs['request_permission'])
            permission.return_value.start.assert_called_once()
        self.window.vision_permission = None

    def test_startup_is_mascot_only_and_restoration_does_not_open_the_prompt(self):
        self.window.start_companion()
        self.qt.processEvents()
        mascot = self.window.mascot
        self.assertTrue(mascot.user_collapsed)
        self.assertFalse(mascot.card.isVisible())
        self.assertFalse(mascot.reply_panel.isVisible())
        self.window.screen_permission_result({'granted': True}, quiet=True)
        self.assertTrue(self.window.vision.enabled)
        self.assertFalse(mascot.card.isVisible())
        self.assertNotIn('Screen vision is on', mascot.bubble.toPlainText())
        mascot.character.click()
        self.qt.processEvents()
        self.assertTrue(mascot.card.isVisible())

    def test_background_permission_result_does_not_replace_an_open_conversation(self):
        self.window.mascot.present('Current task response', compact=True)
        self.window.screen_permission_result({'granted': True}, quiet=True)
        self.assertEqual(self.window.mascot.bubble.toPlainText(), 'Current task response')
        self.window.screen_permission_failed('Permission needs attention', quiet=True)
        self.assertFalse(self.window.vision.enabled)
        self.assertEqual(self.window.mascot.bubble.toPlainText(), 'Current task response')
        self.assertEqual(self.window.essentials_vision.toolTip(), 'Permission needs attention')

    def test_visual_pointer_is_independent_click_through_and_respects_reduced_motion(self):
        from PyQt6.QtGui import QCursor
        pointer = self.window.pointer
        geometry = self.window.mascot.screen().geometry()
        before = QCursor.pos()
        pointer.point_at(geometry, .2, .7, 'Example target', reduced_motion=True)
        self.assertEqual(pointer.pos(), QPoint(geometry.x()+int(.2*geometry.width()), geometry.y()+int(.7*geometry.height())))
        self.assertEqual(QCursor.pos(), before)
        self.assertTrue(pointer.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(pointer.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertEqual(pointer.accessibleDescription(), 'Example target')
        self.assertEqual(pointer.animation.state().name, 'Stopped')
        self.window.clear_guidance()
        self.assertFalse(pointer.isVisible())
        self.assertIsNone(pointer.target_point)

    def test_browser_request_runs_actual_workers_once_without_confirmation_or_false_failure(self):
        from test_request_plan import StagedProvider
        self.window.setup_dialog.reject()
        provider = self.service.provider = StagedProvider('browser_search', 'Safari', 'youtube.com')
        provider.interpret_request.return_value['browser_mode'] = 'window'
        receipt = {'type': 'browse_url', 'requested_url': 'https://youtube.com',
                   'native_result': {'submitted': True, 'tab_placement': 'window',
                                     'browser_observation': {'url': 'https://youtube.com/'}}}
        with patch.object(self.window.desktop_monitor, 'installed_apps', return_value=[{'name': 'Safari', 'bundle_id': 'com.apple.Safari'}]), patch('companion.desktop.ComputerUse.execute_confirmed', return_value=receipt) as execute:
            self.window.input.setPlainText('open a new safari window and search for youtube.com')
            self.window.ask(mode='assist', from_mascot=True)
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
                if 'browser reports' in self.window.mascot.bubble.toPlainText() and not self.window.worker.isRunning():
                    break
            self.qt.processEvents()
        execute.assert_called_once()
        action = execute.call_args.args[0]
        self.assertEqual(action['browser_mode'], 'window')
        self.assertEqual(action['url'], 'https://youtube.com')
        provider.interpret_request.assert_called_once()
        provider.complete_structured.assert_not_called()
        self.assertIsNone(self.window.pending_desktop_action)
        self.assertIn('requested window', self.window.mascot.bubble.toPlainText())
        self.assertTrue(self.window.mascot.isVisible())

    def test_fast_task_reobserves_after_each_action_and_pauses_before_enter(self):
        import base64
        from copy import deepcopy
        from unittest.mock import Mock
        from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
        from PyQt6.QtGui import QImage
        from companion.desktop_context import DesktopContext
        from test_desktop_context import FakeBridge
        from test_computer_task import context
        self.window.setup_dialog.reject()
        bridge = FakeBridge()
        bridge.value = context()
        monitor = self.window.desktop_monitor = self.service.desktop_context = DesktopContext(bridge, clock=lambda: 100)
        monitor.enabled = True
        monitor.collect_once()
        self.window.vision.set_enabled(True)
        area = self.window.mascot.screen().geometry()
        image = QImage(200, 120, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        png = QByteArray()
        buffer = QBuffer(png)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        frame = {'image_data': 'data:image/png;base64,'+base64.b64encode(bytes(png)).decode(),
                 'screen': {'x': area.x(), 'y': area.y(), 'width': area.width(), 'height': area.height()},
                 'display_id': 7, 'captured_monotonic': time.monotonic(), 'windows': [],
                 'text_regions': [{'text': 'Search', 'x': .25, 'y': .35, 'width': .1, 'height': .1}]}
        actions = [{'type': 'click_point', 'x': .3, 'y': .4, 'label': 'Search'},
                   {'type': 'type_text', 'text': 'accessibility'},
                   {'type': 'scroll', 'direction': 'down'},
                   {'type': 'press_key', 'key': 'enter'}]
        outputs = [{'status': 'action', 'message': 'Next step on fresh screen.', 'risk': 'navigation', 'action': action} for action in actions]
        outputs.append({'status': 'done', 'message': 'The requested result is visible.', 'risk': 'navigation', 'action': None})
        class Provider:
            complete_structured = Mock(side_effect=outputs)
        self.service.provider = Provider()
        def submitted(proposal):
            return {'type': proposal['type'], 'label': proposal['label'], 'status': 'submitted'}
        with patch.object(self.window.vision, 'capture', side_effect=lambda *args, **kwargs: deepcopy(frame)) as capture, patch('companion.desktop.ComputerUse.execute_confirmed', side_effect=submitted) as execute:
            self.window.offer_computer_task('Find accessibility help')
            deadline = time.monotonic()+6
            while time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
                if (self.window.pending_desktop_action or {}).get('key') == 'enter' and not self.window.worker.isRunning():
                    break
            self.assertEqual(execute.call_count, 3)
            self.assertEqual(capture.call_count, 4)
            self.assertEqual(self.window.pending_desktop_action['key'], 'enter')
            self.window.desktop_action('desktop:apply')
            deadline = time.monotonic()+4
            while time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
                if self.window.computer_task.status == 'done' and not self.window.worker.isRunning():
                    break
            self.assertEqual(execute.call_count, 4)
            self.assertEqual(capture.call_count, 5)
            self.assertEqual(self.window.computer_task.status, 'done')
            self.assertEqual(len(self.window.computer_task.receipts), 4)
            self.assertIn('model reports completion', self.window.mascot.bubble.toPlainText())
            for call in self.service.provider.complete_structured.call_args_list:
                self.assertIn('Find accessibility help', call.args[1][0]['content'])
                self.assertIsNone(call.kwargs['image_data'])
        self.assertIsNone(self.window.pending_desktop_action)

    def test_stop_cancels_an_automatic_step_queued_for_execution(self):
        from companion.computer_task import ComputerTask
        task = self.window.computer_task = ComputerTask('Find help', automatic=True)
        area = self.window.mascot.screen().geometry()
        step = {'status': 'action', 'message': 'Focus the address bar.', 'review': False,
                'action': {'type': 'press_key', 'key': 'cmd_l', 'label': 'Address bar'},
                'visual_capture': {'screen': {'x': area.x(), 'y': area.y(), 'width': area.width(), 'height': area.height()}, 'captured_monotonic': time.monotonic()}}
        with patch.object(self.window, 'execute_desktop_action') as execute:
            self.window.receive_computer_step(task, step)
            self.window.mascot_action('computer:stop')
            self.qt.processEvents()
            execute.assert_not_called()
        self.assertTrue(task.cancelled.is_set())
        self.assertIsNone(self.window.pending_desktop_action)

    def test_task_refuses_automatic_click_when_capture_display_is_not_connected(self):
        from companion.computer_task import ComputerTask
        task = self.window.computer_task = ComputerTask('Find help', automatic=True)
        action = {'type': 'click_point', 'x': .3, 'y': .4, 'label': 'Help', 'capture_guard': {'synthetic': True}}
        task.pending = action
        step = {'status': 'action', 'message': 'Click Help.', 'review': False, 'action': action,
                'visual_capture': {'screen': {'x': 99999, 'y': 99999, 'width': 100, 'height': 100}, 'captured_monotonic': time.monotonic()}}
        with patch.object(self.window, 'execute_desktop_action') as execute:
            self.window.receive_computer_step(task, step)
            self.qt.processEvents()
            execute.assert_not_called()
        self.assertEqual(task.status, 'blocked')
        self.assertIsNone(self.window.pending_desktop_action)

    def test_task_request_starts_automatically_without_mode_selection(self):
        with patch.object(self.window, 'start_computer_task') as start:
            self.window.offer_computer_task('Check my tasks in Teams')
            choices = [self.window.mascot.choice_layout.itemAt(i).widget().property('companion_action') for i in range(self.window.mascot.choice_layout.count())]
            self.assertEqual(choices, ['computer:stop'])
            self.qt.processEvents()
            start.assert_called_once_with(automatic=True)

    def test_task_autostart_waits_for_request_worker_to_finish(self):
        from PyQt6.QtCore import QObject, pyqtSignal
        class Gate(QObject):
            finished = pyqtSignal()
            running = True
            def isRunning(self):
                return self.running
        gate = Gate()
        self.window.worker = gate
        try:
            with patch.object(self.window, 'start_computer_task') as start:
                self.window.offer_computer_task('Check Teams')
                self.qt.processEvents()
                start.assert_not_called()
                gate.running = False
                gate.finished.emit()
                self.qt.processEvents()
                start.assert_called_once_with(automatic=True)
        finally:
            self.window.worker = None

    def test_stopping_task_before_queued_start_prevents_it_from_starting(self):
        with patch.object(self.window, 'start_computer_task') as start:
            self.window.offer_computer_task('Check Teams')
            self.window.stop_computer_task()
            self.qt.processEvents()
            start.assert_not_called()

    def test_busy_prompt_and_stop_remain_visible_and_interactive(self):
        from companion.computer_task import ComputerTask
        task = self.window.computer_task = ComputerTask('Find help', automatic=True)
        mascot = self.window.mascot
        mascot.present('Observing…', [('Stop task', 'computer:stop')], compact=True)
        self.window.set_busy(True)
        self.qt.processEvents()
        self.assertTrue(mascot.input.isVisible())
        self.assertTrue(mascot.input.isEnabled())
        stop = mascot.choice_layout.itemAt(0).widget()
        self.assertTrue(stop.isEnabled())
        QTest.mouseClick(stop, Qt.MouseButton.LeftButton)
        self.assertTrue(task.cancelled.is_set())
        self.window.set_busy(False)

    def test_typing_interrupts_task_and_draft_survives_progress_updates(self):
        from companion.computer_task import ComputerTask
        task = self.window.computer_task = ComputerTask('Find help', automatic=True)
        mascot = self.window.mascot
        mascot.present('Working…', [('Stop task', 'computer:stop')], compact=True)
        self.window.set_busy(True)
        QTest.keyClicks(mascot.input, 'my next request')
        self.assertTrue(task.cancelled.is_set())
        mascot.present('A later update', placeholder='Ask anything…', compact=True)
        self.assertEqual(mascot.input.text(), 'my next request')
        self.assertFalse(mascot.send.isEnabled())
        self.window.set_busy(False)
        self.assertTrue(mascot.send.isEnabled())

    def test_clicking_pill_padding_focuses_input_without_starting_a_drag(self):
        mascot = self.window.mascot
        mascot.present('Ready', placeholder='Ask anything…', compact=True)
        self.qt.processEvents()
        QTest.mouseClick(mascot.card, Qt.MouseButton.LeftButton, pos=QPoint(3, 3))
        self.qt.processEvents()
        self.assertTrue(mascot.input.hasFocus())
        self.assertIsNone(mascot.drag_position)

    def test_sent_text_is_cleared_but_the_emitted_request_is_preserved(self):
        mascot = self.window.mascot
        mascot.submitted.disconnect()
        requests = []
        mascot.submitted.connect(lambda value, action: requests.append((value, action)))
        mascot.present('Ready', placeholder='Ask anything…', compact=True)
        mascot.input.setText('Open Teams')
        QTest.mouseClick(mascot.send, Qt.MouseButton.LeftButton)
        self.assertEqual(requests, [('Open Teams', 'chat')])
        self.assertEqual(mascot.input.text(), '')

    def test_long_reply_still_scrolls_from_keyboard(self):
        mascot = self.window.mascot
        mascot.present('\n'.join('Step '+str(i) for i in range(100)), compact=True)
        self.qt.processEvents()
        scrollbar = mascot.bubble.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        mascot.bubble.setFocus()
        QTest.keyClick(mascot.bubble, Qt.Key.Key_PageDown)
        self.assertGreater(scrollbar.value(), 0)

    def test_restore_permission_worker_calls_check_instead_of_request(self):
        from companion.desktop import VisionPermission
        from unittest.mock import Mock
        vision = Mock()
        worker = VisionPermission(vision, request_permission=False)
        worker.run()
        vision.check_access.assert_called_once()
        vision.request_access.assert_not_called()

    def test_first_launch_greets_from_mascot_with_panel_hidden(self):
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window.mascot.isVisible())
        self.assertIn('Hey!', self.window.mascot.bubble.toPlainText())
        self.window.mascot_action('setup:restart')
        self.qt.processEvents()
        self.window.mascot.input.setText('Sam')
        QTest.keyClick(self.window.mascot.input, Qt.Key.Key_Return)
        self.qt.processEvents()
        self.assertIn('Nice to meet you, Sam', self.window.mascot.bubble.toPlainText())
        self.assertFalse(self.window.isVisible())

    def test_complete_intro_through_actual_mascot_controls(self):
        self.window.mascot_action('setup:restart')
        self.qt.processEvents()
        for value in ['Sam', 'Engineer']:
            self.window.mascot.input.setText(value)
            QTest.keyClick(self.window.mascot.input, Qt.Key.Key_Return)
            self.qt.processEvents()
        for action in ['setup:choice:"concise"', 'setup:choice:"one_step"',
                       'setup:choice:"keyboard"', 'setup:choice:true', 'setup:choice:false']:
            self.choose(action)
        self.assertIn('Save these settings?', self.window.mascot.bubble.toPlainText())
        self.choose('setup:save')
        self.assertIn('We’re all set, Sam', self.window.mascot.bubble.toPlainText())
        self.assertEqual(self.service.adaptation.effective(self.service.identity)['detail'], 'concise')
        self.assertFalse(self.window.mascot.character.anim_timer.isActive())
        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.provider.calls, [])

    def test_mascot_plan_uses_worker_then_confirms_task_without_opening_panel(self):
        self.window.mascot_action('setup:later')
        self.qt.processEvents()
        self.window.mascot.input.setText('Help me set up my development environment')
        self.window.mascot_action('plan')
        self.qt.processEvents()
        deadline = time.monotonic()+3
        while self.window.worker.isRunning() and time.monotonic() < deadline:
            self.qt.processEvents()
            QTest.qWait(5)
        self.qt.processEvents()
        self.assertEqual(len(self.service.state()['workflows']), 1)
        self.assertTrue(self.window.mascot.compact)
        self.assertFalse(self.window.isVisible())
        self.window.mascot_action('confirm')
        self.qt.processEvents()
        self.assertEqual(self.service.state()['workflows'][0]['current_step'], 1)
        self.assertTrue(self.window.mascot.compact)

    def test_settings_close_leaves_companion_available(self):
        self.window.reveal()
        self.qt.processEvents()
        self.window.close()
        self.qt.processEvents()
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window.mascot.isVisible())
        self.window.mascot.collapse_chat()
        self.qt.processEvents()
        self.assertFalse(self.window.mascot.card.isVisible())
        self.window.mascot.character.click()
        self.qt.processEvents()
        self.assertTrue(self.window.mascot.card.isVisible())

    def test_idle_is_character_only_and_keeps_character_position(self):
        mascot = self.window.mascot
        anchor = mascot.character.mapToGlobal(QPoint())
        mascot.collapse_chat()
        self.qt.processEvents()
        self.assertFalse(mascot.card.isVisible())
        self.assertEqual(mascot.width(), mascot.character.width()+16)
        self.assertLessEqual(mascot.height(), mascot.character.height()+20)
        self.assertEqual(mascot.character.mapToGlobal(QPoint()), anchor)
        self.assertFalse(any(b.isVisible() for b in mascot.findChildren(QPushButton)))
        mascot.character.click()
        self.qt.processEvents()
        self.assertTrue(mascot.card.isVisible())
        self.assertEqual(mascot.character.mapToGlobal(QPoint()), anchor)

    def test_reply_does_not_reopen_collapsed_conversation(self):
        mascot = self.window.mascot
        mascot.collapse_chat()
        mascot.present('A response arrived while you were working.', [('Continue', 'talk')], placeholder='Reply')
        self.qt.processEvents()
        self.assertFalse(mascot.card.isVisible())
        self.assertEqual(mascot.width(), mascot.character.width()+16)
        mascot.character.click()
        self.qt.processEvents()
        self.assertIn('A response arrived', mascot.bubble.toPlainText())
        self.assertTrue(mascot.card.isVisible())

    def test_settings_use_sidebar_and_do_not_compete_with_chat_bubble(self):
        self.window.reveal()
        self.qt.processEvents()
        self.assertFalse(self.window.tabs.tabBar().isVisible())
        self.assertEqual(self.window.panel_navigation.count(), self.window.tabs.count())
        self.assertFalse(self.window.mascot.card.isVisible())
        self.window.panel_navigation.setCurrentRow(self.window.navigation_pages.index(2))
        self.assertEqual(self.window.tabs.currentIndex(), 2)
        self.window.tabs.setCurrentIndex(4)
        self.assertEqual(self.window.panel_navigation.currentRow(), self.window.navigation_pages.index(4))
        self.window.hide()
        self.window.mascot_action('talk')
        self.qt.processEvents()
        self.assertTrue(self.window.mascot.card.isVisible())
        self.assertFalse(self.window.isVisible())

    def test_multiline_composer_enter_submits_shift_enter_adds_line(self):
        self.window.mascot_action('setup:later')
        self.qt.processEvents()
        composer = self.window.mascot.input
        composer.setText('First line')
        QTest.keyClick(composer, Qt.Key.Key_End)
        QTest.keyClick(composer, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClicks(composer, 'Second line')
        self.assertIn('\nSecond line', composer.text())
        self.assertIsNone(self.window.worker)
        self.assertFalse(self.window.mascot.context_button.isVisible())
        self.assertFalse(self.window.mascot.vision_button.isVisible())
        self.assertTrue(self.window.mascot.prompt_settings.isVisible())

    def test_prompt_is_compact_and_menu_controls_are_not_in_normal_chat(self):
        mascot = self.window.mascot
        self.assertTrue(mascot.compact)
        self.assertEqual(mascot.width(), 240)
        self.assertFalse(mascot.choice_area.isVisible())
        self.assertFalse(mascot.stage.isVisible())
        self.assertFalse(mascot.settings_button.isVisible())
        self.assertFalse(mascot.vision_button.isVisible())
        self.assertTrue(mascot.prompt_settings.isVisible())

    def test_enabled_vision_sends_fresh_pixels_from_worker(self):
        from companion.ollama import OllamaProvider
        from companion.provider import AIConfig
        provider = OllamaProvider(AIConfig(base_url='http://127.0.0.1:11434', model='local-vision'))
        self.service.provider = provider
        self.window.vision.set_enabled(True)
        frame = {'image_data': 'data:image/png;base64,ACTUAL_FRAME_TEST',
                 'screen': {'x': 0, 'y': 0, 'width': 800, 'height': 800},
                 'windows': [{'app': 'Xcode', 'title': 'Project'}], 'captured_monotonic': time.monotonic()}
        with patch.object(self.window.vision, 'capture', return_value=frame), patch.object(provider, 'interpret_request', return_value={'operation': 'inspect_screen', 'app_name': '', 'target': ''}), patch.object(provider, 'complete_structured', side_effect=lambda system, messages, schema, image_data=None: self.provider.complete(system, messages, image_data=image_data)):
            self.window.mascot_submit('What is on my screen?', 'chat')
            deadline = time.monotonic()+3
            while self.window.worker.isRunning() and time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
            self.qt.processEvents()
        self.assertEqual(self.provider.calls[-1][2], 'data:image/png;base64,ACTUAL_FRAME_TEST')
        self.assertEqual(self.provider.contexts[-1]['mode'], 'assist')
        self.assertTrue(self.window.mascot.compact)
        self.assertIsNotNone(self.window.pending_target)

    def test_capture_failure_does_not_ask_model_to_guess(self):
        self.window.vision.set_enabled(True)
        with patch.object(self.window.vision, 'capture', side_effect=RuntimeError('Screen recording permission denied')):
            self.window.mascot_submit('What is on screen?', 'chat')
            deadline = time.monotonic()+3
            while self.window.worker.isRunning() and time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
            self.qt.processEvents()
        self.assertEqual(self.provider.calls, [])
        self.assertIn('permission denied', self.window.mascot.bubble.toPlainText())

    def test_confirmed_move_action_repositions_only_the_companion(self):
        self.service.adaptation.set_explicit(self.service.identity, {'reduced_motion': True}, True)
        self.window.pending_desktop_action = {'type': 'move_companion', 'destination': 'left_edge', 'label': 'Move left'}
        self.window.desktop_action('desktop:apply')
        self.qt.processEvents()
        area = self.window.mascot.screen().availableGeometry()
        self.assertEqual(self.window.mascot.x(), area.left()+16)
        self.assertFalse(self.window.mascot.card.isVisible())
        self.assertFalse(self.window.isVisible())

    def test_character_opens_small_pill_and_two_right_circles(self):
        mascot = self.window.mascot
        self.assertFalse(mascot.reply_panel.isVisible())
        self.assertFalse(mascot.header_widget.isVisible())
        self.assertEqual(mascot.card.height(), 34)
        self.assertEqual(mascot.send.width(), 32)
        input_top = mascot.input.mapTo(mascot.card, QPoint()).y()
        self.assertAlmostEqual(input_top+mascot.input.height()/2, mascot.card.height()/2, delta=1)
        self.assertLessEqual(mascot.input.height()-mascot.input.fontMetrics().height(), 2)
        self.assertGreaterEqual(mascot.input.viewport().height(), mascot.input.fontMetrics().height())
        self.assertEqual(mascot.send.width(), mascot.send.height())
        self.assertEqual(mascot.prompt_settings.width(), mascot.prompt_settings.height())
        self.assertLess(mascot.send.x(), mascot.prompt_settings.x())
        def bounds(widget):
            return widget.mapTo(mascot, QPoint()), widget.size()
        send_pos, send_size = bounds(mascot.send)
        settings_pos, settings_size = bounds(mascot.prompt_settings)
        card_pos, _ = bounds(mascot.card)
        character_pos, character_size = bounds(mascot.character)
        self.assertLess(card_pos.x()+mascot.card.width(), send_pos.x())
        self.assertLessEqual(mascot.width()-mascot.character.width(), 90)
        self.assertEqual(mascot.send.parentWidget(), mascot.controls_row)
        self.assertEqual(mascot.prompt_settings.parentWidget(), mascot.controls_row)
        self.assertLess(character_pos.y()+character_size.height(), card_pos.y())
        self.assertAlmostEqual(character_pos.x()+character_size.width()/2, mascot.width()/2, delta=1)
        self.assertAlmostEqual(send_pos.y()+send_size.height()/2, card_pos.y()+mascot.card.height()/2, delta=1)
        self.assertEqual(len([b for b in mascot.findChildren(QPushButton) if b.isVisible()]), 2)
        self.window.mascot_home('Here is an answer.')
        self.qt.processEvents()
        self.assertTrue(mascot.reply_panel.isVisible())
        self.assertLess(mascot.reply_panel.geometry().bottom(), mascot.character_row.geometry().top())
        mascot.collapse_chat()
        mascot.character.click()
        self.qt.processEvents()
        self.assertTrue(mascot.card.isVisible())
        self.assertFalse(mascot.reply_panel.isVisible())

    def test_unconfigured_ai_error_is_shown_inside_mascot(self):
        from companion.provider import AIConfig, ChatProvider
        self.service.provider = ChatProvider(AIConfig())
        self.window.mascot_action('setup:later')
        self.qt.processEvents()
        self.window.mascot.input.setText('Hello')
        QTest.keyClick(self.window.mascot.input, Qt.Key.Key_Return)
        deadline = time.monotonic()+3
        while self.window.worker.isRunning() and time.monotonic() < deadline:
            self.qt.processEvents()
            QTest.qWait(5)
        self.qt.processEvents()
        self.assertIn('AI is not configured', self.window.mascot.bubble.toPlainText())
        self.assertFalse(self.window.mascot.busy)
        self.assertFalse(self.window.isVisible())


    def test_guided_setup_saves_details_and_finishes_without_enabling_permissions(self):
        wizard = self.window.setup_dialog
        self.assertTrue(wizard.isVisible())
        wizard.advance()
        wizard.fields['display_name'].setText('Sam')
        wizard.fields['work_role'].setText('Engineer')
        wizard.advance()
        self.assertEqual(self.window.introduction.user_details(), {})
        wizard.fields['detail'].setCurrentIndex(wizard.fields['detail'].findData('concise'))
        wizard.advance()
        self.assertEqual(self.window.introduction.user_details()['display_name'], 'Sam')
        self.assertEqual(self.service.adaptation.effective(self.service.identity)['detail'], 'concise')
        wizard.advance()
        wizard.advance()
        self.assertFalse(wizard.isVisible())
        self.assertTrue(self.window.introduction.get()['access_setup_reviewed'])
        self.assertFalse(self.window.desktop_monitor.enabled)
        self.assertFalse(self.window.vision.enabled)
        self.assertEqual(self.provider.calls, [])

    def test_setup_permission_buttons_use_real_consent_paths(self):
        wizard = self.window.setup_dialog
        with patch.object(self.window, 'desktop_action') as context:
            wizard.context_button.click()
            context.assert_called_once_with('context:toggle', consented=True)
        with patch.object(self.window, 'toggle_screen_vision') as vision:
            wizard.vision_button.click()
            vision.assert_called_once_with(consented=True)
        self.assertFalse(self.window.vision.enabled)

    def test_settings_default_to_essentials_with_advanced_pages_hidden(self):
        self.assertEqual(self.window.tabs.currentIndex(), self.window.essentials_tab)
        self.assertEqual(self.window.panel_navigation.item(0).text(), 'Settings')
        for index in self.window.advanced_pages:
            self.assertTrue(self.window.panel_navigation.item(self.window.navigation_pages.index(index)).isHidden())
        self.window.advanced_navigation.setChecked(True)
        for index in self.window.advanced_pages:
            self.assertFalse(self.window.panel_navigation.item(self.window.navigation_pages.index(index)).isHidden())

    def test_settings_resize_without_a_bottom_status_strip(self):
        from PyQt6.QtWidgets import QScrollArea
        self.window.reveal()
        self.window.resize(620, 460)
        self.qt.processEvents()
        self.assertEqual((self.window.width(), self.window.height()), (620, 460))
        self.assertFalse(self.window.statusBar().isVisible())
        self.window.statusBar().showMessage('Saved')
        self.assertFalse(self.window.statusBar().isVisible())
        for index in range(self.window.tabs.count()):
            self.assertIsInstance(self.window.tabs.widget(index), QScrollArea)

    def test_companion_text_is_identical_in_history_and_cloud_without_duplicates(self):
        self.window.say('Reading Teams activity.', compact=True)
        self.window.say('Reading Teams activity.', compact=True)
        self.assertEqual(self.window.mascot.bubble.toPlainText(), 'Reading Teams activity.')
        self.assertEqual(self.window.transcript.toPlainText().count('A11y: Reading Teams activity.'), 1)
        self.window.failed('Could not read the page.')
        message = self.window.mascot.bubble.toPlainText()
        self.assertIn('A11y: '+message, self.window.transcript.toPlainText())
        self.assertNotIn('progress is saved', message)

    def test_own_desktop_tools_highlight_uses_visible_qt_bounds_without_minimizing(self):
        with patch.object(self.window.overlay, 'guide') as guide:
            self.window.show_companion_control(str(self.window.context_tab))
            self.qt.processEvents()
            self.assertTrue(self.window.isVisible())
            self.assertTrue(self.window.advanced_navigation.isChecked())
            guide.assert_called_once()
            self.assertEqual(guide.call_args.args[1]['label'], 'Desktop tools')
            self.assertIn('Highlighted Desktop tools', self.window.mascot.bubble.toPlainText())

    def test_own_setting_request_runs_worker_and_highlights_without_screen_capture(self):
        from test_request_plan import StagedProvider
        provider = self.service.provider = StagedProvider('highlight', 'A11y', 'Desktop tools')
        provider.complete_structured.return_value = {'control_id': str(self.window.context_tab)}
        self.window.input.setPlainText('mark me where Desktop tools are in A11y')
        with patch.object(self.window.vision, 'capture') as capture, patch.object(self.window.overlay, 'guide') as guide:
            self.window.ask(from_mascot=True)
            deadline = time.monotonic()+3
            while time.monotonic() < deadline and not guide.called:
                self.qt.processEvents()
                QTest.qWait(5)
            capture.assert_not_called()
            guide.assert_called_once()
            self.assertEqual(guide.call_args.args[1]['label'], 'Desktop tools')
            self.assertTrue(self.window.isVisible())

    def test_desktop_diagnostics_are_collapsed_and_keyboard_accessible(self):
        self.window.reveal()
        self.window.tabs.setCurrentIndex(self.window.context_tab)
        self.assertTrue(self.window.desktop_diagnostics.content.isHidden())
        toggle = self.window.desktop_diagnostics.toggle
        toggle.setFocus()
        QTest.keyClick(toggle, Qt.Key.Key_Space)
        self.assertFalse(self.window.desktop_diagnostics.content.isHidden())
        self.assertEqual(toggle.accessibleDescription(), 'Expanded')
        self.assertTrue(self.window.history_tools.content.isHidden())
        self.assertTrue(self.window.document_tools.content.isHidden())

    def test_model_picker_applies_without_opening_technical_fields(self):
        self.window.connection_details.toggle.setChecked(False)
        self.window.local_models.addItem('local-test-model', 'local-test-model')
        self.window.local_models.setCurrentIndex(self.window.local_models.count()-1)
        self.window.connect_btn.click()
        self.assertEqual(self.service.provider.config.model, 'local-test-model')
        self.assertTrue(self.window.connection_details.content.isHidden())
        self.assertEqual(self.window.connection_summary.text(), 'local-test-model')


    def test_setup_access_action_has_no_duplicate_confirmation(self):
        wizard = self.window.setup_dialog
        with patch.object(self.window, 'confirm_access') as confirm, patch.object(self.window.desktop_monitor, 'enable') as enable:
            wizard.context_button.click()
            enable.assert_called_once()
            confirm.assert_not_called()

    def test_settings_access_can_be_declined_without_enabling(self):
        with patch.object(self.window, 'confirm_access', return_value=False) as confirm, patch.object(self.window.desktop_monitor, 'enable') as enable:
            self.window.desktop_action('context:toggle')
            confirm.assert_called_once()
            enable.assert_not_called()


    def test_left_then_right_requests_move_without_reusing_old_target(self):
        self.service.adaptation.set_explicit(self.service.identity, {'reduced_motion': True}, False)
        self.service.desktop_session.append({'role': 'assistant',
            'content': 'The left Terminal close button is red.', 'source_documents': []})
        for request, destination in [('move to the left of the screen', 'left_edge'),
                                     ('move to the right of the screen', 'right_edge')]:
            self.provider.invalid = {'message': 'I’ll move to that edge.', 'source_ids': [],
                'workflow': None, 'target': None,
                'desktop_action': {'type': 'move_companion', 'destination': destination}}
            self.window.mascot_submit(request, 'chat')
            deadline = time.monotonic()+3
            while self.window.worker.isRunning() and time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
            self.qt.processEvents()
            area = self.window.mascot.screen().availableGeometry()
            expected = area.left()+16 if destination == 'left_edge' else area.right()-self.window.mascot.width()-16
            self.assertEqual(self.window.mascot.x(), expected)
            self.assertIsNone(self.window.pending_target)
            self.assertIsNone(self.window.pending_desktop_action)
            self.assertEqual(self.provider.calls[-1][1][-1]['content'], request)
            self.assertEqual(self.provider.contexts[-1]['request'], request)


    def test_upper_left_changes_both_axes_and_precise_point_centers_character(self):
        self.service.adaptation.set_explicit(self.service.identity, {'reduced_motion': True}, False)
        mascot = self.window.mascot
        self.window.move_companion('bottom_right')
        self.window.move_companion('top_left')
        area = mascot.screen().availableGeometry()
        self.assertEqual(mascot.pos(), QPoint(area.left()+16, area.top()+16))
        self.window.move_companion_to(.5, .5, mascot.screen())
        full = mascot.screen().geometry()
        self.assertAlmostEqual(mascot.x()+mascot.width()/2, full.center().x(), delta=1)
        self.assertAlmostEqual(mascot.y()+mascot.height()/2, full.center().y(), delta=1)

    def test_visual_point_response_uses_its_capture_and_rejects_expired_capture(self):
        self.service.adaptation.set_explicit(self.service.identity, {'reduced_motion': True}, False)
        screen = self.window.mascot.screen()
        area = screen.geometry()
        response = {'message': 'Moving toward the drawing.', 'sources': [], 'workflow': None,
            'target': None, 'desktop_action': {'type': 'move_to_point', 'basis': 'image',
                'x': .5, 'y': .5, 'label': 'Apple drawing'},
            'visual_capture': {'screen': {'x': area.x(), 'y': area.y(), 'width': area.width(), 'height': area.height()},
                               'captured_monotonic': time.monotonic()}}
        self.window.received(response)
        mascot = self.window.mascot
        self.assertAlmostEqual(mascot.x()+mascot.width()/2, area.center().x(), delta=1)
        old = mascot.pos()
        response['desktop_action']['x'] = .1
        response['visual_capture']['captured_monotonic'] -= 100
        self.window.received(response)
        self.assertIn('expired', mascot.bubble.toPlainText())
        self.assertEqual(mascot.pos(), old)


    def test_confirmed_app_action_runs_worker_then_verifies_without_another_action(self):
        self.window.setup_dialog.reject()
        self.window.last_user_request = ('Press New Folder', 'assist', True)
        result = {'type': 'press_control', 'label': 'New Folder', 'status': 'submitted', 'task_completed': False}
        self.provider.invalid = {'request_kind': 'answer', 'message': 'The app changed; please check the folder.',
            'source_ids': [], 'workflow': None, 'target': None, 'desktop_action': None}
        with patch('companion.desktop.ComputerUse.execute_confirmed', return_value=result) as execute:
            self.window.pending_desktop_action = {'type': 'press_control', 'control_id': 'control-0', 'label': 'New Folder'}
            self.window.desktop_action('desktop:apply')
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
                if self.provider.calls and not self.window.worker.isRunning():
                    break
            self.qt.processEvents()
        execute.assert_called_once()
        self.assertEqual(self.provider.contexts[-1]['mode'], 'verify')
        self.assertEqual(self.provider.contexts[-1]['last_action_result']['status'], 'submitted')
        self.assertIn('app changed', self.window.mascot.bubble.toPlainText())
        self.assertTrue(self.window.mascot.reply_panel.isVisible())
        self.assertIsNone(self.window.pending_desktop_action)


    def test_post_action_verification_can_use_metadata_when_screen_capture_fails(self):
        self.window.vision.set_enabled(True)
        self.service.last_action_result = {'type': 'focus_app', 'status': 'submitted', 'task_completed': False}
        self.provider.invalid = {'request_kind': 'answer', 'message': 'I can inspect app metadata, but screen capture is unavailable.',
            'source_ids': [], 'workflow': None, 'target': None, 'desktop_action': None}
        with patch.object(self.window.vision, 'capture', side_effect=RuntimeError('Companion exclusion unavailable')):
            self.window.input.setPlainText('Open Terminal')
            self.window.ask(mode='verify', from_mascot=True)
            deadline = time.monotonic()+3
            while self.window.worker.isRunning() and time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
            self.qt.processEvents()
        self.assertIsNone(self.provider.calls[-1][2])
        self.assertEqual(self.provider.contexts[-1]['visual_context']['status'], 'unavailable')
        self.assertFalse(self.provider.contexts[-1]['evidence']['fresh_image'])
        self.assertIsNone(self.window.pending_desktop_action)
