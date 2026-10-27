"""Tests for the platform-neutral key policy and the keyboard backends.

No keystrokes are injected and no display is needed: the policy is checked
against a recording backend, and the platform-specific pieces are exercised
through their pure functions (or skipped off their platform).

Run with:  py -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402
from backends import KeyboardError, get_keyboard, is_wayland  # noqa: E402
from backends.fake import FakeKeyboard  # noqa: E402


def no_sleep(_seconds):
    """Records nothing, waits nothing: the settle must not slow the tests."""


class EmitPolicyTests(unittest.TestCase):
    def emit_all(self, text, options=None, settle=0.0):
        keyboard = FakeKeyboard()
        for ch in text:
            engine.emit(keyboard, ch, options, sleep=no_sleep, settle=settle)
        return keyboard.events

    def test_plain_character_is_just_that_character(self):
        self.assertEqual(self.emit_all("a"), [("char", "a")])

    def test_plain_line_break_is_enter_only(self):
        self.assertEqual(self.emit_all("\n"), [("key", "enter", ())])

    def test_escape_option_presses_escape_before_enter(self):
        events = self.emit_all("\n", engine.EmitOptions(esc_before_enter=True))
        self.assertEqual(
            events,
            [("key", "esc", ()), ("key", "esc", ()), ("key", "enter", ())],
        )

    def test_escape_option_settles_between_the_escapes(self):
        sleeps = []
        keyboard = FakeKeyboard()
        engine.emit(
            keyboard,
            "\n",
            engine.EmitOptions(esc_before_enter=True),
            sleep=sleeps.append,
            settle=engine.ESCAPE_SETTLE,
        )
        self.assertEqual(sleeps, [engine.ESCAPE_SETTLE, engine.ESCAPE_SETTLE])

    def test_indent_fix_normalises_the_fresh_line_after_enter(self):
        events = self.emit_all("\n", engine.EmitOptions(clear_autoindent=True))
        self.assertEqual(
            events,
            [
                ("key", "enter", ()),
                ("key", "home", ()),
                ("key", "home", ()),
                ("key", "end", ("shift",)),  # selects what the editor inserted
                ("char", " "),  # replaces the selection
                ("key", "backspace", ()),  # removes the space: lines never merge
            ],
        )

    def test_both_options_combine_in_the_documented_order(self):
        events = self.emit_all(
            "\n", engine.EmitOptions(esc_before_enter=True, clear_autoindent=True)
        )
        self.assertEqual(
            [event[1] if event[0] == "key" else event[0] for event in events],
            ["esc", "esc", "enter", "home", "home", "end", "char", "backspace"],
        )

    def test_tab_becomes_a_tab_key(self):
        self.assertEqual(self.emit_all("\t"), [("key", "tab", ())])

    def test_run_plan_uses_the_policy_when_options_are_given(self):
        keyboard = FakeKeyboard()
        plan = engine.build_plan("a\nb", mode="char", human=False, wpm=engine.MAX_WPM)
        engine.run_plan(
            keyboard,
            plan,
            sleep=no_sleep,
            options=engine.EmitOptions(esc_before_enter=True, clear_autoindent=True),
        )
        self.assertEqual(
            [event[1] if event[0] == "key" else event[0] for event in keyboard.events],
            [
                "char",
                "esc",
                "esc",
                "enter",
                "home",
                "home",
                "end",
                "char",
                "backspace",
                "char",
            ],
        )

    def test_run_plan_keeps_the_old_path_without_options(self):
        # Existing callers (and the browser check) pass no options: the plan then
        # drives ``tap_char`` exactly as before.
        class TapOnly(FakeKeyboard):
            def __init__(self):
                super().__init__()
                self.tapped = []

            def tap_char(self, ch):
                self.tapped.append(ch)

        keyboard = TapOnly()
        plan = engine.build_plan("a\n", mode="char", human=False, wpm=engine.MAX_WPM)
        engine.run_plan(keyboard, plan, sleep=no_sleep)
        self.assertEqual(keyboard.tapped, ["a", "\n"])
        self.assertEqual(keyboard.events, [])


class X11PureFunctionTests(unittest.TestCase):
    def setUp(self):
        try:
            from backends.x11 import char_to_keysym
        except Exception as exc:  # pragma: no cover - only on a broken install
            self.skipTest("backends.x11 cannot be imported: %s" % exc)
        self.char_to_keysym = char_to_keysym

    def test_ascii_maps_to_its_code_point(self):
        self.assertEqual(self.char_to_keysym("a"), ord("a"))
        self.assertEqual(self.char_to_keysym(")"), ord(")"))

    def test_upper_case_is_its_own_keysym(self):
        self.assertEqual(self.char_to_keysym("A"), ord("A"))

    def test_latin1_keeps_its_code_point(self):
        # X11 defines Latin-1 keysyms as the code point itself (é = 0xE9 = 233).
        self.assertEqual(self.char_to_keysym("é"), 233)

    def test_beyond_latin1_uses_the_unicode_keysym_range(self):
        for ch in ("—", "你", "😀"):
            self.assertEqual(self.char_to_keysym(ch), 0x01000000 + ord(ch))

    def test_line_break_and_tab_map_to_named_keys(self):
        from backends.x11 import KS_NAMED

        self.assertEqual(self.char_to_keysym("\n"), KS_NAMED["enter"])
        self.assertEqual(self.char_to_keysym("\t"), KS_NAMED["tab"])

    def test_other_control_characters_are_not_typeable(self):
        self.assertIsNone(self.char_to_keysym("\x07"))


class WtypeTests(unittest.TestCase):
    def test_named_key_with_modifiers_builds_a_chord(self):
        from backends.wayland import WtypeKeyboard

        self.assertEqual(
            WtypeKeyboard._key_argv("end", ("shift",)),
            ["wtype", "-M", "shift", "-k", "End", "-m", "shift"],
        )

    def test_unknown_key_name_is_rejected(self):
        from backends.wayland import WtypeKeyboard

        with self.assertRaises(KeyboardError):
            WtypeKeyboard._key_argv("f13")


class SelectorTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows backend")
    def test_windows_selects_the_win32_backend(self):
        keyboard = get_keyboard()
        self.addCleanup(keyboard.close)
        self.assertEqual(keyboard.name, "win32")

    def test_wayland_detection_uses_the_session_variables(self):
        original = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(original)))
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ["XDG_SESSION_TYPE"] = "x11"
        self.assertFalse(is_wayland())
        os.environ["XDG_SESSION_TYPE"] = "wayland"
        self.assertTrue(is_wayland())
        os.environ.pop("XDG_SESSION_TYPE", None)
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        self.assertTrue(is_wayland())


@unittest.skipUnless(sys.platform == "win32", "Win32 SendInput backend")
class Win32AdapterTests(unittest.TestCase):
    def adapter(self):
        from backends.win32 import Win32Keyboard

        batches = []
        keyboard = Win32Keyboard(send=lambda events: (batches.append(events), len(events))[1])
        return batches, keyboard

    def test_named_keys_use_the_real_scan_codes(self):
        batches, keyboard = self.adapter()
        keyboard.key("enter")
        self.assertEqual(batches[0][0].u.ki.wVk, engine.VK_RETURN)
        self.assertEqual(batches[0][0].u.ki.wScan, engine.SCAN_RETURN)
        self.assertEqual(batches[0][1].u.ki.dwFlags, engine.KEYEVENTF_KEYUP)

    def test_home_is_sent_as_an_extended_key(self):
        batches, keyboard = self.adapter()
        keyboard.key("home")
        self.assertTrue(batches[0][0].u.ki.dwFlags & engine.KEYEVENTF_EXTENDEDKEY)

    def test_shift_end_is_one_batch_like_a_real_chord(self):
        batches, keyboard = self.adapter()
        keyboard.key("end", ("shift",))
        self.assertEqual(len(batches), 1)
        keys = [(event.u.ki.wVk, event.u.ki.dwFlags) for event in batches[0]]
        self.assertEqual(
            keys,
            [
                (engine.VK_LSHIFT, 0),
                (engine.VK_END, engine.KEYEVENTF_EXTENDEDKEY),
                (
                    engine.VK_END,
                    engine.KEYEVENTF_EXTENDEDKEY | engine.KEYEVENTF_KEYUP,
                ),
                (engine.VK_LSHIFT, engine.KEYEVENTF_KEYUP),
            ],
        )

    def test_characters_are_typed_as_unicode(self):
        batches, keyboard = self.adapter()
        keyboard.type_char("é")
        self.assertEqual(batches[0][0].u.ki.wScan, ord("é"))
        self.assertTrue(batches[0][0].u.ki.dwFlags & engine.KEYEVENTF_UNICODE)

    def test_space_is_typed_as_a_character(self):
        batches, keyboard = self.adapter()
        keyboard.key("space")
        self.assertEqual(batches[0][0].u.ki.wScan, ord(" "))

    def test_unknown_key_name_is_rejected(self):
        _batches, keyboard = self.adapter()
        with self.assertRaises(KeyboardError):
            keyboard.key("f13")

    def test_unknown_modifier_is_rejected(self):
        _batches, keyboard = self.adapter()
        with self.assertRaises(KeyboardError):
            keyboard.key("end", ("hyper",))


if __name__ == "__main__":
    unittest.main()
