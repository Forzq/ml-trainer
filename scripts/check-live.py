"""Exercise hands-free turns with real Web Audio/MediaRecorder and mocked API audio."""
import argparse
import base64
import faulthandler
import io
import json
import socket
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import uvicorn
from app.catalog import load_cards
from app.config import Settings
from app.server import create_app


def wait(evaluate, expression, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if evaluate(expression):
            return
        time.sleep(.05)
    raise AssertionError("Live test timed out: " + expression)


def checks(evaluate, audio=None, screenshot=None):
    wait(evaluate, "Boolean(state.config && document.querySelector('.hero'))")
    sample = io.BytesIO()
    with wave.open(sample, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0" * 12000)
    encoded = base64.b64encode(sample.getvalue()).decode()
    evaluate(r"""
        window.liveTestErrors = [];
        window.addEventListener('error', e => liveTestErrors.push(e.message));
        window.addEventListener('unhandledrejection', e => liveTestErrors.push(String(e.reason)));
        window.testInputs = []; window.testSpoken = []; window.testTranscribed = 0;
        window.testMP3 = null;
        window.testAnswers = ['Модель запоминает шум и хуже работает на новых данных. Сравниваю с валидацией.',
                              'Я упомянул новые данные. Объясни замечание.', 'Следующий вопрос.', 'Не знаю.'];
        window.testInputContext = new AudioContext();
        window.testGetUserMedia = async () => {
            await testInputContext.resume();
            const oscillator = testInputContext.createOscillator();
            const gain = testInputContext.createGain(); gain.gain.value = 0;
            const destination = testInputContext.createMediaStreamDestination();
            oscillator.frequency.value = 260;
            oscillator.connect(gain).connect(destination); oscillator.start();
            testInputs.push({oscillator,gain,stream:destination.stream});
            return destination.stream;
        };
        navigator.mediaDevices.getUserMedia = testGetUserMedia;
        window.testVoice = on => testInputs.forEach(input => input.gain.gain.value = on ? .12 : 0);
        window.testOpenMics = () => testInputs.filter(input => input.stream.getTracks().some(track => track.readyState === 'live')).length;
        state.config.deepgram = true; state.config.whisper = false;
        state.config.tts = {provider:'fish',ready:true}; state.sound = false;
        window.realTestFetch = window.fetch;
        window.fetch = (input, options) => {
            const url = String(input);
            if (url.includes('/api/speech')) {
                if (testOpenMics()) liveTestErrors.push('Microphone active during coach speech');
                testSpoken.push(JSON.parse(options.body).text);
                if (window.testSpeechFailure) return Promise.resolve(new Response(JSON.stringify({detail:'Test TTS unavailable'}), {status:503,headers:{'Content-Type':'application/json'}}));
                if (window.testMP3) {
                    const sample = testMP3; testMP3 = null;
                    return Promise.resolve(new Response(Uint8Array.from(atob(sample), c=>c.charCodeAt(0)), {headers:{'Content-Type':'audio/mpeg'}}));
                }
                return Promise.resolve(new Response(Uint8Array.from(atob('%s'), c=>c.charCodeAt(0)), {headers:{'Content-Type':'audio/wav'}}));
            }
            if (url.includes('/api/transcribe')) {
                testTranscribed++;
                if (options.body.get('audio').size < 100) liveTestErrors.push('Empty recording');
                const text = testAnswers.shift() || 'Тестовый ответ';
                return Promise.resolve(new Response(JSON.stringify({text,raw_text:text,cleanup:'applied'}), {headers:{'Content-Type':'application/json'}}));
            }
            if (window.testGradeFailure && /\/answer$/.test(url)) return Promise.resolve(new Response(JSON.stringify({detail:'Test grading unavailable'}), {status:503,headers:{'Content-Type':'application/json'}}));
            return realTestFetch(input, options);
        };
        live.timing.followupMs = 1200;
        live.timing.tailMs = 80;
        showStart('classical_ml');
        document.querySelector('#session-mode').value = 'live';
        document.querySelector('#session-mode').dispatchEvent(new Event('change',{bubbles:true}));
        document.querySelector('#live-silence').value = '1800';
        document.querySelector('#session-count').value = '2';
        true
    """ % encoded)
    if audio:
        evaluate("window.testMP3 = " + json.dumps(base64.b64encode(audio.read_bytes()).decode()) + "; true")
    evaluate("document.querySelector('#start-form').requestSubmit(); true")
    wait(evaluate, "live.phase === 'listening' && testOpenMics() === 1")
    assert evaluate("document.querySelector('#answer-input').readOnly && speech.status === 'idle'")
    if screenshot: screenshot()

    def utterance():
        evaluate("testVoice(true); true")
        time.sleep(.4)
        evaluate("testVoice(false); true")

    utterance()
    wait(evaluate, "state.session.reviewing && live.phase === 'followup'")
    assert evaluate("state.session.attempts[0].answer.includes('запоминает шум')")
    utterance()
    wait(evaluate, "state.session.attempts[0].discussion.length === 1 && live.phase === 'followup'")
    utterance()
    wait(evaluate, "state.session.current_index === 1 && live.phase === 'listening'")
    utterance()
    wait(evaluate, "state.session.completed && !live.enabled && Boolean(document.querySelector('.result-hero'))")
    assert evaluate("state.session.attempts.length === 2 && state.session.attempts[1].mode === 'skipped'")
    assert evaluate("testTranscribed === 4 && testOpenMics() === 0 && testSpoken.length >= 5")

    # Failed narration must never open the answer microphone or submit an answer.
    evaluate("window.testSpeechFailure=true; showStart('classical_ml'); document.querySelector('#start-form').requestSubmit(); true")
    wait(evaluate, "live.paused && live.message.includes('Озвучка')")
    assert evaluate("testOpenMics() === 0 && testTranscribed === 4 && state.session.answered === 0")
    evaluate("live.stop(); window.testSpeechFailure=false; live.start(); true")
    wait(evaluate, "live.phase === 'listening' && testOpenMics() === 1")
    evaluate("live.pause(); true")
    assert evaluate("live.paused && testOpenMics() === 0")
    time.sleep(.3)
    assert evaluate("testTranscribed === 4 && state.session.answered === 0")

    # Evaluation failure keeps the cleaned draft for review and releases the mic.
    evaluate("window.testGradeFailure=true; window.testAnswers=['Сохранённый ответ после ошибки']; live.start(); true")
    wait(evaluate, "live.phase === 'listening'")
    utterance()
    wait(evaluate, "live.paused && live.message.includes('Test grading unavailable')")
    assert evaluate("testOpenMics() === 0 && document.querySelector('#answer-input').value === 'Сохранённый ответ после ошибки'")
    assert evaluate("state.session.answered === 0")
    assert evaluate("liveTestErrors.length === 0"), evaluate("JSON.stringify(liveTestErrors)")
    evaluate("live.stop(); testInputs.forEach(input=>input.oscillator.stop()); testInputContext.close(); true")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--audio", type=Path, help="Use a real local MP3 for the first question's streaming playback")
    args = parser.parse_args()
    faulthandler.dump_traceback_later(85, exit=True)
    directory = ROOT / "logs/live-check"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory, ignore_cleanup_errors=True) as temporary:
        settings = Settings(data_dir=Path(temporary)/"data", deepgram_key="", openai_key="", openrouter_key="",
                            model="", embedding_model="", qdrant_url="", qdrant_key="", tts_provider="system", fish_key="")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
        with patch("app.store.load_cards", return_value=load_cards()[:3]):
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started: break
                time.sleep(.05)
            assert server.started
            url = f"http://127.0.0.1:{port}"
            try:
                if args.desktop:
                    from app.desktop import open_window
                    errors = []
                    started = False
                    def check(window):
                        nonlocal started
                        if started: return
                        started = True
                        try: checks(window.evaluate_js, args.audio)
                        except Exception as error: errors.append(repr(error))
                        finally: window.destroy()
                    open_window(SimpleNamespace(url=url), on_loaded=check, profile_path=Path(temporary)/"profile")
                    assert started and not errors, errors
                else:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(channel="msedge", headless=True,
                            args=["--autoplay-policy=no-user-gesture-required"])
                        page = browser.new_page()
                        page.goto(url)
                        checks(page.evaluate, args.audio, lambda: page.screenshot(path=str(ROOT / "logs/preview-live.png"), full_page=True))
                        browser.close()
            finally:
                server.should_exit = True
                thread.join(timeout=10)
    faulthandler.cancel_dump_traceback_later()
    print(json.dumps({"result":"passed", "renderer":"WebView2" if args.desktop else "Edge", "checks":[
        "automatic question and microphone", "real audio energy endpointing", "automatic submission and feedback",
        "spoken discussion", "voice next and skip", "automatic finish", "no microphone during narration",
        "pause releases microphone", "TTS failure pauses", "grading failure preserves draft"]}))


if __name__ == "__main__":
    main()
