import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app

# A frame-shaped fixture for transport tests; playback is covered separately in WebView2.
AUDIO = (b"\xff\xfb\x90\xc4" + b"\0" * 413) * 40
ASYNC_CLIENT = httpx.AsyncClient


def settings_at(path):
    return Settings(data_dir=path, deepgram_key="", openrouter_key="", model="", embedding_model="",
                    qdrant_url="", qdrant_key="", tts_provider="fish", fish_key="private-fish-key",
                    fish_voice_id="1db1618b6eaf4571ac7db70e20eb6727", fish_model="s2.1-pro-free")


def provider(handler):
    return patch("app.speech.httpx.AsyncClient", side_effect=lambda **kwargs: ASYNC_CLIENT(
        transport=httpx.MockTransport(handler), **kwargs))


def headers(client):
    return {"X-App-Token": client.get("/api/config").json()["token"]}


def test_voice_request_audio_cache_and_key_privacy(tmp_path):
    received = []
    def respond(request):
        received.append(request)
        return httpx.Response(200, content=AUDIO, headers={"Content-Type": "audio/mpeg"})
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        config = client.get("/api/config")
        assert "private-fish-key" not in config.text
        assert config.json()["tts"]["ready"]
        assert client.post("/api/speech", json={"text": "Привет"}).status_code == 403
        for _ in range(2):
            response = client.post("/api/speech", json={"text": "Привет"}, headers=headers(client))
            assert response.status_code == 200
            assert response.content == AUDIO
            assert response.headers["content-type"] == "audio/mpeg"
            assert response.headers["cache-control"] == "no-store"
        assert len(received) == 1, "Repeated playback should reuse audio without another API call"
        request = received[0]
        assert request.headers["authorization"] == "Bearer private-fish-key"
        assert request.headers["model"] == "s2.1-pro-free"
        body = json.loads(request.content)
        assert body["reference_id"] == "1db1618b6eaf4571ac7db70e20eb6727"
        assert body["text"] == "Привет"


@pytest.mark.parametrize("status", [401, 402, 403, 404, 429, 503])
def test_provider_errors_do_not_fall_back_or_expose_upstream_body(tmp_path, status):
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(lambda request: httpx.Response(
        status, json={"detail": "private-fish-key"}
    )):
        response = client.post("/api/speech", json={"text": "Привет"}, headers=headers(client))
        assert response.status_code == 502
        assert "Fish Audio" in response.json()["detail"]
        assert "private-fish-key" not in response.text


@pytest.mark.parametrize("setting,value", [("fish_key", ""), ("fish_model", "typo-model"), ("fish_voice_id", "bad-id"), ("tts_provider", "system")])
def test_invalid_settings_do_not_make_billable_requests(tmp_path, setting, value):
    settings = settings_at(tmp_path)
    setattr(settings, setting, value)
    with TestClient(create_app(settings)) as client, patch("app.speech.httpx.AsyncClient") as upstream:
        response = client.post("/api/speech", json={"text": "Привет"}, headers=headers(client))
        assert response.status_code == 409
        upstream.assert_not_called()


def test_blank_and_oversized_text_are_rejected(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client, patch("app.speech.httpx.AsyncClient") as upstream:
        for text in ["", "   ", "a" * 6001]:
            assert client.post("/api/speech", json={"text": text}, headers=headers(client)).status_code == 422
        upstream.assert_not_called()


@pytest.mark.parametrize("content,mime", [(b"", "audio/mpeg"), (b"bad", "audio/mpeg"), (b"{}", "application/json"), (b"a" * (8 * 1024 * 1024 + 1), "audio/mpeg")])
def test_bad_audio_is_not_cached(tmp_path, content, mime):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=content, headers={"Content-Type": mime})
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        for _ in range(2):
            response = client.post("/api/speech", json={"text": "Привет"}, headers=headers(client))
            assert response.status_code == 502
        assert len(calls) == 2


def test_timeout_has_retryable_message(tmp_path):
    def respond(request):
        raise httpx.ReadTimeout("upstream timeout", request=request)
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        response = client.post("/api/speech", json={"text": "Привет"}, headers=headers(client))
        assert response.status_code == 504


def test_cache_evicts_old_entries(tmp_path):
    settings = settings_at(tmp_path)
    with TestClient(create_app(settings)) as client, provider(lambda request: httpx.Response(
        200, content=AUDIO, headers={"Content-Type": "audio/mpeg"}
    )):
        speech = client.app.state.speech
        speech.MAX_CACHE_BYTES = len(AUDIO) * 2
        for text in ["Один", "Два", "Три"]:
            assert client.post("/api/speech", json={"text": text}, headers=headers(client)).status_code == 200
        assert len(speech.cache) == 2
        assert speech.cache_bytes == len(AUDIO) * 2


def test_tone_changes_directives_and_keeps_separate_cache_entries(tmp_path):
    sent = []
    def respond(request):
        sent.append(json.loads(request.content)["text"])
        return httpx.Response(200, content=AUDIO, headers={"Content-Type": "audio/mpeg"})
    expected = {"natural": "Привет", "calm": "[calm] Привет", "friendly": "[friendly] Привет",
                "excited": "[excited] Привет", "soft": "[soft tone] Привет", "whisper": "[whispering] Привет"}
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        for tone, expected_text in expected.items():
            for _ in range(2):
                response = client.post("/api/speech", json={"text": "Привет", "tone": tone}, headers=headers(client))
                assert response.status_code == 200
            assert sent[-1] == expected_text
        assert len(sent) == len(expected), "Each tone should have its own cached audio"


def test_unknown_tone_never_reaches_provider(tmp_path):
    with TestClient(create_app(settings_at(tmp_path))) as client, patch("app.speech.httpx.AsyncClient") as upstream:
        response = client.post("/api/speech", json={"text": "Привет", "tone": "arbitrary instruction"}, headers=headers(client))
        assert response.status_code == 422
        upstream.assert_not_called()
