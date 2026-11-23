"""Start and stop only the local API process owned by this desktop session."""
import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from app.core.config import ROOT

URL = "http://127.0.0.1:8765"
LOG = logging.getLogger("ml-trainer.desktop")

def healthy(url=URL):
    try:
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with direct.open(url + "/api/health", timeout=1) as response:
            return json.load(response).get("app") == "ml-trainer"
    except (OSError, ValueError, urllib.error.URLError):
        return False

class LocalServer:
    def __init__(self, url=URL):
        self.url = url
        self.process = None

    def start(self):
        if healthy(self.url):
            return
        (ROOT / "logs").mkdir(exist_ok=True)
        python = ROOT / ".venv/Scripts/pythonw.exe"
        if not python.exists():
            raise RuntimeError("Сначала запусти Setup.cmd в папке проекта.")
        with (ROOT / "logs/server.log").open("a", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                [str(python), "-m", "app.server"], cwd=ROOT, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if healthy(self.url):
                return
            if self.process.poll() is not None:
                raise RuntimeError("Не удалось запустить сервер. Подробности: logs/server.log. Возможно, порт 8765 занят.")
            time.sleep(0.2)
        raise RuntimeError("Сервер не ответил вовремя. Проверь интернет и настройки embeddings. Подробности: logs/server.log.")

    def stop(self):
        # Do not stop a development server started independently of this window.
        if self.process is None or self.process.poll() is not None:
            return
        try:
            with urllib.request.urlopen(self.url + "/api/config", timeout=2) as response:
                token = json.load(response)["token"]
            request = urllib.request.Request(self.url + "/api/shutdown", data=b"", method="POST",
                                             headers={"X-App-Token": token})
            with urllib.request.urlopen(request, timeout=2):
                pass
            self.process.wait(timeout=8)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            LOG.warning("Graceful server shutdown failed; stopping the owned process.", exc_info=True)
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=5)
