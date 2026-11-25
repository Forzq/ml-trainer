"""SQLite storage for beta invitations, login sessions and participant profiles."""
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
                CREATE TABLE IF NOT EXISTS shared_invites (
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL,
                    capacity INTEGER NOT NULL CHECK(capacity > 0), revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS shared_invite_redemptions (
                    account_id TEXT PRIMARY KEY, invite_id TEXT NOT NULL, registered_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS shared_redemptions_invite ON shared_invite_redemptions(invite_id);
                CREATE TABLE IF NOT EXISTS logins (
                    digest TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS logins_account ON logins(account_id);
                CREATE TABLE IF NOT EXISTS account_profiles (
                    account_id TEXT PRIMARY KEY, display_name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_notes (
                    id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, body TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
            """)
        self.quotas = BetaQuotas(self.connect)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def _create_account(db, label, now):
        account_id = uuid.uuid4().hex
        db.execute("INSERT INTO accounts VALUES (?, ?, 1, ?)", (account_id, label, now))
        return account_id

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
                account_id = self._create_account(db, label, now)
            db.execute("INSERT INTO invites(id,digest,account_id,expires_at) VALUES (?,?,?,?)",
                       (invite_id, digest(code), account_id, now + valid_for))
        return account_id, invite_id, code

    def issue_shared(self, capacity, valid_for):
        code = secrets.token_urlsafe(24)
        invite_id = uuid.uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO shared_invites(id,digest,expires_at,capacity) VALUES (?,?,?,?)",
                       (invite_id, digest(code), int(time.time()) + valid_for, capacity))
        return invite_id, code

    def redeem(self, code):
        code_digest = digest(code)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            now = int(time.time())
            row = db.execute("""
                SELECT i.account_id FROM invites i JOIN accounts a ON a.id=i.account_id
                WHERE i.digest=? AND i.used_at IS NULL AND i.revoked=0 AND i.expires_at>?
                    AND a.active=1
            """, (code_digest, now)).fetchone()
            if row:
                account_id = row[0]
                db.execute("UPDATE invites SET used_at=? WHERE digest=?", (now, code_digest))
            else:
                invite = db.execute("""
                    SELECT id FROM shared_invites i
                    WHERE i.digest=? AND i.revoked=0 AND i.expires_at>?
                        AND (SELECT COUNT(*) FROM shared_invite_redemptions WHERE invite_id=i.id) < i.capacity
                """, (code_digest, now)).fetchone()
                if not invite:
                    return None
                account_id = self._create_account(db, "", now)
                db.execute("INSERT INTO shared_invite_redemptions VALUES (?,?,?)", (account_id, invite[0], now))
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM logins WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO logins VALUES (?,?,?)", (digest(token), account_id, now + SESSION_SECONDS))
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

    def display_name(self, account_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT display_name FROM account_profiles WHERE account_id=?",
                             (account_id,)).fetchone()
        return row[0] if row else None

    def display_names(self):
        with closing(self.connect()) as db:
            return dict(db.execute("SELECT account_id, display_name FROM account_profiles"))

    def registration_times(self):
        with closing(self.connect()) as db:
            return dict(db.execute("""
                SELECT account_id, MIN(registered_at) FROM (
                    SELECT account_id, used_at AS registered_at FROM invites WHERE used_at IS NOT NULL
                    UNION ALL
                    SELECT account_id, registered_at FROM shared_invite_redemptions
                ) GROUP BY account_id
            """))

    def save_display_name(self, account_id, name):
        with closing(self.connect()) as db, db:
            return bool(db.execute("""
                INSERT INTO account_profiles(account_id, display_name)
                SELECT id, ? FROM accounts WHERE id=? AND active=1
                ON CONFLICT(account_id) DO UPDATE SET display_name=excluded.display_name
            """, (name, account_id)).rowcount)

    def add_account_note(self, account_id, text):
        with closing(self.connect()) as db, db:
            return bool(db.execute("""
                INSERT INTO account_notes(account_id, body, created_at)
                SELECT id, ?, ? FROM accounts WHERE id=?
            """, (text, int(time.time()), account_id)).rowcount)

    def account_notes(self):
        with closing(self.connect()) as db:
            notes = {}
            for account, text, created_at in db.execute("""
                SELECT account_id, body, created_at FROM account_notes ORDER BY id DESC
            """):
                notes.setdefault(account, []).append({"text": text, "created_at": created_at})
            return notes

    def revoke_invite(self, invite_id):
        with closing(self.connect()) as db, db:
            single = db.execute("UPDATE invites SET revoked=1 WHERE id=? AND used_at IS NULL",
                                (invite_id,)).rowcount
            shared = db.execute("UPDATE shared_invites SET revoked=1 WHERE id=?", (invite_id,)).rowcount
            return bool(single or shared)

    def revoke_account(self, account_id):
        with closing(self.connect()) as db, db:
            updated = db.execute("UPDATE accounts SET active=0 WHERE id=?", (account_id,)).rowcount
            db.execute("DELETE FROM logins WHERE account_id=?", (account_id,))
            return bool(updated)

    def accounts(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT id, label, active FROM accounts ORDER BY created_at, id").fetchall()
