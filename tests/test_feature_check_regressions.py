from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import live_features as features
import live_harder as harder
import live_broad as broad


class FeatureCheckRegressions(unittest.TestCase):
    def test_empty_native_text_uses_cropped_ocr_only_in_expected_app(self):
        case = next(c for c in broad.build(Mock()) if c['name'] == 'maps_place')
        check = case['turns'][0].checks[0][1]
        with patch.object(broad, 'ax_values', return_value=''), patch.object(broad.le, 'window_title', return_value=''), \
             patch.object(broad.le, 'front_app', return_value='Maps'), \
             patch.object(broad.le, 'screen_lines', return_value=['Eiffel Tower']) as ocr:
            self.assertTrue(check({}, []))
            ocr.assert_called_once_with(window_only=True)
        with patch.object(broad, 'ax_values', return_value=''), patch.object(broad.le, 'window_title', return_value=''), \
             patch.object(broad.le, 'front_app', return_value='Finder'), patch.object(broad.time, 'monotonic', side_effect=[0, 4]), \
             patch.object(broad.le, 'screen_lines') as ocr:
            self.assertFalse(check({}, []))
            ocr.assert_not_called()

    def test_right_click_uses_validated_physical_stimulus_not_axpress(self):
        runner = Mock()
        runner.call.return_value = {'ui': {'pid': 1, 'face': [100, 100]}}
        with patch.object(features, 'osa') as osa, patch.object(features.time, 'sleep'), patch('eval_mouse.right_click') as click:
            features.face_click(runner, right=True)
        click.assert_called_once_with(1,100,100)
        osa.assert_not_called()

    def test_reply_buttons_setup_opens_chat_before_request(self):
        cases = features.build(Mock())
        case = next(c for c in cases if c['name'] == 'companion_reply_buttons')
        runner = Mock()
        with patch.object(features, 'face_click') as click:
            case['setup'](runner)
        click.assert_called_once_with(runner)

    def test_reply_title_padding_survives_the_native_probe_strip(self):
        case = next(c for c in features.build(Mock()) if c['name'] == 'companion_reply_buttons')
        runner = Mock()
        with patch.object(features,'face_click'):
            case['setup'](runner)
        before = dict(pid=42,reply_visible=True)
        after = dict(pid=42,reply_visible=False)
        title = '\u2003\u2003💬 reply'
        with patch.object(features,'ui',side_effect=[before,after]), \
             patch.object(features,'osa',return_value='TITLE:'+title), \
             patch.object(features,'button',side_effect=['false',None]) as button, \
             patch.object(features.time,'sleep'):
            self.assertTrue(case['turns'][0].checks[0][1]({},[]))
        self.assertEqual(button.call_args_list[0].args[1],title)
        self.assertEqual(button.call_args_list[1].args[1],title)

    def test_button_lookup_tolerates_native_title_padding(self):
        with patch.object(features,'ui',return_value={'pid':42}), patch.object(features,'osa') as osa:
            features.button(Mock(),'\u2003💬 reply','AXZoomButton',False)
        self.assertIn('first window whose name ends with',osa.call_args.args[0])
        self.assertEqual(osa.call_args.args[2],'💬 reply')

    def test_finder_sort_accepts_native_name_column_but_rejects_other_sort(self):
        case = next(c for c in harder.build(Mock()) if c['name'] == 'finder_sort')
        task = case['turns'][0]
        try:
            with patch.object(harder, 'osa', return_value='1') as osa, patch.object(harder.le, 'activate'):
                case['setup'](Mock())
            folder = osa.call_args_list[0].args[1]
            for column, expected in [('name column', True), ('name', True), ('modification date column', False)]:
                with self.subTest(column=column), patch.object(harder, 'osa', side_effect=[folder, 'list view', column]):
                    self.assertEqual(task.checks[0][1]({}, []), expected)
            with patch.object(harder, 'osa', side_effect=[str(Path(folder)/'Recipes'), 'list view', 'name column']):
                self.assertFalse(task.checks[0][1]({}, []))
        finally:
            for cleanup in case['cleanup']:
                with patch.object(harder, 'osa'):
                    cleanup()
