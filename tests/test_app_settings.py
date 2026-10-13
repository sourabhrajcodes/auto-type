"""Tests for Auto Typer's settings persistence (no GUI is opened).

Run with:  py -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

spec = importlib.util.spec_from_file_location(
    "auto_typer_app", os.path.join(APP_DIR, "auto_typer.pyw")
)
app = importlib.util.module_from_spec(spec)
sys.modules["auto_typer_app"] = app
spec.loader.exec_module(app)  # module-level code only; main() needs __main__


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original = app.SETTINGS_FILE
        app.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        self.addCleanup(lambda: setattr(app, "SETTINGS_FILE", self.original))

    def write(self, payload) -> None:
        with open(app.SETTINGS_FILE, "w", encoding="utf-8") as handle:
            if isinstance(payload, str):
                handle.write(payload)
            else:
                json.dump(payload, handle)

    def test_missing_file_yields_defaults(self):
        self.assertEqual(app.load_settings(), app.DEFAULTS)

    def test_auto_indent_fix_defaults_off(self):
        self.assertFalse(app.DEFAULTS["auto_indent_fix"])
        self.assertFalse(app.load_settings()["auto_indent_fix"])

    def test_roundtrip_keeps_values(self):
        data = {
            "text": "print('hi')\n",
            "wpm": 120,
            "mode": "char",
            "human": False,
            "start_delay": 7,
            "convert_tabs": False,
            "tab_spaces": 2,
            "minimize": True,
            "topmost": False,
            "esc_before_enter": True,
            "pacing": True,
            "auto_indent_fix": True,
        }
        app.save_settings(data)
        self.assertEqual(app.load_settings(), data)

    def test_saved_file_is_valid_json_encoded_unicode(self):
        app.save_settings({"text": "héllo 😀", **{k: v for k, v in app.DEFAULTS.items() if k != "text"}})
        with open(app.SETTINGS_FILE, "r", encoding="utf-8") as handle:
            self.assertIn("héllo", handle.read())

    def test_bad_values_are_sanitised(self):
        self.write(
            {
                "text": 123,
                "wpm": "fast",
                "mode": "diagonal",
                "human": "yes",
                "start_delay": 99,
                "tab_spaces": 0,
                "minimize": 0,
                "topmost": 1,
                "auto_indent_fix": 0,
            }
        )
        loaded = app.load_settings()
        self.assertFalse(loaded["auto_indent_fix"])
        self.assertEqual(loaded["text"], "")
        self.assertEqual(loaded["wpm"], app.DEFAULTS["wpm"])
        self.assertEqual(loaded["mode"], app.DEFAULTS["mode"])
        self.assertEqual(loaded["start_delay"], 30)
        self.assertEqual(loaded["tab_spaces"], 1)
        self.assertTrue(loaded["human"])
        self.assertTrue(loaded["topmost"])
        self.assertFalse(loaded["minimize"])

    def test_corrupt_file_falls_back_to_defaults(self):
        self.write("{ this is not json")
        self.assertEqual(app.load_settings(), app.DEFAULTS)

    def test_numeric_strings_are_accepted(self):
        self.write({"wpm": "55", "start_delay": "4", "tab_spaces": "6"})
        loaded = app.load_settings()
        self.assertEqual(loaded["wpm"], 55.0)
        self.assertEqual(loaded["start_delay"], 4)
        self.assertEqual(loaded["tab_spaces"], 6)

    def test_partial_file_merges_with_defaults(self):
        self.write({"wpm": 80})
        loaded = app.load_settings()
        self.assertEqual(loaded["wpm"], 80.0)
        self.assertEqual(loaded["mode"], app.DEFAULTS["mode"])

    def test_boolean_spellings_are_understood(self):
        for text, expected in (
            ("true", True),
            (" TRUE ", True),
            ("yes", True),
            ("on", True),
            ("1", True),
            ("false", False),
            ("no", False),
            ("off", False),
            ("0", False),
            ("", False),
        ):
            with self.subTest(text=text):
                self.assertIs(app.as_bool(text), expected)
        self.assertIs(app.as_bool(True), True)
        self.assertIs(app.as_bool(1), True)
        self.assertIs(app.as_bool(0), False)

    def test_unreadable_booleans_keep_the_default(self):
        # "off" must not become True just because it is a non-empty string.
        self.write({"pacing": "maybe", "topmost": None, "minimize": []})
        loaded = app.load_settings()
        self.assertFalse(loaded["pacing"])
        self.assertTrue(loaded["topmost"])  # default is on
        self.assertFalse(loaded["minimize"])

    def test_string_booleans_load_as_expected(self):
        self.write(
            {
                "human": "no",
                "convert_tabs": "1",
                "minimize": "true",
                "topmost": "false",
                "esc_before_enter": "yes",
                "pacing": "off",
                "auto_indent_fix": "on",
            }
        )
        loaded = app.load_settings()
        self.assertFalse(loaded["human"])
        self.assertTrue(loaded["convert_tabs"])
        self.assertTrue(loaded["minimize"])
        self.assertFalse(loaded["topmost"])
        self.assertTrue(loaded["esc_before_enter"])
        self.assertFalse(loaded["pacing"])
        self.assertTrue(loaded["auto_indent_fix"])

    def test_hotkey_getter_degrades_without_win32(self):
        self.assertIsNone(app.key_state_getter(types.SimpleNamespace()))

        def fake_get_state(_vk):  # pragma: no cover - never called here
            return 0

        fake_user32 = types.SimpleNamespace(GetAsyncKeyState=fake_get_state)
        module = types.SimpleNamespace(
            c_int=int, c_short=int, windll=types.SimpleNamespace(user32=fake_user32)
        )
        getter = app.key_state_getter(module)
        self.assertIs(getter, fake_get_state)
        self.assertEqual(getter.argtypes, (int,))
        self.assertIs(getter.restype, int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
