"""Pick the global-hotkey mechanism for this OS and session.

``make_hotkey()`` returns an object with ``start()``/``stop()`` and never
raises: when nothing can watch keys, a quiet no-op is returned and its
``warning`` says why (shown next to the status line).
"""

import sys


class NullHotkey:
    """A hotkey that never fires (macOS, or a compositor without any hook)."""

    name = "none"

    def __init__(self, warning: str = ""):
        self.warning = warning

    def start(self) -> None:
        pass

    def start_polling(self) -> bool:
        return False

    def stop(self) -> None:
        pass


def make_hotkey(on_press, poll: float = 0.04):
    """Global start/stop hotkey for this platform."""
    if sys.platform == "win32":
        from .windows import HotkeyWatcher

        return HotkeyWatcher(0x77, on_press, poll=poll)  # VK_F8

    if sys.platform.startswith("linux"):
        try:
            from .x11 import X11PollingHotkey

            hotkey = X11PollingHotkey(on_press=on_press, poll=poll)
            ok, why = hotkey.available()
            if ok:
                return hotkey
            return NullHotkey(
                "%s - bind 'start_auto_typer.sh --toggle' to a key instead" % why
            )
        except Exception as exc:  # pragma: no cover - defensive
            return NullHotkey("no global hotkey: %s" % (exc,))

    return NullHotkey("global hotkeys are not implemented on this system")
