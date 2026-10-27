"""Tests for the global-hotkey layer.

Nothing here watches real keys: the platform pieces are checked through their
pure logic (bit decoding, pid files) and the factory is checked for returning a
usable object on every platform.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hotkeys  # noqa: E402
from hotkeys import signal_toggle  # noqa: E402


class NullHotkeyTests(unittest.TestCase):
    def test_start_and_stop_are_safe_no_ops(self):
        hotkey = hotkeys.NullHotkey("no way to watch keys")
        hotkey.start()
        hotkey.stop()
        self.assertEqual(hotkey.warning, "no way to watch keys")

    def test_factory_always_returns_something_startable(self):
        hotkey = hotkeys.make_hotkey(lambda: None)
        self.addCleanup(hotkey.stop)
        hotkey.start()
        self.assertIn(hotkey.name, ("win32", "x11", "none"))

    @unittest.skipUnless(sys.platform == "win32", "Windows hotkey")
    def test_windows_uses_the_polling_watcher(self):
        hotkey = hotkeys.make_hotkey(lambda: None)
        self.addCleanup(hotkey.stop)
        self.assertEqual(hotkey.name, "win32")
        self.assertTrue(hotkey.start_polling())


class KeyBitmapTests(unittest.TestCase):
    def test_bits_decode_the_way_x11_packs_them(self):
        from hotkeys.x11 import key_is_down

        bitmap = bytearray(32)
        bitmap[0] = 0b0000_0100  # keycode 2
        self.assertTrue(key_is_down(bitmap, 2))
        self.assertFalse(key_is_down(bitmap, 3))

    def test_high_keycodes_use_the_right_byte(self):
        from hotkeys.x11 import key_is_down

        bitmap = bytearray(32)
        bitmap[8] = 0b0000_0001  # keycode 64
        self.assertTrue(key_is_down(bitmap, 64))
        self.assertFalse(key_is_down(bitmap, 63))

    def test_a_zero_keycode_never_counts_as_pressed(self):
        from hotkeys.x11 import key_is_down

        self.assertFalse(key_is_down(bytearray(32), 0))


class SignalToggleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="auto-typer-pid-")
        self.original = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.tmp
        self.addCleanup(self.restore)

    def restore(self):
        if self.original is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self.original

    def test_pid_file_lives_in_the_runtime_directory(self):
        self.assertEqual(signal_toggle.pid_path().parent, Path(self.tmp))

    def test_pid_round_trip(self):
        signal_toggle.write_pid(4242)
        self.assertEqual(signal_toggle.read_pid(), 4242)
        signal_toggle.clear_pid()
        self.assertIsNone(signal_toggle.read_pid())

    def test_toggle_without_a_running_app_is_false(self):
        signal_toggle.clear_pid()
        self.assertFalse(signal_toggle.send_toggle())

    def test_toggle_clears_a_stale_pid_file(self):
        signal_toggle.write_pid(999_999)  # no such process
        if not signal_toggle.supported():
            self.skipTest("SIGUSR1 is not available on this platform")
        self.assertFalse(signal_toggle.send_toggle())
        self.assertIsNone(signal_toggle.read_pid())

    def test_install_reports_unsupported_platforms(self):
        self.assertEqual(signal_toggle.install(lambda: None), signal_toggle.supported())


if __name__ == "__main__":
    unittest.main()
