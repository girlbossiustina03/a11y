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

    def tearDown(self):
        if self.window.worker:
            self.window.worker.wait(2000)
        self.window.desktop_monitor.disable()
        self.window.context_timer.stop()
        self.window.mascot.close()
        self.window.overlay.close()
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
