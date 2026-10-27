"""A backend that records what it was asked to type instead of typing it.

Lets the newline / auto-indent policy be tested on any OS, including CI.
"""

from .base import Keyboard


class FakeKeyboard(Keyboard):
    name = "fake"

    def __init__(self):
        self.events: list[tuple] = []

    def available(self):
        return True, ""

    def type_char(self, ch: str) -> None:
        self.events.append(("char", ch))

    def key(self, name: str, mods: tuple = ()) -> None:
        self.events.append(("key", name, tuple(mods)))
