"""Persistent beta quotas with fixed windows and atomic reservations."""
import time
from contextlib import closing

DAY_SECONDS = 86400
PROVIDER_SCOPE = "provider"
GLOBAL = "global"
DEFAULT_ACCOUNT = "default-account"


class UsageLimit(Exception):
    def __init__(self, detail, retry_after):
        super().__init__(detail)
        self.retry_after = retry_after


def window_end(now, window):
    return now - now % window + window


def account_subject(account_id):
    return "account:" + account_id


class BetaQuotas:
    def __init__(self, connect):
        self.connect = connect
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS usage (
                    scope TEXT NOT NULL, subject TEXT NOT NULL, expires_at INTEGER NOT NULL,
                    count INTEGER NOT NULL, PRIMARY KEY(scope, subject, expires_at)
                );
                CREATE TABLE IF NOT EXISTS beta_daily_limits (
                    subject TEXT PRIMARY KEY, maximum INTEGER NOT NULL CHECK(maximum >= 0)
                );
            """)

    def consume_provider(self, account_id, account_limit, total_limit):
        self.consume(PROVIDER_SCOPE, [(account_subject(account_id), account_limit), (GLOBAL, total_limit)],
                     window=DAY_SECONDS, message="Достигнут дневной лимит запросов. Попробуй завтра.")

    def consume(self, scope, limits, *, window, message):
        """Reserve one unit from every applicable bucket in a single transaction."""
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            now = int(time.time())
            end = window_end(now, window)
            db.execute("DELETE FROM usage WHERE expires_at<=?", (now,))
            for subject, limit in limits:
                if scope == PROVIDER_SCOPE:
                    limit = self._provider_limit(db, subject, limit)
                row = db.execute("SELECT count FROM usage WHERE scope=? AND subject=? AND expires_at=?",
                                 (scope, subject, end)).fetchone()
                if (row[0] if row else 0) >= limit:
                    raise UsageLimit(message, end - now)
                db.execute("""
                    INSERT INTO usage VALUES (?,?,?,1)
                    ON CONFLICT(scope, subject, expires_at) DO UPDATE SET count=count+1
                """, (scope, subject, end))

    @staticmethod
    def _provider_limit(db, subject, fallback):
        default_subject = GLOBAL if subject == GLOBAL else DEFAULT_ACCOUNT
        row = db.execute("""
            SELECT maximum FROM beta_daily_limits WHERE subject IN (?, ?)
            ORDER BY subject = ? DESC LIMIT 1
        """, (subject, default_subject, subject)).fetchone()
        return row[0] if row is not None else fallback

    def set_provider_limit(self, subject, maximum):
        """Change the cap without changing usage. None restores the inherited limit."""
        if maximum is not None and not 0 <= maximum <= 2**63 - 1:
            raise ValueError("Daily limit must be a non-negative SQLite integer.")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if subject not in (GLOBAL, DEFAULT_ACCOUNT):
                account_id = subject.removeprefix("account:")
                if subject != account_subject(account_id) or not db.execute(
                    "SELECT 1 FROM accounts WHERE id=?", (account_id,),
                ).fetchone():
                    raise ValueError("Account not found.")
            if maximum is None:
                db.execute("DELETE FROM beta_daily_limits WHERE subject=?", (subject,))
            else:
                db.execute("""
                    INSERT INTO beta_daily_limits VALUES (?, ?)
                    ON CONFLICT(subject) DO UPDATE SET maximum=excluded.maximum
                """, (subject, maximum))

    def reset_account_usage(self, account_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
                return False
            end = window_end(int(time.time()), DAY_SECONDS)
            db.execute("DELETE FROM usage WHERE scope=? AND subject=? AND expires_at=?",
                       (PROVIDER_SCOPE, account_subject(account_id), end))
            return True

    def account_quota(self, account_id, account_limit, total_limit):
        subject = account_subject(account_id)
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            end = window_end(int(time.time()), DAY_SECONDS)
            counts = dict(db.execute("""
                SELECT subject, count FROM usage WHERE scope=? AND expires_at=? AND subject IN (?, ?)
            """, (PROVIDER_SCOPE, end, subject, GLOBAL)))
            limit = self._provider_limit(db, subject, account_limit)
            shared_limit = self._provider_limit(db, GLOBAL, total_limit)
            remaining = max(0, min(limit - counts.get(subject, 0), shared_limit - counts.get(GLOBAL, 0)))
            return {"limit": limit, "remaining": remaining, "reset_at": end}

    def provider_usage(self, account_limit, total_limit):
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            end = window_end(int(time.time()), DAY_SECONDS)
            overrides = dict(db.execute("SELECT subject, maximum FROM beta_daily_limits"))
            counts = dict(db.execute("SELECT subject, count FROM usage WHERE scope=? AND expires_at=?",
                                     (PROVIDER_SCOPE, end)))
            accounts = db.execute("SELECT id, label, active FROM accounts ORDER BY created_at, id")
            default_limit = overrides.get(DEFAULT_ACCOUNT, account_limit)
            rows = []
            for account, label, active in accounts:
                subject = account_subject(account)
                rows.append((account, label, active, counts.get(subject, 0),
                             overrides.get(subject, default_limit), subject in overrides))
            return counts.get(GLOBAL, 0), overrides.get(GLOBAL, total_limit), default_limit, end, rows
