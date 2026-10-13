"""UI flow tests for Auto Typer. The window stays hidden (withdrawn) and no
keystrokes are ever injected - these drive the app's state machine directly.

Run with:  py -m unittest discover -s auto-typer/tests -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
import tkinter as tk
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

import engine as engine_module  # noqa: E402  (typing engine, same folder)

spec = importlib.util.spec_from_file_location(
    "auto_typer_app", os.path.join(APP_DIR, "auto_typer.pyw")
)
app_module = importlib.util.module_from_spec(spec)
sys.modules["auto_typer_app"] = app_module
spec.loader.exec_module(app_module)


def make_app(test_case, save_on_close: bool = False):
    """Build a hidden app instance; returns the app (root is registered for cleanup)."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # no display / Tk unavailable
        test_case.skipTest(f"Tk unavailable: {exc}")
    root.withdraw()
    app = app_module.AutoTyperApp(root, dict(app_module.DEFAULTS), save_on_close=save_on_close)
    app.hotkey.stop()  # no global key watching during tests

    def cleanup():
        try:
            app.on_close()  # the app's real shutdown path
        except Exception:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass

    test_case.addCleanup(cleanup)
    return app


def pump(app, rounds: int = 3) -> None:
    """Run the poller the way the event loop would, then flush Tk's idle work.

    The pending scheduled job is cancelled first so we exercise the poller
    exactly once per round instead of stacking duplicate timers.
    """
    for _ in range(rounds):
        if app._poll_job is not None:
            try:
                app.root.after_cancel(app._poll_job)
            except tk.TclError:
                pass
            app._poll_job = None
        app._poll()
        app.root.update()


class UiFlowTests(unittest.TestCase):
    def test_starts_idle_and_ready(self):
        app = make_app(self)
        pump(app)
        self.assertEqual(app.state, "idle")
        self.assertIn("Ready", app.status_label.cget("text"))
        self.assertEqual(app.start_button.cget("text"), "Start typing (F8)")

    def test_start_with_empty_text_refuses_without_typing(self):
        app = make_app(self)
        app.start_typing()
        self.assertEqual(app.state, "idle")
        self.assertIn("Nothing to type yet", app.status_label.cget("text"))

    def test_progress_events_update_bar_status_and_highlight(self):
        app = make_app(self)
        app.text.insert("1.0", "hello world")
        app.run_text = "hello world"
        app.plan_total = 11
        app.typed_total = 0
        app.shown_upto = 0
        app.state = "typing"

        app.events.put(("progress", 9, None))  # highlights flush every 8 characters
        pump(app, rounds=1)

        self.assertIn("9 / 11", app.status_label.cget("text"))
        self.assertAlmostEqual(float(app.progress.cget("value")), 100 * 9 / 11, places=3)
        ranges = app.text.tag_ranges("typed")
        self.assertTrue(ranges, "expected the first 9 characters to be highlighted")
        self.assertEqual(str(ranges[0]), "1.0")
        self.assertEqual(str(ranges[1]), "1.9")
        head = app.text.tag_ranges("head")
        self.assertEqual(str(head[0]), "1.8")
        self.assertEqual(str(head[1]), "1.9")

    def test_injection_error_resets_ui_cleanly(self):
        app = make_app(self)
        app.text.insert("1.0", "hello world")
        app.run_text = "hello world"
        app.plan_total = 11
        app.state = "typing"
        app.events.put(("progress", 9, None))
        pump(app, rounds=1)
        self.assertTrue(app.text.tag_ranges("typed"))

        app.events.put(("error", 0, "Windows blocked the keystroke"))
        pump(app, rounds=1)

        self.assertEqual(app.state, "idle")
        self.assertIn("blocked the keystroke", app.status_label.cget("text"))
        self.assertEqual(float(app.progress.cget("value")), 0)
        self.assertEqual(app.typed_total, 0)
        self.assertEqual(app.resume_from, 0)
        self.assertFalse(app.text.tag_ranges("typed"))
        self.assertFalse(app.text.tag_ranges("head"))
        self.assertEqual(app.start_button.cget("text"), "Start typing (F8)")

    def test_stop_then_resume_offers_resume_button(self):
        app = make_app(self)
        app.text.insert("1.0", "hello world")
        app.run_text = app._normalized_text()
        app.plan_total = 11
        app.state = "typing"
        app.started_at = 0
        app._finish_run(4, None)  # simulates pressing F8 after 4 characters

        self.assertEqual(app.state, "idle")
        self.assertIn("Stopped at 4 / 11", app.status_label.cget("text"))
        self.assertTrue(app._resume_available())
        self.assertEqual(app.start_button.cget("text"), "Resume typing (F8)")

        app.reset_progress(quiet=True)
        self.assertFalse(app._resume_available())
        self.assertEqual(app.start_button.cget("text"), "Start typing (F8)")

    def test_finishing_a_run_clears_resume_state(self):
        app = make_app(self)
        app.text.insert("1.0", "hi")
        app.run_text = "hi"
        app.plan_total = 2
        app.state = "typing"
        app.started_at = 0
        app._finish_run(2, None)

        self.assertIn("Done - typed 2 / 2 characters", app.status_label.cget("text"))
        self.assertFalse(app._resume_available())
        self.assertEqual(app.resume_from, 0)

    def test_hotkey_event_toggles_only_from_idle(self):
        app = make_app(self)
        app.events.put(("hotkey",))
        pump(app, rounds=1)
        # Empty text box: the hotkey must not start a run.
        self.assertEqual(app.state, "idle")
        self.assertIn("Nothing to type yet", app.status_label.cget("text"))

    def test_estimate_updates_with_text_and_speed(self):
        app = make_app(self)
        self.assertIn("nothing to type", app.estimate_label.cget("text"))
        app.text.insert("1.0", "hello world, this is a test.")
        app._refresh_estimate()
        self.assertIn("28 characters", app.estimate_label.cget("text"))
        app.wpm_var.set(100)
        app._refresh_estimate()
        self.assertIn("100 wpm", app.wpm_label.cget("text"))

    def test_close_persists_text_and_settings(self):
        original = app_module.SETTINGS_FILE
        with tempfile.TemporaryDirectory() as tmp:
            app_module.SETTINGS_FILE = os.path.join(tmp, "settings.json")
            try:
                app = make_app(self, save_on_close=True)
                app.text.delete("1.0", "end")
                app.text.insert("1.0", "keep me\nmore")
                app.wpm_var.set(120)
                app.mode_var.set("char")
                app.delay_var.set(5)
                app.esc_enter_var.set(True)
                app.pacing_var.set(True)
                app.indent_fix_var.set(True)
                app.on_close()  # the window's close button
                app.on_close()  # closing twice must not raise

                loaded = app_module.load_settings()
            finally:
                app_module.SETTINGS_FILE = original
        self.assertEqual(loaded["text"], "keep me\nmore")
        self.assertEqual(loaded["wpm"], 120.0)
        self.assertEqual(loaded["mode"], "char")
        self.assertEqual(loaded["start_delay"], 5)
        self.assertTrue(loaded["esc_before_enter"])
        self.assertTrue(loaded["pacing"])
        self.assertTrue(loaded["auto_indent_fix"])

    def test_editor_compatibility_options_reach_the_engine(self):
        app = make_app(self)
        app.text.insert("1.0", "a\nb")

        self.assertFalse(app.esc_enter_var.get())
        self.assertFalse(app.pacing_var.get())
        self.assertFalse(app.indent_fix_var.get())
        self.assertEqual(app.newline_strategy(), engine_module.NEWLINE_ENTER)
        self.assertEqual(
            app.keyboard_options(),
            {"newline_strategy": engine_module.NEWLINE_ENTER, "auto_indent_fix": False},
        )
        self.assertEqual(app._params()["min_gap"], 0.0)
        self.assertEqual(app._params()["min_newline_pause"], 0.0)

        app.esc_enter_var.set(True)
        app.pacing_var.set(True)
        app.indent_fix_var.set(True)
        self.assertEqual(app.newline_strategy(), engine_module.NEWLINE_ESC_ENTER)
        self.assertEqual(
            app.keyboard_options(),
            {"newline_strategy": engine_module.NEWLINE_ESC_ENTER, "auto_indent_fix": True},
        )
        self.assertEqual(app._params()["min_gap"], engine_module.COMPAT_MIN_GAP)
        self.assertEqual(
            app._params()["min_newline_pause"], engine_module.COMPAT_NEWLINE_PAUSE
        )

        app._refresh_estimate()
        self.assertIn("3 characters", app.estimate_label.cget("text"))

    def test_starting_a_run_hands_the_editor_options_to_the_worker(self):
        app = make_app(self)
        app.text.insert("1.0", "a\nb")
        app.esc_enter_var.set(True)
        app.indent_fix_var.set(True)
        app.run_text = app._normalized_text()
        app.plan_total = len(app.run_text)
        seen = []
        original = app._worker
        app._worker = lambda plan, options: seen.append(options)
        try:
            app._begin_typing()
            deadline = time.time() + 2.0
            while not seen and time.time() < deadline:
                time.sleep(0.01)
        finally:
            app._worker = original
        self.assertEqual(
            seen,
            [
                {
                    "newline_strategy": engine_module.NEWLINE_ESC_ENTER,
                    "auto_indent_fix": True,
                }
            ],
        )

    def test_pacing_floors_only_bite_at_high_speeds(self):
        app = make_app(self)
        app.text.insert("1.0", "print('hello world')\nprint('again')")
        params = app._params()
        params["human"] = False
        idle = engine_module.plan_duration(engine_module.build_plan(app._normalized_text(), **params))

        app.pacing_var.set(True)
        params = app._params()
        params["human"] = False
        paced = engine_module.plan_duration(engine_module.build_plan(app._normalized_text(), **params))
        # The app's default 40 wpm is already slower than the compatibility floors.
        self.assertEqual(idle, paced)

    def test_paced_plan_is_slower_than_the_default_one_at_top_speed(self):
        app = make_app(self)
        app.text.insert("1.0", "print('hello world')\nprint('again')")
        app.wpm_var.set(engine_module.MAX_WPM)
        params = app._params()
        params["human"] = False  # deterministic, so only pacing differs
        fast = engine_module.plan_duration(engine_module.build_plan(app._normalized_text(), **params))

        app.pacing_var.set(True)
        params = app._params()
        params["human"] = False
        slow = engine_module.plan_duration(engine_module.build_plan(app._normalized_text(), **params))
        self.assertGreater(slow, fast)

    def test_events_with_missing_fields_do_not_break_the_poller(self):
        app = make_app(self)
        app.events.put(("progress",))  # malformed on purpose
        pump(app, rounds=1)
        app.events.put(("idle", 0, None))
        pump(app, rounds=1)
        self.assertIn("Ready", app.status_label.cget("text"))

    def test_clear_and_paste_buttons_reset_state(self):
        app = make_app(self)
        app.text.insert("1.0", "some text")
        app.resume_from = 5
        app.stopped_text = "some text"
        app.clear_text()
        app._refresh_estimate()
        self.assertEqual(app.text.get("1.0", "end-1c"), "")
        self.assertEqual(app.resume_from, 0)
        self.assertIn("nothing to type", app.estimate_label.cget("text"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
