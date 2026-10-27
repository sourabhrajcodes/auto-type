"""End-to-end check for Auto Typer: inject real keystrokes and verify them.

Opens a tiny window, takes focus, types a known string through the real
``SendInput`` path, and confirms the characters arrived in the window.

The window is a plain text widget, so this also proves the line-break options
(``--esc``, ``--indent-fix``) never add, drop or merge characters: the exact
string must come back.

Focus safety: typing only starts after this process confirms its own window is
the foreground window, and it aborts (without injecting anything) if focus
cannot be secured or is stolen mid-run.

Exit codes: 0 = passed, 1 = failed, 3 = inconclusive (no focus / session busy),
4 = skipped (not Windows).

``--backend`` types through ``backends.get_keyboard()`` + ``engine.emit`` (the
path the app uses), instead of the Windows-only ``WindowsKeyboard.tap_char``.

Run with:  py tests/e2e_selfcheck.py [--esc] [--indent-fix] [--backend]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

if os.name != "nt":
    print("SKIPPED: Auto Typer is Windows-only.")
    raise SystemExit(4)

import tkinter as tk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402
import backends  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetForegroundWindow.restype = wt.HWND
user32.GetAncestor.argtypes = (wt.HWND, wt.UINT)
user32.GetAncestor.restype = wt.HWND
user32.SetForegroundWindow.argtypes = (wt.HWND,)
user32.SetForegroundWindow.restype = wt.BOOL
user32.BringWindowToTop.argtypes = (wt.HWND,)
user32.BringWindowToTop.restype = wt.BOOL
user32.ShowWindow.argtypes = (wt.HWND, ctypes.c_int)
user32.AttachThreadInput.argtypes = (wt.DWORD, wt.DWORD, wt.BOOL)
user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
user32.GetWindowThreadProcessId.restype = wt.DWORD
kernel32.GetCurrentThreadId.restype = wt.DWORD

SW_SHOW = 5
GA_ROOT = 2
VK_F24 = 0x87
KEYEVENTF_KEYUP = 0x0002

# Includes a line break: Enter must arrive as a real newline, not be swallowed.
TEXT = "AutoTyper e2e OK 42!\n \u00e9\u4f60\u597d"


def owns_foreground(hwnd: int) -> bool:
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    return fg == hwnd or user32.GetAncestor(fg, GA_ROOT) == hwnd


def force_foreground(hwnd: int, timeout: float = 4.0) -> bool:
    deadline = time.time() + timeout
    user32.ShowWindow(hwnd, SW_SHOW)
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    self_thread = kernel32.GetCurrentThreadId()
    attached = bool(user32.AttachThreadInput(fg_thread, self_thread, True))
    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        if owns_foreground(hwnd):
            return True
        # Foreground lock workaround: a harmless F24 tap resets the "last input"
        # state so Windows lets a background process activate its window.
        kb = engine.WindowsKeyboard()
        kb._tap(VK_F24, 0, 0)
        user32.SetForegroundWindow(hwnd)
        while time.time() < deadline:
            if owns_foreground(hwnd):
                return True
            time.sleep(0.05)
        return False
    finally:
        if attached:
            user32.AttachThreadInput(fg_thread, self_thread, False)


def main() -> int:
    if not user32.GetForegroundWindow():
        print("INCONCLUSIVE: no foreground window (screen locked or session not interactive).")
        return 3

    root = tk.Tk()
    root.title("Auto Typer - focus test")
    root.geometry("460x130+90+90")
    widget = tk.Text(root, font=("Consolas", 12))
    widget.pack(fill="both", expand=True)
    widget.focus_set()
    root.update()
    hwnd = int(root.wm_frame(), 16)
    root.update()

    if not force_foreground(hwnd):
        print("INCONCLUSIVE: could not bring the test window to the foreground; nothing was typed.")
        root.destroy()
        return 3

    strategy = engine.NEWLINE_ESC_ENTER if "--esc" in sys.argv else engine.NEWLINE_ENTER
    indent_fix = "--indent-fix" in sys.argv
    print(
        f"Focus secured - typing the test string with real SendInput "
        f"(line breaks: {strategy}"
        f"{' + auto-indent fix' if indent_fix else ''})..."
    )
    use_backend = "--backend" in sys.argv
    if use_backend:
        keyboard = backends.get_keyboard()
        options = engine.EmitOptions(
            esc_before_enter=strategy == engine.NEWLINE_ESC_ENTER,
            clear_autoindent=indent_fix,
        )
    else:
        keyboard = engine.WindowsKeyboard(
            newline_strategy=strategy, auto_indent_fix=indent_fix
        )
        options = None
    plan = engine.build_plan(TEXT, wpm=engine.MAX_WPM, mode="char", human=False)
    typed = 0
    lost_focus = False
    for stroke in plan:
        if not owns_foreground(hwnd):
            lost_focus = True
            break
        if options is None:
            keyboard.tap_char(stroke.text)
        else:
            engine.emit(keyboard, stroke.text, options)
        typed += 1
        time.sleep(stroke.post_delay)

    # Drain the message queue so Tk processes the WM_CHAR messages we generated.
    settle = time.time() + 0.5
    while time.time() < settle:
        root.update()
        time.sleep(0.01)

    got = widget.get("1.0", "end-1c")
    root.destroy()

    if lost_focus:
        print(f"INCONCLUSIVE: another window took focus mid-run after {typed} characters.")
        return 3
    if got == TEXT:
        lines = TEXT.count("\n") + 1
        print(
            f"PASS: {len(TEXT)} characters including {lines - 1} line break(s) injected via "
            f"SendInput and verified in the focused window."
        )
        return 0
    print(f"FAIL: injected {len(TEXT)} characters but the window contains {got!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
