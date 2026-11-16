import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app

ASYNC_CLIENT = httpx.AsyncClient
RAW = "Эээ, я бы сравнил rock aug и pr aug, но не уверен."
CLEAN = "Я бы сравнил ROC-AUC и PR-AUC, но не уверен."


def settings_at(path):
    return Settings(data_dir=path, deepgram_key="private-deepgram", openai_key="", openrouter_key="private-openrouter",
                    model="same-trainer-model", transcription_model="", embedding_model="", qdrant_url="", qdrant_key="",
                    tts_provider="system", fish_key="")


def provider(handler):
    return patch("app.transcription.httpx.AsyncClient", side_effect=lambda **kwargs: ASYNC_CLIENT(
        transport=httpx.MockTransport(handler), **kwargs))


def recognized(text):
    return httpx.Response(200, json={"results": {"channels": [{"alternatives": [{"transcript": text}]}]}})


def edited(text=CLEAN):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"text": text})}, "finish_reason": "stop"}]})


def transcribe(client, **kwargs):
    headers = {"X-App-Token": client.get("/api/config").json()["token"]}
    return client.post("/api/transcribe", headers=headers,
                       files={"audio": ("answer.webm", b"test-audio", "audio/webm")}, **kwargs)


def test_voice_cleanup_uses_same_model_and_only_public_question_context(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        return recognized(RAW) if request.url.host == "api.deepgram.com" else edited()
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        headers = {"X-App-Token": client.get("/api/config").json()["token"]}
        state = client.post("/api/sessions", headers=headers, json={"topic": "classical_ml", "count": 1}).json()
        response = transcribe(client, data={"session_id": state["id"], "question_id": state["question"]["id"]})
        assert response.status_code == 200
        assert response.json() == {"text": CLEAN, "raw_text": RAW, "cleanup": "applied", "provider": "deepgram"}
        assert len(requests) == 2
        assert requests[0].content == b"test-audio"
        assert requests[0].headers["authorization"] == "Token private-deepgram"
        request = requests[1]
        assert request.headers["authorization"] == "Bearer private-openrouter"
        data = json.loads(request.content)
        assert data["model"] == "same-trainer-model"
        context = json.loads(data["messages"][1]["content"])
        assert context["transcript"] == RAW
        assert context["context"] == {key: state["question"][key] for key in ("question", "topic", "tags")}
        assert "reference" not in context["context"] and "criteria" not in context["context"]
        assert client.get(f"/api/sessions/{state['id']}").json()["answered"] == 0
        assert "private-openrouter" not in response.text


@pytest.mark.parametrize("trainer_model", ["same-trainer-model", ""])
def test_separate_editor_model_does_not_replace_trainer(tmp_path, trainer_model):
    settings = settings_at(tmp_path)
    settings.model = trainer_model
    settings.transcription_model = "fast-editor-model"
    received = []
    def respond(request):
        if request.url.host == "api.deepgram.com":
            return recognized(RAW)
        received.append(json.loads(request.content))
        return edited()
    with TestClient(create_app(settings)) as client, provider(respond):
        config = client.get("/api/config").json()
        assert config["model"] == trainer_model
        assert config["transcription"] == {"ready": True, "model": "fast-editor-model"}
        assert transcribe(client).json()["text"] == CLEAN
        assert received[0]["model"] == "fast-editor-model"


@pytest.mark.parametrize("failure", ["timeout", "unauthorized", "malformed", "wrong-type", "truncated", "expanded", "erased"])
def test_failed_cleanup_preserves_raw_speech(tmp_path, failure):
    def respond(request):
        if request.url.host == "api.deepgram.com":
            return recognized(RAW)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-openrouter", request=request)
        if failure == "unauthorized":
            return httpx.Response(401, json={"detail": "private-openrouter"})
        if failure == "malformed":
            return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})
        if failure == "wrong-type":
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"text":42}'}}]})
        if failure == "truncated":
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"text":"partial"}'}, "finish_reason": "length"}]})
        return edited("" if failure == "erased" else "invented explanation " * 50)
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        response = transcribe(client)
        assert response.status_code == 200
        assert response.json() == {"text": RAW, "raw_text": RAW, "cleanup": "unavailable", "provider": "deepgram"}
        assert "private-openrouter" not in response.text


@pytest.mark.parametrize("raw,expected,calls", [("", "", 1), ("   ", "   ", 1), ("Эээ, эм, м-м-м… uh, um.", "", 2)])
def test_silence_and_fillers_are_not_invented_into_answers(tmp_path, raw, expected, calls):
    received = []
    def respond(request):
        received.append(request)
        return recognized(raw) if request.url.host == "api.deepgram.com" else edited("")
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        response = transcribe(client)
        assert response.json()["text"] == expected
        assert len(received) == calls


def test_without_openrouter_recognition_still_works(tmp_path):
    settings = settings_at(tmp_path)
    settings.openrouter_key = ""
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.deepgram.com"
        return recognized(RAW)
    with TestClient(create_app(settings)) as client, provider(respond):
        assert transcribe(client).json() == {"text": RAW, "raw_text": RAW, "cleanup": "disabled", "provider": "deepgram"}
        assert len(requests) == 1


def test_deepgram_failure_does_not_call_editor(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.deepgram.com"
        return httpx.Response(503, json={"detail": "private-deepgram"})
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        response = transcribe(client)
        assert response.status_code == 502
        assert "private-deepgram" not in response.text
        assert len(requests) == 1


def test_invalid_audio_and_stale_context_never_reach_providers(tmp_path):
    settings = settings_at(tmp_path)
    settings.openai_key = "private-openai"
    with TestClient(create_app(settings)) as client, patch("app.transcription.httpx.AsyncClient") as upstream:
        headers = {"X-App-Token": client.get("/api/config").json()["token"]}
        state = client.post("/api/sessions", headers=headers, json={"count": 1}).json()
        assert transcribe(client, data={"session_id": state["id"]}).status_code == 422
        assert transcribe(client, data={"session_id": state["id"], "question_id": 999}).status_code == 409
        assert client.post("/api/transcribe", headers=headers, files={"audio": ("empty.webm", b"", "audio/webm")}).status_code == 422
        upstream.assert_not_called()
