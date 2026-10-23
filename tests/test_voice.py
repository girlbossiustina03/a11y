import importlib.util
import unittest

from companion.voice import (FRAME, SAMPLE_RATE, Segmenter, is_farewell, is_no, is_yes, match_choice,
                             speakable, wake_split)


class WakePhraseTests(unittest.TestCase):
    def test_wake_phrase_variants(self):
        for heard in ('Hey Ally.', 'hey allie', 'Hey, Alley!', 'Hi Ally', 'Okay Ally', 'hey ali'):
            self.assertEqual(wake_split(heard), '', heard)

    def test_request_after_wake_phrase(self):
        self.assertEqual(wake_split('Hey Ally. Open Settings.'), 'Open Settings')
        self.assertEqual(wake_split('hey ally, close discord please'), 'close discord please')

    def test_ordinary_speech_does_not_wake(self):
        for heard in ('Really nice weather', 'I told Ally about it', 'Hey Alexa', 'hey', '', 'Totally fine'):
            self.assertIsNone(wake_split(heard), heard)


class ReplyTests(unittest.TestCase):
    def test_yes_no_and_farewell(self):
        for text in ('Yes', 'yes please', 'Yeah, do it.', 'Go ahead', 'confirm'):
            self.assertTrue(is_yes(text), text)
        for text in ('yes but open teams instead', 'Open Teams', 'no'):
            self.assertFalse(is_yes(text), text)
        for text in ('No', 'cancel that', "don't", 'Never mind'):
            self.assertTrue(is_no(text), text)
        for text in ('Goodbye', 'Thanks, that’s all', "okay that's all", 'Stop listening', 'bye Ally'):
            self.assertTrue(is_farewell(text.replace('’', "'")), text)
        self.assertFalse(is_farewell('Open the goodbye card template'))

    def test_spoken_choice_matching(self):
        choices = [('Outlook (classic)', 'a'), ('Outlook (new)', 'b')]
        self.assertEqual(match_choice('the new one, outlook new', choices), ('Outlook (new)', 'b'))
        self.assertEqual(match_choice('the second', choices), ('Outlook (new)', 'b'))
        self.assertIsNone(match_choice('outlook', choices))
        self.assertEqual(match_choice('skip this question', [('Skip this question', 'skip'), ('Go back', 'back')]),
                         ('Skip this question', 'skip'))

    def test_speakable_text(self):
        self.assertEqual(speakable('**Done!** See https://example.com [1] now'), 'Done! See a link now')


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'voice extras (requirements-voice.txt) not installed')
class SegmenterTests(unittest.TestCase):
    def frames(self, amplitude, seconds):
        import numpy as np
        count = int(seconds*SAMPLE_RATE)
        tone = np.sin(np.arange(count)*2*np.pi*220/SAMPLE_RATE)*amplitude
        return tone.astype(np.int16)

    def test_utterance_is_cut_at_silence(self):
        segmenter = Segmenter(end_silence=0.6)
        quiet, speech = self.frames(60, 1.0), self.frames(6000, 1.2)
        self.assertEqual(segmenter.feed(quiet), [])
        self.assertEqual(segmenter.feed(speech), [])
        result = segmenter.feed(self.frames(60, 1.0))
        self.assertEqual(len(result), 1)
        self.assertGreater(len(result[0]), 1.1*SAMPLE_RATE)
        self.assertLessEqual(abs(result[0]).max(), 1.0)

    def test_clicks_and_steady_noise_are_ignored(self):
        segmenter = Segmenter()
        self.assertEqual(segmenter.feed(self.frames(60, 1.0)), [])
        self.assertEqual(segmenter.feed(self.frames(6000, FRAME*2/SAMPLE_RATE)), [])   # 60 ms click
        self.assertEqual(segmenter.feed(self.frames(60, 1.0)), [])

    def test_long_speech_is_split_at_the_limit(self):
        segmenter = Segmenter(max_seconds=2)
        self.assertEqual(len(segmenter.feed(self.frames(6000, 4.5))), 2)



HAS_QT = importlib.util.find_spec('PyQt6') is not None


class FakeTTS:
    """Speaks instantly and reports Ready, like a finished utterance."""
    class State:
        def __init__(self, name):
            self.name = name

    def __init__(self, window):
        self.window, self.spoken = window, []

    def state(self):
        return self.State('Ready')

    def enqueue(self, text):
        self.spoken.append(text)
        self.window.speech_state(self.State('Ready'))

    def say(self, text):
        self.enqueue(text)

    def stop(self):
        pass


class FakeListener:
    def __init__(self):
        self.source, self.mode, self.calls = object(), 'wake', []

    def pause(self):
        self.calls.append('pause')

    def listen(self):
        self.mode = 'conversation'
        self.calls.append('listen')

    def wait_for_wake(self):
        self.mode = 'wake'
        self.calls.append('wake')

    def stop(self):
        self.mode = 'off'


@unittest.skipUnless(HAS_QT, 'Install requirements.txt to run native Qt checks')
class VoiceConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        import tempfile
        from companion.desktop import CompanionWindow
        from companion.models import Identity
        from companion.service import Companion
        from companion.storage import Store
        from test_core import RecordingProvider
        self.temp = tempfile.TemporaryDirectory()
        self.provider = RecordingProvider()
        self.service = Companion(Store(self.temp.name), Identity('company', 'employee'), self.provider)
        self.window = CompanionWindow(self.service)
        self.window.start_companion()
        self.tts = self.window.tts = FakeTTS(self.window)
        self.voice = self.window.voice = FakeListener()
        self.qt.processEvents()

    def tearDown(self):
        if self.window.worker:
            self.window.worker.wait(3000)
        self.window.context_timer.stop()
        self.window.mascot.close()
        self.window.overlay.close()
        self.window.pointer.close()
        self.window.quitting = True
        self.window.close()
        self.window.deleteLater()
        self.qt.processEvents()
        self.temp.cleanup()

    def wait_for_worker(self):
        import time
        deadline = time.monotonic()+5
        while self.window.worker and self.window.worker.isRunning() and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.01)
        for _ in range(5):
            self.qt.processEvents()

    def test_wake_then_request_uses_text_path_and_listens_again(self):
        self.window.voice_woke('')
        self.assertTrue(self.window.voice_conversation)
        self.assertEqual(self.tts.spoken[-1], 'Yes? I’m listening.')
        self.assertEqual(self.voice.calls[-1], 'listen')
        self.window.voice_heard('How do I start onboarding?')
        self.wait_for_worker()
        self.assertEqual(self.provider.contexts[-1]['request'], 'How do I start onboarding?')
        self.assertIn('Follow the company onboarding instructions.', self.tts.spoken[-1])
        self.assertIn('pause', self.voice.calls)
        self.assertEqual(self.voice.calls[-1], 'listen')

    def test_request_spoken_with_wake_phrase_is_submitted(self):
        self.window.voice_woke('how do I start onboarding')
        self.wait_for_worker()
        self.assertEqual(self.provider.contexts[-1]['request'], 'how do I start onboarding')

    def test_farewell_returns_to_wake_word(self):
        self.window.voice_woke('')
        self.window.voice_heard('Thanks, that is all')
        self.assertFalse(self.window.voice_conversation)
        self.assertEqual(self.voice.calls[-1], 'wake')
        self.assertIn('Hey Ally', self.tts.spoken[-1])

    def test_spoken_yes_and_no_answer_confirmations(self):
        from unittest.mock import patch
        self.window.voice_conversation = True
        proposal = {'type': 'quit_app', 'bundle_id': 'notepad.exe', 'label': 'Quit Notepad'}
        self.window.pending_desktop_action = dict(proposal)
        self.window.mascot_home('Ready to quit Notepad. Confirm below.')
        self.assertIn('Say yes to quit Notepad, or no to cancel.', self.tts.spoken[-1])
        with patch.object(self.window, 'execute_desktop_action') as execute:
            self.window.voice_heard('Yes, please.')
        execute.assert_called_once()
        self.window.pending_desktop_action = dict(proposal)
        self.window.mascot_home('Ready to quit Notepad. Confirm below.')
        with patch.object(self.window, 'execute_desktop_action') as execute:
            self.window.voice_heard('No, cancel that.')
        execute.assert_not_called()
        self.assertIsNone(self.window.pending_desktop_action)
        self.assertEqual(self.tts.spoken[-1], 'Okay, I won’t do that.')

    def test_nothing_is_spoken_outside_a_voice_conversation(self):
        self.window.say('Plain text reply')
        self.assertEqual(self.tts.spoken, [])

    def test_task_progress_is_quiet_and_yes_never_stops_a_task(self):
        self.window.voice_conversation = True
        self.window.say('Step 2 · Looking at the screen…', [('Stop', 'computer:stop')])
        self.window.say('Sent: Open Teams. Checking the result…', [('Stop', 'computer:stop')])
        self.window.say('Pressing 5…', [('Stop', 'computer:stop')])
        self.assertEqual(self.tts.spoken, [])
        self.window.say('On it: open the report', [('Stop', 'computer:stop')])
        self.assertIn('Say stop to stop the task.', self.tts.spoken[-1])
        self.assertNotIn('Say yes', self.tts.spoken[-1])

    def test_voice_choice_is_remembered_separately(self):
        access = self.window.access_preferences
        self.assertFalse(access.voice_enabled())
        access.set_voice(True)
        self.assertTrue(access.voice_enabled())
        self.assertEqual(set(access.get()), {'remember', 'app_awareness', 'screen_vision'})
        with self.assertRaises(ValueError):
            access.set_voice('yes')



@unittest.skipUnless(HAS_QT, 'Install requirements.txt to run native Qt checks')
class NaturalVoiceTests(unittest.TestCase):
    def test_reply_is_split_into_short_sentences(self):
        from companion.neural_voice import split_sentences
        self.assertEqual(split_sentences('Hi! I opened Teams.\nYou have two messages?'),
                         ['Hi!', 'I opened Teams.', 'You have two messages?'])
        long = 'one, '*100
        self.assertTrue(all(len(chunk) <= 280 for chunk in split_sentences(long)))
        self.assertEqual(split_sentences('  '), [])

    def test_missing_model_keeps_the_system_voice(self):
        import tempfile
        from unittest import mock
        from companion.neural_voice import neural_voice_available
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict('sys.modules', {'kokoro_onnx': mock.Mock()}):
            self.assertFalse(neural_voice_available(directory))

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'voice extras (requirements-voice.txt) not installed')
    def test_states_stay_busy_until_the_last_sentence_played(self):
        import tempfile
        from unittest import mock
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from companion.neural_voice import NeuralVoice
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(NeuralVoice, '_engine'), \
                mock.patch.object(NeuralVoice, '_play_next', autospec=True,
                                  side_effect=lambda self: self._set_state('Speaking' if self.queue else ('Synthesizing' if self.pending else 'Ready'))):
            voice = NeuralVoice(directory)
            voice.executor.submit = lambda *args: None      # generation is driven by hand below
            states = []
            voice.stateChanged.connect(lambda state: states.append(state.name))
            voice.enqueue('First sentence. Second sentence.')
            self.assertEqual(voice.pending, 2)
            voice._queue_audio(voice.generation, b'\0\0')
            voice.queue.clear(); voice._play_next()
            self.assertEqual(states[-1], 'Synthesizing')       # one sentence still being generated
            voice._queue_audio(voice.generation, b'\0\0')
            voice.queue.clear(); voice._play_next()
            self.assertEqual(states[-1], 'Ready')
            voice.enqueue('Old reply.')
            voice.stop()
            voice._queue_audio(voice.generation-1, b'\0\0')   # audio from a stopped reply is dropped
            self.assertEqual(voice.queue, [])


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(importlib.util.find_spec('PyQt6'), 'PyQt6 missing')
class MicrophonePermissionTests(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from companion import voice
        self.mock, self.Qt, self.voice = mock, Qt, voice
        self.app = QApplication.instance() or QApplication([])
        self.listener = voice.VoiceListener(transcriber=object())
        self.errors = []
        self.listener.failed.connect(self.errors.append)

    def permission(self, state, frozen=True):
        app = self.mock.Mock()
        app.checkPermission.return_value = state
        with self.mock.patch.object(self.voice.sys, 'platform', 'darwin'), \
                self.mock.patch('PyQt6.QtCore.QCoreApplication.instance', return_value=app), \
                self.mock.patch.object(self.voice.paths, 'frozen', return_value=frozen):
            return self.listener.microphone_permission(), app

    def test_mac_app_asks_before_first_listen(self):
        answer, app = self.permission(self.Qt.PermissionStatus.Undetermined)
        self.assertEqual(answer, 'asking')
        app.requestPermission.assert_called_once()

    def test_mac_app_reports_denied_instead_of_recording_silence(self):
        self.assertEqual(self.permission(self.Qt.PermissionStatus.Denied)[0], 'denied')
        self.assertEqual(self.permission(self.Qt.PermissionStatus.Granted)[0], 'granted')
        # From source the terminal owns the microphone prompt, so recording is still attempted.
        self.assertEqual(self.permission(self.Qt.PermissionStatus.Denied, frozen=False)[0], 'granted')

    def test_digital_silence_is_reported_as_blocked(self):
        source = self.mock.Mock()
        source.error.return_value = __import__('PyQt6.QtMultimedia', fromlist=['QAudio']).QAudio.Error.NoError
        self.listener.source, self.listener.heard_signal = source, False
        self.listener.check_microphone()
        self.assertIn('Microphone', self.errors[-1])
        self.assertIsNone(self.listener.source)
