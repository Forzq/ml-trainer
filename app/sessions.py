"""Read session snapshots and reconstruct attempts and discussions for the API."""
import json

from fastapi import HTTPException

from app.catalog import TOPICS, canonical_topic
from app.rubric import prepare_card


def public_card(card):
    """Expose question context without leaking its reference or grading criteria."""
    return {**{key: card[key] for key in ("id", "topic_id", "topic", "title", "question", "level", "tags")},
            "followups": card.get("followups", []), "rubric_version": card.get("rubric_version")}


class SessionReader:
    def __init__(self, store):
        self.store = store

    def state(self, session_id):
        store = self.store
        with store.connect() as db:
            row = db.execute("SELECT id, topic, question_ids, completed_at, current_index,profile,question_snapshots FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Тренировка не найдена.")
            attempts = db.execute(
                "SELECT question_id, answer, feedback, score, mode FROM attempts WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
            turns = db.execute(
                "SELECT id, question_id, message, reply, mode, created_at FROM discussions WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        ids = json.loads(row[2])
        done = {a[0] for a in attempts}
        index = min(row[4], max(0, len(ids) - 1))
        active_id = ids[index] if ids else None
        if row[6] is None:
            # Imports or older writers can still create legacy rows after startup.
            saved = {str(identifier): prepare_card(store.legacy_cards[identifier]) for identifier in ids if identifier in store.legacy_cards}
            with store.connect() as db:
                db.execute("UPDATE sessions SET question_snapshots=? WHERE id=? AND question_snapshots IS NULL",
                           (json.dumps(saved, ensure_ascii=False), session_id))
            snapshots = {int(key): value for key, value in saved.items()}
        else:
            snapshots = {int(key): value for key, value in json.loads(row[6]).items()}
        profile = json.loads(row[5] or "{}") or {"candidate_level": "Middle", "specialization": next((t["name"] for t in TOPICS if t["id"] == canonical_topic(row[1])), "Общий ML / Data Science")}
        complete = bool(row[3]) or active_id not in snapshots
        return {
            "id": row[0], "topic": canonical_topic(row[1]), "total": len(ids), "answered": len(attempts),
            "completed": complete, "current_index": index,
            "reviewing": not complete and active_id in done,
            "profile": profile,
            "question": public_card(snapshots[active_id]) if not complete else None,
            "attempts": [{**json.loads(a[2]), "question": public_card(snapshots[a[0]]),
                          "answer": a[1], "score": a[3], "mode": a[4],
                          "discussion": [{"id": t[0], "message": t[2], "reply": t[3], "mode": t[4], "created_at": t[5]}
                                         for t in turns if t[1] == a[0]]} for a in attempts if a[0] in snapshots],
        }

    def card(self, session_id, question_id):
        with self.store.connect() as db:
            raw = db.execute("SELECT question_snapshots FROM sessions WHERE id=?", (session_id,)).fetchone()[0]
        return json.loads(raw)[str(question_id)]

