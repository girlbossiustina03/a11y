from copy import deepcopy
import json
import unittest
from unittest.mock import Mock
from companion.computer_task import ComputerTask
from companion.models import ValidationError


class FileInteractionTests(unittest.TestCase):
    def setUp(self):
        self.task=ComputerTask('Continue into the Supplies subfolder.',goal_mode='inspect')
        self.step=dict(status='action',risk='navigation',message='Opening Supplies.',
                       action=dict(type='click_point',x=.5,y=.5,label='Supplies'))
        self.marks=[dict(id=1,kind='file or folder',label='Supplies',x=.4,y=.4,width=.2,height=.2)]
        self.provider=Mock(complete_structured=Mock(return_value={'interaction':'open'}))

    def test_open_intent_becomes_double_click_on_the_already_grounded_item(self):
        result=self.task.file_interaction(self.step,self.marks,self.provider,{})
        self.assertEqual(result['action'],dict(self.step['action'],click_count=2))
        self.assertEqual(result['risk'],'navigation')
        self.task.file_interaction(self.step,self.marks,self.provider,{})
        self.assertEqual(self.provider.complete_structured.call_count,1)

    def test_selection_unknown_invalid_and_failed_classification_do_not_open(self):
        for decision in ({'interaction':'select'},{'interaction':'other'},{},None,{'interaction':'delete'}):
            task=ComputerTask('Select Supplies and leave it closed.',goal_mode='inspect')
            self.provider.complete_structured.return_value=decision
            self.assertEqual(task.file_interaction(self.step,self.marks,self.provider,{}),self.step)
        self.provider.complete_structured.side_effect=RuntimeError('provider failed')
        task=ComputerTask('Enter Supplies',goal_mode='inspect')
        self.assertEqual(task.file_interaction(self.step,self.marks,self.provider,{}),self.step)

    def test_explicit_gestures_and_non_file_or_ambiguous_targets_never_call_classifier(self):
        for goal,marks,extra in [('Click Supplies.',self.marks,{}),
                                 ('Double-click Supplies.',self.marks,{'click_count':2}),
                                 ('Enter Supplies',[dict(self.marks[0],kind='button')],{}),
                                 ('Enter Supplies',self.marks+[dict(self.marks[0],id=2,x=.45)],{}),
                                 ('Enter Supplies',self.marks,{'button':'right'}),
                                 ('Enter Supplies',self.marks,{'x':.9})]:
            task=ComputerTask(goal,goal_mode='inspect')
            step=dict(self.step,action=dict(self.step['action'],**extra))
            self.assertEqual(task.file_interaction(step,marks,self.provider,{}),step)
        self.provider.complete_structured.assert_not_called()

    def test_duplicate_native_labels_at_the_same_physical_target_are_one_item(self):
        result=self.task.file_interaction(self.step,self.marks+[dict(self.marks[0],id=2)],self.provider,{})
        self.assertEqual(result['action']['click_count'],2)

    def test_current_native_folder_is_supplied_and_changes_the_cached_decision(self):
        for folder in ('/tmp/one','/tmp/two'):
            self.task.file_interaction(self.step,self.marks,self.provider,{},dict(finder={'target':folder}))
            payload=json.loads(self.provider.complete_structured.call_args.args[1][0]['content'])
            self.assertEqual(payload['current_folder'],folder)
        self.assertEqual(self.provider.complete_structured.call_count,2)

    def test_final_native_hit_guard_still_rejects_a_different_file(self):
        result=self.task.file_interaction(self.step,self.marks,self.provider,{})
        desktop=Mock(bridge=Mock(hit=Mock(return_value={'finder_item':True,'title':'Different'})))
        with self.assertRaises(ValidationError):
            self.task.app_click(result,desktop,{},dict(screen=dict(x=0,y=0,width=1000,height=800)))

    def test_receipt_retains_the_actual_double_click_or_right_button(self):
        self.task.pending=dict(type='click_point',label='Supplies',button='left',click_count=2)
        self.task.record(dict(type='click_point',label='Supplies',status='submitted'))
        self.assertEqual(self.task.receipts[-1]['click_count'],2)
        self.task.pending=dict(type='click_point',label='Supplies',button='right',click_count=1)
        self.task.record(dict(type='click_point',label='Supplies',status='submitted'))
        self.assertEqual(self.task.receipts[-1]['button'],'right')

    def test_receipt_binds_opening_to_the_observed_parent_without_model_path_input(self):
        result=self.task.file_interaction(self.step,self.marks,self.provider,{},dict(finder={'target':'/tmp/owned'}))
        self.task.pending=result['action']
        self.task.record(dict(type='click_point',label='Supplies',status='submitted'))
        self.assertEqual(self.task.receipts[-1]['wanted'],{'file_parent':'/tmp/owned','file_name':'Supplies'})
