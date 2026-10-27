import unittest
from unittest.mock import Mock

from companion.computer_task import ComputerTask
from companion.models import ValidationError
from companion.vision import ScreenVision


class ExactNativeHit(unittest.TestCase):
    def test_shared_prefix_is_not_the_requested_file(self):
        for wanted, actual in [('Report', 'Report backup.txt'), ('A-B.txt', 'A B.txt'),
                               ('Report.txt', 'Report.txt backup'), ('New', 'New Folder')]:
            with self.subTest(wanted=wanted, actual=actual):
                self.assertTrue(ScreenVision.named_hit_conflict({'label': wanted},
                                                              {'finder_item': True, 'title': actual}))

    def test_unicode_normalization_preserves_an_exact_observed_name(self):
        self.assertFalse(ScreenVision.named_hit_conflict({'label': 'Café.txt'},
                                                       {'finder_item': True, 'title': 'Cafe\u0301.txt'}))

    def test_planning_guard_also_rejects_prefix_collisions(self):
        task = ComputerTask('Open Report', goal_mode='inspect')
        desktop = Mock(bridge=Mock(hit=Mock(return_value={'finder_item': True, 'title': 'Report backup.txt'})))
        step = dict(status='action', action=dict(type='click_point', x=.5, y=.5, label='Report'))
        with self.assertRaisesRegex(ValidationError, 'different Finder item'):
            task.app_click(step, desktop, {}, dict(screen=dict(x=0, y=0, width=1000, height=800)))
