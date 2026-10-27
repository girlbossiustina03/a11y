import unittest

from companion.request_plan import preserve_desktop_goal, semantic_plan


class PreparedPlanRegressions(unittest.TestCase):
    def test_app_opening_with_work_survives_repeated_preparation(self):
        request = 'In Calculator, show the metric equivalent of a dozen inches, with centimeters as the destination unit.'
        raw = dict(operation='launch_app', app_name='Calculator', target='a dozen inches',
                   referent='companion', remaining_request='convert to centimeters', goal_mode='inspect')
        prepared = preserve_desktop_goal(raw, request)
        self.assertEqual(prepared['operation'], 'computer_task')
        self.assertEqual(prepared['opening']['operation'], 'launch_app')
        self.assertEqual(preserve_desktop_goal(prepared, request), prepared)

    def test_browser_opening_with_work_survives_repeated_preparation(self):
        request = 'Open this reference page and read its heading.'
        raw = dict(operation='browser_open', app_name='Safari', target='https://example.org',
                   referent='companion', remaining_request='read its heading', goal_mode='inspect')
        prepared = preserve_desktop_goal(raw, request)
        self.assertEqual(prepared['operation'], 'computer_task')
        self.assertEqual(preserve_desktop_goal(prepared, request), prepared)

    def test_pointing_still_cannot_become_activation(self):
        request = 'Point to the close button.'
        raw = dict(operation='click_point', app_name='Safari', target='close button',
                   referent='visible_target')
        self.assertEqual(preserve_desktop_goal(raw, request)['operation'], 'highlight')

    def test_self_movement_is_preserved(self):
        raw = dict(operation='highlight', app_name='A11y', target='upper-left', referent='companion')
        self.assertEqual(semantic_plan(raw, 'Tuck yourself into the upper-left corner.')['operation'], 'move_geometry')
