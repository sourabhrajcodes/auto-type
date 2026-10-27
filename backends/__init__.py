"""Choose the keyboard backend for this OS and session.

``get_keyboard()`` returns the first backend that reports itself usable, or
raises ``KeyboardError`` with every reason it found - the UI shows that text.
"""

import os
import sys

from .base import KEY_NAMES, MOD_NAMES, Keyboard, KeyboardError  # noqa: F401

__all__ = ["get_keyboard", "Keyboard", "KeyboardError", "KEY_NAMES", "MOD_NAMES"]


def is_wayland() -> bool:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session in ("x11", "wayland"):
        return session == "wayland"
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def candidates():
    """Backend classes to try, best first. Imports lazily: X11/Win32 libraries
    must not be loaded on a platform that does not need them."""
    if sys.platform == "win32":
        from .win32 import Win32Keyboard

        return [Win32Keyboard]
    if sys.platform.startswith("linux"):
        from .x11 import X11Keyboard

        if is_wayland():
            from .wayland import WtypeKeyboard

            return [WtypeKeyboard, X11Keyboard]  # X11 still reaches XWayland apps
        return [X11Keyboard]
    raise KeyboardError("unsupported platform: %s" % sys.platform)


def get_keyboard() -> Keyboard:
    reasons = []
    on_wayland = sys.platform.startswith("linux") and is_wayland()
    for cls in candidates():
        keyboard = cls()
        ok, why = keyboard.available()
        if ok:
            if on_wayland and cls.name == "x11":
                keyboard.warning = (
                    "Wayland session: typing only reaches X11/XWayland windows"
                )
            return keyboard
        reasons.append("%s: %s" % (cls.name, why))
    raise KeyboardError("; ".join(reasons))
