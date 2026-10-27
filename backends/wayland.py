"""Wayland keyboard backend through ``wtype``.

Wayland forbids injecting into other windows by design; ``wtype`` uses the
compositor's virtual-keyboard protocol, which Sway, Hyprland, KDE and others
implement. GNOME does not, so ``available()`` reports that instead of failing
later with an unhelpful error.
"""

import shutil
import subprocess

from .base import Keyboard, KeyboardError

WTYPE_KEYS = {
    "enter": "Return",
    "tab": "Tab",
    "esc": "Escape",
    "home": "Home",
    "end": "End",
    "backspace": "BackSpace",
    "space": "space",
}


class WtypeKeyboard(Keyboard):
    name = "wtype"

    def _run(self, argv) -> None:
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise KeyboardError("wtype failed: %s" % (exc,))
        if result.returncode != 0:
            detail = result.stderr.strip() or "exit %d" % result.returncode
            raise KeyboardError("wtype: " + detail)

    @staticmethod
    def _key_argv(name: str, mods: tuple = ()):
        if name not in WTYPE_KEYS:
            raise KeyboardError("unknown key name %r" % (name,))
        argv = ["wtype"]
        for mod in mods:
            argv += ["-M", mod]
        argv += ["-k", WTYPE_KEYS[name]]
        for mod in reversed(tuple(mods)):
            argv += ["-m", mod]
        return argv

    def available(self):
        if not shutil.which("wtype"):
            return False, "wtype is not installed (sudo apt install wtype)"
        try:
            self._run(["wtype", "-M", "shift", "-m", "shift"])  # harmless probe
        except KeyboardError as exc:
            return False, "%s (this compositor needs a different backend)" % (exc,)
        return True, ""

    def type_char(self, ch: str) -> None:
        if ch == "\n":
            return self.key("enter")
        if ch == "\t":
            return self.key("tab")
        if ord(ch) < 0x20:
            return
        # "--" keeps text that starts with "-" from being read as a flag.
        self._run(["wtype", "--", ch])

    def key(self, name: str, mods: tuple = ()) -> None:
        self._run(self._key_argv(name, mods))
