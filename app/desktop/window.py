"""WebView2 window, native theme, microphone permission and JavaScript bridge."""
import ctypes
import logging
import os
from urllib.parse import urlsplit
from app.core.config import ROOT
from app.desktop.instance import TITLE
from app.desktop.server import URL

LOG = logging.getLogger("ml-trainer.desktop")

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

def open_window(server, on_loaded=None, profile_path=None, *, title=TITLE):
    import webview

    # App-owned audio should play after an asynchronous TTS request as well as a click.
    browser_args = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    if "--autoplay-policy=" not in browser_args:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = browser_args + " --autoplay-policy=no-user-gesture-required"
    api = DesktopApi()
    window = webview.create_window(
        title, server.url, js_api=api, width=1320, height=900, min_size=(900, 650),
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
                  icon=str(ROOT / "web/mockroom.ico"), debug=False)
