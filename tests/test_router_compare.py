"""Pairing and non-regression gate without inference."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from router_compare import compare


class RouterComparisonTests(unittest.TestCase):
    def reports(self):
        gold=dict(operation='launch_app',app_name='Calculator',target='',goal_mode='inspect',referent='destination')
        row=dict(row=0,request={'current_request':'Open Calculator'},gold=gold,prediction=deepcopy(gold))
        base=dict(backend='ollama',outputs=[row],failures=[])
        candidate=deepcopy(base)
        base['outputs'][0]['prediction']['app_name']='Wrong'
        return base,candidate

    def test_same_rows_gain_can_qualify_but_never_adopts(self):
        b,c=self.reports()
        result=compare(b,c)
        self.assertTrue(result['qualifies_for_live_validation'])
        self.assertEqual(result['metrics']['app_name']['candidate_correct'],1)
        self.assertNotIn('adopted',result)

    def test_order_content_and_runtime_must_match(self):
        for change in ('row','request','gold','backend'):
            b,c=self.reports()
            if change=='backend': c['backend']='mlx'
            else: c['outputs'][0][change]='different'
            with self.assertRaises(ValueError): compare(b,c)

    def test_parse_or_scope_regression_blocks_even_when_app_field_improves(self):
        for field in ('operation','goal_mode','referent'):
            b,c=self.reports()
            c['outputs'][0]['prediction'][field]='wrong'
            result=compare(b,c)
            self.assertFalse(result['qualifies_for_live_validation'])
            self.assertTrue(result['critical_regressions'])
        b,c=self.reports()
        c['failures']=[{'row':0,'error':'bad JSON'}]
        self.assertFalse(compare(b,c)['qualifies_for_live_validation'])

    def test_action_regression_cannot_be_offset_by_another_corrected_action_flag(self):
        b,c=self.reports()
        for report in (b,c):
            report['outputs'].append(deepcopy(report['outputs'][0]))
            report['outputs'][1]['row']=1
            for index,row in enumerate(report['outputs']):
                row['gold']['acts_on_computer']=bool(index)
        for row in b['outputs']:row['prediction']['acts_on_computer']=False
        for row in c['outputs']:row['prediction']['acts_on_computer']=True
        result=compare(b,c)
        self.assertEqual(result['metrics']['acts_on_computer']['base_correct'],1)
        self.assertEqual(result['metrics']['acts_on_computer']['candidate_correct'],1)
        self.assertFalse(result['qualifies_for_live_validation'])
        self.assertTrue(any(row['field']=='acts_on_computer' for row in result['critical_regressions']))


if __name__=='__main__': unittest.main()
