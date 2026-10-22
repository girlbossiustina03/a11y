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
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
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


class CompanionPointer(QWidget):
    """A separate, click-through visual pointer; never moves the user's mouse."""
    def __init__(self):
        super().__init__()
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setFixedSize(100, 62)
        self.setWindowTitle('A11y companion pointer')
        self.setAccessibleName('A11y target pointer')
        self.animation = QPropertyAnimation(self, b'pos', self)
        self.animation.setDuration(350)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.target_point = None

    def point_at(self, geometry, x, y, label, *, reduced_motion=False):
        import math
        from PyQt6.QtCore import QPoint
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v < 1 for v in (x, y)):
            raise ValueError('The companion pointer needs an interior image coordinate.')
        destination = QPoint(geometry.x()+int(x*geometry.width()), geometry.y()+int(y*geometry.height()))
        self.animation.stop()
        self.target_point = destination
        self.setAccessibleDescription(label)
        if reduced_motion or not self.isVisible():
            self.move(destination)
        else:
            self.animation.setStartValue(self.pos())
            self.animation.setEndValue(destination)
            self.animation.start()
        self.show()
        self.raise_()
        self.update()
        self.timer.start(90000)

    def dismiss(self):
        self.animation.stop()
        self.timer.stop()
        self.hide()
        self.target_point = None

    def paintEvent(self, event):
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QPolygonF
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#09141e'), 2))
        painter.setBrush(QColor('#74cbff'))
        painter.drawPolygon(QPolygonF([QPointF(1, 1), QPointF(4, 29), QPointF(12, 22),
                                      QPointF(18, 34), QPointF(24, 31), QPointF(18, 19), QPointF(29, 18)]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#172531'))
        painter.drawRoundedRect(QRectF(26, 32, 66, 25), 12, 12)
        painter.setPen(QColor('#d5efff'))
        painter.drawText(QRectF(26, 32, 66, 25), Qt.AlignmentFlag.AlignCenter, 'A11y')
