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
    "STOP_POLL_SLICE",
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
            keyboard.tap_char(ch)
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
    ):
        if send is None and not IS_WINDOWS:
            raise RuntimeError(
                "Auto Typer currently supports Windows only "
                "(it types with the Win32 SendInput API)."
            )
        if newline_strategy not in NEWLINE_STRATEGIES:
            raise ValueError(
                f"unknown newline strategy {newline_strategy!r}; "
                f"expected one of {NEWLINE_STRATEGIES}"
            )
        self._send = send if send is not None else send_input_events
        self.newline_strategy = newline_strategy
        self.auto_indent_fix = bool(auto_indent_fix)

    def _tap(self, w_vk: int, w_scan: int, flags: int, extended: bool = False) -> None:
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        self._send(
            [
                _key_event(w_vk, w_scan, flags),
                _key_event(w_vk, w_scan, flags | KEYEVENTF_KEYUP),
            ]
        )

    def clear_auto_indent(self) -> None:
        """Leave a freshly created, still-empty line with no indentation at all.

        Code editors auto-indent after Enter - typically by copying the previous
        line's leading whitespace. Whatever we type next lands *after* that, so
        each line drifts further right (the reported bug). There is no way to ask
        the editor how much it inserted, so the line is normalised instead:

        1. ``Home`` twice - column 0 in both plain and "smart home" editors.
        2. ``Shift+End`` - selects exactly the indentation the editor inserted.
        3. Type a space, then ``Backspace`` - replaces that selection (or inserts
           and deletes a single space when there was nothing to select, so an
           empty selection can never merge two lines), leaving an empty line.
        """
        self._tap(VK_HOME, SCAN_HOME, 0, extended=True)
        self._tap(VK_HOME, SCAN_HOME, 0, extended=True)
        self._send(
            [
                _key_event(VK_LSHIFT, SCAN_LSHIFT, 0),
                _key_event(VK_END, SCAN_END, KEYEVENTF_EXTENDEDKEY),
                _key_event(VK_END, SCAN_END, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP),
                _key_event(VK_LSHIFT, SCAN_LSHIFT, KEYEVENTF_KEYUP),
            ]
        )
        self.tap_char(" ")
        self._tap(VK_BACKSPACE, SCAN_BACKSPACE, 0)

    def tap_char(self, ch: str) -> None:
        if ch in ("\n", "\r"):
            if self.newline_strategy == NEWLINE_ESC_ENTER:
                # Close autocomplete / suggestion popups that would otherwise
                # swallow the Enter and insert a completion instead of a newline.
                self._tap(VK_ESCAPE, SCAN_ESCAPE, 0)
            self._tap(VK_RETURN, SCAN_RETURN, 0)
            if self.auto_indent_fix:
                self.clear_auto_indent()
        elif ch == "\t":
            self._tap(VK_TAB, SCAN_TAB, 0)
        else:
            for unit in _unicode_units(ch):
                self._tap(0, unit, KEYEVENTF_UNICODE)

    def type_text(self, text: str) -> None:
        for ch in text:
            self.tap_char(ch)
