"""Linux X11 keyboard backend: XTest injection through plain ``ctypes``.

No pip packages: it uses libX11 + libXtst (the ``libxtst6`` package). Real
keycodes are sent, so browsers derive the same ``event.code`` a physical
keyboard would give them. Characters that are not on the current layout are
typed through a spare keycode that is remapped per character and handed back on
``close()`` - the same trick xdotool uses.
"""

import ctypes
import ctypes.util
import os
import threading
import time

from .base import Keyboard, KeyboardError

# X keysyms for the named keys (see X11/keysymdef.h).
KS_NAMED = {
    "enter": 0xFF0D,
    "tab": 0xFF09,
    "esc": 0xFF1B,
    "home": 0xFF50,
    "end": 0xFF57,
    "backspace": 0xFF08,
    "space": 0x0020,
    "shift": 0xFFE1,
    "ctrl": 0xFFE3,
    "alt": 0xFFE9,
}


def char_to_keysym(ch: str):
    """X keysym for a character, or None when it cannot be typed as one.

    Latin-1 keysyms equal their code point; everything else uses the Unicode
    keysym range (0x01000000 + code point).
    """
    if ch == "\n":
        return KS_NAMED["enter"]
    if ch == "\t":
        return KS_NAMED["tab"]
    cp = ord(ch)
    if cp < 0x20 or cp == 0x7F:
        return None  # other control characters have no keysym
    if cp <= 0x7E or 0xA0 <= cp <= 0xFF:
        return cp
    return 0x01000000 + cp


class X11Keyboard(Keyboard):
    name = "x11"

    def __init__(self, remap_delay: float = 0.008, force_scratch: bool = None):
        if force_scratch is None:
            force_scratch = os.environ.get("AUTO_TYPER_X11_SCRATCH") == "1"
        self.remap_delay = remap_delay  # raise it if a browser drops characters
        self.force_scratch = force_scratch
        self._x = None
        self._t = None
        self._dpy = None
        self._layout = {}
        self._scratch = None
        self._scratch_sym = 0
        self._per = 0
        self._shift_kc = 0
        self._kc_cache = {}
        self._lock = threading.Lock()

    # -- setup ---------------------------------------------------------------
    def _load(self) -> None:
        if self._x is not None:
            return
        lib_x = ctypes.util.find_library("X11")
        lib_t = ctypes.util.find_library("Xtst")
        if not lib_x:
            raise KeyboardError("libX11 not found (sudo apt install libx11-6)")
        if not lib_t:
            raise KeyboardError("libXtst not found (sudo apt install libxtst6)")
        x, t = ctypes.CDLL(lib_x), ctypes.CDLL(lib_t)
        vp, ci, cul = ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong
        pi = ctypes.POINTER(ci)
        x.XOpenDisplay.restype = vp
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XCloseDisplay.argtypes = [vp]
        x.XFlush.argtypes = [vp]
        x.XSync.argtypes = [vp, ci]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [vp, cul]
        x.XDisplayKeycodes.argtypes = [vp, pi, pi]
        x.XGetKeyboardMapping.restype = ctypes.POINTER(cul)
        x.XGetKeyboardMapping.argtypes = [vp, ctypes.c_ubyte, ci, pi]
        x.XFree.argtypes = [vp]
        x.XChangeKeyboardMapping.argtypes = [vp, ci, ci, ctypes.POINTER(cul), ci]
        t.XTestQueryExtension.restype = ci
        t.XTestQueryExtension.argtypes = [vp, pi, pi, pi, pi]
        t.XTestFakeKeyEvent.restype = ci
        t.XTestFakeKeyEvent.argtypes = [vp, ctypes.c_uint, ci, cul]
        self._x, self._t = x, t

    def available(self):
        try:
            self._load()
        except KeyboardError as exc:
            return False, str(exc)
        if self._dpy:
            return True, ""
        dpy = self._x.XOpenDisplay(None)
        if not dpy:
            return False, "cannot open the X display ($DISPLAY=%r)" % (
                os.environ.get("DISPLAY"),
            )
        probes = [ctypes.c_int() for _ in range(4)]
        has_xtest = self._t.XTestQueryExtension(
            dpy, *[ctypes.byref(p) for p in probes]
        )
        if not has_xtest:
            self._x.XCloseDisplay(dpy)
            return False, "the X server has no XTEST extension"
        self._dpy = dpy
        self._read_keymap()
        return True, ""

    def _read_keymap(self) -> None:
        x = self._x
        low, high, per = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        x.XDisplayKeycodes(self._dpy, ctypes.byref(low), ctypes.byref(high))
        count = high.value - low.value + 1
        ptr = x.XGetKeyboardMapping(self._dpy, low.value, count, ctypes.byref(per))
        self._per = per.value
        rows = []
        for index in range(count):
            rows.append(
                [ptr[index * self._per + column] for column in range(self._per)]
            )
        x.XFree(ctypes.cast(ptr, ctypes.c_void_p))
        layout = {}
        for index, syms in enumerate(rows):
            keycode = low.value + index
            if syms[0] and syms[0] not in layout:
                layout[syms[0]] = (keycode, False)  # unshifted level
            if len(syms) > 1 and syms[1] and syms[1] not in layout:
                layout[syms[1]] = (keycode, True)  # shifted level
        self._layout = layout
        for index in range(count - 1, -1, -1):
            if not any(rows[index]):  # last completely unused keycode
                self._scratch = low.value + index
                break
        self._shift_kc = self._keycode(KS_NAMED["shift"])

    def _ensure(self) -> None:
        if not self._dpy:
            ok, why = self.available()
            if not ok:
                raise KeyboardError(why)

    # -- low level -----------------------------------------------------------
    def _keycode(self, keysym: int) -> int:
        if keysym not in self._kc_cache:
            self._kc_cache[keysym] = self._x.XKeysymToKeycode(self._dpy, keysym)
        return self._kc_cache[keysym]

    def _fake(self, keycode: int, press: bool) -> None:
        if not self._t.XTestFakeKeyEvent(self._dpy, keycode, 1 if press else 0, 0):
            raise KeyboardError("X server refused a key event (XTEST failed)")

    def _tap(self, keycode: int, mod_keycodes: tuple = ()) -> None:
        for mod in mod_keycodes:
            self._fake(mod, True)
        self._fake(keycode, True)
        self._fake(keycode, False)
        for mod in reversed(mod_keycodes):
            self._fake(mod, False)
        self._x.XFlush(self._dpy)

    def _set_scratch(self, keysym: int) -> None:
        # Every level gets the same keysym: a single keysym would make X fold the
        # case for some layouts, so capitals would arrive lowercased.
        arr = (ctypes.c_ulong * self._per)(*([keysym] * self._per))
        self._x.XChangeKeyboardMapping(
            self._dpy, self._scratch, self._per, arr, 1
        )
        self._x.XSync(self._dpy, 0)
        self._scratch_sym = keysym

    # -- Keyboard API --------------------------------------------------------
    def type_char(self, ch: str) -> None:
        keysym = char_to_keysym(ch)
        if keysym is None:
            return
        with self._lock:
            self._ensure()
            hit = None if self.force_scratch else self._layout.get(keysym)
            if hit:
                keycode, shifted = hit
                self._tap(keycode, (self._shift_kc,) if shifted else ())
                return
            if self._scratch is None:
                raise KeyboardError("no free keycode to type %r" % (ch,))
            if keysym != self._scratch_sym:
                self._set_scratch(keysym)
                time.sleep(self.remap_delay)  # let clients see MappingNotify
            self._tap(self._scratch)
            self._x.XSync(self._dpy, 0)

    def key(self, name: str, mods: tuple = ()) -> None:
        if name not in KS_NAMED:
            raise KeyboardError("unknown key name %r" % (name,))
        with self._lock:
            self._ensure()
            keycode = self._keycode(KS_NAMED[name])
            if not keycode:
                raise KeyboardError("key %r is not on this keyboard layout" % (name,))
            self._tap(keycode, tuple(self._keycode(KS_NAMED[m]) for m in mods))

    def close(self) -> None:
        with self._lock:
            if not self._dpy:
                return
            if self._scratch is not None and self._scratch_sym:
                self._set_scratch(0)  # hand the spare keycode back
            self._x.XCloseDisplay(self._dpy)
            self._dpy = None
