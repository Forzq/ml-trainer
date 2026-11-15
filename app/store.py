import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from qdrant_client import QdrantClient, models

from app.config import ROOT, Settings
from app.embeddings import Embeddings


class Store:
    def __init__(self, settings: Settings):
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
            """)
        self.cards = json.loads((ROOT / "content" / "questions.json").read_text(encoding="utf-8"))
        self.by_id = {card["id"]: card for card in self.cards}
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
            if self.vectors.collection_exists(self.collection):
                existing, _ = self.vectors.scroll(self.collection, limit=max(100, len(self.cards) + 1), with_payload=True)
                if {point.id: point.payload for point in existing} == self.by_id:
                    return
            texts = [" ".join([c["topic"], c["title"], c["question"], " ".join(c["tags"])]) for c in self.cards]
            vectors = self.embeddings.encode(texts)
            if not self.vectors.collection_exists(self.collection):
                self.vectors.create_collection(
                    self.collection,
                    vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE),
                )
            self.vectors.upsert(self.collection, points=[
                models.PointStruct(id=card["id"], vector=vector, payload=card)
                for card, vector in zip(self.cards, vectors, strict=True)
            ])
            # Remove deleted seed cards without touching any other collection.
            self.vectors.delete(self.collection, points_selector=models.FilterSelector(filter=models.Filter(
                must_not=[models.HasIdCondition(has_id=list(self.by_id))]
            )))

    def search(self, query: str = "", topic: str = "all") -> list[dict]:
        filters = None if topic == "all" else models.Filter(must=[
            models.FieldCondition(key="topic_id", match=models.MatchValue(value=topic))
        ])
        with self.lock:
            if query.strip():
                found = self.vectors.query_points(
                    self.collection, query=self.embeddings.encode([query])[0],
                    query_filter=filters, limit=100, with_payload=True,
                ).points
                return [dict(point.payload, similarity=round(point.score, 3)) for point in found]
            found, _ = self.vectors.scroll(self.collection, scroll_filter=filters, limit=100, with_payload=True)
            return sorted([point.payload for point in found], key=lambda card: card["id"])

    def history(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("""
                SELECT s.id, s.topic, s.created_at, s.completed_at,
                    COUNT(a.id) AS answered, ROUND(AVG(a.score)) AS score
                FROM sessions s LEFT JOIN attempts a ON a.session_id=s.id
                GROUP BY s.id ORDER BY s.created_at DESC, s.rowid DESC LIMIT 30
            """)]

    def close(self):
        self.vectors.close()
