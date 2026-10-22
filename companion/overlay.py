"""Click-through, expiring highlight. Coordinates use Qt's logical screen geometry."""
from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPainterPath
from PyQt6.QtWidgets import QWidget
from .models import Target


class GuidanceOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.target = None

    def guide(self, geometry, target):
        self.target = Target.parse(target)
        self.setAccessibleName('Highlighted interface target')
        self.setAccessibleDescription(self.target.label)
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
        # One quiet outline; descriptions remain in the companion's accessible reply.
        p.setBrush(QColor(255, 255, 255, 12))
        p.setPen(QPen(QColor('#f5f5f7'), 1.5))
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)


class CompanionPointer(QWidget):
    """A separate, click-through visual pointer; never moves the user's mouse."""
    def __init__(self):
        super().__init__()
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setFixedSize(28, 36)
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#303036'), 1.25, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor('#ffffff'))
        arrow = QPainterPath()
        arrow.moveTo(1, 1)
        arrow.lineTo(1, 25)
        arrow.lineTo(7.5, 19.5)
        arrow.lineTo(12.5, 31)
        arrow.lineTo(17, 29)
        arrow.lineTo(12, 18)
        arrow.lineTo(21, 18)
        arrow.closeSubpath()
        painter.drawPath(arrow)
