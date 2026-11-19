"""Qdrant question indexing and filtered retrieval."""
import hashlib
import threading
from qdrant_client import QdrantClient, models


class QuestionIndex:
    def __init__(self, settings, cards, embeddings):
        self.cards = cards
        self.by_id = {card["id"]: card for card in cards}
        self.embeddings = embeddings
        self.lock = threading.RLock()
        if settings.qdrant_url:
            self.vectors = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_key or None)
        else:
            self.vectors = QdrantClient(path=str(settings.data_dir / "qdrant"), force_disable_check_same_thread=True)
        self.collection = "ml_questions_" + hashlib.sha256(embeddings.name.encode()).hexdigest()[:12]

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

    def close(self):
        self.vectors.close()
