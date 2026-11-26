"""Compose the desktop lifecycle and capture startup errors."""
import argparse
import ctypes
import logging
from contextlib import redirect_stderr, redirect_stdout
from app.core.config import ROOT
from app.desktop.instance import MUTEX_NAME, TITLE, SingleInstance, focus_existing
from app.desktop.server import LocalServer
from app.desktop.tunnel import VPS_MUTEX_NAME, VPS_TITLE, SshTunnel
from app.desktop.window import open_window

LOG = logging.getLogger("ml-trainer.desktop")

def main(on_loaded=None, *, vps=None):
    title = VPS_TITLE if vps else TITLE
    instance = SingleInstance(VPS_MUTEX_NAME if vps else MUTEX_NAME)
    server = SshTunnel(vps) if vps else LocalServer()
    try:
        if not instance.acquire():
            focus_existing(title)
            return
        app_id = "MLTrainer.Desktop.VPS.1" if vps else "MLTrainer.Desktop.1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        server.start()
        profile = ROOT / "data/vps-desktop-profile" if vps else None
        open_window(server, on_loaded=on_loaded, profile_path=profile, title=title)
    finally:
        server.stop()
        instance.close()

def entrypoint():
    parser = argparse.ArgumentParser(description="ML Trainer desktop application")
    parser.add_argument("--vps", metavar="USER@HOST", help="Connect to a private ML Trainer VPS over SSH")
    args = parser.parse_args()
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "desktop.log").open("a", encoding="utf-8", buffering=1) as output:
        with redirect_stdout(output), redirect_stderr(output):
            logging.basicConfig(stream=output, level=logging.INFO)
            try:
                main(vps=args.vps)
            except Exception as error:
                LOG.exception("Desktop application failed")
                details = str(error) if args.vps and isinstance(error, RuntimeError) else (
                    "Не удалось открыть ML Trainer. Подробности: logs/desktop.log.\n\n"
                    "Для окна приложения нужен Microsoft Edge WebView2 Runtime. "
                    "Запусти Setup.cmd, если зависимости ещё не установлены."
                )
                ctypes.windll.user32.MessageBoxW(
                    None, details, VPS_TITLE if args.vps else TITLE, 0x10,
                )
