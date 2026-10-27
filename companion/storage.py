"""Local settings and conversation history; no screenshot storage."""
from contextlib import contextmanager
from collections import defaultdict, deque
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory, *, persist_history=True):
        self.persist_history = persist_history
        self.session_history = defaultdict(lambda: deque(maxlen=100))
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.employee() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS profiles (
                    owner TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS desktop_access (
                    owner TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS introductions (
                    owner TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, created_at TEXT NOT NULL, source_documents TEXT NOT NULL DEFAULT '[]');
                PRAGMA user_version=2;
            ''')

            columns = {r['name'] for r in db.execute('PRAGMA table_info(messages)')}
            if 'source_documents' not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN source_documents TEXT NOT NULL DEFAULT '[]'")

    @contextmanager
    def connect(self, name):
        path = self.directory / name
        db = sqlite3.connect(path, timeout=15)
        try:
            path.chmod(0o600)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def employee(self):
        return self.connect('employee.sqlite3')

    @staticmethod
    def owner(identity):
        # JSON encoding avoids delimiter collisions between tenant/user IDs.
        return json.dumps([identity.company_id, identity.user_id])

    def profile(self, identity):
        with self.employee() as db:
            row = db.execute('SELECT data FROM profiles WHERE owner=?', (self.owner(identity),)).fetchone()
        return json.loads(row['data']) if row else None

    def save_profile(self, identity, value):
        with self.employee() as db:
            db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?)',
                       (self.owner(identity), json.dumps(value)))

    def mutate_profile(self, identity, default_factory, change):
        with self.employee() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM profiles WHERE owner=?', (self.owner(identity),)).fetchone()
            value = json.loads(row['data']) if row else default_factory()
            change(value)
            db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?)',
                       (self.owner(identity), json.dumps(value)))
        return value

    def introduction(self, identity):
        with self.employee() as db:
            row = db.execute('SELECT data FROM introductions WHERE owner=?', (self.owner(identity),)).fetchone()
        return json.loads(row['data']) if row else None

    def save_introduction(self, identity, value):
        with self.employee() as db:
            db.execute('INSERT OR REPLACE INTO introductions VALUES (?,?)',
                       (self.owner(identity), json.dumps(value)))

    def history(self, identity, limit=12):
        if not self.persist_history:
            rows = list(self.session_history[self.owner(identity)])
            return [dict(row) for row in (rows if limit < 0 else rows[-limit:] if limit else [])]
        # Never replay legacy answers whose document permissions can no longer be checked.
        with self.employee() as db:
            rows = db.execute('SELECT role,content,source_documents FROM messages WHERE owner=? ORDER BY id DESC LIMIT ?',
                              (self.owner(identity), limit)).fetchall()
        return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)
                if not json.loads(r['source_documents'])]

    def add_exchange(self, identity, request, reply):
        if not self.persist_history:
            self.session_history[self.owner(identity)].extend(
                ({'role':'user','content':request}, {'role':'assistant','content':reply}))
            return
        with self.employee() as db:
            for role, content in [('user', request), ('assistant', reply)]:
                db.execute('INSERT INTO messages(owner,role,content,created_at) VALUES (?,?,?,?)',
                           (self.owner(identity), role, content, now()))
            db.execute('DELETE FROM messages WHERE owner=? AND id NOT IN '
                       '(SELECT id FROM messages WHERE owner=? ORDER BY id DESC LIMIT 100)',
                       (self.owner(identity), self.owner(identity)))

    def clear_history(self, identity):
        if not self.persist_history:
            self.session_history[self.owner(identity)].clear()
            return
        with self.employee() as db:
            db.execute('DELETE FROM messages WHERE owner=?', (self.owner(identity),))
