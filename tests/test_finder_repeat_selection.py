import unittest
from unittest.mock import Mock
from companion.computer_task import ComputerTask
from companion.models import ValidationError


class FinderRepeatSelection(unittest.TestCase):
    def setUp(self):
        self.task = ComputerTask('Navigate in the current folder', goal_mode='inspect')
        self.desktop = Mock(bridge=Mock(hit=Mock(return_value={'finder_item':True,'title':'Recipes'})))
        self.visual = dict(screen=dict(x=0,y=0,width=1000,height=800))

    def step(self, **extra):
        return dict(status='action', action=dict(type='click_point',x=.5,y=.5,label='Recipes',**extra))

    def test_slow_second_selection_is_rejected_before_rename(self):
        self.task.receipts.append(dict(type='click_point',label='Recipes',status='submitted'))
        with self.assertRaisesRegex(ValidationError,'slow single click can rename'):
            self.task.app_click(self.step(),self.desktop,{},self.visual)

    def test_first_selection_and_explicit_open_or_context_menu_are_allowed(self):
        self.task.app_click(self.step(),self.desktop,{},self.visual)
        self.task.receipts.append(dict(type='click_point',label='Recipes',status='submitted'))
        self.task.app_click(self.step(click_count=2),self.desktop,{},self.visual)
        self.task.app_click(self.step(button='right'),self.desktop,{},self.visual)

    def test_other_control_or_later_selection_is_not_mistaken_for_rename(self):
        self.task.receipts.append(dict(type='press_control',label='Recipes',status='submitted'))
        self.task.app_click(self.step(),self.desktop,{},self.visual)
        self.task.receipts.append(dict(type='click_point',label='Supplies',status='submitted'))
        self.task.app_click(self.step(),self.desktop,{},self.visual)
