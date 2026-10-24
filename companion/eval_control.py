"""Local control channel for scripts/live_eval.py; off unless A11Y_EVAL=1 in a source run.

It types a request into the companion exactly as the user would and reports what
happened: the route, replies, task steps and timing records. It has no command that
confirms, executes or skips anything, so proposals that wait for the user's
confirmation stay pending. The packaged app never opens it. The socket lives in the
data folder and only its owner can connect (0600)."""
import json
import os
import queue
import socket
import stat
import threading
import time
from PyQt6.QtCore import QAbstractAnimation, QObject, pyqtSignal
from . import timing as timing_module


def enabled():
    from .paths import frozen
    return os.getenv('A11Y_EVAL', '').strip() == '1' and not frozen()


TEST_MARKER = 'A11y test'  # only changes whose label carries it can be confirmed by the harness
_shots = {'count': 0}


def step_shot(image_data, step, action=None, status=''):
    """Evaluation only: the step's screenshot (960 px, the click drawn in red) and what was done,
    in the run folder the harness gave (A11Y_EVAL_SHOTS). The normal app never writes screenshots."""
    folder = os.getenv('A11Y_EVAL_SHOTS', '')
    if not enabled() or not folder or not isinstance(image_data, str) or ',' not in image_data:
        return
    import base64
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QColor, QImage, QPainter, QPen
    from PyQt6.QtCore import Qt
    image = QImage.fromData(base64.b64decode(image_data.split(',', 1)[1]))
    if image.isNull():
        return
    image = image.scaledToWidth(960, Qt.TransformationMode.SmoothTransformation)
    action = action or {}
    if isinstance(action.get('x'), (int, float)) and isinstance(action.get('y'), (int, float)):
        painter = QPainter(image)
        painter.setPen(QPen(QColor('red'), 3))
        painter.drawEllipse(QPointF(action['x']*image.width(), action['y']*image.height()), 14, 14)
        painter.end()
    _shots['count'] += 1
    name = 'shot-%04d.jpg' % _shots['count']
    os.makedirs(folder, exist_ok=True)
    image.save(os.path.join(folder, name), 'JPG', 70)
    timing_module.timing('eval.shot', time.monotonic(), file=name, step=step, status=status,
                         action={key: action.get(key) for key in ('type', 'label', 'x', 'y', 'key', 'text', 'url', 'bundle_id') if key in action})


class _Bridge(QObject):
    call = pyqtSignal(object)


class EvalControl:
    def __init__(self, window, path):
        self.window = window
        self.path = str(path)
        self.events = []
        self.lock = threading.Lock()
        self.last_change = time.monotonic()
        self.idle_since = None
        self.bridge = _Bridge()
        self.bridge.call.connect(self.handle)  # queued onto the Qt thread
        timing_module.listeners.append(lambda record: self.event('timing', record))
        say = window.say
        def recorded_say(message, *args, **kwargs):
            self.event('say', {'message': message})
            return say(message, *args, **kwargs)
        window.say = recorded_say
        try:
            mode = os.lstat(self.path).st_mode
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(mode):
                raise RuntimeError('The evaluation socket path is taken by another file: '+self.path)
            os.unlink(self.path)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        previous = os.umask(0o177)
        try:
            self.server.bind(self.path)
        finally:
            os.umask(previous)
        os.chmod(self.path, 0o600)
        self.server.listen(4)
        threading.Thread(target=self.serve, daemon=True).start()
        print('A11y evaluation channel open', flush=True)

    def event(self, kind, data):
        with self.lock:
            self.events.append({'t': round(time.monotonic(), 3), 'kind': kind, 'data': data})
            self.last_change = time.monotonic()

    def serve(self):
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            with connection:
                connection.settimeout(30)
                data = b''
                try:
                    while not data.endswith(b'\n') and len(data) < 65536:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    command = json.loads(data)
                    box = queue.Queue(1)
                    self.bridge.call.emit((command, box))
                    reply = box.get(timeout=20)
                except (ValueError, OSError, queue.Empty) as error:
                    reply = {'error': type(error).__name__}
                try:
                    connection.sendall(json.dumps(reply, default=str).encode()+b'\n')
                except OSError:
                    pass

    def handle(self, item):
        command, box = item
        try:
            box.put(self.run(command if isinstance(command, dict) else {}))
        except Exception as error:  # reported to the harness; the app keeps running
            box.put({'error': type(error).__name__+': '+str(error)[:300]})

    def busy(self):
        window = self.window
        writer = getattr(window, 'app_writer', None)
        animation = window.move_animation
        return bool((window.worker and window.worker.isRunning()) or (writer and writer.isRunning())
                    or (animation and animation.state() == QAbstractAnimation.State.Running))

    def run(self, command):
        window, kind = self.window, command.get('cmd')
        if kind == 'ask':
            request = command.get('request')
            if not isinstance(request, str) or not request.strip():
                return {'error': 'empty request'}
            if self.busy():
                return {'error': 'busy'}
            window.service.last_request_plan = None
            self.event('ask', {'request': request})
            window.mascot_submit(request, 'chat')
            return {'ok': True, 'event_index': len(self.events)}
        if kind == 'stop':
            window.stop_computer_task(announce=False)
            return {'ok': True}
        if kind == 'confirm':
            # Only the harness's own test items ("A11y test 4821"): never a real change.
            pending = window.pending_desktop_action or {}
            if (pending.get('type') != 'app_write' or pending.get('kind') not in ('add_reminder', 'delete_reminder', 'create_note')
                    or TEST_MARKER not in str(pending.get('title', ''))):
                return {'error': 'nothing to confirm that the evaluation created'}
            window.mascot_action('desktop:apply')
            return {'ok': True}
        if kind == 'quit':
            window.request_quit()
            return {'ok': True}
        if kind == 'state':
            return self.state(int(command.get('since', 0)))
        return {'error': 'unknown command'}

    def state(self, since):
        window, now = self.window, time.monotonic()
        task = window.computer_task
        running = bool(task and task.status == 'running' and not task.cancelled.is_set())
        pending = window.pending_desktop_action or {}
        # A running task that waits on the user's confirmation is as far as it can go.
        waiting = running and task.pending is not None and bool(pending)
        idle = not self.busy() and (not running or waiting)
        if not idle:
            self.idle_since = None
        elif self.idle_since is None:
            self.idle_since = now
        with self.lock:
            events, count = self.events[since:], len(self.events)
            quiet = now-max(self.last_change, self.idle_since or now)
        plan = window.service.last_request_plan or {}
        mascot, area = window.mascot.geometry(), window.mascot.screen().availableGeometry()
        return {
            'now': round(now, 3), 'idle': idle, 'quiet_for': round(quiet, 3) if idle else 0, 'events': events, 'event_count': count,
            'ready': {'app_awareness': window.desktop_monitor.enabled, 'screen_vision': window.vision.enabled},
            'plan': {key: plan.get(key) for key in ('operation', 'app_name', 'target', 'goal_mode', 'computed', 'remaining_request', 'opening')},
            'pending_action': {key: pending.get(key) for key in ('type', 'label', 'goal')} if pending else None,
            'task': {'status': task.status, 'goal': task.goal, 'steps': len(task.receipts), 'timings': task.timings,
                     'receipts': [{key: receipt.get(key) for key in ('type', 'label', 'status')} for receipt in task.receipts]} if task else None,
            'mascot': {'x': mascot.x(), 'y': mascot.y(), 'width': mascot.width(), 'height': mascot.height()},
            'screen': {'x': area.x(), 'y': area.y(), 'width': area.width(), 'height': area.height()},
            'last_action': {key: (window.service.last_action_result or {}).get(key) for key in ('type', 'label', 'status')},
        }
