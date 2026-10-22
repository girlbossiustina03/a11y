"""Bounded lexical RAG with access filtering BEFORE ranking or transmission."""
from collections import Counter
import json
import math
import re
from .models import text
from .storage import now, uid

STOP = set('a an the to of and or is are i my me how do can please help with for in on it this that you we our be am configure'.split())


def tokens(value):
    return [t for t in re.findall(r'[^\W_]+', value.casefold()) if len(t) > 1 and t not in STOP]


class Knowledge:
    def __init__(self, store):
        self.store = store

    def ingest(self, identity, title, body, roles):
        if 'admin' not in identity.roles:
            raise PermissionError('Document management requires the configured admin role.')
        title = text(title, 'document title', 200)
        body = text(body, 'document text', 120000)
        if not isinstance(roles, list) or not roles or len(roles) > 20:
            raise ValueError('Choose at least one allowed role; use employee for all employees.')
        roles = sorted(set(text(role, 'role', 60) for role in roles))
        document_id = uid()
        # Overlap retains instructions crossing a chunk boundary; stable IDs support citations.
        chunks = [body[i:i+1600] for i in range(0, len(body), 1400)]
        with self.store.company() as db:
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?)',
                       (document_id, identity.company_id, title, body, json.dumps(roles), now()))
            db.executemany('INSERT INTO chunks VALUES (?,?,?,?)',
                           [(f'{document_id}:{i+1}', document_id, i+1, chunk) for i, chunk in enumerate(chunks)])
        return document_id

    def accessible(self, identity):
        with self.store.company() as db:
            rows = db.execute('SELECT * FROM documents WHERE company_id=? ORDER BY title',
                              (identity.company_id,)).fetchall()
        return [dict(r) for r in rows if set(json.loads(r['roles'])) & set(identity.roles)]

    def list_documents(self, identity):
        return [{'id': r['id'], 'title': r['title'], 'roles': json.loads(r['roles']),
                 'updated_at': r['updated_at']} for r in self.accessible(identity)]

    def delete(self, identity, document_id):
        if 'admin' not in identity.roles:
            raise PermissionError('Document management requires the configured admin role.')
        with self.store.company() as db:
            db.execute('DELETE FROM documents WHERE id=? AND company_id=?', (document_id, identity.company_id))

    def retrieve(self, identity, query, limit=6):
        documents = {r['id']: r for r in self.accessible(identity)}
        if not documents:
            return []
        with self.store.company() as db:
            rows = db.execute('SELECT c.* FROM chunks c JOIN documents d ON d.id=c.document_id '
                              'WHERE d.company_id=?', (identity.company_id,)).fetchall()
        rows = [dict(r) for r in rows if r['document_id'] in documents]
        terms = set(tokens(query))
        if not terms:
            return []
        counters = [Counter(tokens(documents[r['document_id']]['title'] + ' ' + r['content'])) for r in rows]
        frequency = Counter(t for c in counters for t in c)
        ranked = []
        for row, counts in zip(rows, counters):
            score = sum(math.log(1 + len(rows)/(frequency[t]+1)) * counts[t]/(counts[t]+1.2)
                        for t in terms if counts[t])
            if score:
                row.update(title=documents[row['document_id']]['title'], score=score)
                ranked.append(row)
        ranked.sort(key=lambda r: (-r['score'], r['id']))
        return [{k: r[k] for k in ('id', 'document_id', 'title', 'ordinal', 'content')}
                for r in ranked[:limit]]
