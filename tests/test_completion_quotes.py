import unittest
from unittest.mock import Mock
from companion.computer_task import ComputerTask,completion_schema,completion_evidence


class CompletionQuotes(unittest.TestCase):
    def test_quotes_are_only_observed_native_values_or_screen_lines(self):
        observation=dict(goal='Enter Supplies',last_click='Invented button',window='Supplies',
            facts={'finder':{'target':'/tmp/owned/Supplies','view':'list view'}},screen_text=['manifest.txt'])
        choices=completion_schema(observation)['properties']['evidence']['enum']
        self.assertIn('/tmp/owned/Supplies',choices)
        self.assertIn('Supplies',choices)
        self.assertIn('manifest.txt',choices)
        self.assertNotIn('Enter Supplies',choices)
        self.assertNotIn('Invented button',choices)
        self.assertTrue(completion_evidence(dict(met=True,missing='',evidence=choices[0]),observation))
        self.assertFalse(completion_evidence(dict(met=True,missing='',evidence='The folder is already open.'),observation))

    def test_empty_and_large_observations_stay_bounded(self):
        self.assertEqual(completion_schema({})['properties']['evidence']['enum'],[''])
        observation={'screen_text':['x'*2000]+['value '+str(i) for i in range(200)]}
        choices=completion_schema(observation)['properties']['evidence']['enum']
        self.assertEqual(len(choices),80)
        self.assertTrue(all(len(value)<=1024 for value in choices))

    def task(self):
        task=ComputerTask('Continue into the Supplies subfolder.',goal_mode='inspect')
        task.receipts=[dict(type='click_point',label='Supplies',screen='before',click_count=2,
                           wanted={'file_parent':'/tmp/owned','file_name':'Supplies'})]
        task.screen_seen='after'
        task.file_interactions={('/tmp/owned','Supplies'):'open'}
        return task

    def test_folder_name_quote_needs_the_exact_native_destination(self):
        regions=[dict(text='Supplies',x=.1,y=.1),dict(text='manifest.txt',x=.1,y=.2)]
        for target,wanted in [('/tmp/owned/Supplies','done'),('/tmp/owned',None),
                               ('/tmp/unrelated/Supplies',None),('',None)]:
            with self.subTest(target=target):
                task=self.task()
                snapshot=dict(app={'name':'Finder','bundle_id':'com.apple.finder'},window={'title':'Supplies'},
                              finder={'target':target})
                provider=Mock(complete_structured=Mock(side_effect=[
                    dict(met=True,missing='',evidence='Supplies'),dict(message='Supplies is open.')]))
                result=task.goal_met(provider,snapshot,regions,{})
                self.assertEqual(result['status'] if result else None,wanted)
                self.assertIn('enum',provider.complete_structured.call_args_list[0].kwargs['schema']['properties']['evidence'])

    def test_native_parent_cannot_be_claimed_as_a_successful_child_opening(self):
        task=self.task()
        snapshot=dict(app={'name':'Finder','bundle_id':'com.apple.finder'},window={'title':'owned'},
                      finder={'target':'/tmp/owned'})
        observation=task.completion_observation(snapshot,[dict(text='owned',x=0,y=0)])
        self.assertFalse(observation['navigation']['entered'])
        self.assertFalse(completion_evidence(dict(met=True,evidence='owned',missing=''),observation))

    def test_missing_requirement_is_preserved_separately_from_the_exact_quote(self):
        task=self.task()
        provider=Mock(complete_structured=Mock(return_value=dict(met=False,evidence='Supplies',missing='Folder not entered.')))
        missing=task.still_missing(provider,dict(app={'name':'Finder'},window={'title':'Supplies'}),[],{})
        self.assertEqual(missing,'Folder not entered.')

    def test_settings_title_proves_its_pane_but_other_clicked_button_names_still_do_not(self):
        for bundle,title,wanted in [('com.apple.systempreferences','Sound','done'),('com.apple.Maps','Map Modes',None)]:
            task=ComputerTask('Show the requested view.',goal_mode='inspect')
            task.receipts=[dict(type='click_point',label=title,screen='before')]
            task.screen_seen='after'
            provider=Mock(complete_structured=Mock(side_effect=[dict(met=True,evidence=title,missing=''),dict(message='The view is open.')]))
            result=task.goal_met(provider,dict(app={'bundle_id':bundle},window={'title':title}),
                                 [dict(text=title,x=0,y=0),dict(text='Other text',x=0,y=.2)],{})
            self.assertEqual(result['status'] if result else None,wanted)

    def test_real_destination_still_cannot_override_missing_parts_of_compound_goal(self):
        task=self.task()
        provider=Mock(complete_structured=Mock(return_value=dict(met=False,evidence='Supplies',missing='document not open')))
        self.assertIsNone(task.goal_met(provider,dict(app={'name':'Finder'},window={'title':'Supplies'},
            finder={'target':'/tmp/owned/Supplies'}),[dict(text='Supplies',x=0,y=0),dict(text='manifest',x=0,y=.2)],{}))

    def test_exact_native_path_is_evidence_even_when_not_rendered_as_screen_text(self):
        task=self.task()
        provider=Mock(complete_structured=Mock(side_effect=[
            dict(met=True,missing='',evidence='/tmp/owned/Supplies'),dict(message='Supplies is open.')]))
        result=task.goal_met(provider,dict(app={'name':'Finder','bundle_id':'com.apple.finder'},
            window={'title':'Supplies'},finder={'target':'/tmp/owned/Supplies'}),
            [dict(text='Supplies',x=0,y=0),dict(text='manifest.txt',x=0,y=.2)],{})
        self.assertEqual(result['status'],'done')

    def test_planned_criterion_is_not_evidence_and_does_not_replace_original_goal(self):
        task=self.task()
        task.plan={'done_when':'The Supplies folder is open and the manifest has been read.'}
        snapshot=dict(app={'name':'Finder','bundle_id':'com.apple.finder'},window={'title':'Supplies'},
                      finder={'target':'/tmp/owned/Supplies'})
        observation=task.completion_observation(snapshot,[])
        self.assertEqual(observation['goal'],task.goal)
        self.assertEqual(observation['planned_outcome'],task.plan['done_when'])
        self.assertNotIn(task.plan['done_when'],completion_schema(observation)['properties']['evidence']['enum'])
        self.assertFalse(completion_evidence(dict(met=True,evidence=task.plan['done_when'],missing=''),observation))

    def test_settings_sidebar_name_cannot_confirm_a_different_native_pane(self):
        task=ComputerTask('Go to Sound in System Settings.',goal_mode='inspect')
        task.receipts=[dict(type='click_point',label='Sound')]
        provider=Mock(complete_structured=Mock(return_value=dict(met=True,evidence='Sound',missing='')))
        snapshot=dict(app={'name':'System Settings','bundle_id':'com.apple.systempreferences'},window={'title':'Displays'})
        self.assertTrue(task.still_missing(provider,snapshot,[dict(text='Sound',x=0,y=0)],{}))
