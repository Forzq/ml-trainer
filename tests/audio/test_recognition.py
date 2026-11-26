import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.audio.recognition import RecognitionError, recognize_audio
from app.server import create_app
from test_transcription import CLEAN, RAW, edited, provider, recognized, settings_at, transcribe


def fallback_settings(path):
    settings = settings_at(path)
    settings.openai_key = "private-openai"
    settings.openai_transcription_model = "whisper-1"
    return settings


@pytest.mark.parametrize("text", [RAW, "", "   "])
def test_successful_deepgram_including_silence_never_calls_whisper(tmp_path, text):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.deepgram.com"
        return recognized(text)
    with provider(respond):
        assert asyncio.run(recognize_audio(b"test-audio", "audio/webm", fallback_settings(tmp_path))) == (text, "deepgram")
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["timeout", "connection", "unauthorized", "rate-limit", "unavailable", "malformed", "wrong-type"])
def test_deepgram_failures_fall_back_to_whisper_with_the_same_recording(tmp_path, caplog, failure):
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.host == "api.openai.com":
            return httpx.Response(200, json={"text": RAW})
        if failure == "timeout":
            raise httpx.ReadTimeout("private-deepgram", request=request)
        if failure == "connection":
            raise httpx.ConnectError("private-deepgram", request=request)
        if failure == "malformed":
            return httpx.Response(200, content=b"not-json")
        if failure == "wrong-type":
            return recognized(None)
        return httpx.Response({"unauthorized": 401, "rate-limit": 429, "unavailable": 503}[failure],
                              json={"detail": "private-deepgram"})
    with provider(respond):
        result = asyncio.run(recognize_audio(b"test-audio", "audio/webm;codecs=opus", fallback_settings(tmp_path)))
    assert result == (RAW, "whisper")
    assert [request.url.host for request in requests] == ["api.deepgram.com", "api.openai.com"]
    assert requests[0].content == b"test-audio"
    request = requests[1]
    assert request.url.path == "/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer private-openai"
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="answer.webm"' in request.content
    assert b"test-audio" in request.content
    assert b'name="model"\r\n\r\nwhisper-1' in request.content
    assert b'name="response_format"\r\n\r\njson' in request.content
    assert "private-openai" not in caplog.text and "private-deepgram" not in caplog.text


@pytest.mark.parametrize("mime,extension", [("audio/webm;codecs=opus", "webm"), ("audio/mp4", "mp4"), ("audio/wav", "wav")])
def test_whisper_only_uses_configured_model_and_correct_file_extension(tmp_path, mime, extension):
    settings = fallback_settings(tmp_path)
    settings.deepgram_key = ""
    settings.openai_transcription_model = "custom-transcription-model"
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.openai.com"
        assert f'filename="answer.{extension}"'.encode() in request.content
        assert b'name="model"\r\n\r\ncustom-transcription-model' in request.content
        return httpx.Response(200, json={"text": RAW})
    with provider(respond):
        assert asyncio.run(recognize_audio(b"test-audio", mime, settings)) == (RAW, "whisper")
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["timeout", "unauthorized", "unavailable", "malformed", "missing-text", "wrong-type"])
def test_both_recognizers_failing_returns_safe_error_without_retries(tmp_path, caplog, failure):
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.host == "api.deepgram.com":
            return httpx.Response(503, json={"detail": "private-deepgram"})
        if failure == "timeout":
            raise httpx.ReadTimeout("private-openai", request=request)
        if failure == "malformed":
            return httpx.Response(200, content=b"not-json")
        if failure == "missing-text":
            return httpx.Response(200, json={})
        if failure == "wrong-type":
            return httpx.Response(200, json={"text": None})
        return httpx.Response(401 if failure == "unauthorized" else 503, json={"detail": "private-openai"})
    with provider(respond), pytest.raises(RecognitionError) as error:
        asyncio.run(recognize_audio(b"test-audio", "audio/webm", fallback_settings(tmp_path)))
    assert len(requests) == 2
    assert "Deepgram" in str(error.value) and "Whisper" in str(error.value)
    for secret in ("private-openai", "private-deepgram", "test-audio"):
        assert secret not in str(error.value) and secret not in caplog.text


def test_fallback_transcript_goes_through_existing_editor(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.host == "api.deepgram.com":
            return httpx.Response(503)
        if request.url.host == "api.openai.com":
            return httpx.Response(200, json={"text": RAW})
        return edited()
    with TestClient(create_app(fallback_settings(tmp_path))) as client, provider(respond):
        response = transcribe(client)
        assert response.status_code == 200
        assert response.json() == {"text": CLEAN, "raw_text": RAW, "cleanup": "applied", "provider": "whisper"}
        config = client.get("/api/config")
        assert config.json()["deepgram"] and config.json()["whisper"]
        assert config.json()["whisper_model"] == "whisper-1"
        for secret in ("private-deepgram", "private-openai", "private-openrouter"):
            assert secret not in response.text and secret not in config.text
    assert [request.url.host for request in requests] == ["api.deepgram.com", "api.openai.com", "openrouter.ai"]


def test_whisper_only_api_works_without_deepgram_or_editor(tmp_path):
    settings = fallback_settings(tmp_path)
    settings.deepgram_key = settings.openrouter_key = ""
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.openai.com"
        return httpx.Response(200, json={"text": RAW})
    with TestClient(create_app(settings)) as client, provider(respond):
        config = client.get("/api/config").json()
        assert not config["deepgram"] and config["whisper"]
        response = transcribe(client)
        assert response.status_code == 200
        assert response.json() == {"text": RAW, "raw_text": RAW, "cleanup": "disabled", "provider": "whisper"}
    assert len(requests) == 1


def test_editor_failure_does_not_trigger_another_recognizer(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host != "api.openai.com"
        return recognized(RAW) if request.url.host == "api.deepgram.com" else httpx.Response(503)
    with TestClient(create_app(fallback_settings(tmp_path))) as client, provider(respond):
        response = transcribe(client)
        assert response.status_code == 200
        assert response.json() == {"text": RAW, "raw_text": RAW, "cleanup": "unavailable", "provider": "deepgram"}
    assert len(requests) == 2


def test_both_recognizers_failing_api_does_not_call_editor(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host != "openrouter.ai"
        return httpx.Response(503, json={"detail": "private-openai private-deepgram"})
    with TestClient(create_app(fallback_settings(tmp_path))) as client, provider(respond):
        response = transcribe(client)
        assert response.status_code == 502
        assert "private-openai" not in response.text and "private-deepgram" not in response.text
    assert len(requests) == 2
