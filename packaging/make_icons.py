#!/usr/bin/env python3
"""Build the app icons (macOS .icns, Windows .ico, 1024-px PNG).

Uses packaging/icon-source.png when present (drop your artwork there); otherwise
renders the A11y cloud from the same drawing code as the on-screen mascot."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT/'packaging'/'icons'
SOURCE = ROOT/'packaging'/'icon-source.png'


def render_cloud(path, size=1024):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.path.insert(0, str(ROOT))
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen
    from companion.mascot import CLOUD_BODY, CLOUD_INK, CLOUD_LINE, CLOUD_SHADE, cloud_path
    app = QGuiApplication.instance() or QGuiApplication([])
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor('#ffffff'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = size/215  # cloud fills ~70% of the width, like the supplied artwork
    painter.translate(size/2-103.5*scale, size/2-80*scale)
    painter.scale(scale, scale)
    cloud = cloud_path()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(CLOUD_SHADE)
    painter.drawPath(cloud)
    painter.save()
    painter.translate(23, 0)
    painter.scale(0.95, 1)
    painter.translate(-23, 0)
    painter.setBrush(CLOUD_BODY)
    painter.drawPath(cloud)
    painter.restore()
    painter.setPen(QPen(CLOUD_LINE, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(cloud)
    painter.setPen(Qt.PenStyle.NoPen)
    for cx in (82, 118):
        painter.setBrush(CLOUD_INK)
        painter.drawEllipse(QPointF(cx, 87), 8, 10.5)
        painter.setBrush(CLOUD_BODY)
        painter.drawEllipse(QPointF(cx+3, 83), 2.8, 2.8)
    smile = QPainterPath(QPointF(93, 104))
    smile.quadTo(100, 110, 107, 104)
    painter.setPen(QPen(CLOUD_INK, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(smile)
    painter.end()
    image.save(str(path))
    del app


def main():
    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True)
    master = OUT/'A11y.png'
    if SOURCE.exists():
        Image.open(SOURCE).convert('RGBA').resize((1024, 1024), Image.LANCZOS).save(master)
    else:
        render_cloud(master)
    image = Image.open(master).convert('RGBA')
    image.save(OUT/'A11y.icns', sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)])
    image.save(OUT/'A11y.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('Icons written to', OUT)


if __name__ == '__main__':
    main()
