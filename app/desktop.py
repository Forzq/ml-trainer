"""Windows desktop host: native WinForms window, WebView2 and an owned API process."""
import ctypes
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from urllib.parse import urlsplit

from app.config import ROOT

URL = "http://127.0.0.1:8765"
TITLE = "ML Trainer"
LOG = logging.getLogger("ml-trainer.desktop")


def healthy(url=URL):
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
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


class SingleInstance:
    def __init__(self, name="Local\\MLTrainerDesktopV1"):
        self.name = name
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = None

    def acquire(self):
        self.handle = self.kernel.CreateMutexW(None, False, self.name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.get_last_error() != 183

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def focus_existing():
    user = ctypes.windll.user32
    user.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user.FindWindowW.restype = ctypes.c_void_p
    user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user.IsIconic.argtypes = [ctypes.c_void_p]
    user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    for _ in range(75):
        handle = user.FindWindowW(None, TITLE)
        if handle:
            if user.IsIconic(handle):
                user.ShowWindow(handle, 9)
            user.SetForegroundWindow(handle)
            return
        time.sleep(0.2)


def same_origin(uri, url=URL):
    try:
        source, target = urlsplit(str(uri)), urlsplit(url)
        return (source.scheme, source.hostname, source.port) == (target.scheme, target.hostname, target.port)
    except ValueError:
        return False


def ask_microphone(window):
    from System.Windows.Forms import DialogResult, MessageBox, MessageBoxButtons, MessageBoxIcon

    return MessageBox.Show(
        window.native,
        "Разрешить ML Trainer использовать микрофон для голосового ответа?\n\n"
        "Запись начинается только после нажатия «Ответить голосом».",
        TITLE, MessageBoxButtons.YesNo, MessageBoxIcon.Question,
    ) == DialogResult.Yes


def set_native_theme(window, theme):
    """Called on the WinForms UI thread; unsupported DWM attributes are ignored."""
    from System.Drawing import ColorTranslator

    dark = theme == "dark"
    background = "#14141c" if dark else "#fafbfc"
    native = window.native
    native.BackColor = ColorTranslator.FromHtml(background)
    native.webview.DefaultBackgroundColor = ColorTranslator.FromHtml("#101017" if dark else "#f7f8fa")
    try:
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dwm.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        dwm.restype = ctypes.c_long
        handle = native.Handle.ToInt64()
        enabled = ctypes.c_int(dark)
        dwm(handle, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
        # On Windows 11 the caption and caption text can match the application palette.
        caption = ctypes.c_uint(int.from_bytes(bytes.fromhex(background[1:]), "little"))
        foreground = ctypes.c_uint(0x00F7EDEF if dark else 0x00362C20)
        dwm(handle, 35, ctypes.byref(caption), ctypes.sizeof(caption))
        dwm(handle, 36, ctypes.byref(foreground), ctypes.sizeof(foreground))
    except (OSError, AttributeError):
        LOG.debug("Custom window frame theme is unavailable", exc_info=True)


def configure_native(window, url=URL):
    """Attach native handlers on the UI thread before the first page is used."""
    from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState

    control = window.native.webview
    set_native_theme(window, "dark")
    microphone_allowed = False
    initialized = False

    def permission_requested(sender, args):
        nonlocal microphone_allowed
        args.State = CoreWebView2PermissionState.Deny
        args.SavesInProfile = False
        if not same_origin(args.Uri, url) or args.PermissionKind != CoreWebView2PermissionKind.Microphone:
            return
        if not microphone_allowed:
            microphone_allowed = ask_microphone(window)
        if microphone_allowed:
            args.State = CoreWebView2PermissionState.Allow

    def navigation_starting(sender, args):
        if not same_origin(args.Uri, url) and str(args.Uri) != "about:blank":
            args.Cancel = True

    def ready(sender, args):
        nonlocal initialized
        if initialized or control.CoreWebView2 is None:
            return
        initialized = True
        control.CoreWebView2.PermissionRequested += permission_requested
        control.CoreWebView2.NavigationStarting += navigation_starting
        control.CoreWebView2.Settings.AreDefaultContextMenusEnabled = False
        control.CoreWebView2.Settings.AreDevToolsEnabled = False
        control.CoreWebView2.Settings.IsStatusBarEnabled = False

    control.CoreWebView2InitializationCompleted += ready
    if control.CoreWebView2 is not None:
        ready(None, None)


class DesktopApi:
    def __init__(self):
        self._window = None

    def close(self):
        if self._window:
            self._window.destroy()

    def set_theme(self, theme):
        if theme not in ("dark", "light"):
            raise ValueError("Unknown theme")
        if self._window:
            from System import Action

            self._window.native.BeginInvoke(Action(lambda: set_native_theme(self._window, theme)))


def open_window(server, on_loaded=None, profile_path=None):
    import webview

    # App-owned audio should play after an asynchronous TTS request as well as a click.
    browser_args = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    if "--autoplay-policy=" not in browser_args:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = browser_args + " --autoplay-policy=no-user-gesture-required"
    api = DesktopApi()
    window = webview.create_window(
        TITLE, server.url, js_api=api, width=1320, height=900, min_size=(900, 650),
        background_color="#101017", text_select=True,
    )
    api._window = window
    window.events.before_show += lambda: configure_native(window, server.url)
    if on_loaded:
        window.events.loaded += lambda: on_loaded(window)
    profile = profile_path or ROOT / "data/desktop-profile"
    profile.mkdir(parents=True, exist_ok=True)
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(profile),
                  icon=str(ROOT / "web/app.ico"), debug=False)


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
