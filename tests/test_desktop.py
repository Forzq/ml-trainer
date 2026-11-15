import os
from unittest.mock import Mock, patch

import pytest

from app.desktop import DesktopApi, LocalServer, SingleInstance, main, same_origin


def test_origin_requires_exact_scheme_host_and_port():
    assert same_origin("http://127.0.0.1:8765/#training")
    assert not same_origin("https://127.0.0.1:8765/")
    assert not same_origin("http://127.0.0.1:8766/")
    assert not same_origin("http://127.0.0.1.example.org:8765/")
    assert not same_origin("https://example.org/")
    assert not same_origin("http://127.0.0.1:invalid/")


def test_existing_development_server_is_not_stopped():
    server = LocalServer()
    with patch("app.desktop.healthy", return_value=True), patch("app.desktop.subprocess.Popen") as spawn:
        server.start()
        server.stop()
        spawn.assert_not_called()


def test_server_is_stopped_when_native_window_fails():
    with patch("app.desktop.SingleInstance") as mutex, patch("app.desktop.LocalServer") as server, \
         patch("app.desktop.open_window", side_effect=RuntimeError("WebView2 failed")), \
         patch("app.desktop.ctypes.windll", create=True):
        mutex.return_value.acquire.return_value = True
        with pytest.raises(RuntimeError, match="WebView2 failed"):
            main()
        server.return_value.start.assert_called_once()
        server.return_value.stop.assert_called_once()
        mutex.return_value.close.assert_called_once()


def test_second_launch_focuses_window_without_starting_server():
    with patch("app.desktop.SingleInstance") as mutex, patch("app.desktop.LocalServer") as server, \
         patch("app.desktop.focus_existing") as focus, patch("app.desktop.open_window") as window:
        mutex.return_value.acquire.return_value = False
        main()
        focus.assert_called_once()
        server.return_value.start.assert_not_called()
        window.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex")
def test_native_single_instance_lock_is_released():
    first, second = SingleInstance(), SingleInstance()
    try:
        assert first.acquire()
        assert not second.acquire()
    finally:
        first.close()
        second.close()
    third = SingleInstance()
    try:
        assert third.acquire()
    finally:
        third.close()


def test_close_bridge_closes_native_window():
    bridge = DesktopApi()
    bridge._window = Mock()
    bridge.close()
    bridge._window.destroy.assert_called_once()
