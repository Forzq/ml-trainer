import json
from collections import Counter
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.catalog import TOPICS, load_cards
from app.server import create_app
from app.store import Store
from test_app import settings_at, authenticated


def test_bank_has_500_unique_complete_questions_and_preserves_original_ids():
    cards = load_cards()
    assert len(cards) == 500
    assert {card["id"] for card in cards} == set(range(1, 501))
    assert Counter(card["topic_id"] for card in cards) == {topic["id"]: 100 for topic in TOPICS}
    for topic in (item["id"] for item in TOPICS):
        selected = [card for card in cards if card["topic_id"] == topic]
        assert Counter(card["level"] for card in selected) == {"Junior": 40, "Middle": 40, "Senior": 20}
    assert all(len(card["criteria"]) == 3 for card in cards)
    assert [card["title"] for card in cards[:6]] == ["Переобучение", "Разделение данных", "Precision и recall",
                                                    "Дисбаланс классов", "Линейная регрессия", "Регуляризация"]
    assert len({card["question"].casefold() for card in cards}) == 500


@pytest.mark.parametrize("failure", ["duplicate_id", "duplicate_question", "bad_level", "bad_topic", "missing_reference"])
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
    else:
        cards[0].pop("reference")
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(cards), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cards(path)


def test_topic_and_level_filters_apply_to_search_and_sessions(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        config = client.get("/api/config").json()
        assert [topic["id"] for topic in config["topics"]] == [topic["id"] for topic in TOPICS]
        assert config["topics"][0]["levels"] == {"Junior": 40, "Middle": 40, "Senior": 20}
        assert [topic["count"] for topic in config["topics"]] == [100, 100, 100, 100, 100]
        headers = authenticated(client)
        for topic in (item["id"] for item in TOPICS):
            for level, count in [("Junior", 40), ("Middle", 40), ("Senior", 20)]:
                rows = client.get("/api/cards", params={"topic": topic, "level": level}).json()["cards"]
                assert len(rows) == count and all(card["level"] == level and card["topic_id"] == topic for card in rows)
                assert all("reference" not in card and "criteria" not in card for card in rows)
                found = client.get("/api/cards", params={"q": "оценка", "level": level, "topic": topic}).json()["cards"]
                assert found and all(card["level"] == level and card["topic_id"] == topic for card in found)
                state = client.post("/api/sessions", headers=headers,
                                    json={"topic": topic, "level": level, "count": 20}).json()
                assert state["total"] == 20 and state["question"]["level"] == level and state["question"]["topic_id"] == topic
                with client.app.state.store.connect() as db:
                    ids = json.loads(db.execute("SELECT question_ids FROM sessions WHERE id=?", (state["id"],)).fetchone()[0])
                assert len(set(ids)) == 20
                assert all(client.app.state.store.by_id[question_id]["level"] == level for question_id in ids)
        assert client.post("/api/sessions", headers=headers, json={"topic": "unknown"}).status_code == 422
        assert client.get("/api/cards", params={"topic": "unknown"}).json()["cards"] == []
        assert client.post("/api/sessions", headers=headers, json={"level": "Expert"}).status_code == 422


def test_pagination_beyond_100_and_unchanged_seed_does_not_reembed(tmp_path):
    cards = load_cards()
    expanded = cards + [dict(card, id=card["id"] + len(cards), question=card["question"] + " Обоснуй ответ.") for card in cards[:35]]
    with patch("app.store.load_cards", return_value=expanded):
        store = Store(settings_at(tmp_path))
        try:
            assert len(store.search()) == 535
            assert len(store.search("модель")) == 535
        finally:
            store.close()
        with patch("app.embeddings.Embeddings.encode", side_effect=AssertionError("Unchanged bank must not be re-embedded")):
            store = Store(settings_at(tmp_path))
            try:
                assert store.vectors.count(store.collection, exact=True).count == 535
            finally:
                store.close()


def test_expansion_only_embeds_new_text_and_payload_edits_preserve_vectors(tmp_path):
    cards = load_cards()
    initial, expansion = cards[:2], cards[:3]
    with patch("app.store.load_cards", return_value=initial):
        store = Store(settings_at(tmp_path))
        vector = store.vectors.retrieve(store.collection, ids=[1], with_vectors=True)[0].vector
        store.close()
    with patch("app.store.load_cards", return_value=expansion), patch("app.embeddings.Embeddings.encode") as encode:
        encode.return_value = [[1.0] + [0.0] * 767]
        store = Store(settings_at(tmp_path))
        try:
            assert len(encode.call_args.args[0]) == 1
            assert cards[2]["question"] in encode.call_args.args[0][0]
            assert store.vectors.retrieve(store.collection, ids=[1], with_vectors=True)[0].vector == pytest.approx(vector, rel=1e-6, abs=1e-8)
        finally:
            store.close()
    changed = [dict(card, reference=card["reference"] + " Дополнение к ориентиру.") for card in expansion]
    with patch("app.store.load_cards", return_value=changed), patch("app.embeddings.Embeddings.encode", side_effect=AssertionError("Metadata edit must reuse vectors")):
        store = Store(settings_at(tmp_path))
        try:
            assert {card["id"]: card for card in store.search()} == {card["id"]: card for card in changed}
            assert store.vectors.retrieve(store.collection, ids=[1], with_vectors=True)[0].vector == pytest.approx(vector, rel=1e-6, abs=1e-8)
        finally:
            store.close()
