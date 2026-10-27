"""The keyboard interface every operating system implements.

The engine decides *what* keys a character becomes (``engine.emit``); a backend
only decides *how* those keys travel. Keeping that split means the newline and
auto-indent fixes exist once, not once per platform.
"""

from abc import ABC, abstractmethod

KEY_NAMES = ("enter", "tab", "esc", "home", "end", "backspace", "space")
MOD_NAMES = ("shift", "ctrl", "alt")


class KeyboardError(RuntimeError):
    """A human-readable reason why typing cannot work here."""


class Keyboard(ABC):
    name = "base"
    warning = ""  # non-fatal caveat worth showing in the UI

    @abstractmethod
    def available(self) -> "tuple[bool, str]":
        """(True, "") when usable right now, else (False, reason)."""

    @abstractmethod
    def type_char(self, ch: str) -> None:
        """Type one character exactly as written."""

    @abstractmethod
    def key(self, name: str, mods: tuple = ()) -> None:
        """Press and release a named key (see ``KEY_NAMES``), with modifiers."""

    def close(self) -> None:
        """Release anything the backend opened."""
