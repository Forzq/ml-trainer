import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from qdrant_client import QdrantClient, models

from app.config import ROOT, Settings
from app.embeddings import Embeddings
from app.catalog import canonical_topic, load_cards
from app.rubric import prepare_card


class Store:
    def __init__(self, settings: Settings):
        self.cards = load_cards()
        self.by_id = {card["id"]: card for card in self.cards}
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings = Embeddings(settings)
        self.lock = threading.RLock()
        if settings.qdrant_url:
            self.vectors = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_key or None)
        else:
            self.vectors = QdrantClient(path=str(settings.data_dir / "qdrant"), force_disable_check_same_thread=True)
        self.db_path = settings.data_dir / "history.sqlite3"
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
            legacy = dict(self.by_id)
            if archive_path.is_file():
                legacy.update({int(key): value for key, value in json.loads(archive_path.read_text(encoding="utf-8")).items()})
            self.legacy_cards = legacy
            for session_id, raw_ids in db.execute("SELECT id,question_ids FROM sessions WHERE question_snapshots IS NULL").fetchall():
                snapshots = {str(identifier): prepare_card(legacy[identifier]) for identifier in json.loads(raw_ids) if identifier in legacy}
                db.execute("UPDATE sessions SET question_snapshots=? WHERE id=?",
                           (json.dumps(snapshots, ensure_ascii=False), session_id))
        self.collection = "ml_questions_" + hashlib.sha256(self.embeddings.name.encode()).hexdigest()[:12]
        self.seed()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def seed(self):
        with self.lock:
            exists = self.vectors.collection_exists(self.collection)
            existing, offset = {}, None
            if exists:
                while True:
                    page, offset = self.vectors.scroll(self.collection, limit=128, offset=offset, with_payload=True)
                    existing.update({point.id: point.payload for point in page})
                    if offset is None:
                        break
            if existing == self.by_id:
                return
            def text(card):
                return " ".join([card["topic"], card["title"], card["question"], " ".join(card["tags"])])
            changed = [card for card in self.cards
                       if card["id"] not in existing or text(existing[card["id"]]) != text(card)]
            # Preserve existing semantic vectors when only answers, criteria or level change.
            vectors = self.embeddings.encode([text(card) for card in changed]) if changed else []
            if not exists:
                self.vectors.create_collection(
                    self.collection,
                    vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE),
                )
            if changed:
                self.vectors.upsert(self.collection, points=[
                    models.PointStruct(id=card["id"], vector=vector, payload=card)
                    for card, vector in zip(changed, vectors, strict=True)
                ])
            embedded_ids = {card["id"] for card in changed}
            for card in self.cards:
                if card["id"] not in embedded_ids and existing.get(card["id"]) != card:
                    self.vectors.overwrite_payload(self.collection, payload=card, points=[card["id"]])
            # Remove deleted seed cards without touching any other collection.
            removed = list(existing.keys() - self.by_id.keys())
            if removed:
                self.vectors.delete(self.collection, points_selector=models.PointIdsList(points=removed))

    def search(self, query: str = "", topic: str = "all", level: str = "all") -> list[dict]:
        conditions = []
        if topic != "all":
            conditions.append(models.FieldCondition(key="topic_id", match=models.MatchValue(value=topic)))
        if level != "all":
            conditions.append(models.FieldCondition(key="level", match=models.MatchValue(value=level)))
        filters = models.Filter(must=conditions) if conditions else None
        with self.lock:
            if query.strip():
                found = self.vectors.query_points(
                    self.collection, query=self.embeddings.encode([query])[0],
                    query_filter=filters, limit=len(self.cards), with_payload=True,
                ).points
                return [dict(point.payload, similarity=round(point.score, 3)) for point in found]
            found, offset = [], None
            while True:
                page, offset = self.vectors.scroll(self.collection, scroll_filter=filters, limit=128,
                                                   offset=offset, with_payload=True)
                found.extend(page)
                if offset is None:
                    break
            return sorted([point.payload for point in found], key=lambda card: card["id"])

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

    def close(self):
        self.vectors.close()
