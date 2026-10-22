"""Separate company documents from employee state; no screenshot storage."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.company() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, title TEXT NOT NULL,
                    body TEXT NOT NULL, roles TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL, FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE);
                PRAGMA user_version=1;
            ''')
        with self.employee() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS profiles (
                    owner TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS desktop_access (
                    owner TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS introductions (
                    owner TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
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

    def company(self):
        return self.connect('company.sqlite3')

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

    def workflows(self, identity):
        with self.employee() as db:
            rows = db.execute('SELECT data FROM workflows WHERE owner=? ORDER BY updated_at DESC',
                              (self.owner(identity),)).fetchall()
        return [json.loads(r['data']) for r in rows]

    def workflow(self, identity, workflow_id):
        with self.employee() as db:
            row = db.execute('SELECT data FROM workflows WHERE id=? AND owner=?',
                             (workflow_id, self.owner(identity))).fetchone()
        if not row:
            raise ValueError('Workflow not found for this employee.')
        return json.loads(row['data'])

    def create_workflow(self, identity, plan, preferences, sources):
        workflow = dict(plan, id=uid(), current_step=0, status='active', created_at=now(),
                        updated_at=now(), presentation=preferences, sources=sources,
                        confirmations=[])
        self.save_workflow(identity, workflow)
        return workflow

    def save_workflow(self, identity, workflow):
        with self.employee() as db:
            db.execute('INSERT OR REPLACE INTO workflows VALUES (?,?,?,?)',
                       (workflow['id'], self.owner(identity), json.dumps(workflow), now()))

    def confirm_step(self, identity, workflow_id, expected_step):
        # Compare and update in one transaction: repeated clicks cannot skip steps.
        with self.employee() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM workflows WHERE id=? AND owner=?',
                             (workflow_id, self.owner(identity))).fetchone()
            if not row:
                raise ValueError('Workflow not found.')
            w = json.loads(row['data'])
            if type(expected_step) is not int or w['status'] != 'active' or w['current_step'] != expected_step:
                raise ValueError('Progress changed. Review the current step before confirming.')
            w['confirmations'].append({'step': expected_step, 'by': 'user', 'at': now()})
            w['current_step'] += 1
            w['updated_at'] = now()
            if w['current_step'] == len(w['steps']):
                w['status'] = 'completed'
            db.execute('UPDATE workflows SET data=?, updated_at=? WHERE id=? AND owner=?',
                       (json.dumps(w), now(), workflow_id, self.owner(identity)))
        return w

    def history(self, identity, limit=12, allowed_documents=None):
        with self.employee() as db:
            rows = db.execute('SELECT role,content,source_documents FROM messages WHERE owner=? ORDER BY id DESC LIMIT ?',
                              (self.owner(identity), limit)).fetchall()
        return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)
                if allowed_documents is None or set(json.loads(r['source_documents'])) <= allowed_documents]

    def add_exchange(self, identity, request, reply, source_documents=()):
        with self.employee() as db:
            for role, content in [('user', request), ('assistant', reply)]:
                db.execute('INSERT INTO messages(owner,role,content,created_at,source_documents) VALUES (?,?,?,?,?)',
                           (self.owner(identity), role, content, now(), json.dumps(list(source_documents))))
            db.execute('DELETE FROM messages WHERE owner=? AND id NOT IN '
                       '(SELECT id FROM messages WHERE owner=? ORDER BY id DESC LIMIT 100)',
                       (self.owner(identity), self.owner(identity)))

    def clear_history(self, identity):
        with self.employee() as db:
            db.execute('DELETE FROM messages WHERE owner=?', (self.owner(identity),))
