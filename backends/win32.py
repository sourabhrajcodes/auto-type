"""Windows backend: the existing, tested ``SendInput`` transport.

``engine.WindowsKeyboard`` already speaks the neutral interface (``type_char``
and named ``key`` presses with real scan codes); this class only gives it the
backend name and translates its errors, so there is a single Win32 code path.
The key *policy* (Escape before Enter, the auto-indent fix) is ``engine.emit``'s
job, shared with every other platform.
"""

import engine

from .base import Keyboard, KeyboardError


class Win32Keyboard(engine.WindowsKeyboard, Keyboard):
    name = "win32"

    def __init__(self, send=None, **options):
        try:
            super().__init__(send=send, **options)
        except RuntimeError as exc:  # not Windows, or no user32 available
            raise KeyboardError(str(exc))

    def available(self):
        return (True, "") if engine.IS_WINDOWS else (False, "Windows only")

    def key(self, name: str, mods: tuple = ()) -> None:
        try:
            super().key(name, mods)
        except ValueError as exc:
            raise KeyboardError(str(exc))
