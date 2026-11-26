from contextlib import closing

from fastapi.testclient import TestClient

from app.beta.access import BetaAccess
from app.progress.catalog import ProgressCatalog
from app.questions.catalog import load_cards
from app.server import create_app
from test_beta import HEADERS, ORIGIN, settings_at


def test_learning_map_covers_current_bank():
    cards = load_cards()
    progress = ProgressCatalog(cards).snapshot({})
    groups = [group for topic in progress["topics"] for group in topic["skills"]]
    mapped = [question["id"] for group in groups for question in group["questions"]]
    assert sorted(mapped) == sorted(card["id"] for card in cards)
    assert all(group["summary"] for group in groups)


def test_progress_uses_best_ai_grade_and_keeps_accounts_separate(tmp_path, monkeypatch):
    cards = load_cards()[:5]
    monkeypatch.setattr("app.storage.store.load_cards", lambda: cards)
    app = create_app(settings_at(tmp_path))
    access = BetaAccess(tmp_path / "beta.sqlite3")
    first_owner, _, first_code = access.issue("First", 60)
    second_owner, _, second_code = access.issue("Second", 60)

    with TestClient(app, base_url=ORIGIN) as first, closing(TestClient(app, base_url=ORIGIN)) as second:
        assert first.get("/api/progress").status_code == 401
        for client, code in ((first, first_code), (second, second_code)):
            assert client.post("/api/beta/redeem", headers=HEADERS, json={"code": code}).status_code == 200
        with app.state.store.connect() as db:
            for index in range(33):
                identifier = f"attempt-{index}"
                db.execute("INSERT INTO sessions(id, topic, question_ids, owner_id) VALUES (?, 'classical_ml', '[1]', ?)",
                           (identifier, first_owner))
                db.execute("INSERT INTO attempts(session_id, question_id, answer, feedback, score, mode) VALUES (?, 1, '', '{}', ?, 'ai')",
                           (identifier, 85 if index == 0 else 60))
            db.executemany("INSERT INTO sessions(id, topic, question_ids, owner_id) VALUES (?, 'classical_ml', '[2,3,4,5]', ?)",
                           [("first-more", first_owner), ("second-only", second_owner)])
            db.executemany("INSERT INTO attempts(session_id, question_id, answer, feedback, score, mode) VALUES (?, ?, '', '{}', ?, ?)",
                           [("first-more", 2, 70, "ai"), ("first-more", 3, 69, "ai"), ("first-more", 4, 100, "demo"),
                            ("first-more", 5, 100, "skipped"), ("second-only", 3, 100, "ai")])

        result = first.get("/api/progress").json()
        assert result["mastery_score"] == 70
        assert result["totals"] == {"mastered": 2, "attempted": 4, "total": 5}
        topic = result["topics"][0]
        assert topic["coverage"] == 33
        questions = {q["id"]: q for group in topic["skills"] for q in group["questions"]}
        assert [questions[key]["best_score"] for key in range(1, 6)] == [85, 70, 69, None, None]
        assert questions[4]["attempted"] and not questions[5]["attempted"]
        assert second.get("/api/progress").json()["totals"] == {"mastered": 1, "attempted": 1, "total": 5}

        body = {"topic": "classical_ml", "skill": "metrics", "count": 20}
        response = first.post("/api/sessions", headers=HEADERS, json=body)
        assert response.status_code == 200
        assert response.json()["total"] == 2 and response.json()["question"]["id"] in {3, 4}
        assert first.post("/api/sessions", headers=HEADERS, json=body | {"topic": "data_science"}).status_code == 422
