import json

import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from test_app import authenticated, settings_at


@pytest.fixture
def history_client(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        with client.app.state.store.connect() as db:
            db.executemany(
                "INSERT INTO sessions(id,topic,question_ids,created_at,completed_at) VALUES(?,?,?,?,?)",
                [(f"session-{index}", "fundamentals" if index == 1 else "all", "[1,2]",
                  "2026-01-01 12:00:00", "2026-01-01 13:00:00" if index % 3 == 0 else None)
                 for index in range(1, 66)],
            )
            feedback = json.dumps({"score": 50, "feedback": "Saved feedback", "covered": [], "missing": []})
            db.executemany(
                "INSERT INTO attempts(session_id,question_id,answer,feedback,score,mode) VALUES(?,?,?,?,?,?)",
                [(f"session-{index}", 1, "Saved answer", feedback, 50, "demo") for index in range(1, 65)]
                + [("session-1", 2, "", feedback, 0, "skipped")],
            )
        yield client


def test_empty_history_and_stats_update_after_answer_and_completion(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client:
        assert client.get("/api/stats").json() == {"sessions": 0, "completed": 0, "answered": 0}
        assert client.get("/api/history").json() == {
            "sessions": [], "page": 1, "page_size": 30, "total": 0, "total_pages": 1,
        }
        headers = authenticated(client)
        state = client.post("/api/sessions", json={"count": 1}, headers=headers).json()
        assert client.get("/api/stats").json() == {"sessions": 1, "completed": 0, "answered": 0}
        client.post(f"/api/sessions/{state['id']}/answer", headers=headers,
                    json={"question_id": state["question"]["id"], "skip": True}).raise_for_status()
        assert client.get("/api/stats").json() == {"sessions": 1, "completed": 0, "answered": 1}
        client.post(f"/api/sessions/{state['id']}/finish", headers=headers).raise_for_status()
        assert client.get("/api/stats").json() == {"sessions": 1, "completed": 1, "answered": 1}


def test_global_stats_and_all_history_pages_include_old_sessions(history_client):
    client = history_client
    assert client.get("/api/stats").json() == {"sessions": 65, "completed": 21, "answered": 65}
    pages = [client.get("/api/history", params={"page": page}).json() for page in range(1, 4)]
    assert [len(page["sessions"]) for page in pages] == [30, 30, 5]
    for index, page in enumerate(pages, start=1):
        assert (page["page"], page["page_size"], page["total"], page["total_pages"]) == (index, 30, 65, 3)
    rows = [session for page in pages for session in page["sessions"]]
    # Identical timestamps still have a stable order with no duplicates or omissions.
    assert [row["id"] for row in rows] == [f"session-{index}" for index in range(65, 0, -1)]
    assert rows[0]["answered"] == 0
    assert rows[-1]["answered"] == 2 and rows[-1]["topic"] == "classical_ml"
    assert sum(row["answered"] for row in rows) == 65
    restored = client.get("/api/sessions/session-1").json()
    assert restored["attempts"][0]["answer"] == "Saved answer"


def test_history_page_size_and_out_of_range_pages(history_client):
    client = history_client
    result = client.get("/api/history", params={"page": 999, "page_size": 10}).json()
    assert (result["page"], result["page_size"], result["total_pages"]) == (7, 10, 7)
    assert [session["id"] for session in result["sessions"]] == [f"session-{index}" for index in range(5, 0, -1)]
    result = client.get("/api/history", params={"page_size": 100}).json()
    assert len(result["sessions"]) == 65 and result["total_pages"] == 1


def test_history_rejects_invalid_pagination(history_client):
    for params in ({"page": 0}, {"page": -1}, {"page": "invalid"}, {"page_size": 0}, {"page_size": 101}):
        assert history_client.get("/api/history", params=params).status_code == 422
