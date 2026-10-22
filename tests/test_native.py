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
        self.window.panel_navigation.setCurrentRow(2)
        self.assertEqual(self.window.tabs.currentIndex(), 2)
        self.window.tabs.setCurrentIndex(4)
        self.assertEqual(self.window.panel_navigation.currentRow(), 4)
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
        with patch.object(self.window.vision, 'capture', return_value=frame), patch.object(provider, 'complete', side_effect=self.provider.complete):
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
