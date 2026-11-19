"""Compose the desktop lifecycle and capture startup errors."""
import ctypes
import logging
from contextlib import redirect_stderr, redirect_stdout
from app.core.config import ROOT
from app.desktop.instance import TITLE, SingleInstance, focus_existing
from app.desktop.server import LocalServer
from app.desktop.window import open_window

LOG = logging.getLogger("ml-trainer.desktop")

def main(on_loaded=None):
    instance = SingleInstance()
    server = LocalServer()
    try:
        if not instance.acquire():
            focus_existing()
            return
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MLTrainer.Desktop.1")
        server.start()
        open_window(server, on_loaded=on_loaded)
    finally:
        server.stop()
        instance.close()

def entrypoint():
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "desktop.log").open("a", encoding="utf-8", buffering=1) as output:
        with redirect_stdout(output), redirect_stderr(output):
            logging.basicConfig(stream=output, level=logging.INFO)
            try:
                main()
            except Exception:
                LOG.exception("Desktop application failed")
                ctypes.windll.user32.MessageBoxW(
                    None,
                    "Не удалось открыть ML Trainer. Подробности: logs/desktop.log.\n\n"
                    "Для окна приложения нужен Microsoft Edge WebView2 Runtime. "
                    "Запусти Setup.cmd, если зависимости ещё не установлены.",
                    TITLE, 0x10,
                )
