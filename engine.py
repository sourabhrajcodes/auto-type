"""Typing engine for Auto Typer.

Two independent pieces:

* ``build_plan`` - turns text + speed settings into a list of ``Stroke`` timed
  chunks. Pure Python, no OS calls, easy to unit test.
* ``WindowsKeyboard`` - types the strokes for real with the Win32 ``SendInput``
  API using ``KEYEVENTF_UNICODE``. Unicode mode reproduces any character
  (code symbols and non-English text included) exactly as pasted, regardless
  of the active keyboard layout.

No third-party dependencies.
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

__all__ = [
    "Stroke",
    "build_plan",
    "run_plan",
    "plan_duration",
    "trim_plan",
    "wait_interruptibly",
    "base_char_delay",
    "WindowsKeyboard",
    "InjectionError",
    "IS_WINDOWS",
    "NEWLINE_ENTER",
    "NEWLINE_ESC_ENTER",
    "COMPAT_MIN_GAP",
    "COMPAT_NEWLINE_PAUSE",
    "ESCAPE_ATTEMPTS",
    "ESCAPE_SETTLE",
    "STOP_POLL_SLICE",
    "EmitOptions",
    "emit",
]

IS_WINDOWS = os.name == "nt"

CHARS_PER_WORD = 5.0
"""Conventional characters-per-word used to translate WPM into per-character delay."""

MIN_WPM = 10.0
MAX_WPM = 400.0

# Extra pause multipliers applied after a character (or at the end of a word).
PAUSE_AFTER = {",": 1.35, ";": 1.35, ":": 1.35, ".": 2.0, "!": 2.0, "?": 2.0}
NEWLINE_PAUSE = 1.6
SPACE_PAUSE = 0.8
WORD_PAUSE = 1.0
WORD_BURST_RATIO = 0.5  # characters inside one word are typed this much faster

COMPAT_MIN_GAP = 0.025
"""Slowest per-key gap used when compatibility pacing is on (browser editors
start dropping or reordering input when keystrokes arrive faster than that)."""
COMPAT_NEWLINE_PAUSE = 0.12
"""Breathing room after each line break when compatibility pacing is on."""

ESCAPE_ATTEMPTS = 2
"""How often Escape is pressed before each line break (see ``ESCAPE_SETTLE``)."""

ESCAPE_SETTLE = 0.02
"""Settle time after each Escape on the way to a line break (seconds).

Chromium occasionally swallows an injected Escape that lands in the same instant
as the next key. Measured against the browser check at 100 wpm: 1 of 49 Escapes
was lost, and the editor's autocomplete then ate that line's Enter - the exact
"lines run together / indentation drifts" symptom this option exists to fix.
Escapes spaced by this gap were delivered 98 of 98 in the same test, so the key
is pressed twice with a pause between (closing an already closed popup costs
nothing) before the Enter follows.
"""

STOP_POLL_SLICE = 0.02
"""Longest a stop request can wait while the engine is pausing (seconds)."""


@dataclass(frozen=True)
class Stroke:
    """A chunk of text typed together.

    ``text`` is typed one character at a time with ``intra_delay`` between
    characters, then the engine waits ``post_delay`` seconds.
    """

    text: str
    intra_delay: float = 0.0
    post_delay: float = 0.0


def clamp_wpm(wpm: float) -> float:
    return max(MIN_WPM, min(MAX_WPM, float(wpm)))


def base_char_delay(wpm: float) -> float:
    """Seconds between characters for the requested words per minute."""
    return 60.0 / (clamp_wpm(wpm) * CHARS_PER_WORD)


def normalize_text(text: str, convert_tabs: bool = True, tab_spaces: int = 4) -> str:
    """Make pasted text safe to replay: one newline flavour, optional tab expansion."""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if convert_tabs:
        text = text.replace("\t", " " * max(0, int(tab_spaces)))
    return text


def build_plan(
    text: str,
    wpm: float = 40.0,
    mode: str = "word",
    human: bool = True,
    rng: Optional[random.Random] = None,
    convert_tabs: bool = True,
    tab_spaces: int = 4,
    min_gap: float = 0.0,
    min_newline_pause: float = 0.0,
) -> List[Stroke]:
    """Build the timed typing plan.

    ``mode`` is ``"word"`` (each word appears as a burst, then a pause) or
    ``"char"`` (steady character-by-character). With ``human=True`` the delays
    get mild random jitter and longer stops after punctuation and line breaks.
    ``min_gap`` / ``min_newline_pause`` are compatibility floors: no keystroke
    lands closer than ``min_gap`` seconds, and line breaks wait at least
    ``min_newline_pause``. Web editors need those floors.
    """
    text = normalize_text(text, convert_tabs=convert_tabs, tab_spaces=tab_spaces)
    if not text:
        return []

    rng = rng or random.Random()
    base = base_char_delay(wpm)
    strokes: List[Stroke] = []

    def jitter() -> float:
        return rng.uniform(0.6, 1.5) if human else 1.0

    if mode == "char":
        for ch in text:
            post = base * jitter()
            post = max(post, base * PAUSE_AFTER.get(ch, 0.0), min_gap)
            if ch == "\n":
                post = max(post, base * NEWLINE_PAUSE, min_newline_pause)
            strokes.append(Stroke(ch, 0.0, post))
        return strokes

    # Word-by-word: words are typed as quick bursts, whitespace flows fast,
    # and every word/space is followed by a human-ish pause.
    intra = min(0.15, max(0.008, base * WORD_BURST_RATIO, min_gap))
    for token in re.findall(r"\S+|\s+", text):
        if token.isspace():
            post = max(base * SPACE_PAUSE * jitter(), min_gap)
            if "\n" in token:
                post = max(post, base * NEWLINE_PAUSE, min_newline_pause)
            strokes.append(Stroke(token, 0.0, post))
        else:
            post = max(base * WORD_PAUSE * jitter(), min_gap)
            last = token[-1]
            if last in PAUSE_AFTER:
                post = max(post, base * PAUSE_AFTER[last])
            strokes.append(Stroke(token, intra, post))
    return strokes


def plan_duration(plan: Sequence[Stroke]) -> float:
    """Rough total time (seconds) the plan will take."""
    total = 0.0
    for stroke in plan:
        total += stroke.post_delay + stroke.intra_delay * max(0, len(stroke.text) - 1)
    return total


def trim_plan(plan: Sequence[Stroke], skip: int) -> List[Stroke]:
    """Copy of ``plan`` with the first ``skip`` characters removed (used to resume)."""
    if skip <= 0:
        return list(plan)
    trimmed: List[Stroke] = []
    for stroke in plan:
        if skip <= 0:
            trimmed.append(stroke)
            continue
        if len(stroke.text) <= skip:
            skip -= len(stroke.text)
            continue
        trimmed.append(Stroke(stroke.text[skip:], stroke.intra_delay, stroke.post_delay))
        skip = 0
    return trimmed


@dataclass(frozen=True)
class EmitOptions:
    """How each character becomes keys - the same on every operating system.

    ``esc_before_enter`` closes autocomplete popups that would otherwise eat the
    line break; ``clear_autoindent`` removes the indentation an editor inserts
    after Enter so the pasted indentation is the only one left.
    """

    esc_before_enter: bool = False
    clear_autoindent: bool = False


def emit(
    keyboard,
    ch: str,
    options: Optional[EmitOptions] = None,
    sleep: Callable[[float], None] = time.sleep,
    settle: float = ESCAPE_SETTLE,
) -> None:
    """Send one character to a ``backends.base.Keyboard``-style object.

    Pure policy: it decides *which* keys a character becomes, never how they
    travel. Every platform therefore shares one copy of the auto-indent fix.
    """
    options = options or EmitOptions()
    if ch in ("\n", "\r"):
        if options.esc_before_enter:
            for _ in range(ESCAPE_ATTEMPTS):
                keyboard.key("esc")
                if settle > 0:
                    sleep(settle)
        keyboard.key("enter")
        if options.clear_autoindent:
            # Home twice = column 0 in both plain and "smart home" editors;
            # Shift+End selects whatever the editor inserted; the space keeps the
            # Backspace safe so two lines can never merge.
            keyboard.key("home")
            keyboard.key("home")
            keyboard.key("end", ("shift",))
            keyboard.type_char(" ")
            keyboard.key("backspace")
    elif ch == "\t":
        keyboard.key("tab")
    else:
        keyboard.type_char(ch)


def wait_interruptibly(
    sleep: Callable[[float], None],
    seconds: float,
    should_stop: Optional[Callable[[], bool]] = None,
) -> bool:
    """Sleep, but come back early when a stop is requested. False = stop now.

    A single ``time.sleep`` of a slow mode's pause (up to a couple of seconds at
    10 wpm) would otherwise sit between the user's F8 press and the stop, which
    is exactly the delay this avoids. Waits are sliced into ``STOP_POLL_SLICE``
    chunks only when a stop callback exists, so plans without one (tests,
    estimates) keep their single exact sleep.
    """
    if seconds <= 0:
        return should_stop is None or not should_stop()
    if should_stop is None:
        sleep(seconds)
        return True
    remaining = seconds
    while remaining > 1e-9:
        if should_stop():
            return False
        step = min(STOP_POLL_SLICE, remaining)
        sleep(step)
        remaining -= step
    return not should_stop()


def run_plan(
    keyboard: "WindowsKeyboard",
    plan: Sequence[Stroke],
    should_stop: Optional[Callable[[], bool]] = None,
    on_char: Optional[Callable[[int], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    options: Optional[EmitOptions] = None,
) -> int:
    """Type the plan. Returns how many characters were actually typed.

    ``should_stop`` is polled before every character and at least every
    ``STOP_POLL_SLICE`` seconds inside a pause, so a stop is honoured within a
    few tens of milliseconds at any speed - including during the long pauses of
    slow and human-like modes.
    """
    typed = 0
    for stroke in plan:
        last_index = len(stroke.text) - 1
        for index, ch in enumerate(stroke.text):
            if should_stop is not None and should_stop():
                return typed
            if options is None:
                keyboard.tap_char(ch)  # the Windows-only path, kept for the tests
            else:
                emit(keyboard, ch, options, sleep=sleep)
            typed += 1
            if on_char is not None:
                on_char(typed)
            # No intra delay after the final character: the stroke's post delay takes over.
            if stroke.intra_delay > 0 and index < last_index:
                if not wait_interruptibly(sleep, stroke.intra_delay, should_stop):
                    return typed
        if should_stop is not None and should_stop():
            return typed
        if stroke.post_delay > 0:
            if not wait_interruptibly(sleep, stroke.post_delay, should_stop):
                return typed
    return typed


# --------------------------------------------------------------------------
# Win32 keystroke injection
# --------------------------------------------------------------------------

VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_HOME = 0x24
VK_END = 0x23
VK_BACKSPACE = 0x08
VK_LSHIFT = 0xA0
# Hardware scan codes. Browser editors (Monaco / VS Code in the browser and
# most online IDEs) derive the DOM event.code from the scan code, so sending
# the real scan code makes Enter and Tab indistinguishable from a real keyboard.
SCAN_ESCAPE = 0x01
SCAN_RETURN = 0x1C
SCAN_TAB = 0x0F
SCAN_BACKSPACE = 0x0E
# Home and End are "extended" keys: on real hardware they arrive E0-prefixed,
# and browsers read them from the scan code too. Without the flag a code editor
# can read scan 0x47 as Numpad-7 instead of Home.
SCAN_HOME = 0x47
SCAN_END = 0x4F
SCAN_LSHIFT = 0x2A
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1

# Named key -> (virtual key, hardware scan code, extended-key flag).
# ``space`` is typed as a character instead; it has no mapping here.
NAMED_KEYS = {
    "enter": (VK_RETURN, SCAN_RETURN, False),
    "tab": (VK_TAB, SCAN_TAB, False),
    "esc": (VK_ESCAPE, SCAN_ESCAPE, False),
    "home": (VK_HOME, SCAN_HOME, True),
    "end": (VK_END, SCAN_END, True),
    "backspace": (VK_BACKSPACE, SCAN_BACKSPACE, False),
}
NAMED_MODS = {"shift": (VK_LSHIFT, SCAN_LSHIFT)}

NEWLINE_ENTER = "enter"
NEWLINE_ESC_ENTER = "esc_enter"
NEWLINE_STRATEGIES = (NEWLINE_ENTER, NEWLINE_ESC_ENTER)

if IS_WINDOWS:  # pragma: no cover - structure definitions
    import ctypes
    import ctypes.wintypes as wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),  # ULONG_PTR
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),  # ULONG_PTR
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _SendInput = _user32.SendInput
    _SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    _SendInput.restype = wintypes.UINT


class InjectionError(RuntimeError):
    """Raised when Windows refuses a synthetic keystroke."""


def _unicode_units(ch: str) -> Sequence[int]:
    """UTF-16 code units for a character (surrogate pairs for astral chars)."""
    code = ord(ch)
    if code > 0xFFFF:
        code -= 0x10000
        return (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF))
    return (code,)


def _key_event(w_vk: int = 0, w_scan: int = 0, flags: int = 0) -> "INPUT":
    return INPUT(
        type=INPUT_KEYBOARD,
        u=_INPUTUNION(
            ki=KEYBDINPUT(
                wVk=w_vk, wScan=w_scan, dwFlags=flags, time=0, dwExtraInfo=None
            )
        ),
    )


def _check_inserted(sent: int, count: int) -> None:
    if sent != count:
        raise InjectionError(
            "Windows blocked the keystroke (SendInput inserted "
            f"{sent}/{count} events, WinError {ctypes.get_last_error()}). "
            "The target may be running as administrator, or a UAC prompt "
            "may be on screen."
        )


def send_input_events(events: Sequence["INPUT"]) -> int:
    """Insert keyboard events into the input stream; raises on failure."""
    count = len(events)
    array = (INPUT * count)(*events)
    sent = _SendInput(count, array, ctypes.sizeof(INPUT))
    _check_inserted(sent, count)
    return sent


class WindowsKeyboard:
    """Types characters into whatever window currently has focus.

    ``send`` is injectable so the timing loop can be tested without
    injecting real keystrokes.
    """

    def __init__(
        self,
        send: Optional[Callable[[Sequence["INPUT"]], int]] = None,
        newline_strategy: str = NEWLINE_ENTER,
        auto_indent_fix: bool = False,
        escape_settle: float = ESCAPE_SETTLE,
    ):
        if send is None and not IS_WINDOWS:
            raise RuntimeError(
                "The Win32 SendInput keyboard is Windows only; use "
                "backends.get_keyboard() to pick a keyboard for this system."
            )
        if newline_strategy not in NEWLINE_STRATEGIES:
            raise ValueError(
                f"unknown newline strategy {newline_strategy!r}; "
                f"expected one of {NEWLINE_STRATEGIES}"
            )
        self._send = send if send is not None else send_input_events
        self.newline_strategy = newline_strategy
        self.auto_indent_fix = bool(auto_indent_fix)
        self.escape_settle = max(0.0, float(escape_settle))

    def _tap(self, w_vk: int, w_scan: int, flags: int, extended: bool = False) -> None:
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        self._send(
            [
                _key_event(w_vk, w_scan, flags),
                _key_event(w_vk, w_scan, flags | KEYEVENTF_KEYUP),
            ]
        )

    def key(self, name: str, mods: tuple = ()) -> None:
        """Press and release a named key, with modifiers (see ``NAMED_KEYS``)."""
        if name == "space":
            self.type_char(" ")
            return
        if name not in NAMED_KEYS:
            raise ValueError(f"unknown key name {name!r}")
        unknown = [m for m in mods if m not in NAMED_MODS]
        if unknown:
            raise ValueError(f"unknown modifier(s) {unknown!r}")
        w_vk, w_scan, extended = NAMED_KEYS[name]
        if not mods:
            self._tap(w_vk, w_scan, 0, extended=extended)
            return
        # One SendInput batch, like a real chord: hold the modifiers, tap, release.
        base = KEYEVENTF_EXTENDEDKEY if extended else 0
        events = [_key_event(*NAMED_MODS[m], 0) for m in mods]
        events.append(_key_event(w_vk, w_scan, base))
        events.append(_key_event(w_vk, w_scan, base | KEYEVENTF_KEYUP))
        events.extend(
            _key_event(*NAMED_MODS[m], KEYEVENTF_KEYUP) for m in reversed(mods)
        )
        self._send(events)

    def type_char(self, ch: str) -> None:
        """Type one character as its UTF-16 unit(s)."""
        for unit in _unicode_units(ch):
            self._tap(0, unit, KEYEVENTF_UNICODE)

    def tap_char(self, ch: str) -> None:
        """Type one character using this class's saved newline/indent options.

        The policy lives in ``emit``; this only remembers the constructor
        arguments, so the legacy entry point and the app cannot drift apart.
        """
        emit(
            self,
            ch,
            EmitOptions(
                esc_before_enter=self.newline_strategy == NEWLINE_ESC_ENTER,
                clear_autoindent=self.auto_indent_fix,
            ),
            settle=self.escape_settle,
        )

    def type_text(self, text: str) -> None:
        for ch in text:
            self.tap_char(ch)
