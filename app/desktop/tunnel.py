"""Own a private SSH tunnel for the Windows VPS window."""
import shutil
import socket
import subprocess
import time
from pathlib import Path

from app.core.config import ROOT
from app.desktop.server import healthy

LOCAL_PORT = 8768
VPS_TITLE = "ML Trainer — VPS"
VPS_MUTEX_NAME = "Local\\MLTrainerVpsDesktopV1"


class SshTunnel:
    url = f"http://127.0.0.1:{LOCAL_PORT}"

    def __init__(self, target):
        self.target = target
        self.process = None

    def start(self):
        key = Path.home() / ".ssh/ml_trainer_vps_ed25519"
        ssh = shutil.which("ssh.exe")
        if not ssh or not key.is_file():
            raise RuntimeError("Для подключения к VPS нужны клиент OpenSSH и ключ ML Trainer в папке .ssh.")
        try:
            with socket.socket() as port:
                port.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                port.bind(("127.0.0.1", LOCAL_PORT))
        except OSError as error:
            raise RuntimeError(f"Порт {LOCAL_PORT} уже занят. Закрой другое приложение, которое его использует.") from error
        logs = ROOT / "logs"
        logs.mkdir(exist_ok=True)
        with (logs / "vps-ssh.log").open("a", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                [ssh, "-C", "-N", "-T", "-i", str(key), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                 "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=12",
                 "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3",
                 "-L", f"127.0.0.1:{LOCAL_PORT}:127.0.0.1:8765", "--", self.target],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        deadline = time.monotonic() + 22
        while self.process.poll() is None and time.monotonic() < deadline:
            if healthy(self.url) and self.process.poll() is None:
                return
            time.sleep(0.2)
        raise RuntimeError("Не удалось подключиться к ML Trainer на VPS. Подробности в logs/vps-ssh.log.")

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
