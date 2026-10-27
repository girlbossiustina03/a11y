"""Bounded conversational memory and reference resolution, without apps or models."""
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from companion.models import Identity
from companion.service import Companion
from companion.storage import Store


class MemoryContextTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.provider = Mock(cloud=False)
        self.provider.complete_structured.return_value = {'message':'The code was cobalt-5821.'}
        self.app = Companion(Store(self.folder.name),Identity('test','memory'),self.provider)

    def fill(self):
        self.app.remember('user','My expedition code is cobalt-5821.')
        self.app.remember('assistant','I will remember it for this conversation.')
        for i in range(12):
            self.app.remember('user','Intervening request %d'%i)
            self.app.remember('assistant','Result %d'%i,private=i%2==0)

    def test_fact_survives_twelve_intervening_exchanges(self):
        self.fill()
        self.app.converse('What code did I tell you earlier?',{})
        messages=self.provider.complete_structured.call_args.args[1]
        self.assertIn('cobalt-5821',json.dumps(messages))
        self.assertLessEqual(len(self.app.conversation),64)

    def test_extended_memory_keeps_existing_cloud_and_pause_privacy(self):
        self.fill()
        self.app.remember('assistant','private screen detail',private=True)
        self.provider.cloud=True
        self.app.converse('What did we discuss?',{})
        messages=json.dumps(self.provider.complete_structured.call_args.args[1])
        self.assertNotIn('private screen detail',messages)
        self.assertIn('cobalt-5821',messages)
        self.app.forget_desktop()
        self.assertFalse(any(t['private'] for t in self.app.conversation))
        self.assertIn('cobalt-5821',json.dumps(list(self.app.conversation)))

    def test_reference_resolver_can_select_older_task_without_screen_memory(self):
        with patch.object(self.app,'route_request',return_value={'operation':'computer_task','target':'fixture','app_name':''}):
            for request in ['Open the Expedition folder in Finder.']+['Open test pane %d'%i for i in range(11)]:
                self.app.prepare_request(request)
        self.app.remember('assistant','private screen detail',private=True)
        self.provider.complete_structured.reset_mock()
        self.provider.complete_structured.return_value={'request':'Open the Expedition folder in Finder.'}
        resolved=self.app.resolve_follow_up('Return to the folder from earlier in our conversation.')
        self.assertEqual(resolved,'Open the Expedition folder in Finder.')
        payload=json.loads(self.provider.complete_structured.call_args.args[1][0]['content'])
        self.assertIn('Open the Expedition folder in Finder.',json.dumps(payload))
        self.assertNotIn('private screen detail',json.dumps(payload))
        self.assertEqual(payload['last_task'],'Open test pane 10')

    def test_memory_prompt_is_bounded_even_with_long_turns(self):
        for i in range(100):
            self.app.remember('user',('%03d '%i)+'x'*590)
            self.app.remember('assistant','y'*590)
        self.app.converse('What did I just say?',{})
        messages=self.provider.complete_structured.call_args.args[1]
        self.assertLessEqual(sum(len(m['content']) for m in messages[:-2]),18000)
        self.assertIn('099 ',json.dumps(messages))


if __name__ == '__main__':
    unittest.main()
