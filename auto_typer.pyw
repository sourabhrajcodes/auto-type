#!/usr/bin/env pythonw
"""Auto Typer - paste text, press F8, and it types it out for you.

Steady character-by-character or word-by-word bursts, with an optional
human-like rhythm. Keystrokes go through the platform backend in ``backends/``
(Win32 SendInput, or XTest/wtype on Linux), so they land in whatever window has
focus (editor, browser, form, chat...).

Run it by double-clicking this file or ``start_auto_typer.bat`` (both start it
without a console window), or from a terminal with ``pyw auto_typer.pyw``.
"""

from __future__ import annotations

import json
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

import engine  # noqa: E402  (after sys.path fix-up)
import backends  # noqa: E402
import hotkeys  # noqa: E402
from hotkeys import signal_toggle  # noqa: E402
# Re-exported for the tests, which check the Win32 key-state wrapper directly.
from hotkeys.windows import HotkeyWatcher, key_state_getter  # noqa: E402,F401


def settings_file_for(app_dir: str) -> str:
    """Settings next to the program on Windows (as before), XDG on Linux."""
    if sys.platform == "win32":
        return os.path.join(app_dir, "settings.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "auto-typer", "settings.json")


SETTINGS_FILE = settings_file_for(APP_DIR)

# Palette borrowed from the College Countdown app so the two feel related.
BG = "#1a1a1a"
CARD = "#242424"
INPUT = "#2a2a2a"
TEXT = "#e0e0e0"
DIM = "#888888"
MUTED = "#555555"
ACCENT = "#d4a030"
ACCENT_BRIGHT = "#f0c040"
BORDER = "#333333"
TYPED_BG = "#3a3320"

DEFAULTS = {
    "text": "",
    "wpm": 40,
    "mode": "word",
    "human": True,
    "start_delay": 3,
    "convert_tabs": True,
    "tab_spaces": 4,
    "minimize": False,
    "topmost": True,
    "esc_before_enter": False,
    "pacing": False,
    "auto_indent_fix": False,
}

VK_F8 = 0x77
HOTKEY_POLL_SECONDS = 0.04
TEXT_BOX_MIN_HEIGHT = 90
"""Smallest useful height for the text box; the window minimum leaves this much."""

# Setting keys that hold a yes/no value.
BOOL_KEYS = (
    "human",
    "convert_tabs",
    "minimize",
    "topmost",
    "esc_before_enter",
    "pacing",
    "auto_indent_fix",
)


def as_bool(value, default: bool = False) -> bool:
    """A yes/no setting, from JSON booleans, 0/1, or "true"/"false" text.

    The settings file is user-writable, and ``bool("false")`` is ``True`` in
    Python - a hand-edited file must not be able to flip an option on by
    writing "false". Anything unreadable keeps the default.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
    return default


def load_settings() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if isinstance(saved, dict):
            for key in DEFAULTS:
                if key in saved:
                    data[key] = saved[key]
    except (OSError, ValueError):
        pass
    # Sanitise, the file is user-writable.
    try:
        data["wpm"] = max(engine.MIN_WPM, min(engine.MAX_WPM, float(data["wpm"])))
    except (TypeError, ValueError):
        data["wpm"] = DEFAULTS["wpm"]
    if data["mode"] not in ("word", "char"):
        data["mode"] = DEFAULTS["mode"]
    try:
        data["start_delay"] = max(0, min(30, int(data["start_delay"])))
    except (TypeError, ValueError):
        data["start_delay"] = DEFAULTS["start_delay"]
    try:
        data["tab_spaces"] = max(1, min(8, int(data["tab_spaces"])))
    except (TypeError, ValueError):
        data["tab_spaces"] = DEFAULTS["tab_spaces"]
    for key in BOOL_KEYS:
        data[key] = as_bool(data[key], bool(DEFAULTS[key]))
    if not isinstance(data["text"], str):
        data["text"] = ""
    return data


def save_settings(data: dict) -> None:
    """Atomic write, same style as the app's JSON storage layer."""
    tmp = SETTINGS_FILE + ".tmp"
    try:
        if os.path.dirname(SETTINGS_FILE):
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except OSError:
        pass


class AutoTyperApp:
    def __init__(self, root: tk.Tk, settings: dict, save_on_close: bool = True):
        self.root = root
        self.settings = settings
        self.save_on_close = save_on_close

        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self.hotkey = hotkeys.make_hotkey(
            lambda: self.events.put(("hotkey", 0, None)), poll=HOTKEY_POLL_SECONDS
        )
        self.hotkey_warning = getattr(self.hotkey, "warning", "")
        # Wayland has no global shortcut API: the app listens for SIGUSR1, and
        # the user binds `start_auto_typer.sh --toggle` in their own settings.
        if signal_toggle.install(lambda: self.events.put(("hotkey", 0, None))):
            signal_toggle.write_pid()
        self._destroyed = False
        self._poll_job = None

        self.state = "idle"  # idle | counting | typing
        self.typed_total = 0
        self.resume_from = 0
        self.stopped_text: str | None = None
        self.run_text = ""
        self.plan_total = 0
        self.shown_upto = 0
        self.highlight_ok = True
        self.started_at = 0.0
        self.resume_hint = False

        root.title("Auto Typer")
        root.configure(bg=BG)
        root.geometry("780x700")
        root.minsize(660, 560)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Escape>", lambda _event: self.request_stop())

        self._build_widgets()
        self._apply_settings_to_widgets()
        self._fit_minimum_size()
        self.hotkey.start()

        self.events.put(("idle", 0, None))
        self._schedule_poll()

    # ------------------------------------------------------------------ UI

    def _build_widgets(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "AutoTyper.Horizontal.TProgressbar",
            troughcolor=INPUT,
            background=ACCENT,
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )

        # Row 1 is the text box and the only row with weight, so it is the one
        # that grows and - importantly - the one that gives up space when the
        # window is made short. With plain packing Tk clips whichever rows were
        # packed last (the whole status area) instead of shrinking the box.
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = tk.Frame(self.root, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        tk.Label(
            header, text="Auto Typer", bg=BG, fg=ACCENT_BRIGHT,
            font=("Segoe UI Semibold", 17),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Paste your text below, click Start (or press F8), then focus the window you want it typed into.",
            bg=BG, fg=DIM, font=("Segoe UI", 9),
        ).pack(anchor="w")

        self.text_frame = tk.Frame(self.root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        text_frame = self.text_frame
        text_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 8))
        self.text = tk.Text(
            text_frame, bg=INPUT, fg=TEXT, insertbackground=ACCENT_BRIGHT,
            selectbackground="#4a4a2a", relief="flat", wrap="word",
            font=("Consolas", 11), undo=True, padx=10, pady=8, height=14,
        )
        scroll = tk.Scrollbar(text_frame, command=self.text.yview, bg=CARD, troughcolor=INPUT, relief="flat")
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("typed", background=TYPED_BG)
        self.text.tag_configure("head", background=ACCENT, foreground="#1a1a1a")

        controls = tk.Frame(self.root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        controls.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))

        speed_row = tk.Frame(controls, bg=CARD)
        speed_row.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(speed_row, text="Speed", bg=CARD, fg=TEXT, font=("Segoe UI", 10)).pack(side="left")
        self.wpm_var = tk.IntVar(value=int(DEFAULTS["wpm"]))
        self.wpm_scale = tk.Scale(
            speed_row, from_=engine.MIN_WPM, to=engine.MAX_WPM, resolution=5,
            orient="horizontal", variable=self.wpm_var, command=lambda _v: self._refresh_estimate(),
            bg=CARD, fg=TEXT, troughcolor=INPUT, highlightthickness=0,
            activebackground=ACCENT, length=230, showvalue=False, relief="flat",
        )
        self.wpm_scale.pack(side="left", padx=(10, 8))
        self.wpm_label = tk.Label(speed_row, text="40 wpm", bg=CARD, fg=ACCENT_BRIGHT, width=10, anchor="w", font=("Segoe UI", 10))
        self.wpm_label.pack(side="left")

        self.estimate_label = tk.Label(speed_row, text="", bg=CARD, fg=DIM, font=("Segoe UI", 9))
        self.estimate_label.pack(side="right")

        mode_row = tk.Frame(controls, bg=CARD)
        mode_row.pack(fill="x", padx=10, pady=(2, 4))
        tk.Label(mode_row, text="Style", bg=CARD, fg=TEXT, font=("Segoe UI", 10)).pack(side="left", padx=(0, 8))
        self.mode_var = tk.StringVar(value="word")
        for value, label in (("word", "Word by word"), ("char", "Character by character")):
            tk.Radiobutton(
                mode_row, text=label, value=value, variable=self.mode_var,
                command=self._refresh_estimate, bg=CARD, fg=TEXT, selectcolor=INPUT,
                activebackground=CARD, activeforeground=ACCENT_BRIGHT, relief="flat",
                highlightthickness=0, font=("Segoe UI", 9),
            ).pack(side="left", padx=(0, 12))
        self.human_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            mode_row, text="Human-like rhythm (tiny randomness + pauses at ., ! ? and line breaks)",
            variable=self.human_var, command=self._refresh_estimate, bg=CARD, fg=TEXT,
            selectcolor=INPUT, activebackground=CARD, activeforeground=ACCENT_BRIGHT,
            relief="flat", highlightthickness=0, font=("Segoe UI", 9),
        ).pack(side="left")

        options_row = tk.Frame(controls, bg=CARD)
        options_row.pack(fill="x", padx=10, pady=(2, 4))
        tk.Label(options_row, text="Switch to target after", bg=CARD, fg=TEXT, font=("Segoe UI", 10)).pack(side="left")
        self.delay_var = tk.IntVar(value=int(DEFAULTS["start_delay"]))
        tk.Spinbox(
            options_row, from_=0, to=30, textvariable=self.delay_var, width=3,
            bg=INPUT, fg=TEXT, buttonbackground=INPUT, relief="flat",
            highlightthickness=0, font=("Segoe UI", 10), justify="center",
        ).pack(side="left", padx=(8, 4))
        tk.Label(options_row, text="s  ·", bg=CARD, fg=DIM, font=("Segoe UI", 9)).pack(side="left", padx=(0, 12))
        self.tabs_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            options_row, text="Tab =", variable=self.tabs_var, command=self._refresh_estimate,
            bg=CARD, fg=TEXT, selectcolor=INPUT, activebackground=CARD,
            activeforeground=ACCENT_BRIGHT, relief="flat", highlightthickness=0, font=("Segoe UI", 9),
        ).pack(side="left")
        self.tab_spaces_var = tk.IntVar(value=4)
        tk.Spinbox(
            options_row, from_=1, to=8, textvariable=self.tab_spaces_var, width=2,
            bg=INPUT, fg=TEXT, buttonbackground=INPUT, relief="flat",
            highlightthickness=0, font=("Segoe UI", 9), justify="center",
            command=self._refresh_estimate,
        ).pack(side="left", padx=(4, 2))
        tk.Label(options_row, text="spaces", bg=CARD, fg=DIM, font=("Segoe UI", 9)).pack(side="left", padx=(0, 12))
        self.minimize_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            options_row, text="Minimize while typing", variable=self.minimize_var,
            bg=CARD, fg=TEXT, selectcolor=INPUT, activebackground=CARD,
            activeforeground=ACCENT_BRIGHT, relief="flat", highlightthickness=0, font=("Segoe UI", 9),
        ).pack(side="left")
        self.topmost_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            options_row, text="Keep on top", variable=self.topmost_var, command=self._apply_topmost,
            bg=CARD, fg=TEXT, selectcolor=INPUT, activebackground=CARD,
            activeforeground=ACCENT_BRIGHT, relief="flat", highlightthickness=0, font=("Segoe UI", 9),
        ).pack(side="left", padx=(12, 0))

        compat_row = tk.Frame(controls, bg=CARD)
        compat_row.pack(fill="x", padx=10, pady=(2, 10))
        tk.Label(compat_row, text="Web code editors", bg=CARD, fg=TEXT, font=("Segoe UI", 10)).pack(
            side="left", anchor="n", padx=(0, 8), pady=(2, 0)
        )
        # The three checkboxes stack so their labels stay readable in a narrow window.
        compat_checks = tk.Frame(compat_row, bg=CARD)
        compat_checks.pack(side="left", fill="x", expand=True)
        self.esc_enter_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            compat_checks,
            text="Press Esc before each line break (editors whose autocomplete eats Enter)",
            variable=self.esc_enter_var, command=self._refresh_estimate,
            bg=CARD, fg=TEXT, selectcolor=INPUT, activebackground=CARD,
            activeforeground=ACCENT_BRIGHT, relief="flat", highlightthickness=0, font=("Segoe UI", 9),
        ).pack(side="top", anchor="w")
        self.indent_fix_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            compat_checks,
            text="Clear the editor's auto-indent after each line break (indentation stays exact)",
            variable=self.indent_fix_var, command=self._refresh_estimate,
            bg=CARD, fg=TEXT, selectcolor=INPUT, activebackground=CARD,
            activeforeground=ACCENT_BRIGHT, relief="flat", highlightthickness=0, font=("Segoe UI", 9),
        ).pack(side="top", anchor="w")
        self.pacing_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            compat_checks,
            text="Compatibility pacing (slower, stops editors dropping characters)",
            variable=self.pacing_var, command=self._refresh_estimate,
            bg=CARD, fg=TEXT, selectcolor=INPUT, activebackground=CARD,
            activeforeground=ACCENT_BRIGHT, relief="flat", highlightthickness=0, font=("Segoe UI", 9),
        ).pack(side="top", anchor="w")

        button_row = tk.Frame(self.root, bg=BG)
        button_row.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.start_button = tk.Button(
            button_row, text="Start typing (F8)", command=self.toggle,
            bg=ACCENT, fg="#1a1a1a", activebackground=ACCENT_BRIGHT, activeforeground="#1a1a1a",
            relief="flat", font=("Segoe UI Semibold", 11), padx=18, pady=8, cursor="hand2",
        )
        self.start_button.pack(side="left")
        self.reset_button = tk.Button(
            button_row, text="Reset progress", command=self.reset_progress,
            bg=INPUT, fg=TEXT, activebackground=BORDER, activeforeground=ACCENT_BRIGHT,
            relief="flat", font=("Segoe UI", 10), padx=12, pady=8, cursor="hand2",
        )
        self.reset_button.pack(side="left", padx=8)
        self.paste_button = tk.Button(
            button_row, text="Paste clipboard", command=self.paste_clipboard,
            bg=INPUT, fg=TEXT, activebackground=BORDER, activeforeground=ACCENT_BRIGHT,
            relief="flat", font=("Segoe UI", 10), padx=12, pady=8, cursor="hand2",
        )
        self.paste_button.pack(side="right", padx=(8, 0))
        self.clear_button = tk.Button(
            button_row, text="Clear", command=self.clear_text,
            bg=INPUT, fg=TEXT, activebackground=BORDER, activeforeground=ACCENT_BRIGHT,
            relief="flat", font=("Segoe UI", 10), padx=12, pady=8, cursor="hand2",
        )
        self.clear_button.pack(side="right")

        status_frame = tk.Frame(self.root, bg=BG)
        status_frame.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.status_label = tk.Label(status_frame, text="", bg=BG, fg=TEXT, anchor="w", font=("Segoe UI", 10))
        self.status_label.pack(fill="x")
        self.progress = ttk.Progressbar(
            status_frame, style="AutoTyper.Horizontal.TProgressbar",
            orient="horizontal", mode="determinate", maximum=100,
        )
        self.progress.pack(fill="x", pady=(4, 2))
        hint = (
            "F8 = start / stop  ·  Esc = stop  ·  tip: press Start with this window "
            "focused to watch it type into the box itself."
        )
        warning = getattr(self, "hotkey_warning", "")
        if warning:
            hint = "%s  ·  %s" % (warning, hint)
        self.hint_label = tk.Label(
            status_frame, text=hint,
            bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 8),
        )
        self.hint_label.pack(fill="x")

        self.text.bind("<KeyRelease>", lambda _e: self._schedule_estimate())
        self.text.bind("<<Paste>>", lambda _e: self._schedule_estimate())
        self.text.bind("<<Cut>>", lambda _e: self._schedule_estimate())
        self.text.bind("<<Modified>>", self._on_text_modified)

    def _fit_minimum_size(self) -> None:
        """Make the minimum window size match what the layout actually needs.

        Tk clips packed widgets as soon as the window is smaller than their
        requested size, which is how the long option labels and the whole status
        area used to disappear. The minimum is measured from the real layout
        (any font/DPI) instead of being a hard-coded guess; only the text box is
        allowed to shrink, down to ``TEXT_BOX_MIN_HEIGHT``.
        """
        try:
            self.root.update_idletasks()
            width = self.root.winfo_reqwidth()
            fixed_height = self.root.winfo_reqheight() - self.text_frame.winfo_reqheight()
        except tk.TclError:  # pragma: no cover - only if Tk is half-built
            return
        self.root.minsize(max(660, width), max(560, fixed_height + TEXT_BOX_MIN_HEIGHT))

    def _apply_settings_to_widgets(self) -> None:
        s = self.settings
        self.text.insert("1.0", s["text"])
        self.text.edit_modified(False)
        self.wpm_var.set(int(s["wpm"]))
        self.mode_var.set(s["mode"])
        self.human_var.set(s["human"])
        self.delay_var.set(int(s["start_delay"]))
        self.tabs_var.set(s["convert_tabs"])
        self.tab_spaces_var.set(int(s["tab_spaces"]))
        self.minimize_var.set(s["minimize"])
        self.topmost_var.set(s["topmost"])
        self.esc_enter_var.set(s["esc_before_enter"])
        self.pacing_var.set(s["pacing"])
        self.indent_fix_var.set(s["auto_indent_fix"])
        self._apply_topmost()
        self._refresh_estimate()

    def _on_text_modified(self, _event=None) -> None:
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self._schedule_estimate()

    # ---------------------------------------------------------- helpers

    def _params(self) -> dict:
        pacing = bool(self.pacing_var.get())
        return {
            "wpm": float(self.wpm_var.get()),
            "mode": self.mode_var.get(),
            "human": bool(self.human_var.get()),
            "convert_tabs": bool(self.tabs_var.get()),
            "tab_spaces": int(self.tab_spaces_var.get()),
            "min_gap": engine.COMPAT_MIN_GAP if pacing else 0.0,
            "min_newline_pause": engine.COMPAT_NEWLINE_PAUSE if pacing else 0.0,
        }

    def emit_options(self) -> engine.EmitOptions:
        """Which keys each character becomes, straight from the checkboxes."""
        return engine.EmitOptions(
            esc_before_enter=bool(self.esc_enter_var.get()),
            clear_autoindent=bool(self.indent_fix_var.get()),
        )

    def _normalized_text(self) -> str:
        return engine.normalize_text(
            self.text.get("1.0", "end-1c"),
            convert_tabs=bool(self.tabs_var.get()),
            tab_spaces=int(self.tab_spaces_var.get()),
        )

    def _schedule_estimate(self) -> None:
        if self._estimate_job is not None:
            self.root.after_cancel(self._estimate_job)
        self._estimate_job = self.root.after(250, self._refresh_estimate)

    _estimate_job = None

    def _refresh_estimate(self) -> None:
        self._estimate_job = None
        self.wpm_label.configure(text=f"{int(self.wpm_var.get())} wpm")
        text = self._normalized_text()
        if not text:
            self.estimate_label.configure(text="nothing to type yet")
            self.progress.configure(value=0)
            self._update_start_button()
            return
        plan = engine.build_plan(text, rng=random.Random(1234), **self._params())
        seconds = engine.plan_duration(plan)
        self.estimate_label.configure(
            text=f"{len(text):,} characters · about {self._human_time(seconds)}"
        )
        self._update_start_button()

    @staticmethod
    def _human_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f} s"
        minutes, secs = divmod(int(round(seconds)), 60)
        return f"{minutes} min {secs:02d} s"

    def _update_start_button(self) -> None:
        if self.state == "typing":
            self.start_button.configure(text="Stop (F8)", bg="#8a3a2a", activebackground="#a84a34")
        elif self.state == "counting":
            self.start_button.configure(text="Cancel (F8)", bg="#8a3a2a", activebackground="#a84a34")
        elif self._resume_available():
            self.start_button.configure(text="Resume typing (F8)", bg=ACCENT, activebackground=ACCENT_BRIGHT)
        else:
            self.start_button.configure(text="Start typing (F8)", bg=ACCENT, activebackground=ACCENT_BRIGHT)

    def _resume_available(self) -> bool:
        return (
            self.stopped_text is not None
            and self.stopped_text == self._normalized_text()
            and 0 < self.resume_from < len(self.stopped_text)
        )

    def _set_status(self, message: str) -> None:
        self.status_label.configure(text=message)

    def _apply_topmost(self) -> None:
        # Only keeps the setup window on top while idle; typing needs the target visible.
        topmost = bool(self.topmost_var.get()) and self.state == "idle"
        try:
            self.root.attributes("-topmost", topmost)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ actions

    def paste_clipboard(self) -> None:
        if self.state != "idle":
            return
        try:
            clip = self.root.clipboard_get()
        except tk.TclError:
            self._set_status("Clipboard is empty.")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", clip)
        self.reset_progress(quiet=True)
        self._schedule_estimate()

    def clear_text(self) -> None:
        if self.state != "idle":
            return
        self.text.delete("1.0", "end")
        self.reset_progress(quiet=True)
        self._schedule_estimate()

    def reset_progress(self, quiet: bool = False) -> None:
        if self.state != "idle":
            return
        self.resume_from = 0
        self.stopped_text = None
        self.shown_upto = 0
        self.typed_total = 0
        self.text.tag_remove("typed", "1.0", "end")
        self.text.tag_remove("head", "1.0", "end")
        self.progress.configure(value=0)
        if not quiet:
            self._set_status("Progress reset - the next run starts from the beginning.")
        self._refresh_estimate()

    def toggle(self) -> None:
        if self.state == "idle":
            self.start_typing()
        elif self.state == "counting":
            self._cancel_countdown("Start cancelled.")
        else:
            self.request_stop()

    def start_typing(self) -> None:
        raw = self.text.get("1.0", "end-1c")
        text = self._normalized_text()
        if not text.strip():
            self._set_status("Nothing to type yet - paste or write some text first.")
            return

        resume = self._resume_available()
        if not resume:
            self.resume_from = 0
        self.run_text = text
        self.highlight_ok = raw == text or not raw
        self.stop_event.clear()
        self.typed_total = self.resume_from if resume else 0
        self.plan_total = len(text)
        self.shown_upto = self.typed_total if resume else 0
        self.save_settings_now()

        self.state = "counting"
        self._apply_topmost()
        self._update_start_button()
        delay = int(self.delay_var.get())
        if delay <= 0:
            self._begin_typing()
        else:
            self._countdown_left = delay
            self._tick_countdown()

    def _tick_countdown(self) -> None:
        if self.state != "counting":
            return
        self._set_status(
            f"Starting in {self._countdown_left} s - click the window you want this typed into… (F8 to cancel)"
        )
        if self._countdown_left <= 0:
            self._begin_typing()
            return
        self._countdown_left -= 1
        self._countdown_job = self.root.after(1000, self._tick_countdown)

    def _cancel_countdown(self, message: str) -> None:
        if self._countdown_job is not None:
            self.root.after_cancel(self._countdown_job)
            self._countdown_job = None
        self.state = "idle"
        self._apply_topmost()
        self._update_start_button()
        self._set_status(message)

    def _begin_typing(self) -> None:
        self._countdown_job = None
        plan = engine.build_plan(self.run_text, **self._params())
        if self.typed_total > 0:
            plan = engine.trim_plan(plan, self.typed_total)
        if not plan:
            self.state = "idle"
            self._update_start_button()
            self._set_status("Nothing left to type.")
            return
        self.state = "typing"
        self.started_at = time.time()
        self._apply_topmost()
        self._update_start_button()
        self._set_status(f"Typing… 0 / {self.plan_total:,} characters (F8 to stop)")
        if self.minimize_var.get():
            try:
                self.root.iconify()
            except tk.TclError:
                pass
        threading.Thread(
            target=self._worker, args=(plan, self.emit_options()), daemon=True
        ).start()

    def _worker(self, plan, options) -> None:
        keyboard = None
        try:
            keyboard = backends.get_keyboard()
            typed = engine.run_plan(
                keyboard,
                plan,
                should_stop=self.stop_event.is_set,
                on_char=lambda n: self.events.put(("progress", n, None)),
                options=options,
            )
            self.events.put(("done", typed, None))
        except Exception as exc:  # injection blocked, no backend, ...
            self.events.put(("error", 0, str(exc)))
        finally:
            if keyboard is not None:
                try:
                    keyboard.close()
                except Exception:
                    pass

    def request_stop(self) -> None:
        if self.state == "counting":
            self._cancel_countdown("Start cancelled.")
        elif self.state == "typing":
            self.stop_event.set()
            self._set_status("Stopping…")

    def _finish_run(self, typed_this_run: int, error: str | None) -> None:
        self.state = "idle"
        absolute = self.typed_total + typed_this_run
        self.typed_total = absolute
        if error:
            # Nothing resumable happened; make the UI match a fresh start.
            self.typed_total = 0
            self.shown_upto = 0
            self.stopped_text = None
            self.resume_from = 0
            self.text.tag_remove("typed", "1.0", "end")
            self.text.tag_remove("head", "1.0", "end")
            self.progress.configure(value=0)
            self._set_status(f"Stopped: {error}")
        elif absolute >= self.plan_total:
            elapsed = max(0.0, time.time() - self.started_at)
            self._set_status(
                f"Done - typed {absolute:,} / {self.plan_total:,} characters in {self._human_time(elapsed)}."
            )
            self.stopped_text = None
            self.resume_from = 0
            self.text.tag_remove("head", "1.0", "end")
        else:
            self._set_status(
                f"Stopped at {absolute:,} / {self.plan_total:,} characters - press Start (F8) to continue from here."
            )
            self.stopped_text = self.run_text
            self.resume_from = absolute
        self._apply_topmost()
        self._update_start_button()
        self._refresh_estimate()

    def _apply_progress(self, typed_this_run: int) -> None:
        absolute = self.typed_total + typed_this_run
        self.progress.configure(value=min(100.0, 100.0 * absolute / max(1, self.plan_total)))
        self._set_status(
            f"Typing… {absolute:,} / {self.plan_total:,} characters (F8 to stop)"
        )
        if not self.highlight_ok:
            return
        # "+ N chars" counts Unicode code points in Tk too, so Python offsets can
        # be used as they are. (Emoji are two units in an index's *string form*
        # but one in its arithmetic - tests cover this with an emoji.)
        if absolute - self.shown_upto >= 8 or absolute >= self.plan_total:
            start = f"1.0 + {self.shown_upto} chars"
            end = f"1.0 + {absolute} chars"
            self.text.tag_add("typed", start, end)
            self.shown_upto = absolute
        self.text.tag_remove("head", "1.0", "end")
        self.text.tag_add("head", f"1.0 + {absolute - 1} chars", f"1.0 + {absolute} chars")

    def save_settings_now(self) -> None:
        self.settings.update(
            {
                "text": self.text.get("1.0", "end-1c"),
                "wpm": int(self.wpm_var.get()),
                "mode": self.mode_var.get(),
                "human": bool(self.human_var.get()),
                "start_delay": int(self.delay_var.get()),
                "convert_tabs": bool(self.tabs_var.get()),
                "tab_spaces": int(self.tab_spaces_var.get()),
                "minimize": bool(self.minimize_var.get()),
                "topmost": bool(self.topmost_var.get()),
                "esc_before_enter": bool(self.esc_enter_var.get()),
                "pacing": bool(self.pacing_var.get()),
                "auto_indent_fix": bool(self.indent_fix_var.get()),
            }
        )
        save_settings(self.settings)

    def on_close(self) -> None:
        if self._destroyed:  # idempotent: the window manager may ask twice
            return
        self._destroyed = True
        self.stop_event.set()
        self.hotkey.stop()
        signal_toggle.clear_pid()
        for job in (self._poll_job, self._estimate_job, self._countdown_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self._poll_job = self._estimate_job = self._countdown_job = None
        try:  # drop any other pending timer so nothing fires after destroy
            for job in self.root.tk.call("after", "info"):
                self.root.after_cancel(job)
        except tk.TclError:
            pass
        if self.save_on_close:
            self.save_settings_now()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------------- poller

    def _schedule_poll(self) -> None:
        if self._destroyed:
            return
        try:
            self._poll_job = self.root.after(40, self._poll)
        except tk.TclError:
            self._poll_job = None

    def _poll(self) -> None:
        self._poll_job = None
        try:
            self._drain_events()
        except Exception as exc:  # the poller must survive anything
            self._set_status(f"Internal error: {exc}")
        self._schedule_poll()

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            # Events are (kind, value, message); short tuples are tolerated so a
            # new producer can never take the poller (and the app) down.
            kind = event[0] if len(event) > 0 else ""
            value = event[1] if len(event) > 1 else None
            message = event[2] if len(event) > 2 else None
            try:
                self._handle_event(kind, value, message)
            except Exception as exc:  # one bad event must not stop the app
                self._set_status(f"Internal error: {exc}")

    def _handle_event(self, kind: str, value, message) -> None:
        if kind == "progress":
            self._apply_progress(int(value))
        elif kind == "done":
            if self.state == "typing":
                self._finish_run(int(value), None)
        elif kind == "error":
            if self.state == "typing":
                self._finish_run(0, message or "unknown error")
        elif kind == "hotkey":
            self.toggle()
        elif kind == "idle":
            self._refresh_estimate()
            self._set_status(
                "Ready - paste your text, press F8, then focus the window you want it typed into."
            )

    _countdown_job = None
    _countdown_left = 0


def main(argv: list[str]) -> int:
    if "--toggle" in argv:
        # Used as a desktop shortcut on Wayland, where no global key exists.
        if signal_toggle.send_toggle():
            return 0
        print(
            "Auto Typer is not running (no pid file), so there is nothing to toggle."
        )
        return 1
    try:  # say why up front instead of failing when the first key is sent
        probe = backends.get_keyboard()
    except backends.KeyboardError as exc:
        print("Auto Typer cannot type here: %s" % (exc,))
        return 1
    probe.close()
    settings = load_settings()
    root = tk.Tk()
    app = AutoTyperApp(root, settings, save_on_close="--selftest-ui" not in argv)
    if "--selftest-ui" in argv:
        # Build the whole UI and pump the event loop briefly, then exit.
        deadline = time.time() + 0.6
        while time.time() < deadline:
            root.update()
            time.sleep(0.02)
        app.hotkey.stop()
        root.destroy()
        print("UI OK")
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
