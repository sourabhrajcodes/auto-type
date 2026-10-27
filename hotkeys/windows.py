"""Windows global hotkey: GetAsyncKeyState polling (works without focus).

Moved here from the app so every platform picks its hotkey through one
factory; the behaviour is unchanged.
"""

import threading

POLL_SECONDS = 0.04


def key_state_getter(ctypes_module):
    """``GetAsyncKeyState`` wrapper, or ``None`` where Win32 user32 is missing."""
    windll = getattr(ctypes_module, "windll", None)
    if windll is None:  # not Windows: the hotkey watcher simply never fires
        return None
    get_state = windll.user32.GetAsyncKeyState
    get_state.argtypes = (ctypes_module.c_int,)
    get_state.restype = ctypes_module.c_short
    return get_state


class HotkeyWatcher(threading.Thread):
    """Watches a single key globally with GetAsyncKeyState (no focus needed)."""

    name = "win32"
    warning = ""

    def __init__(self, vk: int, on_press, poll: float = POLL_SECONDS):
        super().__init__(daemon=True)
        import ctypes

        self._get_state = key_state_getter(ctypes)
        self._vk = vk
        self._on_press = on_press
        self._poll = poll
        self._stop = threading.Event()

    def start_polling(self) -> bool:
        self.start()
        return self._get_state is not None

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        if self._get_state is None:  # no Win32 keyboard state to watch
            return
        was_down = False
        while not self._stop.wait(self._poll):
            is_down = bool(self._get_state(self._vk) & 0x8000)
            if is_down and not was_down:
                try:
                    self._on_press()
                except Exception:
                    pass
            was_down = is_down
