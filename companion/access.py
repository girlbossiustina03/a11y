"""Explicit per-employee consent to restore desktop access, separate from OS grants."""
class AccessPreferences:
    def __init__(self, store, identity):
        self.store, self.identity = store, identity

    def get(self):
        with self.store.employee() as db:
            row = db.execute('SELECT data FROM desktop_access WHERE owner=?', (self.store.owner(self.identity),)).fetchone()
        import json
        value = json.loads(row['data']) if row else {}
        return {key: value.get(key) is True for key in ('remember', 'app_awareness', 'screen_vision')}

    def save(self, *, remember=None, app_awareness=None, screen_vision=None):
        import json
        with self.store.employee() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM desktop_access WHERE owner=?', (self.store.owner(self.identity),)).fetchone()
            value = json.loads(row['data']) if row else {}
            for key, choice in (('remember', remember), ('app_awareness', app_awareness), ('screen_vision', screen_vision)):
                if choice is not None:
                    if type(choice) is not bool:
                        raise ValueError('Access choices must be boolean.')
                    value[key] = choice
            if value.get('remember') is not True:
                value = dict(value, remember=False, app_awareness=False, screen_vision=False)
            db.execute('INSERT OR REPLACE INTO desktop_access VALUES (?,?)', (self.store.owner(self.identity), json.dumps(value)))
        return self.get()


    def approved(self, feature):
        if feature not in ('app_awareness', 'screen_vision'):
            raise ValueError('Unknown access feature.')
        import json
        with self.store.employee() as db:
            row = db.execute('SELECT data FROM desktop_access WHERE owner=?', (self.store.owner(self.identity),)).fetchone()
        value = json.loads(row['data']) if row else {}
        return value.get('approved', {}).get(feature) is True or (value.get('remember') is True and value.get(feature) is True)

    def approve(self, feature):
        """Record explicit app consent separately from OS grants and enabled state."""
        if feature not in ('app_awareness', 'screen_vision'):
            raise ValueError('Unknown access feature.')
        import json
        with self.store.employee() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM desktop_access WHERE owner=?', (self.store.owner(self.identity),)).fetchone()
            value = json.loads(row['data']) if row else {}
            value.setdefault('approved', {})[feature] = True
            db.execute('INSERT OR REPLACE INTO desktop_access VALUES (?,?)', (self.store.owner(self.identity), json.dumps(value)))
