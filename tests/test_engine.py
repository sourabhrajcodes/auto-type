"""Unit tests for the Auto Typer engine (no real keystrokes are injected).

Run with:  py -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402

CODE_SAMPLE = (
    "def add(a, b):\n"
    "    return a + b  # sums two numbers\n"
    "\n"
    "print(add(2, 3))\n"
)
UNICODE_SAMPLE = "héllo wörld — 你好, नमस्ते! 😀 Done."


class FakeKeyboard:
    """Records the characters it was asked to type."""

    def __init__(self):
        self.typed = []

    def tap_char(self, ch):
        self.typed.append(ch)


class VirtualClock:
    """Stand-in for time.sleep that just accumulates time."""

    def __init__(self):
        self.now = 0.0

    def __call__(self, seconds):
        self.now += seconds


class PlanTests(unittest.TestCase):
    def test_plan_rebuilds_the_exact_text(self):
        for mode in ("word", "char"):
            for sample in (CODE_SAMPLE, UNICODE_SAMPLE, "single", "  leading and trailing  \n"):
                with self.subTest(mode=mode, sample=sample[:12]):
                    plan = engine.build_plan(sample, wpm=60, mode=mode, human=True)
                    self.assertEqual("".join(s.text for s in plan), sample)

    def test_char_mode_delay_matches_wpm(self):
        plan = engine.build_plan("ab cd", wpm=60, mode="char", human=False)
        # 60 wpm = 300 chars/min -> 0.2 s per character
        for stroke in plan:
            self.assertAlmostEqual(stroke.post_delay, 0.2, places=6)

    def test_punctuation_and_newlines_pause_longer(self):
        plan = engine.build_plan("a.!\n", wpm=60, mode="char", human=False)
        delays = {s.text: s.post_delay for s in plan}
        self.assertAlmostEqual(delays["."], 0.4, places=6)
        self.assertAlmostEqual(delays["!"], 0.4, places=6)
        self.assertAlmostEqual(delays["\n"], 0.32, places=6)
        self.assertAlmostEqual(delays["a"], 0.2, places=6)

    def test_word_mode_uses_bursts_then_pauses(self):
        plan = engine.build_plan("hello world", wpm=60, mode="word", human=False)
        words = [s for s in plan if not s.text.isspace()]
        spaces = [s for s in plan if s.text.isspace()]
        self.assertEqual([s.text for s in words], ["hello", "world"])
        self.assertEqual(len(spaces), 1)
        for stroke in words:
            self.assertGreater(stroke.intra_delay, 0)
            self.assertLess(stroke.intra_delay, stroke.post_delay)
        for stroke in spaces:
            self.assertEqual(stroke.intra_delay, 0)
            self.assertGreater(stroke.post_delay, 0)

    def test_word_mode_words_never_contain_whitespace(self):
        for stroke in engine.build_plan("a b\tc\nd  e", mode="word"):
            if not stroke.text.isspace():
                self.assertFalse(any(ch.isspace() for ch in stroke.text))

    def test_human_jitter_varies_but_stays_positive(self):
        rng = random.Random(7)
        plan = engine.build_plan("aaaaaaaaa", wpm=60, mode="char", human=True, rng=rng)
        delays = [s.post_delay for s in plan]
        self.assertGreater(len(set(round(d, 6) for d in delays)), 3)
        self.assertTrue(all(d > 0 for d in delays))

        steady = engine.build_plan("aaaaaaaaa", wpm=60, mode="char", human=False)
        self.assertEqual(len({round(s.post_delay, 9) for s in steady}), 1)

    def test_crlf_is_normalised(self):
        crlf = engine.build_plan("a\r\nb", mode="char")
        lf = engine.build_plan("a\nb", mode="char")
        self.assertEqual([s.text for s in crlf], [s.text for s in lf])

    def test_tab_conversion_toggle(self):
        converted = engine.build_plan("a\tb", mode="char", tab_spaces=2)
        self.assertEqual("".join(s.text for s in converted), "a  b")
        kept = engine.build_plan("a\tb", mode="char", convert_tabs=False)
        self.assertEqual("".join(s.text for s in kept), "a\tb")

    def test_empty_and_whitespace_text(self):
        self.assertEqual(engine.build_plan(""), [])
        plan = engine.build_plan(" \n ", mode="word")
        self.assertEqual("".join(s.text for s in plan), " \n ")

    def test_wpm_is_clamped(self):
        slow = engine.build_plan("aa", wpm=0.001, human=False)
        self.assertAlmostEqual(slow[0].post_delay, engine.base_char_delay(engine.MIN_WPM), places=6)
        fast = engine.build_plan("aa", wpm=10_000, human=False)
        self.assertAlmostEqual(fast[0].post_delay, engine.base_char_delay(engine.MAX_WPM), places=6)

    def test_compatibility_pacing_floors_every_gap(self):
        plain = engine.build_plan("a b\nc", wpm=engine.MAX_WPM, mode="word", human=False)
        paced = engine.build_plan(
            "a b\nc",
            wpm=engine.MAX_WPM,
            mode="word",
            human=False,
            min_gap=engine.COMPAT_MIN_GAP,
            min_newline_pause=engine.COMPAT_NEWLINE_PAUSE,
        )
        self.assertEqual("".join(s.text for s in paced), "a b\nc")
        for stroke in paced:
            self.assertGreaterEqual(stroke.post_delay, engine.COMPAT_MIN_GAP)
            if stroke.intra_delay:
                self.assertGreaterEqual(stroke.intra_delay, engine.COMPAT_MIN_GAP)
            if "\n" in stroke.text:
                self.assertAlmostEqual(stroke.post_delay, engine.COMPAT_NEWLINE_PAUSE)
        self.assertGreater(engine.plan_duration(paced), engine.plan_duration(plain))

    def test_pacing_applies_in_char_mode_too(self):
        plan = engine.build_plan(
            "a\nb",
            wpm=engine.MAX_WPM,
            mode="char",
            human=False,
            min_gap=engine.COMPAT_MIN_GAP,
            min_newline_pause=engine.COMPAT_NEWLINE_PAUSE,
        )
        delays = {s.text: s.post_delay for s in plan}
        self.assertGreaterEqual(delays["a"], engine.COMPAT_MIN_GAP)
        self.assertAlmostEqual(delays["\n"], engine.COMPAT_NEWLINE_PAUSE)

    def test_pacing_off_by_default(self):
        plan = engine.build_plan("a\nb", wpm=engine.MAX_WPM, mode="char", human=False)
        delays = {s.text: s.post_delay for s in plan}
        self.assertLess(delays["\n"], engine.COMPAT_NEWLINE_PAUSE)

    def test_plan_duration_adds_up(self):
        plan = engine.build_plan("hi there friend", wpm=30, mode="word", human=False)
        expected = sum(s.post_delay + s.intra_delay * max(0, len(s.text) - 1) for s in plan)
        self.assertAlmostEqual(engine.plan_duration(plan), expected, places=9)
        self.assertGreater(engine.plan_duration(plan), 0)


class RunPlanTests(unittest.TestCase):
    def test_types_everything_in_order(self):
        keyboard = FakeKeyboard()
        plan = engine.build_plan(CODE_SAMPLE, wpm=engine.MAX_WPM, mode="word", human=False)
        clock = VirtualClock()
        typed = engine.run_plan(keyboard, plan, sleep=clock)
        self.assertEqual(typed, len(CODE_SAMPLE))
        self.assertEqual("".join(keyboard.typed), CODE_SAMPLE)
        self.assertAlmostEqual(clock.now, engine.plan_duration(plan), places=6)

    def test_stop_request_is_honoured_almost_instantly(self):
        keyboard = FakeKeyboard()
        plan = engine.build_plan(CODE_SAMPLE, mode="char", human=False)
        typed = engine.run_plan(
            keyboard, plan, should_stop=lambda: len(keyboard.typed) >= 5, sleep=VirtualClock()
        )
        self.assertEqual(typed, 5)
        self.assertEqual(len(keyboard.typed), 5)

    def test_progress_callback_counts_up(self):
        seen = []
        engine.run_plan(
            FakeKeyboard(),
            engine.build_plan("abc", mode="char"),
            on_char=seen.append,
            sleep=VirtualClock(),
        )
        self.assertEqual(seen, [1, 2, 3])


class StopLatencyTests(unittest.TestCase):
    def test_wait_interruptibly_slices_only_when_a_stop_callback_exists(self):
        calls = []
        self.assertTrue(engine.wait_interruptibly(calls.append, 0.05))
        self.assertEqual(calls, [0.05])  # one exact sleep, nothing sliced

        calls.clear()
        stopped = {"now": False}
        self.assertTrue(engine.wait_interruptibly(calls.append, 0.05, lambda: stopped["now"]))
        self.assertAlmostEqual(sum(calls), 0.05, places=9)
        self.assertGreater(len(calls), 1)  # long waits are sliced for polling

        calls.clear()
        stopped["now"] = True
        self.assertFalse(engine.wait_interruptibly(calls.append, 0.5, lambda: stopped["now"]))
        self.assertEqual(calls, [])  # already stopping: sleeps nothing more

    def test_stop_is_honoured_inside_a_long_pause(self):
        # At 10 wpm a single pause lasts over a second. F8 must not wait for the
        # pause to finish playing out.
        plan = engine.build_plan("print('hello world.')\nx = 1", wpm=10, mode="char", human=False)
        keyboard = FakeKeyboard()
        clock = VirtualClock()
        pressed_at = []

        def sleep(seconds):
            if not pressed_at and clock.now >= 0.5:  # the key press lands mid-pause
                pressed_at.append(clock.now)
            clock.now += seconds

        typed = engine.run_plan(
            keyboard, plan, should_stop=lambda: bool(pressed_at), sleep=sleep
        )
        self.assertTrue(pressed_at, "this plan should contain a pause longer than 0.5 s")
        self.assertGreater(typed, 0)
        self.assertLessEqual(clock.now - pressed_at[0], engine.STOP_POLL_SLICE + 1e-9)

    def test_no_stop_callback_keeps_the_planned_duration(self):
        plan = engine.build_plan("hello world.", wpm=10, mode="char", human=False)
        clock = VirtualClock()
        engine.run_plan(FakeKeyboard(), plan, sleep=clock)
        self.assertAlmostEqual(clock.now, engine.plan_duration(plan), places=9)


class ResumePropertyTests(unittest.TestCase):
    def test_stopping_and_resuming_at_every_character_reproduces_the_text(self):
        text = "def f(a):\n    return a + 1  # ok\n\nprint(f('x'))\n"
        plan = engine.build_plan(
            text, wpm=engine.MAX_WPM, mode="word", human=True, rng=random.Random(99)
        )
        for split in range(len(text) + 1):
            with self.subTest(split=split):
                first = FakeKeyboard()
                typed = engine.run_plan(
                    first,
                    plan,
                    should_stop=lambda: len(first.typed) >= split,
                    sleep=lambda _seconds: None,
                )
                self.assertEqual(typed, split)
                self.assertEqual("".join(first.typed), text[:split])

                rest = FakeKeyboard()
                engine.run_plan(rest, engine.trim_plan(plan, typed), sleep=lambda _s: None)
                self.assertEqual("".join(rest.typed), text[split:])


class TrimPlanTests(unittest.TestCase):
    def test_trim_removes_exactly_n_characters(self):
        for mode in ("word", "char"):
            plan = engine.build_plan(CODE_SAMPLE, mode=mode, wpm=engine.MAX_WPM)
            for skip in (0, 1, 7, len(CODE_SAMPLE) - 1, len(CODE_SAMPLE), len(CODE_SAMPLE) + 5):
                with self.subTest(mode=mode, skip=skip):
                    left = "".join(s.text for s in engine.trim_plan(plan, skip))
                    self.assertEqual(left, CODE_SAMPLE[skip:])

    def test_trim_keeps_original_plan_intact(self):
        plan = engine.build_plan("hello world", mode="word")
        before = [s.text for s in plan]
        engine.trim_plan(plan, 6)
        self.assertEqual([s.text for s in plan], before)


@unittest.skipUnless(engine.IS_WINDOWS, "Win32 structures only exist on Windows")
class Win32InjectionTests(unittest.TestCase):
    def collector(self):
        batches = []

        def send(events):
            batches.append(events)
            return len(events)

        return batches, engine.WindowsKeyboard(send=send)

    def test_input_struct_layout_matches_win32(self):
        import ctypes

        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(engine.INPUT), expected)
        self.assertEqual(engine.INPUT_KEYBOARD, 1)

    def test_plain_character_uses_unicode_scan_code(self):
        batches, keyboard = self.collector()
        keyboard.tap_char("A")
        self.assertEqual(len(batches), 1)
        down, up = batches[0]
        self.assertEqual(down.type, engine.INPUT_KEYBOARD)
        self.assertEqual(down.u.ki.wScan, ord("A"))
        self.assertEqual(down.u.ki.wVk, 0)
        self.assertEqual(down.u.ki.dwFlags, engine.KEYEVENTF_UNICODE)
        self.assertEqual(
            up.u.ki.dwFlags, engine.KEYEVENTF_UNICODE | engine.KEYEVENTF_KEYUP
        )

    def test_newline_and_tab_use_virtual_keys(self):
        batches, keyboard = self.collector()
        keyboard.tap_char("\n")
        keyboard.tap_char("\t")
        self.assertEqual(batches[0][0].u.ki.wVk, engine.VK_RETURN)
        self.assertEqual(batches[1][0].u.ki.wVk, engine.VK_TAB)
        self.assertEqual(batches[1][0].u.ki.dwFlags, 0)

    def test_line_break_carries_the_real_scan_code(self):
        # Browser editors read DOM event.code from the scan code; without it
        # some of them treat the Enter as "Unidentified" and ignore it.
        batches, keyboard = self.collector()
        keyboard.tap_char("\n")
        down = batches[0][0]
        self.assertEqual(down.u.ki.wVk, engine.VK_RETURN)
        self.assertEqual(down.u.ki.wScan, engine.SCAN_RETURN)
        self.assertEqual(down.u.ki.dwFlags, 0)
        self.assertEqual(batches[0][1].u.ki.dwFlags, engine.KEYEVENTF_KEYUP)

    def test_tab_carries_the_real_scan_code(self):
        batches, _keyboard = self.collector()
        _keyboard.tap_char("\t")
        self.assertEqual(batches[0][0].u.ki.wScan, engine.SCAN_TAB)

    def test_esc_enter_strategy_dismisses_popups_before_breaking_the_line(self):
        batches = []

        def send(events):
            batches.append(events)
            return len(events)

        keyboard = engine.WindowsKeyboard(send=send, newline_strategy=engine.NEWLINE_ESC_ENTER)
        keyboard.tap_char("\n")
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0][0].u.ki.wVk, engine.VK_ESCAPE)
        self.assertEqual(batches[0][0].u.ki.wScan, engine.SCAN_ESCAPE)
        self.assertEqual(batches[1][0].u.ki.wVk, engine.VK_RETURN)

    def test_plain_enter_strategy_sends_no_escape(self):
        batches, keyboard = self.collector()
        self.assertEqual(keyboard.newline_strategy, engine.NEWLINE_ENTER)
        keyboard.tap_char("\n")
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][0].u.ki.wVk, engine.VK_RETURN)

    def test_auto_indent_fix_is_off_by_default(self):
        batches, keyboard = self.collector()
        self.assertFalse(keyboard.auto_indent_fix)
        keyboard.tap_char("\n")
        self.assertEqual(len(batches), 1)  # Enter only, nothing else is sent

    def test_auto_indent_fix_clears_the_new_line_after_enter(self):
        batches = []
        keyboard = engine.WindowsKeyboard(
            send=lambda events: (batches.append(events), len(events))[1],
            auto_indent_fix=True,
        )
        keyboard.tap_char("\n")

        keys = [(batch[0].u.ki.wVk, batch[0].u.ki.wScan) for batch in batches]
        self.assertEqual(
            keys,
            [
                (engine.VK_RETURN, engine.SCAN_RETURN),
                (engine.VK_HOME, engine.SCAN_HOME),
                (engine.VK_HOME, engine.SCAN_HOME),
                (engine.VK_LSHIFT, engine.SCAN_LSHIFT),  # Shift+End chord
                (0, ord(" ")),  # the space replaces the selected indentation
                (engine.VK_BACKSPACE, engine.SCAN_BACKSPACE),
            ],
        )

    def test_auto_indent_home_and_end_are_extended_keys(self):
        # Browsers map DOM keys from the scan code; without the E0 flag the
        # editor can read scan 0x47 as Numpad-7 instead of Home.
        batches = []
        keyboard = engine.WindowsKeyboard(
            send=lambda events: (batches.append(events), len(events))[1],
            auto_indent_fix=True,
        )
        keyboard.tap_char("\n")
        home_down, home_up = batches[1]
        self.assertEqual(home_down.u.ki.dwFlags, engine.KEYEVENTF_EXTENDEDKEY)
        self.assertEqual(
            home_up.u.ki.dwFlags,
            engine.KEYEVENTF_EXTENDEDKEY | engine.KEYEVENTF_KEYUP,
        )
        shift_down, end_down, end_up, shift_up = batches[3]
        self.assertEqual(shift_down.u.ki.wVk, engine.VK_LSHIFT)
        self.assertEqual(shift_down.u.ki.dwFlags, 0)
        self.assertEqual(end_down.u.ki.dwFlags, engine.KEYEVENTF_EXTENDEDKEY)
        self.assertEqual(
            end_up.u.ki.dwFlags,
            engine.KEYEVENTF_EXTENDEDKEY | engine.KEYEVENTF_KEYUP,
        )
        self.assertEqual(shift_up.u.ki.dwFlags, engine.KEYEVENTF_KEYUP)

    def test_auto_indent_fix_always_types_a_space_before_backspace(self):
        # If the editor inserted nothing there is no selection, and a bare
        # Backspace at column 0 would join this line with the previous one, so
        # the space makes the Backspace safe in every editor.
        batches = []
        keyboard = engine.WindowsKeyboard(
            send=lambda events: (batches.append(events), len(events))[1],
            auto_indent_fix=True,
        )
        keyboard.tap_char("\n")
        last_two = [(batch[0].u.ki.wVk, batch[0].u.ki.wScan) for batch in batches[-2:]]
        self.assertEqual(
            last_two, [(0, ord(" ")), (engine.VK_BACKSPACE, engine.SCAN_BACKSPACE)]
        )

    def test_auto_indent_fix_combines_with_the_esc_strategy(self):
        batches = []
        keyboard = engine.WindowsKeyboard(
            send=lambda events: (batches.append(events), len(events))[1],
            newline_strategy=engine.NEWLINE_ESC_ENTER,
            auto_indent_fix=True,
        )
        keyboard.tap_char("\n")
        kinds = [batch[0].u.ki.wVk for batch in batches]
        self.assertEqual(kinds[0], engine.VK_ESCAPE)
        self.assertEqual(kinds[1], engine.VK_RETURN)
        self.assertEqual(kinds[2:4], [engine.VK_HOME, engine.VK_HOME])

    def test_auto_indent_fix_leaves_ordinary_characters_alone(self):
        batches = []
        keyboard = engine.WindowsKeyboard(
            send=lambda events: (batches.append(events), len(events))[1],
            auto_indent_fix=True,
        )
        keyboard.type_text("ab")
        self.assertEqual(len(batches), 2)
        self.assertEqual([batch[0].u.ki.wScan for batch in batches], [ord("a"), ord("b")])

    def test_auto_indent_fix_survives_the_full_text_path(self):
        # The reset keys are extra keystrokes, not characters: the plan and the
        # typed text must be unaffected.
        batches = []
        keyboard = engine.WindowsKeyboard(
            send=lambda events: (batches.append(events), len(events))[1],
            auto_indent_fix=True,
        )
        engine.run_plan(
            keyboard,
            engine.build_plan("a\nb", mode="char", human=False, wpm=engine.MAX_WPM),
            sleep=lambda _seconds: None,
        )
        returns = [b for b in batches if b[0].u.ki.wVk == engine.VK_RETURN]
        self.assertEqual(len(returns), 1)
        self.assertGreater(len(batches), 3)  # the reset keys really were sent

    def test_unknown_newline_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            engine.WindowsKeyboard(send=lambda events: len(events), newline_strategy="slide")

    def test_escape_strategy_leaves_ordinary_characters_alone(self):
        batches = []
        keyboard = engine.WindowsKeyboard(
            send=lambda events: (batches.append(events), len(events))[1],
            newline_strategy=engine.NEWLINE_ESC_ENTER,
        )
        keyboard.type_text("ab")
        self.assertEqual(len(batches), 2)  # one batch per character, no escapes
        self.assertEqual([b[0].u.ki.wScan for b in batches], [ord("a"), ord("b")])

    def test_surrogate_pair_is_split_into_two_utf16_units(self):
        batches, keyboard = self.collector()
        keyboard.tap_char("\U0001F600")  # 😀
        self.assertEqual(len(batches), 2)
        self.assertEqual(
            [b[0].u.ki.wScan for b in batches], list(engine._unicode_units("\U0001F600"))
        )
        self.assertEqual([b[0].u.ki.wScan for b in batches], [0xD83D, 0xDE00])

    def test_type_text_preserves_order(self):
        batches, keyboard = self.collector()
        keyboard.type_text("a\nb c")
        typed = "".join(
            "\n" if b[0].u.ki.wVk == engine.VK_RETURN else chr(b[0].u.ki.wScan) for b in batches
        )
        self.assertEqual(typed, "a\nb c")

    def test_blocked_injection_raises_informative_error(self):
        with self.assertRaisesRegex(engine.InjectionError, "blocked the keystroke"):
            engine._check_inserted(1, 2)
        engine._check_inserted(2, 2)  # no raise

    def test_construction_fails_clearly_without_send_impl_on_windows(self):
        keyboard = engine.WindowsKeyboard()  # real SendInput path must construct
        self.assertTrue(callable(keyboard.tap_char))


if __name__ == "__main__":
    unittest.main(verbosity=2)
