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

    def settle(self):
        """Let the pause after speaking pass (the mic must not hear A11y's own voice)."""
        import time
        from companion.desktop import LISTEN_AFTER_SPEAKING_MS
        deadline = time.monotonic()+LISTEN_AFTER_SPEAKING_MS/1000+0.2
        while time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.01)

    def test_wake_then_request_uses_text_path_and_listens_again(self):
        self.window.voice_woke('')
        self.assertTrue(self.window.voice_conversation)
        self.assertEqual(self.tts.spoken[-1], 'Yes?')
        self.assertEqual(self.voice.calls[-1], 'pause')  # not yet: the speakers are still finishing
        self.settle()
        self.assertEqual(self.voice.calls[-1], 'listen')
        self.window.voice_heard('How do I start onboarding?')
        self.wait_for_worker()
        self.assertEqual(self.provider.contexts[-1]['request'], 'How do I start onboarding?')
        self.assertIn('Follow the company onboarding instructions.', self.tts.spoken[-1])
        self.assertIn('pause', self.voice.calls)
        self.settle()
        self.assertEqual(self.voice.calls[-1], 'listen')

    def test_recognition_names_are_common_work_apps_and_running_ones(self):
        from unittest.mock import patch
        from companion.desktop import VOICE_NAMES
        running = {'available_apps': [{'name': 'Figma', 'bundle_id': 'com.figma'}, {'name': 'A11y', 'bundle_id': 'a11y'},
                                      {'name': 'Safari', 'bundle_id': 'com.apple.Safari'}]}
        with patch.object(self.window.desktop_monitor, 'context', return_value=running):
            self.window.load_voice_vocabulary()
        self.assertEqual(self.voice.vocabulary[:len(VOICE_NAMES)], VOICE_NAMES)
        self.assertIn('Figma', self.voice.vocabulary)
        self.assertNotIn('A11y', self.voice.vocabulary)
        self.assertEqual(self.voice.vocabulary.count('Safari'), 1)

    def test_request_spoken_with_wake_phrase_is_submitted(self):
        self.window.voice_woke('how do I start onboarding')
        self.wait_for_worker()
        self.assertEqual(self.provider.contexts[-1]['request'], 'how do I start onboarding')

    def test_farewell_returns_to_wake_word(self):
        self.window.voice_woke('')
        self.window.voice_heard('Thanks, that is all')
        self.assertFalse(self.window.voice_conversation)
        self.settle()
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
        self.window.say('On it.', [('Stop', 'computer:stop')])
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


@unittest.skipUnless(importlib.util.find_spec('PyQt6') and importlib.util.find_spec('numpy'), 'PyQt6 or numpy missing')
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
        # PyQt6's signature is requestPermission(permission, handler); a third argument raised
        # inside a Qt slot and aborted the app when voice was turned on.
        self.assertEqual(len(app.requestPermission.call_args.args), 2)
        from PyQt6.QtCore import QCoreApplication
        self.assertIn('handler', QCoreApplication.requestPermission.__doc__)
        self.assertNotIn('context', QCoreApplication.requestPermission.__doc__)

    def test_mac_app_reports_denied_instead_of_recording_silence(self):
        self.assertEqual(self.permission(self.Qt.PermissionStatus.Denied)[0], 'denied')
        self.assertEqual(self.permission(self.Qt.PermissionStatus.Granted)[0], 'granted')
        # From source the terminal owns the microphone prompt, so recording is still attempted.
        self.assertEqual(self.permission(self.Qt.PermissionStatus.Denied, frozen=False)[0], 'granted')

    def test_digital_silence_is_reported_as_blocked_only_after_a_second_check(self):
        source = self.mock.Mock()
        source.error.return_value = __import__('PyQt6.QtMultimedia', fromlist=['QAudio']).QAudio.Error.NoError
        self.listener.source, self.listener.heard_signal = source, False
        session = self.listener.session
        with self.mock.patch('companion.voice.QTimer.singleShot') as later:
            self.listener.check_microphone(session, final=False)  # a headset may still be switching on
        self.assertEqual(self.errors, [])
        later.assert_called_once()
        self.listener.check_microphone(session, final=True)
        self.assertIn('Microphone', self.errors[-1])
        self.assertIsNone(self.listener.source)

    def test_turning_voice_off_while_models_load_never_opens_the_microphone(self):
        # Reported: voice turned off during loading came back on, then reported a blocked mic.
        ready = []
        self.listener.ready.connect(lambda: ready.append(True))
        with self.mock.patch.object(self.voice, 'voice_available', return_value=True), \
                self.mock.patch.object(self.listener.executor, 'submit') as submit:
            self.listener.start()
        load, session = submit.call_args.args
        self.listener.stop()
        self.listener.transcriber = self.mock.Mock()
        load(session)
        self.assertEqual(ready, [])
        self.assertFalse(self.listener.open_microphone())  # a late permission answer cannot open it either
        self.assertIsNone(self.listener.source)

    def test_stale_checks_from_an_earlier_session_are_ignored(self):
        source = self.mock.Mock()
        self.listener.source, self.listener.heard_signal = source, False
        old = self.listener.session
        self.listener.session += 1
        self.listener.check_microphone(old, final=True)
        self.assertEqual(self.errors, [])


@unittest.skipUnless(importlib.util.find_spec('PyQt6'), 'PyQt6 missing')
class NaturalVoiceDownloadTests(unittest.TestCase):
    """Setup and turning voice on downloaded the same file at once; one rename then failed."""
    def test_simultaneous_downloads_fetch_each_file_once_and_both_succeed(self):
        import tempfile, threading, time
        from pathlib import Path
        from unittest import mock
        from companion import neural_voice
        fetched, errors = [], []
        def fake_retrieve(url, path, hook=None):
            fetched.append(url.rsplit('/', 1)[1])
            time.sleep(0.05)
            Path(path).write_bytes(b'model')
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch('urllib.request.urlretrieve', side_effect=fake_retrieve):
            folder = neural_voice.model_directory(directory)
            folder.mkdir(parents=True)
            (folder/'kokoro-v1.0.onnx.part').write_bytes(b'stale')
            def run():
                try:
                    neural_voice.download_models(directory)
                except Exception as error:
                    errors.append(error)
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(sorted(fetched), sorted([neural_voice.MODEL_FILE, neural_voice.VOICES_FILE]))
            self.assertTrue(neural_voice.neural_voice_available(directory) or not importlib.util.find_spec('kokoro_onnx'))
            self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([neural_voice.MODEL_FILE, neural_voice.VOICES_FILE]))


class HearingTests(unittest.TestCase):
    """Reported: it heard things nobody said, woke on other speech and cut the user off."""
    def segment(self, text, no_speech=0.0, logprob=-0.2):
        from types import SimpleNamespace
        return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob)

    def test_noise_turned_into_words_is_dropped(self):
        from companion.voice import heard_text
        self.assertEqual(heard_text([self.segment(' Open Teams.')]), 'Open Teams.')
        self.assertEqual(heard_text([self.segment(" I didn't have this case for too long, man.", no_speech=0.8, logprob=-0.9)]), '')
        self.assertEqual(heard_text([self.segment(' Thank you.')]), '')
        self.assertEqual(heard_text([self.segment(' something', logprob=-1.5)]), '')

    def test_hello_and_other_greetings_do_not_wake(self):
        self.assertIsNone(wake_split('Hello Ellie, how are you'))
        self.assertEqual(wake_split('Hey Ally open Teams'), 'open Teams')

    @unittest.skipUnless(importlib.util.find_spec('PyQt6') and importlib.util.find_spec('numpy'), 'PyQt6 or numpy missing')
    def test_wake_needs_the_accurate_model_to_agree(self):
        from PyQt6.QtWidgets import QApplication
        from companion.voice import VoiceListener, SPEECH_MODEL
        QApplication.instance() or QApplication([])
        heard = {'tiny.en': 'Hey Ally', SPEECH_MODEL: 'Hey, I lost it.'}
        class Fake:
            def transcribe(self, audio, name, prompt=None):
                return heard[name]
        listener = VoiceListener(transcriber=Fake())
        woke = []
        listener.woke.connect(woke.append)
        listener._transcribe(None, 'wake', listener.generation)
        self.assertEqual(woke, [])
        heard[SPEECH_MODEL] = 'Hey Ally, open Teams.'
        listener._transcribe(None, 'wake', listener.generation)
        self.assertEqual(woke, ['open Teams'])

    @unittest.skipUnless(importlib.util.find_spec('PyQt6') and importlib.util.find_spec('numpy'), 'PyQt6 or numpy missing')
    def test_a_one_second_pause_does_not_end_the_turn_and_app_names_guide_recognition(self):
        from PyQt6.QtWidgets import QApplication
        from companion.voice import VoiceListener
        QApplication.instance() or QApplication([])
        listener = VoiceListener(transcriber=object())
        listener.source = object()
        listener.listen()
        self.assertGreaterEqual(listener.segmenter.end_frames*FRAME/SAMPLE_RATE, 1.5)
        listener.vocabulary = ['Microsoft Teams', 'Mail']
        self.assertIn('Microsoft Teams', listener.prompt())
        # Reported: recognition "all over the place". The prompt had up to 60 installed apps led by
        # "Open", which made Whisper hear names and commands that were never said.
        listener.vocabulary = ['App %d' % number for number in range(60)]
        prompt = listener.prompt()
        self.assertEqual(prompt.count(','), 11)
        self.assertFalse(prompt.startswith('Open'))
        self.assertTrue(listener.prompt('Hey Ally.').startswith('Hey Ally. App 0, '))

    @unittest.skipUnless(importlib.util.find_spec('PyQt6'), 'PyQt6 missing')
    def test_natural_voice_queues_half_a_second_of_audio(self):
        # Reported: speech stuttered. Qt's default sink buffer ran dry whenever the app was busy.
        import tempfile
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication
        from companion import neural_voice
        QApplication.instance() or QApplication([])
        # Test machines have no audio device (Qt then ignores the size), so check the request itself.
        with tempfile.TemporaryDirectory() as folder, patch.object(neural_voice.NeuralVoice, '_engine'), \
                patch('PyQt6.QtMultimedia.QAudioSink') as sink:
            voice = neural_voice.NeuralVoice(folder)
            voice._ensure_sink()
            sink.return_value.setBufferSize.assert_called_once_with(neural_voice.SAMPLE_RATE)
            voice.executor.shutdown(wait=True)


@unittest.skipUnless(importlib.util.find_spec('PyQt6'), 'PyQt6 missing')
class ReplyStyleTests(unittest.TestCase):
    """Reported: 'Looks done. The goal to read the last email has been achieved.' sounds robotic."""
    def test_goal_status_filler_is_removed_and_the_answer_kept(self):
        from companion.desktop import brief
        self.assertEqual(brief('The goal to read the last email has been achieved. The email from Rockstar Games '
                               'with verification code 368229 is visible in the Mail app.'),
                         'The email from Rockstar Games with verification code 368229 is visible in the Mail app.')
        self.assertEqual(brief('The email from Rockstar Games is visible in the Mail app, and the goal is confirmed as completed.'),
                         'The email from Rockstar Games is visible in the Mail app.')
        self.assertEqual(brief('I set a timer for 5 minutes. The task is complete.'), 'I set a timer for 5 minutes.')
        self.assertEqual(brief('Goal achieved.'), 'Done.')
        self.assertEqual(brief('Your last email is from Rockstar Games: code 368229.'), 'Your last email is from Rockstar Games: code 368229.')
