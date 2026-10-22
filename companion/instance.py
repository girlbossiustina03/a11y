"""Process-lifetime local lock; no PID killing or stale-file deletion."""
import errno
import hashlib
import json
import os
from pathlib import Path


def _lock(file, *, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    if windows:
        import msvcrt
        file.seek(0)
        if not file.read(1):
            file.write(' ')
            file.flush()
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(file, *, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    if windows:
        import msvcrt
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def build_id():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    for path in sorted((root.parent/'native').glob('*.swift')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


class DesktopInstance:
    def __init__(self, directory):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory/'desktop-instance.lock').open('a+')
        try:
            _lock(self.file)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                self.file.close()
                raise
            self.file.seek(0)
            owner = self.file.read(1024)
            self.file.close()
            raise RuntimeError('A11y is already running. Quit it from its companion menu before relaunching. '+owner) from None
        self.file.seek(0)
        self.file.truncate()
        self.file.write(json.dumps({'pid': os.getpid(), 'build': build_id()}))
        self.file.flush()

    def close(self):
        if not self.file.closed:
            _unlock(self.file)
            self.file.close()
