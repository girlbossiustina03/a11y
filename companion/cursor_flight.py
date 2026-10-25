"""Her cursor: when she clicks, her window melts into a pointer, the pointer flies to the target on a
curved path (different every time), a ripple marks the click, and it grows back into her window
beside the point. All of it is painted in one click-through overlay over the screen; it never moves
the user's mouse and never takes a click (the real click is sent when the flight ends)."""
import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

MORPH_MS, CLICK_MS = 230, 170
CURSOR = 26  # the pointer's height in points


def flight_path(start, end, rng=random):
    """A cubic curve from start to end that bends a different way each time, as a hand would.
    Returns the four control points; the ends are exact."""
    dx, dy = end.x()-start.x(), end.y()-start.y()
    distance = math.hypot(dx, dy) or 1.0
    nx, ny = -dy/distance, dx/distance  # across the line
    bend = distance*rng.uniform(0.12, 0.32)*rng.choice((-1, 1))
    # Usually one arc, sometimes a gentle S.
    second = bend*(rng.uniform(0.4, 1.0) if rng.random() < 0.75 else -rng.uniform(0.3, 0.7))
    a, b = rng.uniform(0.2, 0.38), rng.uniform(0.62, 0.8)
    p1 = QPointF(start.x()+dx*a+nx*bend, start.y()+dy*a+ny*bend)
    p2 = QPointF(start.x()+dx*b+nx*second, start.y()+dy*b+ny*second)
    return start, p1, p2, end


def bezier(points, t):
    p0, p1, p2, p3 = points
    u = 1-t
    return QPointF(u*u*u*p0.x()+3*u*u*t*p1.x()+3*u*t*t*p2.x()+t*t*t*p3.x(),
                   u*u*u*p0.y()+3*u*u*t*p1.y()+3*u*t*t*p2.y()+t*t*t*p3.y())


def ease(t):
    """Slow start and end, no overshoot (she never overshoots, owner)."""
    return 4*t*t*t if t < 0.5 else 1-(-2*t+2)**3/2


def travel_ms(start, end):
    return int(max(320, min(850, 260+math.hypot(end.x()-start.x(), end.y()-start.y())*0.55)))


def pointer_path(tip, size=CURSOR):
    """The rounded, tail-less arrowhead (iPad / Codex style): tip at `tip`, pointing up and to the left,
    two equal wings around an axis tilted 30° from vertical, and a soft dip at the back."""
    s = size/22.0
    def toward(degrees, length):
        angle = math.radians(degrees)
        return QPointF(tip.x()+math.sin(angle)*length*s, tip.y()+math.cos(angle)*length*s)
    left, right = toward(8, 20.0), toward(52, 20.0)
    dip = toward(30, 11.5)
    path = QPainterPath(tip)
    path.lineTo(left)
    path.quadTo(dip, right)
    path.closeSubpath()
    return path


class CursorFlight(QWidget):
    """One flight at a time, over the screen the flight is on."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setWindowTitle('A11y cursor')
        self.setAccessibleName('A11y cursor')
        self.fill, self.edge, self.card = QColor('#7BCACD'), QColor('#E0E0E0'), QColor('#191D27')
        self.snapshot = None
        self.phase, self.progress = None, 0.0
        self.start_rect = self.end_rect = QRectF()
        self.points = None
        self.animation = None
        self.done = None

    def set_colors(self, palette):
        """Her theme: the pointer in her accent, see-through, with her text colour as its edge."""
        self.fill, self.edge, self.card = QColor(palette.cyan), QColor(palette.text), QColor(palette.background)

    def fly(self, screen_rect, start_rect, snapshot, target, end_rect, done):
        """start_rect / end_rect: her window before and after (global); target: the click point (global).
        `done` runs once, after she has re-formed beside the point."""
        self.stop()
        self.setGeometry(screen_rect)
        origin = QPointF(screen_rect.topLeft())
        self.start_rect = QRectF(start_rect).translated(-origin)
        self.end_rect = QRectF(end_rect).translated(-origin)
        self.snapshot, self.done = snapshot, done
        tip = QPointF(target)-origin
        self.points = flight_path(self.start_rect.center(), tip)
        self.show()
        self.raise_()
        self.run('melt', MORPH_MS, lambda: self.run('travel', travel_ms(self.points[0], tip),
                                                     lambda: self.run('click', CLICK_MS, lambda: self.run('form', MORPH_MS, self.finish))))

    def run(self, phase, duration, then):
        self.phase, self.progress = phase, 0.0
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration)
        animation.valueChanged.connect(self.step)
        animation.finished.connect(then)
        self.animation = animation
        animation.start()

    def step(self, value):
        self.progress = float(value)
        self.update()

    def finish(self):
        done, self.done = self.done, None
        self.phase, self.animation = None, None
        self.hide()
        if done:
            done()

    def stop(self):
        """Cut a flight short (Stop pressed); its `done` does not run."""
        if self.animation is not None:
            self.animation.stop()
            self.animation = None
        self.done, self.phase = None, None
        self.hide()

    def flying(self):
        return self.phase is not None

    # Painting

    def paintEvent(self, event):
        if self.phase is None or self.points is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.progress
        if self.phase == 'melt':   # her window shrinks into the pointer where she stood
            self.paint_window(p, self.shrink(self.start_rect, self.points[0], ease(t)), 1-t)
            self.paint_pointer(p, self.points[0], min(1.0, t*1.6), 0.5+0.5*t)
        elif self.phase == 'travel':
            self.paint_pointer(p, bezier(self.points, ease(t)), 1.0, 1.0)
        elif self.phase == 'click':  # a ripple where it clicks, the pointer pressing in
            tip = self.points[3]
            ring = QColor(self.fill)
            ring.setAlphaF(0.55*(1-t))
            p.setPen(QPen(ring, 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            radius = 6+18*t
            p.drawEllipse(tip, radius, radius)
            self.paint_pointer(p, tip, 1.0, 1.0-0.12*math.sin(math.pi*t))
        elif self.phase == 'form':   # and grows back into her window beside the point
            self.paint_window(p, self.shrink(self.end_rect, self.points[3], 1-ease(t)), t)
            self.paint_pointer(p, self.points[3], 1-t, 1.0-0.5*t)

    @staticmethod
    def shrink(rect, point, amount):
        """rect pulled toward point: 0 is the rect, 1 a small square at the point."""
        small = QRectF(point.x()-8, point.y()-8, 16, 16)
        lerp = lambda a, b: a+(b-a)*amount
        return QRectF(lerp(rect.x(), small.x()), lerp(rect.y(), small.y()),
                      lerp(rect.width(), small.width()), lerp(rect.height(), small.height()))

    def paint_window(self, p, rect, opacity):
        if opacity <= 0.01 or rect.width() < 2:
            return
        p.save()
        p.setOpacity(max(0.0, min(1.0, opacity)))
        radius = min(10.0, rect.width()/4, rect.height()/4)
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        p.fillPath(clip, self.card)
        if self.snapshot is not None and not self.snapshot.isNull():
            p.setClipPath(clip)
            p.drawPixmap(rect, self.snapshot, QRectF(self.snapshot.rect()))
            p.setClipping(False)
        edge = QColor(self.edge)
        edge.setAlphaF(0.25)
        p.setPen(QPen(edge, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.restore()

    def paint_pointer(self, p, tip, opacity, scale):
        if opacity <= 0.01:
            return
        p.save()
        p.setOpacity(max(0.0, min(1.0, opacity)))
        # One rounded outline (the arrowhead grown by a round-joined stroke), filled once: see-through
        # without a darker core, with her text colour as a thin rim.
        from PyQt6.QtGui import QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(3.0*scale*CURSOR/22.0)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        path = pointer_path(tip, CURSOR*scale)
        shape = path.united(stroker.createStroke(path)).simplified()
        shadow = QColor(0, 0, 0, 55)
        for offset in (2.2, 1.2):  # a soft shadow so it reads on light and dark
            p.fillPath(shape.translated(0.6, offset), shadow)
        fill = QColor(self.fill)
        fill.setAlphaF(0.8)
        p.fillPath(shape, fill)
        edge = QColor(self.edge)
        edge.setAlphaF(0.85)
        p.setPen(QPen(edge, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)
        p.restore()
