"""Arithmetic in code: direct answers, and exact Calculator key presses when asked."""
import os
os.environ.setdefault('A11Y_WEB_ANSWERS', '0')  # tests never look things up online unless a test turns it on
from copy import deepcopy
import time
import unittest
from unittest.mock import Mock
from companion.arithmetic import answer, evaluate, keypad
from companion.computer_task import ComputerTask
from companion.desktop_context import DesktopContext
from test_core import CompanionFixture
from test_desktop_context import FakeBridge


def calculator(labels, platform='macOS'):
    return {'status': 'available', 'platform': platform, 'accessibility': 'granted',
            'app': {'name': 'Calculator', 'bundle_id': 'com.apple.calculator', 'pid': 7},
            'window': {'title': 'Calculator', 'bounds': {'x': 0, 'y': 0, 'width': 300, 'height': 400}},
            'available_apps': [{'name': 'Calculator', 'bundle_id': 'com.apple.calculator'}],
            'controls': [{'id': 'control-%d' % i, 'label': label, 'role': 'AXButton', 'enabled': True,
                          'bounds': {'x': 10+i*30, 'y': 300, 'width': 28, 'height': 28}} for i, label in enumerate(labels)]}


class ArithmeticTests(unittest.TestCase):
    def test_plain_arithmetic_is_answered(self):
        self.assertEqual(answer('5 + 5?'), '5 + 5 = 10')
        self.assertEqual(answer('what is 12 times 3'), '12 × 3 = 36')
        self.assertEqual(answer('whats 7-10'), '7-10 = -3')
        for text in ('what is love', 'where is china', 'open calculator', '5', 'call 555 1234'):
            self.assertIsNone(answer(text), text)

    def test_evaluator_refuses_anything_but_arithmetic(self):
        for expr in ('__import__("os")', '2**100000', 'a+1', '[1]'):
            with self.assertRaises((ValueError, SyntaxError)):
                evaluate(expr)


class ArithmeticServiceTests(CompanionFixture, unittest.TestCase):
    def test_five_plus_five_needs_no_model_app_or_task(self):
        # Live: "5 + 5?" opened Calculator and pressed 5 twice.
        self.app.desktop_context = DesktopContext(FakeBridge(), clock=lambda: 100)
        self.app.provider = Mock()
        result = self.app.ask('5 + 5?')
        self.assertEqual(result['message'], '5 + 5 = 10')
        self.assertIsNone(result['desktop_action'])
        self.app.provider.interpret_request.assert_not_called()
        self.app.provider.complete_structured.assert_not_called()


class CalculatorKeypadTests(unittest.TestCase):
    def run_task(self, labels, platform='macOS'):
        bridge = FakeBridge()
        bridge.value = calculator(labels, platform)
        desktop = DesktopContext(bridge, clock=lambda: 100)
        desktop.enabled = True
        vision, provider = Mock(enabled=True, generation=0), Mock()
        task = ComputerTask('open calculator and add 15 + 5', automatic=True, goal_mode='inspect')
        pressed = []
        for _ in range(10):
            step = task.propose(desktop, vision, provider, {'x': 0, 'y': 0})
            if step['status'] != 'action':
                break
            pressed.append(step['action']['label'])
            task.record({'type': 'press_control', 'label': step['action']['label'], 'status': 'submitted'})
        return task, step, pressed, provider, vision

    def test_mac_keys_are_pressed_exactly_without_the_model(self):
        task, step, pressed, provider, vision = self.run_task(['All Clear', '1', '5', 'Add', 'Equals', '7'])
        self.assertEqual(pressed, ['All Clear', '1', '5', 'Add', '5', 'Equals'])
        self.assertEqual(step['status'], 'done')
        self.assertIn('The answer is 20', step['message'])
        provider.complete_structured.assert_not_called()
        vision.capture.assert_not_called()

    def test_windows_calculator_names_are_understood(self):
        task, step, pressed, provider, _ = self.run_task(['Clear', 'One', 'Five', 'Plus', 'Equals'], 'Windows')
        self.assertEqual(pressed, ['Clear', 'One', 'Five', 'Plus', 'Five', 'Equals'])
        self.assertEqual(step['status'], 'done')

    def test_unknown_keypad_hands_over_to_the_model(self):
        bridge = FakeBridge()
        bridge.value = calculator(['Mystery'])
        desktop = DesktopContext(bridge, clock=lambda: 100)
        desktop.enabled = True
        vision = Mock(enabled=True, generation=0)
        vision.capture.side_effect = lambda *a, **k: {'image_data': 'data:image/png;base64,x', 'display_id': 1,
            'screen': {'x': 0, 'y': 0, 'width': 300, 'height': 400}, 'captured_monotonic': time.monotonic()}
        provider = Mock()
        provider.complete_structured.return_value = {'status': 'needs_user', 'message': 'Unknown layout.', 'risk': 'navigation', 'action': None}
        task = ComputerTask('open calculator and add 2 + 2', automatic=True, goal_mode='inspect')
        self.assertEqual(task.propose(desktop, vision, provider, {'x': 0, 'y': 0})['status'], 'needs_user')
        provider.complete_structured.assert_called()
        self.assertIsNone(task.keypad)

    def test_keypad_only_for_explicit_calculator_goals(self):
        self.assertIsNone(keypad('add 5 + 5'))
        self.assertEqual(keypad('open calculator and add 5 + 5')[0], ['clear', '5', '+', '5', '='])
        self.assertIsNone(keypad('open calculator and compute (2+3)*4'))  # left to the model


if __name__ == '__main__':
    unittest.main()
