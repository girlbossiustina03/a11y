#!/usr/bin/env python3
"""Live Ollama grounding evaluation on a synthetic desktop, never real/private pixels.

Run from the repo: .venv/bin/python scripts/evaluate_movement.py --model qwen3.5:9b
No desktop actions are executed. Nonzero exit means connection/model/case failure.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def fixture_image():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer
    app = QApplication.instance() or QApplication([])
    scene = QSvgRenderer(str(Path(__file__).parent/'fixtures'/'movement-scene.svg'))
    frame = QImage(1200, 800, QImage.Format.Format_ARGB32)
    painter = QPainter(frame)
    scene.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    frame.save(buffer, 'PNG')
    return 'data:image/png;base64,'+base64.b64encode(bytes(data)).decode(), app


def main():
    from companion.desktop_context import DesktopContext
    from companion.models import Identity
    from companion.ollama import OllamaProvider
    from companion.provider import AIConfig
    from companion.service import Companion
    from companion.storage import Store
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.getenv('A11Y_AI_MODEL', 'qwen3.5:9b'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    image, qt = fixture_image()
    provider = OllamaProvider(AIConfig(base_url=os.getenv('A11Y_OLLAMA_URL', 'http://127.0.0.1:11434'), model=args.model, timeout=180))
    # Geometry tolerance allows pointing at different parts of the same test object.
    cases = [
        ('upper left', 'move to the upper left corner', False, 'corner', 'top_left'),
        ('upper right', 'move to the upper right corner', False, 'corner', 'top_right'),
        ('lower left', 'move to the bottom left corner', False, 'corner', 'bottom_left'),
        ('lower right', 'move to the bottom right corner', False, 'corner', 'bottom_right'),
        ('center', 'move yourself to the center of the screen', False, 'point', (.5, .5, .08, .08)),
        ('clock without pixels', 'move to the date and time', False, 'request_screen', None),
        ('menu-bar clock', 'move to the date and time in the menu bar', True, 'point', (.9, .02, .08, .03)),
        ('Fastfetch Apple', 'move to the fastfetch Apple logo in the bottom terminal', True, 'point', (.665, .695, .07, .105)),
        ('terminal GET/POST', 'move to the GET and POST text in the upper terminal', True, 'point', (.22, .22, .15, .07)),
        ('upper Terminal close', 'move to the red close button of the upper terminal', True, 'point', (.0483, .0963, .025, .025)),
        ('unknown object', 'move to the purple dinosaur', True, 'clarify', None),
    ]
    corners = {'top_left': (0, 0), 'top_right': (1, 0), 'bottom_left': (0, 1), 'bottom_right': (1, 1), 'center': (.5, .5)}
    results = []
    with tempfile.TemporaryDirectory(prefix='a11y-movement-eval-') as directory:
        service = Companion(Store(directory), Identity('evaluation', 'fixture-user'), provider)
        service.desktop_context = DesktopContext(None)  # Native-only tools; no actual observation/execution.
        service.desktop_session.append({'role': 'assistant', 'content': 'Earlier we located a Terminal close button.', 'source_documents': []})
        for name, request, pixels, expected, destination in cases:
            started = time.monotonic()
            record = {'case': name, 'pass': False}
            try:
                result = service.ask(request, mode='assist', image_data=image if pixels else None,
                    screen_geometry={'x': 0, 'y': 0, 'width': 1200, 'height': 800},
                    visual_context={'test_fixture': True, 'screen': {'x': 0, 'y': 0, 'width': 1200, 'height': 800}} if pixels else None)
                action = result.get('desktop_action') or {}
                record['intent'] = service.last_request_plan
                record['action'] = {key: action[key] for key in ('type', 'destination', 'x', 'y', 'basis') if key in action}
                if expected == 'request_screen':
                    record['pass'] = action.get('type') == 'request_screen'
                elif expected == 'clarify':
                    record['pass'] = not action and result['target'] is None
                else:
                    if expected == 'corner':
                        target_x, target_y = corners[destination]
                        tolerance_x = tolerance_y = .06
                    else:
                        target_x, target_y, tolerance_x, tolerance_y = destination
                    if action.get('type') == 'move_companion':
                        x, y = corners.get(action['destination'], (-10, -10))
                    else:
                        x, y = action.get('x', -10), action.get('y', -10)
                    record['pass'] = (action.get('type') in ('move_companion', 'move_to_point') and result['target'] is None
                        and abs(x-target_x) <= tolerance_x and abs(y-target_y) <= tolerance_y
                        and (not pixels or action.get('basis') == 'image'))
            except RuntimeError as error:
                record['error'] = str(error)
            except ValueError as error:
                record['error'] = str(error)
            record['seconds'] = round(time.monotonic()-started, 2)
            results.append(record)
            print(json.dumps(record), flush=True)
            if 'not reachable' in record.get('error', ''):
                break
    report = {'model': args.model, 'fixture': 'synthetic desktop; no real screenshots or actions',
              'passed': sum(item['pass'] for item in results), 'total': len(results), 'expected_total': len(cases), 'results': results}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('model', 'passed', 'total', 'expected_total')}))
    return 0 if len(results) == len(cases) and all(item['pass'] for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
