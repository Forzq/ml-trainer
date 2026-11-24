"""SQLite storage for beta invitations and login sessions."""
import hashlib
import secrets
import sqlite3
import time
import uuid
from contextlib import closing

from app.beta.quotas import BetaQuotas

COOKIE = "__Host-mockroom"
SESSION_SECONDS = 30 * 24 * 60 * 60


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class BetaAccess:
    def __init__(self, path):
        self.path = path
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, active INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS invites (
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, account_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL, used_at INTEGER, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS logins (
                    digest TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS logins_account ON logins(account_id);
            """)
        self.quotas = BetaQuotas(self.connect)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def issue(self, label, valid_for, *, account_id=None):
        code = secrets.token_urlsafe(24)
        now = int(time.time())
        invite_id = uuid.uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if account_id:
                exists = db.execute("SELECT 1 FROM accounts WHERE id=? AND active=1", (account_id,)).fetchone()
                if not exists:
                    raise ValueError("Active beta account not found.")
            else:
                account_id = uuid.uuid4().hex
                db.execute("INSERT INTO accounts VALUES (?, ?, 1, ?)", (account_id, label, now))
            db.execute("INSERT INTO invites(id,digest,account_id,expires_at) VALUES (?,?,?,?)",
                       (invite_id, digest(code), account_id, now + valid_for))
        return account_id, invite_id, code

    def redeem(self, code):
        now = int(time.time())
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""
                SELECT i.account_id FROM invites i JOIN accounts a ON a.id=i.account_id
                WHERE i.digest=? AND i.used_at IS NULL AND i.revoked=0 AND i.expires_at>?
                    AND a.active=1
            """, (digest(code), now)).fetchone()
            if row is None:
                return None
            token = secrets.token_urlsafe(32)
            db.execute("UPDATE invites SET used_at=? WHERE digest=?", (now, digest(code)))
            db.execute("DELETE FROM logins WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO logins VALUES (?,?,?)", (digest(token), row[0], now + SESSION_SECONDS))
            return token

    def authenticate(self, token):
        if not token or len(token) != 43:
            return None
        with closing(self.connect()) as db:
            row = db.execute("""
                SELECT l.account_id FROM logins l JOIN accounts a ON a.id=l.account_id
                WHERE l.digest=? AND l.expires_at>? AND a.active=1
            """, (digest(token), int(time.time()))).fetchone()
        return row[0] if row else None

    def logout(self, token):
        with closing(self.connect()) as db, db:
            db.execute("DELETE FROM logins WHERE digest=?", (digest(token),))

    def revoke_invite(self, invite_id):
        with closing(self.connect()) as db, db:
            return bool(db.execute("UPDATE invites SET revoked=1 WHERE id=? AND used_at IS NULL",
                                   (invite_id,)).rowcount)

    def revoke_account(self, account_id):
        with closing(self.connect()) as db, db:
            updated = db.execute("UPDATE accounts SET active=0 WHERE id=?", (account_id,)).rowcount
            db.execute("DELETE FROM logins WHERE account_id=?", (account_id,))
            return bool(updated)

    def accounts(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT id, label, active FROM accounts ORDER BY created_at, id").fetchall()
