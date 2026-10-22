"""Persistence and process-lifetime launch guard; no desktop or network access."""
import json
import subprocess
import sys
import tempfile
import unittest
from companion.access import AccessPreferences
from companion.instance import DesktopInstance, build_id
from companion.models import Identity
from companion.storage import Store


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.identity = Identity('company', 'employee')
        self.access = AccessPreferences(self.store, self.identity)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_off_and_session_enabling_does_not_grant_restoration(self):
        self.access.save(app_awareness=True, screen_vision=True)
        self.assertEqual(self.access.get(), {'remember': False, 'app_awareness': False, 'screen_vision': False})

    def test_remembered_access_survives_restart_and_is_scoped_to_employee(self):
        self.access.save(remember=True, app_awareness=True, screen_vision=True)
        restored = AccessPreferences(Store(self.temp.name), self.identity)
        self.assertTrue(restored.get()['screen_vision'])
        self.assertFalse(AccessPreferences(self.store, Identity('company', 'other')).get()['remember'])
        self.assertFalse(AccessPreferences(self.store, Identity('other', 'employee')).get()['remember'])

    def test_pause_survives_restart_and_forgetting_clears_old_grants(self):
        self.access.save(remember=True, app_awareness=True, screen_vision=True)
        self.access.save(screen_vision=False)
        self.assertEqual(self.access.get(), {'remember': True, 'app_awareness': True, 'screen_vision': False})
        self.access.save(remember=False)
        self.access.save(remember=True)
        self.assertFalse(self.access.get()['app_awareness'])
        self.assertFalse(self.access.get()['screen_vision'])

    def test_consent_is_distinct_from_enabled_access_and_survives_pause(self):
        self.assertFalse(self.access.approved('screen_vision'))
        self.access.approve('screen_vision')
        self.assertTrue(self.access.approved('screen_vision'))
        self.assertFalse(self.access.get()['screen_vision'])
        self.access.save(remember=True, screen_vision=True)
        self.access.save(screen_vision=False)
        self.assertTrue(AccessPreferences(Store(self.temp.name), self.identity).approved('screen_vision'))
        self.assertFalse(self.access.get()['screen_vision'])

    def test_disabling_restoration_preserves_consent_but_not_enabled_flags(self):
        self.access.approve('app_awareness')
        self.access.save(remember=True, app_awareness=True)
        self.access.save(remember=False)
        self.assertTrue(self.access.approved('app_awareness'))
        self.assertFalse(self.access.get()['remember'])
        self.assertFalse(self.access.get()['app_awareness'])

    def test_legacy_remembered_enabled_access_counts_as_existing_consent(self):
        self.access.save(remember=True, app_awareness=True)
        self.assertTrue(self.access.approved('app_awareness'))
        self.assertFalse(self.access.approved('screen_vision'))

    def test_non_boolean_permission_cannot_be_saved(self):
        with self.assertRaises(ValueError):
            self.access.save(remember='yes')


class InstanceTests(unittest.TestCase):
    def test_second_process_is_refused_and_release_allows_relaunch(self):
        with tempfile.TemporaryDirectory() as directory:
            first = DesktopInstance(directory)
            script = 'from companion.instance import DesktopInstance; import sys; i=DesktopInstance(sys.argv[1]); i.close()'
            try:
                blocked = subprocess.run([sys.executable, '-c', script, directory], capture_output=True, text=True)
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn('already running', blocked.stderr)
                self.assertIn('build', self._metadata(directory))
            finally:
                first.close()
            allowed = subprocess.run([sys.executable, '-c', script, directory], capture_output=True, text=True)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    @staticmethod
    def _metadata(directory):
        from pathlib import Path
        return json.loads((Path(directory)/'desktop-instance.lock').read_text())

    def test_windows_byte_lock_backend_does_not_import_unix_fcntl(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from companion.instance import _lock, _unlock
        file = Mock()
        file.read.return_value = ''
        file.fileno.return_value = 42
        backend = SimpleNamespace(locking=Mock(), LK_NBLCK=1, LK_UNLCK=0)
        with patch.dict('sys.modules', {'msvcrt': backend}):
            _lock(file, windows=True)
            _unlock(file, windows=True)
        self.assertEqual(backend.locking.call_args_list[0].args, (42, 1, 1))
        self.assertEqual(backend.locking.call_args_list[1].args, (42, 0, 1))
        file.write.assert_called_once_with(' ')

    def test_source_build_marker_is_short_and_stable(self):
        self.assertEqual(build_id(), build_id())
        self.assertEqual(len(build_id()), 10)
