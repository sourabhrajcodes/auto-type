"""Browser check: do Auto Typer's line breaks survive a web editor?

Opens ``editor_sim.html`` in a throwaway browser window. That page imitates a
code editor whose autocomplete popup swallows Enter (the original bug report),
and with ``--case autoindent`` it also copies the current line's indentation
onto every new line (the second bug report: indentation that drifts right).
Real keystrokes are then injected with the Win32 SendInput path and the page
reports its own result back over HTTP, so the check is self-verifying.

Expected outcomes:

* ``--case popup --strategy enter``      -> the popup eats the Enter: BUG REPRODUCED
* ``--case popup --strategy esc_enter``  -> Esc first, the newline lands: PASS
* ``--case autoindent`` (no --indent-fix) -> the editor's auto-indent shifts
  every line: BUG REPRODUCED
* ``--case autoindent --indent-fix``     -> the typed text arrives exactly: PASS

The browser runs with its own throwaway profile and is closed again afterwards.
Keystrokes are only sent while the target window is confirmed foreground.

Exit codes: 0 = outcome matched, 1 = unexpected outcome, 3 = inconclusive,
4 = skipped (not Windows / no browser found).

Run with:  py tests/browser_enter_check.py --case autoindent --indent-fix
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid

if os.name != "nt":
    print("SKIPPED: Auto Typer is Windows-only.")
    raise SystemExit(4)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402

PAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor_sim.html")

POPUP_SAMPLE = "hello\nworld"
# The second line is indented, the third is not: an editor that copies the
# previous line's indentation pushes the third line right on its own.
AUTOINDENT_SAMPLE = "if x:\n    a = 1\nb = 2"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetForegroundWindow.restype = wt.HWND
user32.GetAncestor.argtypes = (wt.HWND, wt.UINT)
user32.GetAncestor.restype = wt.HWND
user32.SetForegroundWindow.argtypes = (wt.HWND,)
user32.BringWindowToTop.argtypes = (wt.HWND,)
user32.ShowWindow.argtypes = (wt.HWND, ctypes.c_int)
user32.AttachThreadInput.argtypes = (wt.DWORD, wt.DWORD, wt.BOOL)
user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.IsWindowVisible.argtypes = (wt.HWND,)
user32.GetWindowTextLengthW.argtypes = (wt.HWND,)
user32.GetWindowTextW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)
user32.GetClassNameW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)
user32.EnumWindows.argtypes = (ctypes.c_void_p, wt.LPARAM)
kernel32.GetCurrentThreadId.restype = wt.DWORD

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
GA_ROOT = 2
SW_SHOW = 5
VK_F23 = 0x86  # checker's "clear the page" key
VK_F24 = 0x87  # harmless delivery probe (inserts no text)

LATEST: dict = {}
LATEST_AT = 0.0
READY = threading.Event()


class ReportHandler(http.server.BaseHTTPRequestHandler):
    def _serve_page(self) -> None:
        with open(PAGE_FILE, "rb") as handle:
            data = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/editor_sim.html"):
            self._serve_page()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        global LATEST_AT
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            state = json.loads(raw)
        except ValueError:
            state = {}
        if isinstance(state, dict):
            LATEST.clear()
            LATEST.update(state)
            LATEST_AT = time.time()
        READY.set()
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args) -> None:  # keep the output clean
        pass


def find_browser(explicit: str | None) -> str | None:
    if explicit:
        return explicit if os.path.exists(explicit) else None
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def window_by_title(needle: str, timeout: float = 20.0):
    """Visible top-level window whose title contains ``needle``.

    Edge and Chrome hand the window to a child process, so the launched PID is
    not reliable; the unique run tag in the window title is.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        hits: list[int] = []

        @WNDENUMPROC
        def callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and needle in window_title(hwnd):
                hits.append(hwnd)
                return False
            return True

        user32.EnumWindows(callback, 0)
        if hits:
            return hits[0]
        time.sleep(0.2)
    return None


def window_class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def owns_foreground(hwnd: int) -> bool:
    """True only when the frame window hosting the page is in front.

    Chromium also owns untitled helper windows; while one of those holds the
    foreground, keystrokes go nowhere, so they must not count as "focused".
    """
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    return fg == hwnd or user32.GetAncestor(fg, GA_ROOT) == hwnd


def probe_key_delivery(hwnd: int, timeout: float = 20.0) -> bool:
    """Wait until a harmless probe key is actually delivered to the page.

    Chromium shuffles the foreground between helper windows for the first
    seconds after launch, so keystrokes sent too early vanish. F24 inserts no
    text but still produces a keydown the page counts, which makes this a
    reliable readiness signal (replaces guesswork about timers).
    """
    keyboard = engine.WindowsKeyboard()
    deadline = time.time() + timeout
    stable_since: float | None = None
    while time.time() < deadline:
        if not owns_foreground(hwnd):
            stable_since = None
            force_foreground(hwnd, timeout=1.5)
            time.sleep(0.2)
            continue
        now = time.time()
        stable_since = stable_since or now
        if now - stable_since < 0.8:  # let activation settle first
            time.sleep(0.15)
            continue
        before = LATEST.get("keysSeen", 0)
        keyboard._tap(VK_F24, 0, 0)
        time.sleep(0.35)
        if LATEST.get("keysSeen", 0) > before:
            return True
    return False


def force_foreground(hwnd: int, timeout: float = 4.0) -> bool:
    user32.ShowWindow(hwnd, SW_SHOW)
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    self_thread = kernel32.GetCurrentThreadId()
    attached = bool(user32.AttachThreadInput(fg_thread, self_thread, True))
    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if owns_foreground(hwnd):
                return True
            time.sleep(0.05)
        engine.WindowsKeyboard(send=lambda events: len(events))._tap(VK_F24, 0, 0)
        user32.SetForegroundWindow(hwnd)
        while time.time() < deadline + 1.0:
            if owns_foreground(hwnd):
                return True
            time.sleep(0.05)
        return False
    finally:
        if attached:
            user32.AttachThreadInput(fg_thread, self_thread, False)


def main(argv) -> int:
    parser = argparse.ArgumentParser(description="Browser line-break check")
    parser.add_argument("--text", default=None, help="defaults per --case")
    parser.add_argument(
        "--case",
        choices=("popup", "autoindent"),
        default="popup",
        help="popup: the autocomplete popup swallows Enter; "
        "autoindent: the editor copies the previous line's indentation",
    )
    parser.add_argument(
        "--strategy",
        choices=(engine.NEWLINE_ENTER, engine.NEWLINE_ESC_ENTER),
        default=engine.NEWLINE_ESC_ENTER,
    )
    parser.add_argument(
        "--indent-fix",
        action="store_true",
        help="turn on the 'clear the editor's auto-indent' option",
    )
    parser.add_argument("--wpm", type=float, default=60.0)
    parser.add_argument("--browser", default=None, help="path to msedge.exe / chrome.exe")
    parser.add_argument("--timeout", type=float, default=45.0, help="browser startup timeout")
    args = parser.parse_args(argv)
    autoindent = args.case == "autoindent"
    text = args.text if args.text is not None else (
        AUTOINDENT_SAMPLE if autoindent else POPUP_SAMPLE
    )

    browser = find_browser(args.browser)
    if not browser:
        print("SKIPPED: no Edge or Chrome found (pass --browser PATH).")
        return 4

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ReportHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    run_tag = uuid.uuid4().hex[:8]
    query = {"run": run_tag, "expect": text}
    if autoindent:
        query["autoindent"] = "1"
    url = f"http://127.0.0.1:{port}/editor_sim.html?{urllib.parse.urlencode(query)}"
    profile = tempfile.mkdtemp(prefix="autotyper-browser-check-")
    proc = None
    kill_pids: set[int] = set()
    try:
        print(f"Opening a throwaway browser window ({os.path.basename(browser)})...")
        proc = subprocess.Popen(
            [
                browser,
                f"--app={url}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=780,600",
                "--window-position=120,120",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not READY.wait(timeout=args.timeout):
            print("INCONCLUSIVE: the test page never reported in (browser blocked?).")
            return 3

        hwnd = window_by_title(run_tag, timeout=15)
        if not hwnd:
            print("INCONCLUSIVE: could not find the test window.")
            return 3
        kill_pids.update({proc.pid, window_pid(hwnd)})
        browser_pid = window_pid(hwnd)
        force_foreground(hwnd)
        if not probe_key_delivery(hwnd):
            print("INCONCLUSIVE: keystrokes never reached the page (focus never settled).")
            return 3
        keys_before = LATEST.get("keysSeen", 0)

        print(
            f"Typing {text!r} with line breaks: {args.strategy}"
            f"{' + auto-indent fix' if args.indent_fix else ''}"
        )
        keyboard = engine.WindowsKeyboard(
            newline_strategy=args.strategy, auto_indent_fix=args.indent_fix
        )
        plan = engine.build_plan(text, wpm=args.wpm, mode="char", human=False)

        def clear_page() -> None:
            for _ in range(3):  # F23 makes the page wipe itself over the same key channel
                keyboard._tap(VK_F23, 0, 0)
                time.sleep(0.12)
            time.sleep(0.35)

        def type_once() -> list[str] | None:
            """Returns None on success, else a note about who stole the focus."""
            interruption: list[str] = []

            def watch(_typed: int) -> None:
                # Stop the moment focus leaves: never type into an unrelated window.
                if not owns_foreground(hwnd) and not interruption:
                    thief = user32.GetForegroundWindow()
                    interruption.append(
                        f"{window_title(thief) or '<untitled>'!r} "
                        f"class={window_class(thief)!r} pid={window_pid(thief)}"
                    )

            engine.run_plan(
                keyboard, plan, on_char=watch, should_stop=lambda: bool(interruption)
            )
            return interruption[0] if interruption else None

        interruption = None
        for attempt in range(1, 4):
            clear_page()
            if not probe_key_delivery(hwnd, timeout=12.0):
                print("INCONCLUSIVE: keystrokes stopped reaching the page.")
                return 3
            keys_before = LATEST.get("keysSeen", 0)
            interruption = type_once()
            if interruption is None:
                break
            print(
                f"Attempt {attempt}: focus left the test window "
                f"(taken by {interruption}) - retrying."
            )
        if interruption is not None:
            print("INCONCLUSIVE: focus kept moving mid-run; nothing to judge.")
            return 3
        if LATEST.get("resets", 0) == 0:
            print("WARNING: the page never acknowledged a reset key; results may be stale.")

        deadline = time.time() + 4.0
        while time.time() < deadline:
            if LATEST.get("value") == text:
                break
            time.sleep(0.1)

        value = LATEST.get("value", "")
        badge = LATEST.get("badge", "")
        keys = LATEST.get("keysSeen", 0)
        print(f"Page content: {value!r}   (badge: {badge})")
        print(
            f"Diagnostics:  {keys} key press(es) reached the page, "
            f"focused={LATEST.get('pageFocused')}, activeElement={LATEST.get('activeElement')!r}"
        )
        if keys <= keys_before:
            print("INCONCLUSIVE: no keystrokes reached the page (focus problem), nothing to judge.")
            return 3
        if autoindent:
            if args.indent_fix:
                if value == text:
                    print("PASS: the editor's auto-indent was cleared - text arrived exactly.")
                    return 0
                print("FAIL: the auto-indent fix did not reproduce the text exactly.")
                return 1
            if value == text:
                print("UNEXPECTED: the editor's auto-indent changed nothing; nothing to fix.")
                return 1
            print(
                "BUG REPRODUCED: the editor's own indentation drifted the text - "
                "this is what '--indent-fix' fixes."
            )
            return 0
        if args.strategy == engine.NEWLINE_ESC_ENTER:
            if value == text:
                print("PASS: the line break survived the editor's autocomplete popup.")
                return 0
            print("FAIL: the Esc+Enter strategy did not produce the expected text.")
            return 1
        if value == text:
            print("UNEXPECTED: plain Enter survived this popup; the simulation did not bite.")
            return 1
        if "SUGGEST" in value or badge.startswith("FAIL"):
            print("BUG REPRODUCED: plain Enter was swallowed - this is what 'esc_enter' fixes.")
            return 0
        print("FAIL: plain Enter produced unexpected output (see content above).")
        return 1
    finally:
        for pid in sorted(kill_pids):
            if pid > 0:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        server.shutdown()
        server.server_close()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
