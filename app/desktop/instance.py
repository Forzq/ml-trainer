"""Windows mutex and foreground activation for a single application instance."""
import ctypes
import time

TITLE = "ML Trainer"

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
