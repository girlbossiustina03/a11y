"""Pure parsers only: no Mac, model, socket or UI calls."""
from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import subprocess


sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from live_conversation import denies_control, reminder_times, task_started, parse_reminders, note_words
from live_broad import private_roundtrip
import live_broad
import live_heldout
from live_conversation import page, build


class LiveSuiteParsers(unittest.TestCase):
    def test_control_denial(self):
        for reply in ("I can't control your computer.", 'I cannot use the computer.', 'I’m unable to control it.'):
            self.assertTrue(denies_control(reply))
        for reply in ('Safari is already open.', "I can't see that page.", 'I can control the computer.'):
            self.assertFalse(denies_control(reply))

    def test_only_current_turn_events(self):
        self.assertFalse(task_started([]))
        self.assertFalse(task_started([{'kind':'say','data':{'event':'task.done'}}]))
        self.assertTrue(task_started([{'kind':'timing','data':{'event':'task.start'}}]))

    def test_native_reminder_epoch(self):
        day = datetime(2027, 1, 4).date()
        items = [{'due':datetime(2027,1,4,hour).timestamp()} for hour in (9,10)]
        self.assertTrue(reminder_times(items,day,[9,10]))
        self.assertFalse(reminder_times(items,day,[9,9]))
        self.assertFalse(reminder_times(items[:1],day,[9,10]))
        self.assertFalse(reminder_times([{}],day,[9]))

    def test_note_html_does_not_count_attributes(self):
        self.assertNotIn('hi', note_words('<div style="white-space: pre-wrap">A11y test 123</div>'))
        self.assertEqual(note_words('<div>hi</div><div>bye &amp; hello</div>'), 'hi bye & hello')

    def test_reminder_rows(self):
        items = parse_reminders('id1\tA11y test 123\t2027\t1\t4\t9\t0\nid2\tA11y test 123')
        self.assertEqual(items[0]['due'], datetime(2027,1,4,9).timestamp())
        self.assertNotIn('due', items[1])
        self.assertEqual(parse_reminders(''), [])
        with self.assertRaises(ValueError):
            parse_reminders('broken')

    def test_private_path_requires_close_after_open(self):
        opening = {'label':'File > New Private Window','type':'choose_menu'}
        closing = {'label':'File > Close Window','type':'choose_menu'}
        self.assertTrue(private_roundtrip([opening,closing]))
        self.assertFalse(private_roundtrip([closing,opening]))
        self.assertFalse(private_roundtrip([opening]))


class LiveHarnessChecks(unittest.TestCase):
    def test_page_host_boundary_and_observation(self):
        for address, expected in [('https://en.wikipedia.org/wiki/Test', True),
                                  ('https://wikipedia.org/', True),
                                  ('https://fakewikipedia.org/', False),
                                  ('https://wikipedia.org.evil.test/', False)]:
            state = {}
            with patch('live_conversation.le.safari_front_tab', return_value=(address, '')):
                self.assertEqual(page('wikipedia.org')(state, []), expected)
            self.assertEqual(state['_observed']['url'], address)

    def test_menu_hierarchy_and_marks(self):
        observed = {}
        with patch('live_broad.osa', return_value='✓') as osa:
            self.assertTrue(live_broad.menu_mark('Calendar', 'View', 'Day', observed))
        self.assertIn('of menu 1 of menu bar item', osa.call_args.args[0])
        self.assertEqual(observed['menu_marks']['View > Day'], '✓')
        with patch('live_broad.osa', side_effect=RuntimeError('menu missing')):
            with self.assertRaisesRegex(RuntimeError, 'menu missing'):
                live_broad.menu_mark('Calendar', 'View', 'Week')

    def test_osa_keeps_error(self):
        result = subprocess.CompletedProcess([], 1, '', 'No such menu (-1728)')
        with patch('live_heldout.subprocess.run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'No such menu'):
                live_heldout.osa('return 1')

    def test_selection_attributes(self):
        with patch('live_broad.osa', return_value='yes') as osa:
            self.assertTrue(live_broad.selected('Clock', 'World Clock'))
        for attribute in ('AXTitle', 'AXDescription', 'AXIdentifier', 'AXValue', 'AXSelected'):
            self.assertIn(attribute, osa.call_args.args[0])

    def test_second_note_uses_new_id_and_cleans_only_owned(self):
        with patch('live_conversation.installed', return_value=set()):
            cases = build(None)
        case = next(c for c in cases if c['name'] == 'two_notes')
        deleted = []
        ids = ['owner', 'owner, first', 'owner, first', 'owner, first, second']
        def osa(script, *args):
            if 'delete note id' in script:
                deleted.append(args[0])
                return ''
            if 'id of every note whose' in script:
                return 'first'
            if 'id of every note' in script:
                return ids.pop(0)
            if 'body of note id' in script:
                self.assertEqual(args, ('second',))
                return '<div>bye</div>'
            return '<div>hi</div>'
        with patch('live_conversation.osa', side_effect=osa), patch('live_conversation.le.activate'):
            case['setup'](None)
            self.assertTrue(case['turns'][0].checks[0][1]({}, []))
            case['turns'][1].setup(None)
            self.assertTrue(case['turns'][1].checks[0][1]({}, []))
            case['cleanup'][0]()
        self.assertEqual(set(deleted), {'first', 'second'})
