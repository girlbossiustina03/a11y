"""Small resolution-independent control glyphs, painted with the UI's stroke weight."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor


def control_icon(name):
    pixmap = QPixmap(40, 40)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor('#ffffff' if name == 'send' else '#e5e5ea')
    painter.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if name == 'send':
        painter.drawLine(10, 15, 10, 5)
        painter.drawLine(10, 5, 6, 9)
        painter.drawLine(10, 5, 14, 9)
    else:
        painter.translate(10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for _ in range(8):
            painter.drawRoundedRect(QRectF(-1.2, -7.4, 2.4, 3), .5, .5)
            painter.rotate(45)
        painter.setPen(QPen(color, 1.7))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(-5, -5, 10, 10))
        painter.drawEllipse(QRectF(-1.8, -1.8, 3.6, 3.6))
    painter.end()
    return QIcon(pixmap)
