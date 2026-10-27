"""Owner's Finder rename detour: gesture semantics, not per-file rules."""
import unittest
from unittest.mock import Mock,patch
from companion.computer_task import requested_gesture, finder_name_editor, needs_review


class ClickGestureTests(unittest.TestCase):
    def test_panel_yields_key_without_activating_another_app(self):
        from companion import mac_window
        selectors=[]
        def send(receiver,selector,*a,**kw):
            selectors.append(selector)
            return selector=='isKeyWindow'
        with patch.object(mac_window,'ns_window',return_value=7),patch.object(mac_window,'send',side_effect=send):
            self.assertTrue(mac_window.release_key(Mock()))
        self.assertEqual(selectors,['isKeyWindow','resignKeyWindow'])

    def test_app_window_qualifier_keeps_exact_click_shortcut(self):
        from companion.computer_task import scoped_click_goal
        self.assertEqual(scoped_click_goal('Double-click Expedition in this Finder window.','Finder'),(('expedition',),'left',2))
        self.assertNotEqual(scoped_click_goal('Double-click Expedition in this Preview window.','Finder'),(('expedition',),'left',2))
        self.assertNotEqual(scoped_click_goal('Double-click Expedition and then delete it.','Finder'),(('expedition',),'left',2))

    def test_open_target_only_opens_an_observed_file_target(self):
        from companion.computer_task import resolve_target,schema_for
        from companion.models import ValidationError
        marks=[dict(id='t1',kind='file or folder',label='Expedition',x=.1,y=.2,width=.2,height=.04),
               dict(id='t2',kind='button',label='Other',x=.4,y=.5,width=.1,height=.1)]
        action=resolve_target({'action':{'type':'open_target','target_id':'t1'}},marks)['action']
        self.assertEqual((action['type'],action['click_count'],action['label']),('click_point',2,'Expedition'))
        for target in ('t2','missing'):
            with self.assertRaises(ValidationError): resolve_target({'action':{'type':'open_target','target_id':target}},marks)
        schema=schema_for('macOS',target_ids=['t1','t2'],file_target_ids=['t1'])
        variants=schema['anyOf'][0]['properties']['action']['anyOf']
        opening=next(v for v in variants if v['properties']['type']['enum']==['open_target'])
        self.assertEqual(opening['properties']['target_id']['enum'],['t1'])

    def test_same_native_target_is_not_ambiguous_but_separate_rows_are(self):
        from companion.computer_task import labelled_targets,label_words
        screen=dict(x=0,y=0,width=1000,height=800)
        control=dict(label='Expedition',bounds=dict(x=100,y=100,width=100,height=20))
        self.assertEqual(len(labelled_targets(label_words('Expedition'),[],[control,dict(control)],screen)),1)
        other=dict(control,bounds=dict(x=100,y=130,width=100,height=20))
        self.assertEqual(len(labelled_targets(label_words('Expedition'),[],[control,other],screen)),2)

    def test_qualifiers_do_not_downgrade_double_click(self):
        for label,request in [
            ('Expedition','Double-click Expedition in this Finder window.'),
            ('Quarterly report.txt','Double-click Quarterly report.txt so I can read it.'),
            ('Budget 2027.xlsx','Double-click the Budget 2027.xlsx file in the open folder.'),
        ]:
            action=dict(type='click_point',x=.2,y=.3,label=label)
            result=requested_gesture(action,request)
            self.assertEqual((result['button'],result['click_count']),('left',2))
            self.assertEqual((result['x'],result['y']),(.2,.3))
            self.assertNotIn('click_count',action)

    def test_intermediate_targets_are_unchanged(self):
        action=dict(type='click_point',x=.2,y=.3,label='View')
        for request in ['Double-click Expedition in Finder.','Open the Expedition folder.',
                        'Double-click Overview then click View.']:
            self.assertEqual(requested_gesture(action,request),action)

    def test_sensitive_targets_still_review(self):
        action=dict(type='click_point',x=.2,y=.3,label='Delete')
        right=requested_gesture(action,'Right-click Delete to inspect its context menu.')
        self.assertEqual((right['button'],right['click_count']),('right',1))
        self.assertTrue(needs_review(right,'navigation'))
        self.assertTrue(needs_review(dict(type='choose_menu',path='File > Rename'),'navigation'))
        self.assertTrue(needs_review(dict(type='click_point',label='Rename'),'navigation'))

    def test_filename_editor_requires_finder_and_native_row_ancestry(self):
        snapshot=dict(app={'bundle_id':'com.apple.finder'},focused_role='AXTextField',focused_container_roles=['AXCell','AXRow','AXOutline'])
        self.assertTrue(finder_name_editor(snapshot))
        for change in [dict(app={'bundle_id':'com.apple.TextEdit'}),dict(focused_role='secure_input'),
                       dict(focused_container_roles=['AXToolbar','AXWindow']),dict(focused_container_roles=[])]:
            self.assertFalse(finder_name_editor(dict(snapshot,**change)))
        self.assertTrue(finder_name_editor(dict(snapshot,focused_container_roles=['AXApplication'],window={})))
        self.assertFalse(finder_name_editor(dict(snapshot,focused_container_roles=['AXApplication'],window={'bounds':{'x':0}})))

    def test_native_filename_mismatch_rejects_guessed_position(self):
        from companion.computer_task import ComputerTask
        from companion.models import ValidationError
        task=ComputerTask('Open a folder',goal_mode='inspect')
        desktop=Mock(bridge=Mock(hit=Mock(return_value={'finder_item':True,'title':'Other.txt'})))
        step=dict(status='action',action=dict(type='click_point',x=.5,y=.5,label='Expedition'))
        with self.assertRaisesRegex(ValidationError,'different Finder item'):
            task.app_click(step,desktop,{},dict(screen=dict(x=0,y=0,width=1000,height=800)))
        desktop.bridge.hit.return_value=dict(finder_item=True,title='Expedition')
        self.assertEqual(task.app_click(step,desktop,{},dict(screen=dict(x=0,y=0,width=1000,height=800))),step)

    def test_execution_hit_guard_covers_code_clicks_and_menu_overlays(self):
        from companion.vision import ScreenVision
        proposal=dict(label='Expedition')
        self.assertTrue(ScreenVision.named_hit_conflict(proposal,dict(role='AXMenuItem',title='Right')))
        self.assertTrue(ScreenVision.named_hit_conflict(proposal,dict(finder_item=True,title='Other.txt')))
        self.assertFalse(ScreenVision.named_hit_conflict(proposal,dict(finder_item=True,title='Expedition')))
        self.assertFalse(ScreenVision.named_hit_conflict(proposal,dict(role='AXImage',title='icon')))
        self.assertFalse(ScreenVision.named_hit_conflict(proposal,None))

    def test_conflicting_native_hit_sends_no_mouse_event(self):
        import time
        from companion.vision import ScreenVision
        vision=ScreenVision('/private/tmp/a11y-unit-guard')
        vision.set_enabled(True)
        screen=dict(x=0,y=0,width=1000,height=800)
        guard=dict(screen=screen,display_id=1,windows=[],region_hash='same',captured_monotonic=time.monotonic())
        vision.capture=Mock(return_value={'image_data':'synthetic'})
        vision.click_guard=Mock(return_value=guard)
        desktop=Mock(bridge=Mock(hit=Mock(return_value={'role':'AXMenuItem','title':'Right'})))
        with self.assertRaisesRegex(ValueError,'different file or menu'):
            vision.execute_click(Mock(),desktop,dict(type='click_point',label='Expedition',x=.2,y=.3,capture_guard=guard))
        desktop.bridge.click.assert_not_called()
        desktop.bridge.drag.assert_not_called()


if __name__ == '__main__':
    unittest.main()
