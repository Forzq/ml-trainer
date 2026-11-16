import json
import sqlite3
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.server import create_app
from test_app import authenticated, settings_at


def start(client, headers, count=2):
    return client.post("/api/sessions", json={"topic": "classical_ml", "count": count}, headers=headers).json()


def answer(client, headers, state, text="Модель запоминает шум обучающей выборки."):
    response = client.post(f"/api/sessions/{state['id']}/answer", headers=headers,
                           json={"question_id": state["question"]["id"], "answer": text})
    assert response.status_code == 200
    return response.json()["session"]


def test_question_stays_open_for_multiple_messages_and_survives_restart(tmp_path):
    settings = settings_at(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = authenticated(client)
        state = start(client, headers)
        question_id = state["question"]["id"]
        state = answer(client, headers, state)
        assert state["question"]["id"] == question_id
        assert state["current_index"] == 0 and state["reviewing"] and not state["completed"]
        score = state["attempts"][0]["score"]
        for text in ["Я это уже упомянул. Почему ты считаешь ответ неполным?", "Покажи конкретный пример."]:
            response = client.post(f"/api/sessions/{state['id']}/discuss", headers=headers,
                                   json={"question_id": question_id, "message": text})
            assert response.status_code == 200
            state = response.json()["session"]
            assert state["question"]["id"] == question_id
            assert state["answered"] == 1
            assert state["attempts"][0]["score"] == score
        assert len(state["attempts"][0]["discussion"]) == 2
        session_id = state["id"]
    with TestClient(create_app(settings)) as client:
        restored = client.get(f"/api/sessions/{session_id}").json()
        assert restored["reviewing"] and restored["question"]["id"] == question_id
        assert len(restored["attempts"][0]["discussion"]) == 2
        assert restored["attempts"][0]["discussion"][0]["message"].startswith("Я это")
        next_state = client.post(f"/api/sessions/{session_id}/next", headers=authenticated(client),
                                 json={"question_id": question_id}).json()
        assert not next_state["reviewing"] and next_state["current_index"] == 1
        assert next_state["question"]["id"] != question_id
        assert len(next_state["attempts"][0]["discussion"]) == 2


def test_last_question_can_be_discussed_before_results(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        headers = authenticated(client)
        state = answer(client, headers, start(client, headers, count=1))
        assert state["reviewing"] and not state["completed"]
        endpoint = f"/api/sessions/{state['id']}"
        body = {"question_id": state["question"]["id"], "message": "А если выборка маленькая?"}
        assert client.post(endpoint + "/discuss", headers=headers, json=body).status_code == 200
        finished = client.post(endpoint + "/next", headers=headers, json={"question_id": body["question_id"]}).json()
        assert finished["completed"] and finished["question"] is None
        assert finished["attempts"][0]["discussion"]
        assert client.post(endpoint + "/discuss", headers=headers, json=body).status_code == 409


def test_discussion_guards_and_stale_next_click(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        headers = authenticated(client)
        state = start(client, headers)
        endpoint = f"/api/sessions/{state['id']}"
        question_id = state["question"]["id"]
        assert client.post(endpoint + "/next", headers=headers, json={"question_id": question_id}).status_code == 409
        assert client.post(endpoint + "/discuss", headers=headers, json={"question_id": question_id, "message": "Уточнение"}).status_code == 409
        state = answer(client, headers, state)
        assert client.post(endpoint + "/discuss", headers=headers, json={"question_id": 999, "message": "Уточнение"}).status_code == 409
        assert client.post(endpoint + "/discuss", headers=headers, json={"question_id": question_id, "message": " "}).status_code == 422
        assert client.post(endpoint + "/next", headers=headers, json={"question_id": question_id}).status_code == 200
        assert client.post(endpoint + "/next", headers=headers, json={"question_id": question_id}).status_code == 409
        assert client.post(endpoint + "/discuss", headers=headers, json={"question_id": question_id, "message": "Старый вопрос"}).status_code == 409


def test_ai_gets_current_question_and_discussion_context_only(tmp_path):
    settings = settings_at(tmp_path)
    settings.openrouter_key = "test-key"
    settings.model = "test-model"
    received = []
    def reply(**kwargs):
        request = kwargs["json"]
        received.append(request)
        if "response_format" in request:
            context = json.loads(request["messages"][-1]["content"])
            content = json.dumps({"feedback": "Разбор ответа", "criterion_results": [
                {"id": criterion["id"], "status": "correct", "credit": 4, "evidence": context["student_answer"][:200]}
                for criterion in context["criteria"]]}, ensure_ascii=False)
        else:
            content = "Ты прав: твоя формулировка передаёт нужный смысл. Уточню замечание."
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": content}}]}
        return response
    with TestClient(create_app(settings)) as client, patch("app.trainer.httpx.Client") as provider:
        provider.return_value.__enter__.return_value.post.side_effect = lambda *args, **kwargs: reply(**kwargs)
        headers = authenticated(client)
        state = answer(client, headers, start(client, headers))
        first_id = state["question"]["id"]
        endpoint = f"/api/sessions/{state['id']}"
        first_message = "Уникальное возражение по первой карточке: A17"
        for text in [first_message, "А почему ты изменил объяснение?"]:
            response = client.post(endpoint + "/discuss", headers=headers, json={"question_id": first_id, "message": text})
            assert response.status_code == 200
        messages = received[-1]["messages"]
        assert messages[-1]["content"] == "А почему ты изменил объяснение?"
        assert first_message in [item["content"] for item in messages]
        assert any(item["role"] == "assistant" and "Ты прав" in item["content"] for item in messages)
        state = client.post(endpoint + "/next", headers=headers, json={"question_id": first_id}).json()
        state = answer(client, headers, state, "Только ответ ко второй карточке")
        response = client.post(endpoint + "/discuss", headers=headers, json={"question_id": state["question"]["id"], "message": "Обсудим второй вопрос"})
        assert response.status_code == 200
        assert first_message not in json.dumps(received[-1]["messages"], ensure_ascii=False)


def test_discussion_provider_failure_does_not_save_half_turn(tmp_path):
    settings = settings_at(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = authenticated(client)
        state = answer(client, headers, start(client, headers))
        with patch("app.server.discuss", side_effect=ValueError("bad provider response")):
            response = client.post(f"/api/sessions/{state['id']}/discuss", headers=headers,
                                   json={"question_id": state["question"]["id"], "message": "Не согласен"})
        assert response.status_code == 502
        restored = client.get(f"/api/sessions/{state['id']}").json()
        assert restored["reviewing"] and restored["attempts"][0]["discussion"] == []


def test_old_database_migration_preserves_pending_question(tmp_path):
    path = tmp_path / "history.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions (id TEXT PRIMARY KEY, topic TEXT NOT NULL, question_ids TEXT NOT NULL,
                                   created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
            CREATE TABLE attempts (id INTEGER PRIMARY KEY, session_id TEXT, question_id INTEGER,
                answer TEXT, feedback TEXT, score INTEGER, mode TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id,question_id));
        """)
        db.execute("INSERT INTO sessions(id,topic,question_ids) VALUES('legacy','fundamentals','[1,2]')")
        feedback = json.dumps({"feedback": "Старый разбор", "covered": [], "missing": [], "score": 50, "mode": "demo"})
        db.execute("INSERT INTO attempts(session_id,question_id,answer,feedback,score,mode) VALUES('legacy',1,'Старый ответ',?,50,'demo')", (feedback,))
    with TestClient(create_app(settings_at(tmp_path))) as client:
        state = client.get("/api/sessions/legacy").json()
        assert state["question"]["id"] == 2
        assert state["current_index"] == 1 and not state["reviewing"]
        assert state["attempts"][0]["answer"] == "Старый ответ"
        assert state["topic"] == "classical_ml"
        assert client.get("/api/history").json()["sessions"][0]["topic"] == "classical_ml"
