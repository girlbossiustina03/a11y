"""Click-through, expiring highlight. Coordinates use Qt's logical screen geometry."""
from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget
from .models import Target


class GuidanceOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.target = None

    def guide(self, geometry, target):
        self.target = Target.parse(target)
        self.setGeometry(geometry)
        self.show()
        self.update()
        self.timer.start(10000)

    def paintEvent(self, event):
        if not self.target:
            return
        t = self.target
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(t.x*self.width(), t.y*self.height(), t.width*self.width(), t.height*self.height())
        p.setPen(QPen(QColor('#101c23'), 8))
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(QPen(QColor('#ffd166'), 4))
        p.drawRoundedRect(rect, 6, 6)
        label = QRectF(max(8, min(rect.x(), self.width()-370)),
                       max(8, rect.y()-72), min(360, self.width()-16), 64)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#172f33'))
        p.drawRoundedRect(label, 8, 8)
        p.setPen(QColor('white'))
        p.drawText(label.adjusted(10, 4, -10, -4), Qt.TextFlag.TextWordWrap, t.label)
