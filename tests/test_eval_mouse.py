import ctypes as C
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from eval_mouse import right_click


class TestMouseStimulus(unittest.TestCase):
    def libraries(self, owner):
        ax,cg,cf = Mock(),Mock(),Mock()
        ax.AXUIElementCreateSystemWide.return_value = 11
        def hit(system,x,y,result):
            C.cast(result,C.POINTER(C.c_void_p))[0] = 12
            return 0
        def pid(hit,result):
            C.cast(result,C.POINTER(C.c_int))[0] = owner
            return 0
        ax.AXUIElementCopyElementAtPosition.side_effect = hit
        ax.AXUIElementGetPid.side_effect = pid
        cg.CGEventCreateMouseEvent.side_effect = [13,14]
        return ax,cg,cf

    def test_uses_real_right_events_only_on_the_owned_process(self):
        libs = self.libraries(42)
        with patch('eval_mouse.time.sleep'):
            right_click(42,100,200,libraries=libs)
        cg = libs[1]
        self.assertEqual([c.args[1] for c in cg.CGEventCreateMouseEvent.call_args_list],[3,4])
        self.assertEqual([c.args for c in cg.CGEventPost.call_args_list],[(0,13),(0,14)])

    def test_changed_owner_sends_no_mouse_event(self):
        libs = self.libraries(99)
        with self.assertRaisesRegex(RuntimeError,'owned companion'):
            right_click(42,100,200,libraries=libs)
        libs[1].CGEventPost.assert_not_called()
