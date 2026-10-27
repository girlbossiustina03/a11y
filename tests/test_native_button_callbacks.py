import gc
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import weakref
from unittest.mock import Mock
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget
from companion.mac_window import weak_callback
from companion.mascot import CharacterButton, Mascot


class NativeCallbacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_qt_close_method_can_be_bound_without_retaining_widget(self):
        widget = QWidget()
        widget.show()
        callback = weak_callback(widget.close)
        callback()()
        self.assertFalse(widget.isVisible())
        reference = weakref.ref(widget)
        del widget
        gc.collect()
        self.assertIsNone(reference())
        self.assertIsNone(callback())

    def test_python_bound_method_still_works(self):
        class Owner:
            def close(self):
                self.closed = True
        owner = Owner()
        weak_callback(owner.close)()()
        self.assertTrue(owner.closed)

    def test_native_control_click_does_not_open_chat_on_face_or_margin(self):
        def event(kind):
            return QMouseEvent(kind, QPointF(10,10), QPointF(10,10), Qt.MouseButton.LeftButton,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
        owner = Mock(native=True, drag_position=None)
        Mascot.mousePressEvent(owner, event(QEvent.Type.MouseButtonPress))
        Mascot.mouseReleaseEvent(owner, event(QEvent.Type.MouseButtonRelease))
        owner.open_chat_from_user.assert_not_called()
        face = Mock(owner=Mock(native=True))
        CharacterButton.mousePressEvent(face, event(QEvent.Type.MouseButtonPress))
        CharacterButton.mouseReleaseEvent(face, event(QEvent.Type.MouseButtonRelease))
        face.click.assert_not_called()
