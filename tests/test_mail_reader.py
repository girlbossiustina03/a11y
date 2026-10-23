"""Reading Apple Mail in code: which message, its text, and nothing stored or sent to a model."""
import unittest
from unittest.mock import Mock, patch
from companion import mail_reader
from companion.desktop_context import DesktopContext
from test_core import CompanionFixture
from test_desktop_context import FakeBridge


class PositionTests(unittest.TestCase):
    def test_requests_from_the_reports(self):
        for request, n in (('read out my last email', 1), ('Check what my second last email says.', 2),
                           ('what is my latest mail', 1), ('read me my last mail please', 1),
                           ('who sent my most recent email', 1), ('read my second to last email', 2),
                           ('what does my third latest email say', 3)):
            self.assertEqual(mail_reader.position(request), n, request)
        for request in ('open the mail broski', 'what do you see on screen', 'send an email to Ana', 'what is in my notes'):
            self.assertIsNone(mail_reader.position(request), request)


class NewestTests(unittest.TestCase):
    def runner(self, listings, message='Rockstar Games <noreply@rockstargames.com>\x1fYour code\x1fThursday, 23 October 2026\x1fYour verification code is 368229.\n'):
        calls = []
        def run(script, argument, timeout):
            calls.append((script, argument))
            return listings.pop(0) if script is mail_reader.LISTING else message
        return run, calls

    def test_nth_newest_is_chosen_by_date_not_list_order(self):
        listing = '11\x1f2026-10-22T08:00:00\x1e12\x1f2026-10-23T09:30:00\x1e13\x1f2026-10-23T07:00:00\x1e'
        run, calls = self.runner([listing])
        found = mail_reader.newest(2, run)
        self.assertEqual(calls[-1], (mail_reader.MESSAGE, 13))  # second newest by date
        self.assertEqual(found[1], 'Your code')
        run, calls = self.runner([listing])
        mail_reader.newest(1, run)
        self.assertEqual(calls[-1], (mail_reader.MESSAGE, 12))

    def test_window_widens_until_enough_messages(self):
        run, calls = self.runner(['', '5\x1f2026-10-01T10:00:00\x1e'])
        self.assertIsNotNone(mail_reader.newest(1, run))
        self.assertEqual([argument for script, argument in calls if script is mail_reader.LISTING], [3, 30])
        run, _ = self.runner(['', '', ''])
        self.assertIsNone(mail_reader.newest(1, run))

    def test_reply_names_sender_subject_and_text(self):
        reply = mail_reader.describe(1, ('Rockstar Games <noreply@rockstargames.com>', 'Your code', 'Thursday', 'Your verification code is 368229.'))
        self.assertTrue(reply.startswith('Your last email is from Rockstar Games, subject "Your code", received Thursday.'))
        self.assertIn('368229', reply)
        self.assertIn('Email number 2 from the newest', mail_reader.describe(2, ('a', 'b', 'c', 'd')))

    def test_denied_automation_explains_the_setting(self):
        result = Mock(returncode=1, stderr='execution error: Not authorized to send Apple events to Mail. (-1743)', stdout='')
        with patch('companion.mail_reader.subprocess.run', return_value=result), self.assertRaisesRegex(PermissionError, 'Automation'):
            mail_reader.run(mail_reader.LISTING, 3, 5)


class MailServiceTests(CompanionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app.desktop_context = DesktopContext(FakeBridge(), clock=lambda: 100)
        self.app.provider = Mock()

    def test_read_my_last_email_needs_no_model_and_is_not_saved(self):
        found = ('Rockstar Games', 'Your code', 'today', 'Your verification code is 368229.')
        with patch.object(mail_reader, 'available', return_value=True), patch.object(mail_reader, 'newest', return_value=found) as newest:
            response = self.app.ask('read out my last email')
        newest.assert_called_once_with(1)
        self.assertIn('368229', response['message'])
        self.assertTrue(response['full_text'])
        self.assertTrue(response['read_aloud'])
        self.app.provider.interpret_request.assert_not_called()
        self.app.provider.complete_structured.assert_not_called()
        self.assertNotIn('368229', str(self.app.store.history(self.app.identity, limit=50)))

    def test_other_platforms_use_the_normal_path(self):
        with patch.object(mail_reader, 'available', return_value=False), patch.object(mail_reader, 'newest') as newest:
            try:
                self.app.ask('read out my last email')
            except Exception:
                pass
        newest.assert_not_called()


if __name__ == '__main__':
    unittest.main()
