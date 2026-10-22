#!/usr/bin/env python3
"""Exercise a real local model over five synthetic UI states. Executes NO OS actions."""
import argparse
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QColor, QFont
from PyQt6.QtWidgets import QApplication
from companion.computer_task import ComputerTask
from companion.desktop_context import DesktopContext
from companion.ollama import OllamaProvider
from companion.provider import AIConfig
from companion.vision import ScreenVision


class Scene:
    enabled = True
    generation = 0
    click_guard = staticmethod(ScreenVision.click_guard)

    def __init__(self):
        self.phase = 0

    def sample(self):
        return {'status': 'available', 'accessibility': 'granted',
                'app': {'name': 'Safari', 'bundle_id': 'com.apple.Safari'},
                'window': {'title': 'Company Help', 'bounds': {'x': 0, 'y': 0, 'width': 1000, 'height': 700}},
                'focused_role': 'AXTextField' if self.phase in (1, 2) else 'AXGroup',
                'focused_bounds': {'x': 160, 'y': 150, 'width': 640, 'height': 56},
                'controls': [], 'installed_apps': [{'name': 'Safari', 'bundle_id': 'com.apple.Safari'}],
                'available_apps': [{'name': 'Safari', 'bundle_id': 'com.apple.Safari'}]}

    def catalog(self):
        return self.sample()['installed_apps']

    def capture(self, *args, **kwargs):
        image = QImage(1000, 700, QImage.Format.Format_RGB32)
        image.fill(QColor('#10151c'))
        painter = QPainter(image)
        painter.setPen(QColor('white'))
        painter.setFont(QFont('Helvetica', 28))
        painter.drawText(90, 85, 'Company Help')
        if self.phase < 4:
            painter.setPen(QColor('#708090'))
            painter.setBrush(QColor('#24303d'))
            painter.drawRoundedRect(QRectF(160, 150, 640, 56), 12, 12)
            painter.setPen(QColor('white' if self.phase >= 2 else '#aabbcc'))
            painter.setFont(QFont('Helvetica', 20))
            painter.drawText(180, 185, 'VPN setup' if self.phase >= 2 else 'Search company instructions')
            if self.phase == 1:
                painter.drawLine(175, 162, 175, 195)
            painter.setBrush(QColor('#2879de'))
            painter.drawRoundedRect(QRectF(815, 150, 110, 56), 12, 12)
            painter.setPen(QColor('white'))
            painter.drawText(830, 185, 'Search')
        if self.phase == 3:
            painter.setPen(QColor('#79bcff'))
            painter.drawText(180, 290, 'VPN setup instructions')
            painter.setPen(QColor('white'))
            painter.drawText(180, 330, 'Configure the company VPN on macOS.')
        if self.phase == 4:
            painter.drawText(160, 170, 'VPN setup instructions')
            painter.setFont(QFont('Helvetica', 18))
            painter.drawText(160, 230, '1. Get the VPN client from your company portal.')
            painter.drawText(160, 275, '2. Ask IT for your organization’s connection profile.')
        painter.end()
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        return {'image_data': 'data:image/png;base64,'+base64.b64encode(bytes(encoded)).decode(),
                'screen': {'x': 0, 'y': 0, 'width': 1000, 'height': 700},
                'display_id': 7, 'captured_monotonic': time.monotonic(), 'windows': []}

    def accepts(self, step):
        action = step.get('action') or {}
        kind = action.get('type')
        x, y = action.get('x', -1)*1000, action.get('y', -1)*700
        if self.phase == 0:
            return kind == 'click_point' and 160 <= x <= 800 and 150 <= y <= 206
        if self.phase == 1:
            return kind == 'type_text' and action.get('text', '').strip().casefold() == 'vpn setup'
        if self.phase == 2:
            return kind == 'press_key' and action.get('key') == 'enter' or kind == 'click_point' and 815 <= x <= 925 and 150 <= y <= 206
        if self.phase == 3:
            return kind == 'click_point' and 175 <= x <= 600 and 260 <= y <= 310
        return step['status'] == 'done' and action == {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.getenv('A11Y_AI_MODEL', 'qwen3-vl:8b-instruct'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    qt = QApplication.instance() or QApplication([])
    scene = Scene()
    desktop = DesktopContext(scene)
    desktop.enabled = True
    provider = OllamaProvider(AIConfig(base_url=os.getenv('A11Y_OLLAMA_URL', 'http://127.0.0.1:11434'), model=args.model, timeout=180))
    task = ComputerTask('Use the Company Help search field to find VPN setup and open its instructions.', automatic=True)
    records = []
    for phase in range(5):
        scene.phase = phase
        started = time.monotonic()
        record = {'phase': phase, 'pass': False}
        try:
            step = task.propose(desktop, scene, provider, {'x': 0, 'y': 0})
            record.update(status=step['status'], action={k: v for k, v in (step.get('action') or {}).items() if k != 'capture_guard'},
                          review=step.get('review'), message=step['message'], **{'pass': scene.accepts(step)})
            if record['pass'] and step.get('action'):
                # Simulation only: advance the annotated fixture, never call an executor.
                task.record({'type': step['action']['type'], 'label': step['action'].get('label'), 'status': 'fixture_simulated'})
        except (ValueError, RuntimeError) as error:
            record['error'] = str(error)
        record['seconds'] = round(time.monotonic()-started, 2)
        records.append(record)
        print(json.dumps(record), flush=True)
        if not record['pass']:
            break
    report = {'model': args.model, 'fixture': 'five synthetic UI states; no actual desktop read or actions executed',
              'passed': sum(r['pass'] for r in records), 'total': len(records), 'expected_total': 5, 'results': records}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2)+'\n')
    return 0 if len(records) == 5 and all(r['pass'] for r in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
