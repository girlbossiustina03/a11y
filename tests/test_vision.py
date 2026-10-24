import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
import unittest
from unittest.mock import patch
from companion.vision import ScreenVision
from companion.ollama import OllamaProvider
from companion.provider import AIConfig, ChatProvider
from companion.models import validate_response, ValidationError
from test_core import CompanionFixture


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.vision = ScreenVision('/private/tmp/a11y-vision-unit')
        self.vision.set_enabled(True)
        self.provider = OllamaProvider(AIConfig(base_url='http://127.0.0.1:11434', model='local-vision'))
        self.provider.metadata['local-vision'] = {'capabilities': ['completion', 'vision']}

    def test_capture_is_local_and_passes_display_selection(self):
        with patch.object(self.vision, 'call', return_value={'image_data': 'data:image/png;base64,FRAME',
             'screen': {'x': 1440, 'y': 0, 'width': 1440, 'height': 900}}) as call:
            frame = self.vision.capture(self.provider, x=1440, y=0)
            self.assertEqual(frame['image_data'], 'data:image/png;base64,FRAME')
            self.assertIn('captured_monotonic', frame)
            call.assert_called_once_with('--x', '1440', '--y', '0')

    def test_fast_text_requests_native_ocr_on_the_same_transient_frame(self):
        with patch.object(self.vision, 'call', return_value={'image_data': 'data:image/png;base64,FRAME', 'text_regions': []}) as call:
            self.vision.capture(self.provider, fast_text=True)
        call.assert_called_once_with('--x', '0', '--y', '0', '--ocr')

    def test_paused_remote_and_text_only_modes_do_not_capture(self):
        with patch.object(self.vision, 'call') as call:
            with self.assertRaises(RuntimeError):
                self.vision.capture(ChatProvider(AIConfig(model='remote')))
            self.provider.metadata['local-vision'] = {'capabilities': ['completion']}
            with self.assertRaises(RuntimeError):
                self.vision.capture(self.provider)
            self.vision.set_enabled(False)
            with self.assertRaises(RuntimeError):
                self.vision.capture(self.provider)
            call.assert_not_called()

    def test_protected_app_and_secure_input_block_capture(self):
        for desktop in [{'status': 'private_app'}, {'focused_role': 'secure_input'}]:
            with patch.object(self.vision, 'call') as call:
                with self.assertRaises(RuntimeError):
                    self.vision.capture(self.provider, desktop=desktop)
                call.assert_not_called()

    def test_pause_while_capture_in_flight_discards_the_frame(self):
        def paused(*args):
            self.vision.set_enabled(False)
            return {'image_data': 'data:image/png;base64,FRAME'}
        with patch.object(self.vision, 'call', side_effect=paused):
            with self.assertRaisesRegex(RuntimeError, 'discarded'):
                self.vision.capture(self.provider)

    def test_missing_image_is_an_error_not_an_empty_desktop(self):
        with patch.object(self.vision, 'call', return_value={'screen': {}}):
            with self.assertRaisesRegex(RuntimeError, 'cannot infer'):
                self.vision.capture(self.provider)

    def test_perception_and_own_movement_tools_are_bounded(self):
        base = {'message': 'I need a fresh view', 'source_ids': [], 'workflow': None, 'target': None}
        native = object()
        response = validate_response(dict(base, desktop_action={'type': 'request_screen'}), set(), desktop=native)
        self.assertEqual(response['desktop_action']['type'], 'request_screen')
        response = validate_response(dict(base, desktop_action={'type': 'move_companion', 'destination': 'left_edge'}), set(), desktop=native)
        self.assertEqual(response['desktop_action']['destination'], 'left_edge')
        with self.assertRaises(ValidationError):
            validate_response(dict(base, desktop_action={'type': 'move_companion', 'destination': 'arbitrary shell'}), set(), desktop=native)
        with self.assertRaises(ValidationError):
            validate_response(dict(base, desktop_action={'type': 'request_screen'}), set())


class VisualServiceTests(CompanionFixture, unittest.TestCase):
    def test_actual_image_and_visual_metadata_reach_model_and_stay_ephemeral(self):
        self.app.ask('What is on screen?', mode='assist', image_data='data:image/png;base64,FRESH_FRAME',
                     visual_context={'windows': [{'app': 'Xcode', 'title': 'My project'}], 'companion_excluded': True})
        self.assertEqual(self.provider.calls[-1][2], 'data:image/png;base64,FRESH_FRAME')
        context = self.provider.contexts[-1]
        self.assertTrue(context['evidence']['fresh_image'])
        self.assertEqual(context['visual_context']['windows'][0]['app'], 'Xcode')
        self.assertEqual(self.store.history(self.employee), [])
        self.app.ask('What should I do next?', mode='assist', image_data='data:image/png;base64,NEXT_FRAME')
        self.assertTrue(any(m['content'] == 'What is on screen?' for m in self.provider.calls[-1][1]))

    def test_absent_window_is_explicitly_unknown_and_never_empty_evidence(self):
        self.app.ask('What is on my desktop?')
        evidence = self.provider.contexts[-1]['evidence']
        self.assertFalse(evidence['window_metadata_present'])
        self.assertEqual(evidence['missing_window_metadata_means'], 'unknown, not an empty desktop')


class ModelImageTests(unittest.TestCase):
    def frame(self, width, height):
        import base64
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PyQt6.QtGui import QImage
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        return 'data:image/png;base64,'+base64.b64encode(bytes(data)).decode()

    def test_model_copy_is_narrower_and_keeps_aspect_ratio(self):
        import base64
        import importlib.util
        if importlib.util.find_spec('PyQt6') is None:
            self.skipTest('PyQt6 missing')
        from PyQt6.QtGui import QImage
        from companion.vision import ScreenVision
        scaled = ScreenVision.model_image(self.frame(1440, 900))
        image = QImage.fromData(base64.b64decode(scaled.split(',', 1)[1]))
        self.assertEqual((image.width(), image.height()), (1280, 800))
        small = self.frame(1200, 750)
        self.assertEqual(ScreenVision.model_image(small), small)
        with patch.dict('os.environ', {'A11Y_MODEL_IMAGE_WIDTH': '1440'}):
            original = self.frame(1440, 900)
            self.assertEqual(ScreenVision.model_image(original), original)
