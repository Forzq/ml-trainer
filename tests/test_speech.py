import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.speech import Speech, SpeechError

# A frame-shaped fixture for transport tests; playback is covered separately in WebView2.
AUDIO = (b"\xff\xfb\x90\xc4" + b"\0" * 413) * 40
ASYNC_CLIENT = httpx.AsyncClient


def settings_at(path):
    return Settings(data_dir=path, deepgram_key="", openai_key="", openrouter_key="", model="", embedding_model="",
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
        assert body["latency"] == "low"
        assert body["chunk_length"] == 100


@pytest.mark.parametrize("status", [401, 402, 403, 404, 429, 503])
def test_provider_errors_do_not_fall_back_or_expose_upstream_body(tmp_path, status):
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(lambda request: httpx.Response(
        status, json={"detail": "private-fish-key"}
    )):
        response = client.post("/api/speech", json={"text": "Привет"}, headers=headers(client))
        assert response.status_code == 502
        assert "Fish Audio" in response.json()["detail"]
        assert "private-fish-key" not in response.text


@pytest.mark.parametrize("setting,value", [("fish_key", ""), ("fish_model", "typo-model"), ("fish_voice_id", "bad-id"), ("tts_provider", "system"), ("fish_latency", "typo")])
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
    expected = {"natural": "Привет", "calm": "[calm] Привет", "very_calm_slow": "[very calm and slowly] Привет", "friendly": "[friendly] Привет",
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


def test_streaming_route_and_cached_replay(tmp_path):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=AUDIO, headers={"Content-Type": "audio/mpeg"})
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(respond):
        for stream in [True, False, True]:
            response = client.post("/api/speech", json={"text": "Streaming sample", "stream": stream}, headers=headers(client))
            assert response.status_code == 200
            assert response.content == AUDIO
            assert response.headers["content-type"] == "audio/mpeg"
            assert response.headers["cache-control"] == "no-store"
        assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 429])
def test_stream_errors_before_audio_have_json_response(tmp_path, status):
    with TestClient(create_app(settings_at(tmp_path))) as client, provider(lambda request: httpx.Response(status)):
        response = client.post("/api/speech", json={"text": "Streaming sample", "stream": True}, headers=headers(client))
        assert response.status_code == 502
        assert "Fish Audio" in response.json()["detail"]


class PausedAudio(httpx.AsyncByteStream):
    def __init__(self):
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        yield AUDIO[:2048]
        await self.release.wait()
        yield AUDIO[2048:]

    async def aclose(self):
        self.closed = True


def test_first_chunk_precedes_provider_completion_and_other_phrases_do_not_wait(tmp_path):
    async def check():
        paused = PausedAudio()
        speech = Speech(settings_at(tmp_path))
        requests = []
        def respond(request):
            requests.append(json.loads(request.content)["text"])
            if len(requests) == 1:
                return httpx.Response(200, stream=paused, headers={"Content-Type": "audio/mpeg"})
            return httpx.Response(200, content=AUDIO, headers={"Content-Type": "audio/mpeg"})
        with provider(respond):
            stream = speech.stream("First phrase")
            first = await asyncio.wait_for(anext(stream), timeout=2)
            assert first == AUDIO[:2048]
            assert not paused.closed and not paused.release.is_set()
            # A different phrase must not wait for a global synthesis lock.
            assert await asyncio.wait_for(speech.synthesize("Second phrase"), timeout=2) == AUDIO
            assert len(speech.cache) == 1
            paused.release.set()
            rest = b"".join([chunk async for chunk in stream])
            assert first + rest == AUDIO
            assert paused.closed and not speech.pending
            assert len(speech.cache) == 2
    asyncio.run(check())


def test_cancel_closes_provider_and_never_caches_partial_audio(tmp_path):
    async def check():
        paused = PausedAudio()
        speech = Speech(settings_at(tmp_path))
        with provider(lambda request: httpx.Response(200, stream=paused, headers={"Content-Type": "audio/mpeg"})):
            stream = speech.stream("Cancelled phrase")
            assert await anext(stream) == AUDIO[:2048]
            await stream.aclose()
            assert paused.closed
            assert not speech.pending and not speech.cache
    asyncio.run(check())


def test_same_phrase_in_flight_is_deduplicated(tmp_path):
    async def check():
        paused = PausedAudio()
        speech = Speech(settings_at(tmp_path))
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, stream=paused, headers={"Content-Type": "audio/mpeg"})
        with provider(respond):
            first = speech.stream("Same phrase")
            head = await anext(first)
            second = asyncio.create_task(speech.synthesize("Same phrase"))
            await asyncio.sleep(0)
            assert not second.done()
            paused.release.set()
            assert head + b"".join([chunk async for chunk in first]) == AUDIO
            assert await asyncio.wait_for(second, timeout=2) == AUDIO
            assert len(calls) == 1 and not speech.pending
    asyncio.run(check())


def test_stream_interruption_is_not_cached(tmp_path):
    class InterruptedAudio(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield AUDIO[:2048]
            raise httpx.ReadError("private upstream information")
    async def check():
        speech = Speech(settings_at(tmp_path))
        with provider(lambda request: httpx.Response(200, stream=InterruptedAudio(), headers={"Content-Type": "audio/mpeg"})):
            stream = speech.stream("Interrupted phrase")
            assert await anext(stream) == AUDIO[:2048]
            with pytest.raises(SpeechError) as error:
                await anext(stream)
            assert error.value.status == 502
            assert "private" not in error.value.detail
            assert not speech.cache and not speech.pending
    asyncio.run(check())


def test_http_stream_delivers_before_eof_and_disconnect_closes_provider(tmp_path):
    async def check():
        app = create_app(settings_at(tmp_path))
        paused = PausedAudio()
        received = []
        first_audio = asyncio.Event()
        disconnected = asyncio.Event()
        requested = False
        body = json.dumps({"text": "HTTP streaming phrase", "stream": True}).encode()
        async def receive():
            nonlocal requested
            if not requested:
                requested = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            received.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                first_audio.set()
        async with app.router.lifespan_context(app):
            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                     "http_version": "1.1", "method": "POST", "scheme": "http",
                     "path": "/api/speech", "raw_path": b"/api/speech", "root_path": "", "query_string": b"",
                     "server": ("testserver", 80), "client": ("127.0.0.1", 1000),
                     "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                                 (b"x-app-token", app.state.token.encode())]}
            with provider(lambda request: httpx.Response(200, stream=paused, headers={"Content-Type": "audio/mpeg"})):
                task = asyncio.create_task(app(scope, receive, send))
                try:
                    await asyncio.wait_for(first_audio.wait(), timeout=2)
                    assert received[0]["status"] == 200
                    assert b"".join(item.get("body", b"") for item in received) == AUDIO[:2048]
                    assert not paused.release.is_set() and not task.done()
                finally:
                    disconnected.set()
                    await asyncio.wait_for(task, timeout=2)
                assert paused.closed and not app.state.speech.cache and not app.state.speech.pending
    asyncio.run(check())
