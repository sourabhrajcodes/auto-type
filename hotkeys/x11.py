"""Linux X11 global hotkey by polling the keyboard state with XQueryKeymap.

Deliberately the same shape as the Windows watcher: poll, detect a rising edge,
call back. It does not grab the key, so F8 keeps working in every other program
and there is no grab conflict to handle.
"""

import ctypes
import ctypes.util
import threading

F8_KEYSYM = 0xFFC5  # XK_F8

MAP_BYTES = 32  # XQueryKeymap fills 32 bytes = 256 key bits


def key_is_down(bitmap, keycode: int) -> bool:
    """Decode one key from an ``XQueryKeymap`` bitmap (pure, unit-testable)."""
    if keycode <= 0:
        return False
    index, bit = divmod(keycode, 8)
    return bool(bitmap[index] & (1 << bit))


class X11PollingHotkey(threading.Thread):
    name = "x11"
    warning = ""

    def __init__(self, keysym: int = F8_KEYSYM, on_press=None, poll: float = 0.04):
        super().__init__(daemon=True)
        self.keysym = keysym
        self._on_press = on_press
        self._poll = poll
        self._stop = threading.Event()
        self._x = None
        self._dpy = None
        self._keycode = 0

    def _load(self) -> None:
        if self._x is not None:
            return
        lib = ctypes.util.find_library("X11")
        if not lib:
            raise OSError("libX11 not found (sudo apt install libx11-6)")
        x = ctypes.CDLL(lib)
        vp, ci, cul = ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong
        x.XOpenDisplay.restype = vp
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XCloseDisplay.argtypes = [vp]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [vp, cul]
        x.XQueryKeymap.restype = ci
        x.XQueryKeymap.argtypes = [vp, ctypes.POINTER(ctypes.c_char)]
        self._x = x

    def available(self):
        """(True, "") when the hotkey can be watched here, else (False, reason)."""
        try:
            self._load()
        except OSError as exc:
            return False, str(exc)
        if not self._dpy:
            dpy = self._x.XOpenDisplay(None)
            if not dpy:
                return False, "cannot open the X display"
            self._dpy = dpy
        if not self._keycode:
            self._keycode = self._x.XKeysymToKeycode(self._dpy, self.keysym)
            if not self._keycode:
                return False, "F8 is not on this keyboard layout"
        return True, ""

    def start_polling(self) -> bool:
        self.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        ok, _why = self.available()
        if not ok:
            return
        bitmap = (ctypes.c_char * MAP_BYTES)()
        was_down = False
        while not self._stop.wait(self._poll):
            if not self._x.XQueryKeymap(self._dpy, bitmap):
                continue
            is_down = key_is_down(bitmap, self._keycode)
            if is_down and not was_down and self._on_press is not None:
                try:
                    self._on_press()
                except Exception:
                    pass
            was_down = is_down

    def close(self) -> None:
        if self._dpy and self._x:
            self._x.XCloseDisplay(self._dpy)
            self._dpy = None
