import re
import unittest
from unittest.mock import Mock

from companion import mac_apps


class NoteCreationRegression(unittest.TestCase):
    def test_note_title_is_supplied_by_the_first_body_line_only(self):
        # Notes derives its name from the first HTML line. Supplying both name
        # and body inserts another title, as observed in features-2.
        title = 'A11y test 90800'
        script = Mock(return_value=title)
        kind, action = mac_apps.prepare('create_note', title+' | Bring two pears.', bridge=None, script=script)
        self.assertEqual(kind, 'confirm')
        script.reset_mock()
        mac_apps.perform(action, bridge=None, script=script)
        source, supplied_title, body = script.call_args.args
        self.assertEqual(supplied_title, title)
        self.assertEqual(body.count(title), 1)
        self.assertIn('Bring two pears.', body)
        properties = re.search(r'with properties \{([^}]*)\}', source).group(1)
        self.assertNotRegex(properties, r'\bname\s*:')
        self.assertRegex(properties, r'\bbody\s*:')
