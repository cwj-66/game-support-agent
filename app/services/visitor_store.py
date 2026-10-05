"""Persistent anonymous access control shared with the portfolio login service."""
import hashlib
import hmac
import re
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager

VISITOR_COOKIE = 'gsa_portfolio_visitor'

def sign_visitor(ident, secret):
    return ident + '.' + hmac.new(secret.encode(), ident.encode(), hashlib.sha256).hexdigest()

def verify_visitor(value, secret):
    ident, _, signature = (value or '').partition('.')
    if not re.fullmatch(r'[0-9a-f]{32}', ident):
        return None
    expected = sign_visitor(ident, secret).partition('.')[2]
    return ident if hmac.compare_digest(signature, expected) else None

class VisitorStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS visitors (
                    id TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
                    blocked INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, last_ip TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS turns (
                    visitor TEXT NOT NULL, request TEXT NOT NULL,
                    PRIMARY KEY(visitor,request));
                CREATE TABLE IF NOT EXISTS login_ips (
                    ip TEXT PRIMARY KEY, count INTEGER NOT NULL, window REAL NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ensure(self, ident, ip=''):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO visitors(id,created) VALUES(?,?)', (ident, time.time()))
            if ip:
                db.execute('UPDATE visitors SET last_ip=? WHERE id=?', (ip, ident))

    def state(self, ident):
        with self.connect() as db:
            row = db.execute('SELECT * FROM visitors WHERE id=?', (ident,)).fetchone()
        return dict(row) if row else None

    def ip_attempt(self, ip, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM login_ips WHERE ip=?', (ip,)).fetchone()
            db.execute('DELETE FROM login_ips WHERE window < ?', (now - 3600,))
            if row and now - row['window'] < 60 and row['count'] >= 5:
                return max(1, int(60 - (now - row['window'])))
            count, start = (row['count'] + 1, row['window']) if row and now-row['window']<60 else (1,now)
            db.execute('INSERT OR REPLACE INTO login_ips VALUES(?,?,?)', (ip,count,start))
        return 0

    def login_result(self, ident, correct):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM visitors WHERE id=?', (ident,)).fetchone()
            if not row or row['blocked']:
                return {'blocked': True, 'remaining': 0}
            failures = 0 if correct else row['failures'] + 1
            db.execute('UPDATE visitors SET failures=?,blocked=? WHERE id=?', (failures,int(failures>=5),ident))
        return {'blocked': failures>=5, 'remaining': max(0,5-failures)}

    def reserve(self, ident, request, limit=50):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM visitors WHERE id=?', (ident,)).fetchone()
            if not row or row['blocked']:
                return 'blocked'
            if db.execute('SELECT 1 FROM turns WHERE visitor=? AND request=?', (ident,request)).fetchone():
                return 'duplicate'
            if row['used'] >= limit:
                return 'exhausted'
            db.execute('INSERT INTO turns VALUES(?,?)', (ident,request))
            db.execute('UPDATE visitors SET used=used+1 WHERE id=?', (ident,))
        return 'accepted'
