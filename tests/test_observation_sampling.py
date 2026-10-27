from copy import deepcopy
import threading
import unittest
from unittest.mock import Mock
from companion.desktop_context import DesktopContext
from companion.computer_task import observe_desktop


class ObservationSampling(unittest.TestCase):
    def context(self,bridge):
        context=DesktopContext(bridge,clock=lambda:100)
        context.enabled=True
        return context

    def test_detailed_snapshot_survives_a_subsequent_background_poll(self):
        detailed=dict(status='available',app={'bundle_id':'com.apple.finder'},
                      finder={'target':'/tmp/owned/Reports'},targets=[{'label':'Report'}])
        bridge=Mock(sample_targets=Mock(return_value=deepcopy(detailed)),
                    sample=Mock(return_value=dict(status='available',app={'bundle_id':'com.apple.finder'})))
        context=self.context(bridge)
        captured=observe_desktop(context,targets=True)
        context.collect_once()
        self.assertEqual(captured['finder']['target'],'/tmp/owned/Reports')
        self.assertNotIn('finder',context.context())

    def test_collectors_are_serialized_but_access_can_be_disabled_during_collection(self):
        entered,release,targets=threading.Event(),threading.Event(),threading.Event()
        def basic():
            entered.set()
            release.wait(2)
            return dict(status='available')
        def detailed(bundle):
            targets.set()
            return dict(status='available',targets=[])
        context=self.context(Mock(sample=basic,sample_targets=detailed))
        first=threading.Thread(target=context.collect_once)
        second=threading.Thread(target=lambda:context.collect_once(targets=True))
        first.start()
        try:
            self.assertTrue(entered.wait(1))
            second.start()
            self.assertFalse(targets.wait(.03))
            context.disable()
            self.assertFalse(context.enabled)
        finally:
            release.set();first.join(2)
            if second.ident is not None:second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(context.context()['status'],'off')

    def test_legacy_bridge_collectors_fall_back_to_their_context(self):
        desktop=Mock(collect_once=Mock(return_value=None),context=Mock(return_value={'status':'available'}))
        self.assertEqual(observe_desktop(desktop,targets=True),{'status':'available'})
