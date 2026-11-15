"""Run UI and fake microphone checks inside the real Windows WebView2 host."""
import json
import faulthandler
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn

from app.config import Settings
from app.desktop import open_window
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
    faulthandler.dump_traceback_later(45, exit=True)
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--use-fake-device-for-media-stream"
    (ROOT / "logs/native-check").mkdir(parents=True, exist_ok=True)
    errors = []
    finished = threading.Event()
    # WebView2 may retain telemetry files briefly after its last window closes.
    with tempfile.TemporaryDirectory(dir=ROOT / "logs/native-check", prefix="native-", ignore_cleanup_errors=True) as temporary:
        temp = Path(temporary)
        settings = Settings(data_dir=temp / "data", deepgram_key="", openrouter_key="", model="", embedding_model="", qdrant_url="", qdrant_key="")
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
                window.evaluate_js("state.sound = false; showStart('fundamentals'); document.querySelector('#session-count').value='2'; document.querySelector('#start-form').requestSubmit(); true")
                wait_js(window, "Boolean(document.querySelector('#answer-input'))")
                window.evaluate_js("document.querySelector('#answer-input').value='Модель запоминает шум и хуже работает на новых данных. Сравниваем с валидацией.'; document.querySelector('#answer-form').requestSubmit(); true")
                wait_js(window, "Boolean(document.querySelector('[data-action=next]'))")
                assert window.evaluate_js("document.querySelector('.message-text:last-of-type') !== null")
                window.evaluate_js("document.querySelector('[data-action=next]').click(); true")
                wait_js(window, "Boolean(document.querySelector('#answer-input'))")
                window.evaluate_js("""
                    state.config.deepgram = true;
                    const originalFetch = window.fetch;
                    window.fetch = (input, options) => String(input).includes('/api/transcribe')
                        ? Promise.resolve(new Response(JSON.stringify({text:'Тестовая запись в Windows-приложении'}), {status:200, headers:{'Content-Type':'application/json'}}))
                        : originalFetch(input, options);
                    document.querySelector('[data-action=record]').click(); true
                """)
                wait_js(window, "state.recorder?.state === 'recording'")
                time.sleep(1.2)
                window.evaluate_js("document.querySelector('[data-action=record]').click(); true")
                wait_js(window, "document.querySelector('#answer-input')?.value === 'Тестовая запись в Windows-приложении'")
                assert window.evaluate_js("state.stream === null")
                window.evaluate_js("document.querySelector('[data-action=skip]').click(); true")
                wait_js(window, "Boolean(document.querySelector('[data-action=next]'))")
                window.evaluate_js("document.querySelector('[data-action=next]').click(); true")
                wait_js(window, "Boolean(document.querySelector('.result-hero'))")
                window.evaluate_js("showSettings(); true")
                assert "Озвучка · Windows" in window.evaluate_js("document.querySelector('#settings-content').textContent")
                # Exercise the actual JS -> Python close bridge.
                window.run_js("document.querySelector('[data-action=shutdown]').click()")
                finished.set()
            except Exception as error:
                errors.append(repr(error))
                window.destroy()

        try:
            print("Opening native WebView2 window...", flush=True)
            with patch("app.desktop.ask_microphone", return_value=True) as permission:
                open_window(SimpleNamespace(url=url), on_loaded=check, profile_path=temp / "profile")
                if not errors:
                    assert permission.call_count == 1, "Native microphone permission handler was not called"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        assert finished.is_set() and not errors, errors
        faulthandler.cancel_dump_traceback_later()
        print(json.dumps({"result": "passed", "renderer": "WebView2", "checks": ["native window", "training", "native microphone permission", "recording", "transcription UI", "microphone release", "results", "close bridge"]}))


if __name__ == "__main__":
    main()
