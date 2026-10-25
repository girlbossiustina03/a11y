#!/usr/bin/env python3
"""Build the app icons (macOS .icns, Windows .ico, 1024-px PNG).

Uses packaging/icon-source.png when present (drop your artwork there); otherwise
renders A11y's icon: her terminal window in a Terminal-style frame, with her face."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT/'packaging'/'icons'
SOURCE = ROOT/'packaging'/'icon-source.png'


def render_terminal(path, size=1024):
    """A11y's icon: a light, Terminal-style frame holding her dark window (the three window buttons, her
    face in the terminal font, a prompt). Fixed Clear Dark colours, so the icon never follows a theme."""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.path.insert(0, str(ROOT))
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QImage, QLinearGradient,
                             QPainter, QPainterPath, QPen)
    from companion import faces
    from companion.terminal_theme import THEMES
    app = QGuiApplication.instance() or QGuiApplication([])
    theme = THEMES['clear_dark']
    body, text, cyan = QColor(theme.background), QColor(theme.text), QColor(theme.cyan)
    family = next((f for f in ('JetBrainsMono Nerd Font', 'JetBrains Mono', 'SF Mono', 'Menlo') if f in QFontDatabase.families()), 'Menlo')
    k = size/1024
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(0)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    def rounded(rect, radius):
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path
    tile = QRectF(100*k, 100*k, 824*k, 824*k)  # Apple's icon grid: 824 of 1024, room for the shadow
    frame = rounded(tile, 185*k)
    for i, alpha in enumerate((18, 14, 10, 7, 4)):
        p.fillPath(frame.translated(0, (6+i*4)*k), QColor(0, 0, 0, alpha))
    metal = QLinearGradient(tile.topLeft(), tile.bottomLeft())
    metal.setColorAt(0, QColor('#e9eaee'))
    metal.setColorAt(1, QColor('#b7bac2'))
    p.fillPath(frame, metal)
    p.setPen(QPen(QColor(255, 255, 255, 160), 3*k))
    p.drawPath(frame)
    window = tile.adjusted(70*k, 90*k, -70*k, -90*k)
    shape = rounded(window, 70*k)
    title = 110*k
    p.save()
    p.setClipPath(shape)
    fill = QLinearGradient(window.topLeft(), window.bottomLeft())
    fill.setColorAt(0, body.lighter(118))
    fill.setColorAt(1, body.darker(112))
    p.fillRect(window, fill)
    bar = QRectF(window.x(), window.y(), window.width(), title)
    shade = QLinearGradient(bar.topLeft(), bar.bottomLeft())
    shade.setColorAt(0, QColor('#3a3f4b'))
    shade.setColorAt(1, QColor('#2c313c'))
    p.fillRect(bar, shade)
    p.fillRect(QRectF(bar.x(), bar.bottom()-2*k, bar.width(), 2*k), QColor(0, 0, 0, 90))
    p.restore()
    for i, color in enumerate((QColor('#FF5F57'), QColor('#FEBC2E'), QColor('#28C840'))):
        p.setBrush(color)
        p.setPen(QPen(color.darker(125), title*0.024))
        p.drawEllipse(QPointF(window.x()+title*0.62+i*title*0.58, window.y()+title/2), title*0.2, title*0.2)
    # Her face, block characters drawn as solid cells (no seams), with a faint terminal glow.
    lines = faces.face('pixel', 'idle')
    area = QRectF(window.x()+window.width()*0.14, window.y()+title+window.height()*0.08, window.width()*0.72, window.height()*0.5)
    font = QFont(family)
    font.setPixelSize(200)
    metrics = QFontMetricsF(font)
    cols, rows = max(len(line) for line in lines), len(lines)
    scale = min(area.width()/(metrics.horizontalAdvance('M')*cols), area.height()/(metrics.lineSpacing()*rows))
    font.setPixelSize(int(200*scale))
    metrics = QFontMetricsF(font)
    p.setFont(font)
    cw, ch = metrics.horizontalAdvance('M'), metrics.lineSpacing()
    left, top = area.center().x()-cw*cols/2, area.center().y()-ch*rows/2
    blocks = {'█': (0, 1, 1.0), '▀': (0, .5, 1.0), '▄': (.5, 1, 1.0), '░': (0, 1, .28), '▒': (0, 1, .5), '▓': (0, 1, .75)}
    def draw(dx, dy, strength):
        for i, line in enumerate(lines):
            for j, char in enumerate(line):
                x, y = left+j*cw+dx, top+i*ch+dy
                color = QColor(text)
                if char in blocks:
                    a, b, alpha = blocks[char]
                    color.setAlphaF(alpha*strength)
                    p.fillRect(QRectF(x-0.5, y+a*ch-0.5, cw+1, (b-a)*ch+1), color)
                elif char.strip():
                    color.setAlphaF(strength)
                    p.setPen(color)
                    p.drawText(QPointF(x, y+metrics.ascent()), char)
    for dx, dy in ((-3*k, 0), (3*k, 0), (0, -3*k), (0, 3*k)):
        draw(dx, dy, 0.12)
    draw(0, 0, 1.0)
    prompt = QFont(family)
    prompt.setPixelSize(int(window.height()*0.1))
    prompt.setBold(True)
    p.setFont(prompt)
    p.setPen(cyan)
    px, py = window.x()+window.width()*0.11, window.bottom()-window.height()*0.1
    p.drawText(QPointF(px, py), '›')
    gap = QFontMetricsF(prompt).horizontalAdvance('› ')
    p.fillRect(QRectF(px+gap, py-window.height()*0.078, window.height()*0.05, window.height()*0.09), cyan)
    p.setPen(QPen(QColor(255, 255, 255, 30), 2*k))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(shape)
    p.end()
    image.save(str(path))
    del app


def main():
    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True)
    master = OUT/'A11y.png'
    if SOURCE.exists():
        Image.open(SOURCE).convert('RGBA').resize((1024, 1024), Image.LANCZOS).save(master)
    else:
        render_terminal(master)
    image = Image.open(master).convert('RGBA')
    image.save(OUT/'A11y.icns', sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)])
    image.save(OUT/'A11y.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('Icons written to', OUT)


if __name__ == '__main__':
    main()
