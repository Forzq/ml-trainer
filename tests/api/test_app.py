from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.questions.catalog import load_cards
from app.search.embeddings import Embeddings
from app.server import create_app


def settings_at(path: Path):
    return Settings(data_dir=path, deepgram_key="", openai_key="", openrouter_key="", model="", embedding_model="", qdrant_url="", qdrant_key="", tts_provider="system", fish_key="")


def authenticated(client):
    return {"X-App-Token": client.get("/api/config").json()["token"]}


def test_vectors_search_and_topics(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        assert client.get("/").status_code == 200
        config = client.get("/api/config").json()
        assert config["cards"] == len(load_cards())
        assert config["database"] == "Qdrant Local"
        assert not config["ai"]
        found = client.get("/api/cards", params={"q": "переобучение"}).json()["cards"]
        assert found[0]["title"] == "Переобучение"
        assert "reference" not in found[0]
        rows = client.get("/api/cards", params={"topic": "classical_ml"}).json()["cards"]
        assert len(rows) == config["topics"][0]["count"]
        assert all(card["topic_id"] == "classical_ml" for card in rows)


def test_full_session_and_history_survive_restart(tmp_path):
    settings = settings_at(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = authenticated(client)
        state = client.post("/api/sessions", json={"topic": "classical_ml", "count": 2}, headers=headers).json()
        session_id = state["id"]
        assert state["total"] == 2
        response = client.post(f"/api/sessions/{session_id}/answer", headers=headers, json={
            "question_id": state["question"]["id"], "answer": "Модель запоминает шум обучающих данных и хуже работает на новых. Сравним качество с валидацией.",
        })
        assert response.status_code == 200
        result = response.json()
        assert result["evaluation"]["mode"] == "demo"
        assert result["evaluation"]["score"] == 100
        assert result["session"]["answered"] == 1
        assert result["session"]["reviewing"] and not result["session"]["completed"]
        state = client.post(f"/api/sessions/{session_id}/next", headers=headers,
                            json={"question_id": result["session"]["question"]["id"]}).json()
        response = client.post(f"/api/sessions/{session_id}/answer", headers=headers, json={"question_id": state["question"]["id"], "skip": True})
        assert not response.json()["session"]["completed"]
        assert response.json()["session"]["reviewing"]
        assert client.post(f"/api/sessions/{session_id}/next", headers=headers,
                           json={"question_id": state["question"]["id"]}).json()["completed"]
        assert client.get("/api/history").json()["sessions"][0]["completed_at"]
    with TestClient(create_app(settings)) as client:
        state = client.get(f"/api/sessions/{session_id}").json()
        assert state["completed"]
        assert len(state["attempts"]) == 2
        assert state["attempts"][0]["answer"].startswith("Модель")
        assert client.get("/api/config").json()["cards"] == len(load_cards())


def test_validation_duplicate_answers_and_local_request_protection(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        assert client.post("/api/sessions", json={}).status_code == 403
        headers = authenticated(client)
        assert client.post("/api/sessions", json={}, headers=dict(headers, Origin="https://example.org")).status_code == 403
        assert client.post("/api/sessions", json={"topic": "unknown"}, headers=headers).status_code == 422
        state = client.post("/api/sessions", json={"count": 1}, headers=headers).json()
        endpoint = f"/api/sessions/{state['id']}/answer"
        assert client.post(endpoint, json={"question_id": 1, "answer": " "}, headers=headers).status_code == 422
        payload = {"question_id": state["question"]["id"], "answer": "Новые данные и валидация"}
        assert client.post(endpoint, json=payload, headers=headers).status_code == 200
        assert client.post(endpoint, json=payload, headers=headers).status_code == 409
        assert client.post("/api/transcribe", files={"audio": ("a.webm", b"abc", "audio/webm")}, headers=headers).status_code == 409


def test_finish_early_and_rotating_question_selection(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        headers = authenticated(client)
        state = client.post("/api/sessions", json={"topic": "classical_ml", "count": 2}, headers=headers).json()
        first_id = state["question"]["id"]
        client.post(f"/api/sessions/{state['id']}/answer", json={"question_id": first_id, "skip": True}, headers=headers)
        finished = client.post(f"/api/sessions/{state['id']}/finish", headers=headers).json()
        assert finished["completed"] and finished["answered"] == 1
        next_session = client.post("/api/sessions", json={"topic": "classical_ml", "count": 1}, headers=headers).json()
        assert next_session["question"]["id"] != first_id






def test_ai_response_validation_and_no_silent_demo_fallback(tmp_path, caplog):
    settings = settings_at(tmp_path)
    settings.model = "test-model"
    settings.openrouter_key = "secret-not-for-browser"
    with TestClient(create_app(settings)) as client:
        headers = authenticated(client)
        assert "secret-not-for-browser" not in client.get("/api/config").text
        state = client.post("/api/sessions", json={"count": 1}, headers=headers).json()
        endpoint = f"/api/sessions/{state['id']}/answer"
        payload = {"question_id": state["question"]["id"], "answer": "мой ответ"}
        with patch("app.integrations.openrouter.httpx.Client") as provider:
            provider.return_value.__enter__.return_value.post.return_value.status_code = 200
            provider.return_value.__enter__.return_value.post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"score":999,"feedback":"bad","covered":[],"missing":[]}'}}]
            }
            assert client.post(endpoint, json=payload, headers=headers).status_code == 502
        assert client.get(f"/api/sessions/{state['id']}").json()["answered"] == 0
        assert "Model response rejected" in caplog.text
        assert "Model call failed: operation=evaluate" in caplog.text
        assert "secret-not-for-browser" not in caplog.text
        assert "мой ответ" not in caplog.text
