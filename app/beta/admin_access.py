"""Password verification and server-side sessions for the beta administrator."""
import hashlib
import hmac
import secrets
import time
from contextlib import closing
from threading import BoundedSemaphore

from app.beta.access import digest
from app.beta.quotas import UsageLimit

ADMIN_COOKIE = "__Host-mockroom-admin"
ADMIN_SESSION_SECONDS = 8 * 60 * 60


def password_hash(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**15, r=8, p=3,
                          maxmem=64 * 1024 * 1024, dklen=32)


class AdminAccess:
    def __init__(self, connect):
        self.connect = connect
        self.password_check = BoundedSemaphore(1)
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS beta_admin (
                    id INTEGER PRIMARY KEY CHECK(id = 1), login TEXT NOT NULL,
                    salt BLOB NOT NULL, password_hash BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS beta_admin_sessions (
                    digest TEXT PRIMARY KEY, expires_at INTEGER NOT NULL
                );
            """)

    def set_credentials(self, login, password, *, replace=False):
        login = login.strip()
        if not 1 <= len(login) <= 64 or not 12 <= len(password) <= 256:
            raise ValueError("Логин должен содержать до 64 символов, пароль — от 12 до 256 символов.")
        salt = secrets.token_bytes(16)
        encoded = password_hash(password, salt)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not replace and db.execute("SELECT 1 FROM beta_admin").fetchone():
                raise ValueError("Администратор уже настроен.")
            db.execute("""
                INSERT INTO beta_admin VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET login=excluded.login, salt=excluded.salt,
                    password_hash=excluded.password_hash
            """, (login, salt, encoded))
            db.execute("DELETE FROM beta_admin_sessions")

    def login(self, login, password):
        if not self.password_check.acquire(blocking=False):
            raise UsageLimit("Проверка входа занята. Попробуй через пару секунд.", 2)
        try:
            with closing(self.connect()) as db:
                row = db.execute("SELECT login, salt, password_hash FROM beta_admin").fetchone()
            if not row:
                return None
            name, salt, expected = row
            valid_password = hmac.compare_digest(password_hash(password, salt), expected)
            if not valid_password or not hmac.compare_digest(login.strip().encode(), name.encode()):
                return None
            token = secrets.token_urlsafe(32)
            now = int(time.time())
            with closing(self.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM beta_admin_sessions WHERE expires_at<=?", (now,))
                created = db.execute("""
                    INSERT INTO beta_admin_sessions
                    SELECT ?, ? WHERE EXISTS (SELECT 1 FROM beta_admin WHERE password_hash=?)
                """, (digest(token), now + ADMIN_SESSION_SECONDS, expected)).rowcount
            return token if created else None
        finally:
            self.password_check.release()

    def authenticate(self, token):
        if not token or len(token) != 43:
            return False
        with closing(self.connect()) as db:
            return bool(db.execute("SELECT 1 FROM beta_admin_sessions WHERE digest=? AND expires_at>?",
                                   (digest(token), int(time.time()))).fetchone())

    def logout(self, token):
        with closing(self.connect()) as db, db:
            db.execute("DELETE FROM beta_admin_sessions WHERE digest=?", (digest(token),))
