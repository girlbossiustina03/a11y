from copy import deepcopy
from unittest.mock import patch
from companion.computer_task import ComputerTask
from test_reported_failures import Harness,region,CALCULATOR


class FileOpeningSettle(Harness):
    snapshot=deepcopy(CALCULATOR)
    snapshot.update(app={'name':'Finder','bundle_id':'com.apple.finder'},focused_role='AXOutline',
                    finder={'target':'/tmp/Expedition','view':'list view','sort':'name column'})
    snapshot['window']=dict(CALCULATOR['window'],title='Supplies')
    regions=[region('Supplies',.1,.1),region('Name',.1,.2),region('manifest.txt',.1,.3)]

    def task(self):
        task=ComputerTask('Enter Supplies',goal_mode='inspect')
        task.receipts=[dict(type='click_point',label='Supplies',click_count=2,screen='before',
                           wanted={'file_parent':'/tmp/Expedition','file_name':'Supplies'})]
        return task

    def test_file_open_waits_for_stable_native_identity_even_when_ocr_is_unchanged(self):
        task=self.task()
        def settle(_):self.desktop.bridge.value['finder']['target']='/tmp/Expedition/Supplies'
        with patch('companion.computer_task.time.sleep',side_effect=settle) as sleep, \
             patch.object(task,'plan_start',return_value=None), \
             patch.object(task,'goal_met',return_value=dict(status='done',action=None,message='Supplies is open.')) as check:
            result=self.propose(task)
        self.assertEqual(result['status'],'done')
        self.assertEqual(sleep.call_count,2)
        self.assertEqual(check.call_args.args[1]['finder']['target'],'/tmp/Expedition/Supplies')
        self.provider.complete_structured.assert_not_called()

    def test_stop_during_file_settle_prevents_model_call_or_action(self):
        task=self.task()
        with patch('companion.computer_task.time.sleep',side_effect=lambda _:task.cancelled.set()), \
             patch.object(task,'plan_start',return_value=None):
            with self.assertRaisesRegex(ValueError,'stopped'):
                self.propose(task)
        self.provider.complete_structured.assert_not_called()

    def test_ocr_order_changes_do_not_prolong_an_unchanged_native_scene(self):
        from companion.computer_task import observation_state
        snapshot={'app':{'bundle_id':'com.apple.finder'},'finder':{'target':'/tmp/Reports'}}
        regions=[{'text':'Reports'},{'text':'Name'},{'text':'manifest.txt'}]
        self.assertEqual(observation_state(snapshot,{'text_regions':regions}),
                         observation_state(snapshot,{'text_regions':list(reversed(regions))}))
        changed=deepcopy(snapshot);changed['finder']['target']='/tmp/Reports/Child'
        self.assertNotEqual(observation_state(snapshot,{'text_regions':regions}),
                            observation_state(changed,{'text_regions':regions}))
