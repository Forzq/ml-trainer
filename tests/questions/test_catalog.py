import json
from collections import Counter
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.questions.catalog import GITHUB_QUESTION_TAG, MOCK_INTERVIEW_TAG, TOPICS, load_cards
from app.search.embeddings import Embeddings
from app.server import create_app
from app.storage.store import Store
from test_app import settings_at, authenticated


def test_bank_preserves_the_original_ids_and_topic_distribution():
    cards = load_cards()
    base = [card for card in cards if card["id"] <= 500]
    assert {card["id"] for card in base} == set(range(1, 501))
    original_topics = ("classical_ml", "data_science", "nlp", "cv", "dl")
    assert Counter(card["topic_id"] for card in base) == dict.fromkeys(original_topics, 100)
    for topic in original_topics:
        selected = [card for card in base if card["topic_id"] == topic]
        assert Counter(card["level"] for card in selected) == {"Junior": 40, "Middle": 40, "Senior": 20}
    assert all(2 <= len(card["criteria"]) <= 6 and sum(c["max_points"] for c in card["criteria"]) == 100 for card in cards)
    assert [card["title"] for card in cards[:6]] == ["Переобучение", "Разделение данных", "Precision и recall",
                                                    "Дисбаланс классов", "Линейная регрессия", "Регуляризация"]
    assert len({card["question"].casefold() for card in cards}) == len(cards)
    assert {card["interview_frequency"] for card in cards} == {1, 2, 3}


@pytest.mark.parametrize("failure", ["duplicate_id", "duplicate_question", "bad_level", "bad_topic", "bad_frequency", "missing_reference"])
def test_invalid_catalog_is_rejected(tmp_path, failure):
    cards = load_cards()[:2]
    if failure == "duplicate_id":
        cards[1]["id"] = cards[0]["id"]
    elif failure == "duplicate_question":
        cards[1]["question"] = cards[0]["question"]
    elif failure == "bad_level":
        cards[0]["level"] = "Basic"
    elif failure == "bad_topic":
        cards[0]["topic_id"] = "unknown"
    elif failure == "bad_frequency":
        cards[0]["interview_frequency"] = 4
    else:
        cards[0].pop("reference")
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(cards), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cards(path)


def test_topic_and_level_filters_apply_to_search_and_sessions(tmp_path):
    cards = load_cards()
    with TestClient(create_app(settings_at(tmp_path))) as client:
        config = client.get("/api/config").json()
        assert [topic["id"] for topic in config["topics"]] == [topic["id"] for topic in TOPICS]
        topic_counts = Counter(card["topic_id"] for card in cards)
        level_counts = Counter((card["topic_id"], card["level"]) for card in cards)
        assert {topic["id"]: topic["count"] for topic in config["topics"]} == topic_counts
        assert topic_counts["ml_system_design"] > 0
        headers = authenticated(client)
        for topic in (item["id"] for item in TOPICS):
            for level in ("Junior", "Middle", "Senior"):
                count = level_counts[topic, level]
                rows = client.get("/api/cards", params={"topic": topic, "level": level}).json()["cards"]
                assert len(rows) == count and all(card["level"] == level and card["topic_id"] == topic for card in rows)
                assert all(card["interview_frequency"] in (1, 2, 3) for card in rows)
                assert all("reference" not in card and "criteria" not in card for card in rows)
                found = client.get("/api/cards", params={"q": "оценка", "level": level, "topic": topic}).json()["cards"]
                assert found and all(card["level"] == level and card["topic_id"] == topic for card in found)
                state = client.post("/api/sessions", headers=headers,
                                    json={"topic": topic, "level": level, "count": 20}).json()
                session_size = min(20, count)
                assert state["total"] == session_size and state["question"]["level"] == level and state["question"]["topic_id"] == topic
                with client.app.state.store.connect() as db:
                    ids = json.loads(db.execute("SELECT question_ids FROM sessions WHERE id=?", (state["id"],)).fetchone()[0])
                assert len(set(ids)) == session_size
                assert all(client.app.state.store.by_id[question_id]["level"] == level for question_id in ids)
        assert client.post("/api/sessions", headers=headers, json={"topic": "unknown"}).status_code == 422
        assert client.get("/api/cards", params={"topic": "unknown"}).json()["cards"] == []
        assert client.post("/api/sessions", headers=headers, json={"level": "Expert"}).status_code == 422


@pytest.mark.parametrize(("tag", "source_field"), [
    (MOCK_INTERVIEW_TAG, "mock_sources"), (GITHUB_QUESTION_TAG, "github_sources"),
])
def test_source_tags_filter_qdrant_without_returning_references(tmp_path, tag, source_field):
    cards = load_cards()
    expected = [card for card in cards if tag in card["tags"]]
    unrelated = next(card for card in cards if tag not in card["tags"])
    assert any(card["id"] <= 500 for card in expected)
    assert any(card["id"] > 500 for card in expected)
    with patch("app.storage.store.load_cards", return_value=expected + [unrelated]), TestClient(create_app(settings_at(tmp_path))) as client:
        with patch.object(Embeddings, "encode", side_effect=AssertionError("An exact tag lookup should not call embeddings")):
            rows = client.get("/api/cards", params={"q": f" {tag.upper()} "}).json()["cards"]
            filtered = client.get("/api/cards", params={"q": tag, "topic": "nlp", "level": "Middle"}).json()["cards"]
        assert [row["id"] for row in rows] == sorted(card["id"] for card in expected)
        assert [row["id"] for row in filtered] == sorted(card["id"] for card in expected if card["topic_id"] == "nlp" and card["level"] == "Middle")
        assert all({"reference", "criteria", "mock_sources", "github_sources"}.isdisjoint(row) for row in rows)
        persisted = client.app.state.store.search(tag)
        assert all(row[source_field] and row["reference"] for row in persisted)


def test_pagination_beyond_100_and_unchanged_seed_does_not_reembed(tmp_path):
    cards = load_cards()
    expanded = cards + [dict(card, id=card["id"] + len(cards), question=card["question"] + " Обоснуй ответ.") for card in cards[:35]]
    with patch("app.storage.store.load_cards", return_value=expanded):
        store = Store(settings_at(tmp_path))
        try:
            assert len(store.search()) == len(expanded)
            assert len(store.search("модель")) == len(expanded)
        finally:
            store.close()
        with patch("app.search.embeddings.Embeddings.encode", side_effect=AssertionError("Unchanged bank must not be re-embedded")):
            store = Store(settings_at(tmp_path))
            try:
                assert store.vectors.count(store.collection, exact=True).count == len(expanded)
            finally:
                store.close()


def test_expansion_only_embeds_new_text_and_payload_edits_preserve_vectors(tmp_path):
    cards = load_cards()
    initial, expansion = cards[:2], cards[:3]
    with patch("app.storage.store.load_cards", return_value=initial):
        store = Store(settings_at(tmp_path))
        vector = store.vectors.retrieve(store.collection, ids=[1], with_vectors=True)[0].vector
        store.close()
    with patch("app.storage.store.load_cards", return_value=expansion), patch("app.search.embeddings.Embeddings.encode") as encode:
        encode.return_value = [[1.0] + [0.0] * 767]
        store = Store(settings_at(tmp_path))
        try:
            assert len(encode.call_args.args[0]) == 1
            assert cards[2]["question"] in encode.call_args.args[0][0]
            assert store.vectors.retrieve(store.collection, ids=[1], with_vectors=True)[0].vector == pytest.approx(vector, rel=1e-6, abs=1e-8)
        finally:
            store.close()
    changed = [dict(card, reference=card["reference"] + " Дополнение к ориентиру.", interview_frequency=1)
               for card in expansion]
    with patch("app.storage.store.load_cards", return_value=changed), patch("app.search.embeddings.Embeddings.encode", side_effect=AssertionError("Metadata edit must reuse vectors")):
        store = Store(settings_at(tmp_path))
        try:
            assert {card["id"]: card for card in store.search()} == {card["id"]: card for card in changed}
            assert store.vectors.retrieve(store.collection, ids=[1], with_vectors=True)[0].vector == pytest.approx(vector, rel=1e-6, abs=1e-8)
        finally:
            store.close()


def test_all_topics_sessions_balance_topics_and_keep_level_filter(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        headers = authenticated(client)
        # Even a heavily practiced topic must still be represented in a mixed session.
        with client.app.state.store.connect() as db:
            db.execute("INSERT INTO sessions(id,topic,question_ids) VALUES('old','classical_ml','[1]')")
            db.executemany(
                "INSERT INTO attempts(session_id,question_id,answer,feedback,score,mode) VALUES('old',?,'','{}',0,'skipped')",
                [(card["id"],) for card in client.app.state.store.cards if card["topic_id"] == "classical_ml"],
            )
        for level in ("all", "Junior", "Middle", "Senior"):
            for count in (2, 4, 5, 7, 20):
                response = client.post("/api/sessions", headers=headers, json={"topic": "all", "level": level, "count": count})
                assert response.status_code == 200
                state = response.json()
                with client.app.state.store.connect() as db:
                    ids = json.loads(db.execute("SELECT question_ids FROM sessions WHERE id=?", (state["id"],)).fetchone()[0])
                cards = [client.app.state.store.by_id[question_id] for question_id in ids]
                assert len(ids) == len(set(ids)) == count
                assert level == "all" or all(card["level"] == level for card in cards)
                counts = Counter(card["topic_id"] for card in cards)
                sizes = [counts[topic["id"]] for topic in TOPICS]
                assert max(sizes) - min(sizes) <= 1
                assert state["question"]["topic_id"] != "classical_ml"


def test_short_mixed_sessions_rotate_after_practice_and_restart(tmp_path):
    settings = settings_at(tmp_path)
    practiced = Counter()
    question_ids = []

    def complete_short_session(client):
        headers = authenticated(client)
        state = client.post("/api/sessions", headers=headers, json={"topic": "all", "count": 2}).json()
        for _ in range(2):
            practiced[state["question"]["topic_id"]] += 1
            question_ids.append(state["question"]["id"])
            endpoint = f"/api/sessions/{state['id']}"
            client.post(endpoint + "/answer", headers=headers,
                        json={"question_id": state["question"]["id"], "skip": True}).raise_for_status()
            response = client.post(endpoint + "/next", headers=headers,
                                   json={"question_id": state["question"]["id"]})
            response.raise_for_status()
            state = response.json()
        assert state["completed"]

    with TestClient(create_app(settings)) as client:
        complete_short_session(client)
    with TestClient(create_app(settings)) as client:
        for _ in range(len(TOPICS) - 1):
            complete_short_session(client)
    assert practiced == {topic["id"]: 2 for topic in TOPICS}
    assert len(question_ids) == len(set(question_ids)) == 2 * len(TOPICS)
