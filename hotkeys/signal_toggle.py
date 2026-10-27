"""The Wayland answer to a global hotkey.

Wayland gives applications no way to watch keys globally, and no way to register
a system-wide shortcut. So the app publishes its process id, listens for
``SIGUSR1``, and the user binds ``start_auto_typer.sh --toggle`` to a key in
their desktop's own shortcut settings - the shortcut runs as a normal program,
which every compositor allows.
"""

import os
import signal
import tempfile
from pathlib import Path

APP = "auto-typer"


def supported() -> bool:
    return hasattr(signal, "SIGUSR1")


def pid_path() -> Path:
    """Runtime directory when the session provides one, else the temp dir."""
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / (APP + ".pid")


def write_pid(pid: int = None) -> None:
    path = pid_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pid if pid is not None else os.getpid()), encoding="utf-8")
    except OSError:
        pass


def read_pid():
    try:
        return int(pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def clear_pid() -> None:
    try:
        pid_path().unlink()
    except OSError:
        pass


def send_toggle() -> bool:
    """Ask a running app to start/stop. False when no app is running."""
    if not supported():
        return False
    pid = read_pid()
    if not pid:
        return False
    try:
        os.kill(pid, signal.SIGUSR1)
    except OSError:  # the process died and left its pid file behind
        clear_pid()
        return False
    return True


def install(callback) -> bool:
    """Run ``callback`` when the app receives SIGUSR1. False where unsupported."""
    if not supported():
        return False

    def handler(_signum, _frame):
        try:
            callback()
        except Exception:
            pass

    signal.signal(signal.SIGUSR1, handler)
    return True
