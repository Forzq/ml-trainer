"""SQLite history, connections and backward-compatible schema migrations."""
import json
import sqlite3
from contextlib import contextmanager
from app.core.config import ROOT
from app.questions.catalog import canonical_topic
from app.questions.rubric import prepare_card


class HistoryRepository:
    def __init__(self, db_path, cards_by_id):
        self.db_path = db_path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, topic TEXT NOT NULL, question_ids TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, question_id INTEGER NOT NULL,
                    answer TEXT NOT NULL, feedback TEXT NOT NULL, score INTEGER NOT NULL,
                    mode TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, question_id)
                );
                CREATE TABLE IF NOT EXISTS discussions (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, question_id INTEGER NOT NULL,
                    message TEXT NOT NULL, reply TEXT NOT NULL, mode TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS discussions_question ON discussions(session_id, question_id, id);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
            if "current_index" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN current_index INTEGER NOT NULL DEFAULT 0")
                # Old versions advanced immediately after grading. Preserve their pending question.
                for session_id, raw_ids in db.execute("SELECT id, question_ids FROM sessions").fetchall():
                    ids = json.loads(raw_ids)
                    done = {row[0] for row in db.execute("SELECT question_id FROM attempts WHERE session_id=?", (session_id,))}
                    index = next((i for i, question_id in enumerate(ids) if question_id not in done), max(0, len(ids) - 1))
                    db.execute("UPDATE sessions SET current_index=? WHERE id=?", (index, session_id))
            if "profile" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN profile TEXT NOT NULL DEFAULT '{}'")
            if "question_snapshots" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN question_snapshots TEXT")
            # Preserve the pre-edit conditions/rubrics for historical sessions before seeding new cards.
            archive_path = ROOT / "content/question-versions-v1.json"
            legacy = dict(cards_by_id)
            if archive_path.is_file():
                legacy.update({int(key): value for key, value in json.loads(archive_path.read_text(encoding="utf-8")).items()})
            self.legacy_cards = legacy
            for session_id, raw_ids in db.execute("SELECT id,question_ids FROM sessions WHERE question_snapshots IS NULL").fetchall():
                snapshots = {str(identifier): prepare_card(legacy[identifier]) for identifier in json.loads(raw_ids) if identifier in legacy}
                db.execute("UPDATE sessions SET question_snapshots=? WHERE id=?",
                           (json.dumps(snapshots, ensure_ascii=False), session_id))

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def stats(self):
        with self.connect() as db:
            sessions, completed, answered = db.execute("""
                SELECT COUNT(*), COUNT(completed_at), (SELECT COUNT(*) FROM attempts)
                FROM sessions
            """).fetchone()
        return {"sessions": sessions, "completed": completed, "answered": answered}

    def history(self, page: int = 1, page_size: int = 30):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            total = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            total_pages = max(1, (total + page_size - 1) // page_size)
            page = min(page, total_pages)
            sessions = [dict(row, topic=canonical_topic(row["topic"])) for row in db.execute("""
                SELECT s.id, s.topic, s.created_at, s.completed_at,
                    COUNT(a.id) AS answered, ROUND(AVG(a.score)) AS score
                FROM sessions s LEFT JOIN attempts a ON a.session_id=s.id
                GROUP BY s.id ORDER BY s.created_at DESC, s.rowid DESC LIMIT ? OFFSET ?
            """, (page_size, (page - 1) * page_size))]
        return {"sessions": sessions, "page": page, "page_size": page_size,
                "total": total, "total_pages": total_pages}
