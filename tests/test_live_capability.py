"""Offline suite contracts: no desktop access or inference."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import live_capability as suite
from live_conversation import run


class CapabilitySuiteTests(unittest.TestCase):
    def test_path_checks_accept_aliases_but_not_other_files_or_empty_results(self):
        import live_eval
        with tempfile.TemporaryDirectory() as parent:
            root=Path(parent)/'real'
            root.mkdir()
            alias=Path(parent)/'alias'
            alias.symlink_to(root,target_is_directory=True)
            self.assertTrue(live_eval.same_path(alias/'document.txt',root/'document.txt'))
            self.assertFalse(live_eval.same_path(alias/'other.txt',root/'document.txt'))
            self.assertFalse(live_eval.same_path('',root))

    def test_diagnostic_snapshot_never_keeps_field_values_or_window_titles(self):
        from companion.eval_control import observation_state
        result=observation_state(dict(app={'name':'Finder','bundle_id':'com.apple.finder'},
            window={'title':'secret title','bounds':{'x':1}},focused={'value':'secret field'},focused_role='AXOutline'))
        self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(result['window_bounds'],{'x':1})

    def test_only_native_probe_wrapper_uses_foreground_io(self):
        import live_eval
        with patch.object(live_eval.sys,'platform','darwin'):
            self.assertEqual(live_eval.native_command('osascript','-e','return 1'),
                             ['/bin/sh','-c','taskpolicy -B -p $$ && exec "$@"','native-probe','osascript','-e','return 1'])
        with patch.object(live_eval.sys,'platform','win32'):
            self.assertEqual(live_eval.native_command('probe'),['probe'])

    def test_evidence_crop_excludes_surrounding_windows_at_retina_scale(self):
        from companion.eval_control import evidence_rect
        screen = dict(x=-1000,y=0,width=1000,height=700)
        bounds = dict(x=-900,y=100,width=400,height=300)
        self.assertEqual(evidence_rect(bounds,screen,2000,1400),(200,200,800,600))
        self.assertEqual(evidence_rect(dict(bounds,x=-1100),screen,2000,1400),(0,200,600,600))
        self.assertIsNone(evidence_rect(dict(bounds,x=400),screen,2000,1400))
        self.assertIsNone(evidence_rect(bounds,dict(screen,width=0),2000,1400))
        self.assertIsNone(evidence_rect(dict(bounds,x=float('nan')),screen,2000,1400))

    def build(self):
        with patch.object(suite, 'osa', side_effect=AssertionError('native during build')), \
             patch.object(suite.tempfile, 'mkdtemp', side_effect=AssertionError('fixture during build')):
            return suite.build(Mock())

    def test_long_case_retains_process_across_ten_intervening_requests(self):
        cases = self.build()
        case = next(c for c in cases if c['name'] == 'long_conversation')
        names = [t.family for t in case['turns']]
        self.assertGreaterEqual(names.index('distant_task')-names.index('first_task'), 11)
        self.assertGreaterEqual(names.index('distant_fact')-names.index('remember_fact'), 11)
        for c in cases:
            for t in c['turns']:
                self.assertNotRegex(t.request+' '+t.wanted_app, r'(?i)\b(mail|messages|photos|contacts|teams|whatsapp|facetime|youtube)\b')
                self.assertEqual(len(t.checks), 2)

    def test_double_click_requires_actual_double_click_not_just_destination(self):
        state = {}
        def event(n):
            return [{'kind':'timing','data':{'event':'eval.shot','action':{'type':'click_point','click_count':n}}}]
        self.assertFalse(suite.action_seen(state,event(1),'click_point',click_count=2))
        self.assertTrue(suite.action_seen(state,event(2),'click_point',click_count=2))
        self.assertFalse(suite.action_seen(state,[],'click_point',click_count=2))

    def test_fixture_removed_after_native_cleanup_error(self):
        case = self.build()[0]
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)/'owned'
            root.mkdir()
            with patch.object(suite.tempfile,'mkdtemp',return_value=str(root)), patch.object(suite,'osa'):
                case['setup'](Mock())
            with patch.object(suite,'osa',side_effect=RuntimeError('native failed')):
                with self.assertRaises(RuntimeError):
                    case['cleanup'][0]()
            self.assertFalse(root.exists())

    def test_runner_uses_one_process_and_incremental_records_for_conversation(self):
        case = next(c for c in self.build() if c['name'] == 'long_conversation')
        case = dict(case, setup=None, cleanup=[])
        app, window = Mock(), Mock()
        app.run.return_value = ({'plan':{'operation':'answer'}},[],False)
        # Outcome checks are independently covered elsewhere; exercise orchestration here.
        for t in case['turns']:
            t.checks = [('fixture',lambda s,e: True)]
        with tempfile.TemporaryDirectory() as folder, \
             patch('live_conversation.le.app_names',return_value=set()), \
             patch('live_conversation.le.running',side_effect=AssertionError('per-app polling')), \
             patch('live_conversation.osa',side_effect=AssertionError('native')):
            run(app,window,Path(folder),[case])
            rows=json.loads((Path(folder)/'summary.json').read_text())
        app.launch.assert_called_once()
        self.assertEqual(app.run.call_count,len(case['turns']))
        self.assertEqual(len(rows),len(case['turns']))
        self.assertTrue(all(r['plan']=={'operation':'answer'} for r in rows))


if __name__ == '__main__':
    unittest.main()
