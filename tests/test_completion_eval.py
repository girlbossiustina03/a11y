import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('completion_eval',Path(__file__).resolve().parents[1]/'scripts/completion_eval.py')
eval_module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_module)


class CompletionEval(unittest.TestCase):
    def test_build_is_reproducible_balanced_and_contains_adversarial_pairs(self):
        rows=eval_module.build(7)
        self.assertEqual(rows,eval_module.build(7))
        self.assertNotEqual(rows,eval_module.build(8))
        self.assertEqual(len(rows),12)
        self.assertEqual(sum(r['gold'] for r in rows),5)
        self.assertEqual(len({r['name'] for r in rows}),12)
        by_name={r['name']:r for r in rows}
        self.assertFalse(by_name['selected_child']['observation']['navigation']['entered'])
        self.assertNotEqual(by_name['settings_sidebar_only']['observation']['window'],'Sound')
        self.assertEqual(len(by_name['document_content_missing']['observation']['screen_text']),1)
        self.assertGreater(len(by_name['document_content']['observation']['screen_text']),1)

    def test_score_separates_unsafe_success_claims_from_missed_completions(self):
        rows=[dict(gold=gold,effective_met=met,correct=gold==met) for gold,met in
              [(True,True),(False,False),(True,False),(False,True)]]
        self.assertEqual(eval_module.score(rows),dict(total=4,correct=2,false_positives=1,false_negatives=1))
