"""Run UI and fake microphone checks inside the real Windows WebView2 host."""
import json
import argparse
import base64
import io
import faulthandler
import os
import socket
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import uvicorn

from app.core.config import Settings
from app.desktop.window import open_window
from app.server import create_app


def wait_js(window, expression, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = window.evaluate_js(expression)
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Desktop UI timed out: " + expression)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, help="Optional real MP3 sample to verify complete playback")
    options = parser.parse_args()
    faulthandler.dump_traceback_later(45, exit=True)
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--use-fake-device-for-media-stream"
    (ROOT / "logs/native-check").mkdir(parents=True, exist_ok=True)
    errors = []
    finished = threading.Event()
    # WebView2 may retain telemetry files briefly after its last window closes.
    with tempfile.TemporaryDirectory(dir=ROOT / "logs/native-check", prefix="native-", ignore_cleanup_errors=True) as temporary:
        temp = Path(temporary)
        settings = Settings(data_dir=temp / "data", deepgram_key="", openai_key="", openrouter_key="", model="", embedding_model="", qdrant_url="", qdrant_key="", tts_provider="system", fish_key="")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        assert server.started
        started = False

        def check(window):
            nonlocal started
            if started:
                return
            started = True
            try:
                wait_js(window, "Boolean(state.config && document.querySelector('.hero'))")
                assert window.evaluate_js("isDesktop()")
                assert window.evaluate_js("Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder)")
                assert window.evaluate_js("window.pywebview.platform") == "edgechromium"
                assert window.evaluate_js("document.documentElement.dataset.theme") == "dark"
                window.evaluate_js("document.querySelector('[data-page=settings]').click(); true")
                wait_js(window, "Boolean(document.querySelector('#theme-choice'))")
                window.evaluate_js("const choice = document.querySelector('#theme-choice'); choice.value='light'; choice.dispatchEvent(new Event('change')); true")
                wait_js(window, "document.documentElement.dataset.theme === 'light'")
                window.evaluate_js("const choice = document.querySelector('#theme-choice'); choice.value='dark'; choice.dispatchEvent(new Event('change')); true")
                wait_js(window, "document.documentElement.dataset.theme === 'dark'")
                window.evaluate_js("state.sound = false; showStart('cv'); document.querySelector('#session-count').value='2'; document.querySelector('#start-form').requestSubmit(); true")
                wait_js(window, "Boolean(document.querySelector('#answer-input'))")
                window.evaluate_js("document.querySelector('#answer-input').value='Модель запоминает шум и хуже работает на новых данных. Сравниваем с валидацией.'; document.querySelector('#answer-form').requestSubmit(); true")
                wait_js(window, "Boolean(document.querySelector('[data-action=next]'))")
                assert window.evaluate_js("document.querySelector('.message-text:last-of-type') !== null")
                assert window.evaluate_js("state.session.reviewing && document.querySelector('#answer-input') !== null")
                window.evaluate_js("document.querySelector('#answer-input').value='Я упомянул новые данные. Объясни своё замечание.'; document.querySelector('#answer-form').requestSubmit(); true")
                wait_js(window, "state.session.attempts[0].discussion.length === 1 && !state.busy")
                window.evaluate_js("document.querySelector('[data-action=next]').click(); true")
                wait_js(window, "state.session.current_index === 1 && !state.session.reviewing && !state.busy")
                assert window.evaluate_js("document.querySelectorAll('.message-text').length") == 1
                window.evaluate_js("""
                    state.config.deepgram = true;
                    const originalFetch = window.fetch;
                    window.fetch = (input, options) => String(input).includes('/api/transcribe')
                        ? (window.recordedForm = options.body, Promise.resolve(new Response(JSON.stringify({text:'Тестовая запись в Windows-приложении', raw_text:'Эээ, тестовая запись в Windows-приложении', cleanup:'applied'}), {status:200, headers:{'Content-Type':'application/json'}})))
                        : originalFetch(input, options);
                    document.querySelector('[data-action=record]').click(); true
                """)
                wait_js(window, "state.recorder?.state === 'recording'")
                time.sleep(1.2)
                window.evaluate_js("document.querySelector('[data-action=record]').click(); true")
                wait_js(window, "document.querySelector('#answer-input')?.value === 'Тестовая запись в Windows-приложении'")
                assert window.evaluate_js("document.querySelector('#transcription-review').textContent.includes('Эээ, тестовая запись')")
                assert window.evaluate_js("window.recordedForm.get('session_id') === state.session.id && Number(window.recordedForm.get('question_id')) === state.session.question.id")
                assert window.evaluate_js("state.stream === null")
                window.evaluate_js("document.querySelector('[data-action=skip]').click(); true")
                wait_js(window, "Boolean(document.querySelector('[data-action=next]'))")
                window.evaluate_js("document.querySelector('[data-action=next]').click(); true")
                wait_js(window, "Boolean(document.querySelector('.result-hero'))")
                window.evaluate_js("openSettings('connections'); true")
                wait_js(window, "Boolean(document.querySelector('#connection-settings'))")
                settings_text = window.evaluate_js("document.querySelector('#connection-settings').textContent")
                assert "Озвучка" in settings_text and "Системный голос" in settings_text
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(b"\0" * (24000 * 2 * 3))
                audio_bytes = options.audio.read_bytes() if options.audio else buffer.getvalue()
                mime = "audio/mpeg" if options.audio else "audio/wav"
                encoded = base64.b64encode(audio_bytes).decode()
                window.evaluate_js("""
                    window.fetchBeforeSpeechTest = window.fetch;
                    window.nativeSpokenTexts = []; window.nativeSpokenTones = [];
                    state.config.tts = {provider:'fish',ready:true,voice_id:'1db1618b6eaf4571ac7db70e20eb6727',model:'s2.1-pro-free'};
                    window.fetch = (input, options) => String(input).includes('/api/speech')
                        ? (window.nativeSpokenTexts.push(JSON.parse(options.body).text), window.nativeSpokenTones.push(JSON.parse(options.body).tone), Promise.resolve(new Response(Uint8Array.from(atob('%s'), c => c.charCodeAt(0)), {headers:{'Content-Type':'%s'}})))
                        : window.fetchBeforeSpeechTest(input, options);
                    syncVoiceControls();
                    const toneSelect = document.querySelector('#voice-tone');
                    toneSelect.value='friendly'; toneSelect.dispatchEvent(new Event('change', {bubbles:true}));
                    document.querySelector('[data-action=preview-voice]').click(); true
                """ % (encoded, mime))
                wait_js(window, "speech.status === 'playing'")
                assert window.evaluate_js("Boolean(speech.audio && !speech.audio.paused)")
                assert window.evaluate_js("window.nativeSpokenTones[window.nativeSpokenTones.length-1] === 'friendly'")
                if options.audio:
                    wait_js(window, "speech.status === 'idle'", timeout=30)
                    assert window.evaluate_js("MediaSource.isTypeSupported('audio/mpeg')")
                    # Hold the provider's tail indefinitely: playback must start before EOF.
                    window.evaluate_js("""
                        window.streamingSpeechFetch = window.fetch;
                        window.fetch = (input, options) => String(input).includes('/api/speech')
                            ? Promise.resolve(new Response(new ReadableStream({
                                start(controller) {
                                    const bytes = Uint8Array.from(atob('%s'), c => c.charCodeAt(0));
                                    controller.enqueue(bytes.slice(0, 24000));
                                    window.releaseSpeechTail = () => { controller.enqueue(bytes.slice(24000)); controller.close(); };
                                    window.speechTailReleased = false;
                                },
                                cancel() { window.speechStreamCancelled = true; }
                            }), {headers:{'Content-Type':'audio/mpeg'}}))
                            : window.streamingSpeechFetch(input, options);
                        document.querySelector('[data-action=preview-voice]').click(); true
                    """ % encoded)
                    wait_js(window, "speech.status === 'playing' && speech.receiving")
                    assert window.evaluate_js("speech.audio.currentTime >= 0 && !speech.audio.paused && !window.speechTailReleased")
                    window.evaluate_js("window.speechTailReleased = true; releaseSpeechTail(); true")
                    wait_js(window, "speech.status === 'idle'", timeout=30)
                    window.evaluate_js("document.querySelector('[data-action=preview-voice]').click(); true")
                    wait_js(window, "speech.status === 'playing' && speech.receiving")
                    window.evaluate_js("cancelSpeech(); true")
                    wait_js(window, "window.speechStreamCancelled === true && !speech.receiving")
                    window.evaluate_js("window.fetch = window.streamingSpeechFetch; true")
                window.evaluate_js("cancelSpeech(); true")
                assert window.evaluate_js("speech.audio === null && speech.status === 'idle'")
                window.evaluate_js("""
                    const volume = document.querySelector('#voice-volume');
                    volume.value = '40'; volume.dispatchEvent(new Event('input', {bubbles:true}));
                    const auto = document.querySelector('#auto-speech');
                    auto.checked = true; auto.dispatchEvent(new Event('change', {bubbles:true}));
                    showStart('dl'); document.querySelector('#session-level').value='Senior'; document.querySelector('#start-form').requestSubmit(); true
                """)
                wait_js(window, "Boolean(document.querySelector('#answer-input')) && speech.status === 'playing'")
                assert window.evaluate_js("speech.audio.volume === 0.4")
                assert window.evaluate_js("state.session.question.level === 'Senior'")
                window.evaluate_js("document.querySelector('#answer-input').value='Модель запоминает шум и хуже обобщает новые данные.'; document.querySelector('#answer-form').requestSubmit(); true")
                wait_js(window, "state.awaitingNext && speech.status === 'playing'")
                assert window.evaluate_js("window.nativeSpokenTexts[window.nativeSpokenTexts.length-1] === state.session.attempts[state.session.attempts.length-1].feedback")
                window.evaluate_js("document.querySelector('#answer-input').value='А если я сформулировал это другими словами?'; document.querySelector('#answer-form').requestSubmit(); true")
                wait_js(window, "state.session.attempts[0].discussion.length === 1 && speech.status === 'playing'")
                assert window.evaluate_js("window.nativeSpokenTexts[window.nativeSpokenTexts.length-1] === state.session.attempts[0].discussion[0].reply")
                window.evaluate_js("openSettings(); true")
                wait_js(window, "Boolean(document.querySelector('#voice-volume'))")
                assert window.evaluate_js("speech.status === 'idle'")
                window.evaluate_js("const volume = document.querySelector('#voice-volume'); volume.value='22'; volume.dispatchEvent(new Event('input')); document.querySelector('#auto-speech').click(); document.querySelector('#settings-resume').click(); true")
                wait_js(window, "state.page === 'training' && Boolean(document.querySelector('#answer-input'))")
                window.evaluate_js("const replay=document.querySelectorAll('[data-action=speak]'); replay[replay.length-1].click(); true")
                wait_js(window, "speech.status === 'playing'")
                assert window.evaluate_js("state.sound === false && speech.audio.volume === 0.22")
                window.evaluate_js("openSettings(); true")
                wait_js(window, "Boolean(document.querySelector('[data-action=shutdown]'))")
                # Exercise the actual JS -> Python close bridge.
                window.run_js("document.querySelector('[data-action=shutdown]').click()")
                finished.set()
            except Exception as error:
                errors.append(repr(error))
                window.destroy()

        try:
            print("Opening native WebView2 window...", flush=True)
            with patch("app.desktop.window.ask_microphone", return_value=True) as permission:
                open_window(SimpleNamespace(url=url), on_loaded=check, profile_path=temp / "profile")
                if not errors:
                    assert permission.call_count == 1, "Native microphone permission handler was not called"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        assert finished.is_set() and not errors, errors
        faulthandler.cancel_dump_traceback_later()
        print(json.dumps({"result": "passed", "renderer": "WebView2", "checks": ["native window", "dark theme and theme bridge", "training", "native microphone permission", "recording", "transcription UI", "microphone release", "Fish audio playback and stop", "automatic feedback narration", "manual replay", "live volume", "results", "close bridge"]}))


if __name__ == "__main__":
    main()
