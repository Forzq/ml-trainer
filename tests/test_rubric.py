import json
import sqlite3
from copy import deepcopy
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.catalog import load_cards
from app.config import ROOT
from app.rubric import Evaluation, PROMPT_VERSION, prepare_card, score_evaluation
from app.server import create_app
from test_app import authenticated, settings_at


def cv_card():
    return next(card for card in load_cards() if card["id"] == 302)


def judgement(card, credits):
    statuses = {0: "not_answered", 1: "partial", 2: "partial", 3: "partial", 4: "correct"}
    return {"feedback": "Высоту, ширину и RGB ты объяснил верно. Батч — это число изображений, а не область фильтра.",
            "criterion_results": [{"id": criterion["id"], "credit": credit, "status": statuses[credit],
                                   "evidence": "Изображение состоит из пикселей" if credit else ""}
                                  for criterion, credit in zip(card["criteria"], credits, strict=True)]}


def test_known_partial_cv_answer_keeps_credit_for_dimensions_and_rgb():
    card = cv_card()
    raw = judgement(card, [2, 4, 4, 0])
    raw["criterion_results"][-1].update(status="incorrect", evidence="Батч — это размер изображения под фильтром")
    result = score_evaluation(card, Evaluation.model_validate(raw), "test-model", {"candidate_level": "Middle"})
    assert result["score"] == 60
    assert [item["earned_points"] for item in result["criterion_results"]] == [10, 20, 30, 0]
    assert len(result["covered"]) == 2 and len(result["partial"]) == 1
    assert result["criterion_results"][-1]["status"] == "incorrect"
    assert result["prompt_version"] == PROMPT_VERSION and result["rubric_version"] == card["rubric_version"]
    assert result["model"] == "test-model"
    assert "HWC" not in " ".join(c["label"] for c in card["criteria"])
    assert any("HWC" in text for text in card["followups"])


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "invented_score"])
def test_incomplete_or_invented_evaluations_are_rejected(mutation):
    card = cv_card(); raw = judgement(card, [4, 4, 4, 4])
    if mutation == "missing": raw["criterion_results"].pop()
    if mutation == "duplicate": raw["criterion_results"][-1]["id"] = raw["criterion_results"][0]["id"]
    if mutation == "unknown": raw["criterion_results"][0]["id"] = "secret-extra-rule"
    if mutation == "invented_score": raw["score"] = 100
    with pytest.raises(ValueError):
        score_evaluation(card, Evaluation.model_validate(raw), "test-model", {})


@pytest.mark.parametrize("status,credit,evidence", [("correct", 2, "text"), ("partial", 0, "text"),
    ("incorrect", 4, "text"), ("not_answered", 1, ""), ("correct", True, "text"), ("partial", 1.5, "text"), ("correct", 4, "")])
def test_contradictory_credit_and_missing_evidence_are_rejected(status, credit, evidence):
    raw = judgement(cv_card(), [4, 4, 4, 4])
    raw["criterion_results"][0].update(status=status, credit=credit, evidence=evidence)
    with pytest.raises(ValueError): Evaluation.model_validate(raw)


def test_zero_full_and_partial_scores_are_computed_from_stored_weights():
    card = load_cards()[0]
    for credits, expected in [([0, 0, 0], 0), ([4, 4, 4], 100), ([2, 2, 2], 50), ([1, 1, 1], 25)]:
        result = score_evaluation(card, Evaluation.model_validate(judgement(card, credits)), "test", {})
        assert result["score"] == expected
        assert sum(row["earned_points"] for row in result["criterion_results"]) == result["score"]


def test_session_profile_and_snapshots_drive_evaluation_and_survive_restart(tmp_path):
    card = cv_card(); settings = settings_at(tmp_path)
    settings.openrouter_key = "private-key"; settings.model = "test-model"
    received = []
    def respond(*args, **kwargs):
        payload = kwargs["json"]; received.append(payload)
        return httpx.Response(200, request=httpx.Request("POST", "https://example.test"),
                              json={"choices": [{"message": {"content": json.dumps(judgement(card, [2, 4, 4, 0]))}}]})
    with patch("app.store.load_cards", return_value=[card]):
        with TestClient(create_app(settings)) as client:
            headers = authenticated(client)
            session = client.post("/api/sessions", headers=headers, json={"topic": "cv", "count": 1, "candidate_level": "Middle"}).json()
            session_id = session["id"]
            # Even an in-memory bank update cannot alter the question already asked.
            client.app.state.store.by_id[302] = dict(card, question="A different question")
            with patch("app.trainer.httpx.Client") as provider:
                provider.return_value.__enter__.return_value.post.side_effect = respond
                response = client.post(f"/api/sessions/{session_id}/answer", headers=headers,
                                       json={"question_id": 302, "answer": "Изображение состоит из пикселей. RGB — три канала."})
            assert response.status_code == 200
            assert response.json()["evaluation"]["score"] == 60
            context = json.loads(received[0]["messages"][-1]["content"])
            assert context["candidate_level"] == "Middle" and context["question_level"] == "Junior"
            assert context["specialization"] == "CV"
            assert context["question"] == card["question"] and context["followups"] == card["followups"]
            assert sum(c["max_points"] for c in context["criteria"]) == 100
            assert "keywords" not in context["criteria"][0]
            assert "необязательное" in received[0]["messages"][0]["content"]
            assert received[0]["max_tokens"] == 2000
        with TestClient(create_app(settings)) as client:
            restored = client.get(f"/api/sessions/{session_id}").json()
            assert restored["profile"]["candidate_level"] == "Middle"
            assert restored["attempts"][0]["question"]["question"] == card["question"]
            assert restored["attempts"][0]["criterion_results"][0]["status"] == "partial"


def test_old_cv_history_keeps_original_question_and_score(tmp_path):
    settings = settings_at(tmp_path); original = json.loads((ROOT / "content/question-versions-v1.json").read_text(encoding="utf-8"))["302"]
    with sqlite3.connect(tmp_path / "history.sqlite3") as db:
        db.executescript("""
            CREATE TABLE sessions(id TEXT PRIMARY KEY, topic TEXT, question_ids TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
            CREATE TABLE attempts(id INTEGER PRIMARY KEY,session_id TEXT,question_id INTEGER,answer TEXT,feedback TEXT,score INTEGER,mode TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(session_id,question_id));
            INSERT INTO sessions(id,topic,question_ids,completed_at) VALUES('old','cv','[302]','2026-11-16');
        """)
        db.execute("INSERT INTO attempts(session_id,question_id,answer,feedback,score,mode) VALUES('old',302,'old answer',?,25,'ai')",
                   (json.dumps({"feedback": "Old feedback", "covered": [], "missing": []}),))
    with patch("app.store.load_cards", return_value=[cv_card()]), TestClient(create_app(settings)) as client:
        attempt = client.get("/api/sessions/old").json()["attempts"][0]
        assert attempt["score"] == 25 and attempt["feedback"] == "Old feedback"
        assert attempt["question"]["question"] == original["question"]
        assert "criterion_results" not in attempt
        new = client.post("/api/sessions", headers=authenticated(client), json={"topic": "cv", "count": 1}).json()
        assert new["question"]["question"] != original["question"]
