# Auto Typer

**Paste your text, press Start, and Auto Typer types it out for you** — one key at a time, at the
speed you choose, into whatever window you have focused: an online code editor, a website form, a
chat box, a note-taking app, anything that accepts a keyboard.

It does **not** use copy-paste. It presses the keys, like a very fast (or very patient) person.
That is exactly why it works on web pages that block paste, and exactly why you should read the
"before you start" notes below.

Windows 10 / 11 · Python standard library only · no account, no internet, no telemetry.

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Contents

1. [What is it, and who is it for?](#1-what-is-it-and-who-is-it-for)
2. [Get it running (no programming needed)](#2-get-it-running-no-programming-needed)
3. [Using the app](#3-using-the-app)
4. [All options explained](#4-all-options-explained)
5. [Recommended settings for online code editors](#5-recommended-settings-for-online-code-editors)
6. [Troubleshooting](#6-troubleshooting)
7. [How it works (the short technical version)](#7-how-it-works-the-short-technical-version)
8. [Verify it on your own PC (optional)](#8-verify-it-on-your-own-pc-optional)
9. [Project files](#9-project-files)
10. [Build a standalone .exe](#10-build-a-standalone-exe)
11. [FAQ](#11-faq)
12. [Limitations and responsible use](#12-limitations-and-responsible-use)

---

## 1. What is it, and who is it for?

Auto Typer is a small Windows desktop app. You paste (or type) the text you want, pick a speed,
click **Start**, and click into the window where the text should appear. Auto Typer then types it
there, character by character, while you do something else.

Typical uses:

- **Online coding tests and practice sites** (HackerRank-style editors) where paste is blocked or
  strips indentation.
- **Long forms and portals** where you have the answers saved somewhere and want them entered
  without retyping.
- **Chats, tickets and emails** where you send the same message again and again.
- **Live demos, streams and recordings** where you want text to appear on screen at a human pace.

### What it can do

- Type any text, including code with indentation, emoji and non-English characters (हिन्दी, 中文, é).
- Type at 10–400 words per minute, word by word or character by character, with an optional
  human-like rhythm (small random variations, longer pauses after punctuation and line ends).
- Start with a countdown, so you have time to click into the target window.
- Stop at any moment with **F8** (works from anywhere) and **resume from the same character** later.
- Handle the two things web code editors do to break automated typing — see
  [section 5](#5-recommended-settings-for-online-code-editors).
- Remember your text and settings between launches.

### What it cannot do

- **It cannot type into windows running as administrator** (or into the UAC prompt / lock screen).
  Windows blocks synthetic keystrokes coming from a normal app — that is a security feature, not a
  bug. See [Limitations](#12-limitations-and-responsible-use).
- It does not work on macOS or Linux (it uses a Windows-only keyboard API).
- It cannot make a website accept input that the website itself blocks.
- It does not read the screen, and it cannot check what actually appeared in the target window.

---

## 2. Get it running (no programming needed)

You need Windows 10 or 11. Everything below takes about five minutes the first time.

### Step 1 — Install Python (once)

1. Go to <https://www.python.org/downloads/windows/> and download the latest **Windows installer
   (64-bit)**.
2. Run the installer. **On the first screen, tick the checkbox "Add python.exe to PATH"** — this is
   the step people miss. Then click *Install Now*.
3. To confirm it worked, press `Win + R`, type `cmd`, press Enter, and in the black window type:

   ```
   py --version
   ```

   You should see something like `Python 3.12.10`. If you see "not recognized", re-run the
   installer, choose *Modify*, and make sure the PATH option is enabled.

### Step 2 — Download this project

On this GitHub page: click the green **Code** button → **Download ZIP**, then right-click the
downloaded ZIP → **Extract All**. Put the folder somewhere you will find it again, for example your
Desktop. (If you use Git, `git clone https://github.com/sourabhrajcodes/auto-type.git` does the
same thing.)

### Step 3 — Start the app

Open the folder and **double-click `start_auto_typer.bat`**. The Auto Typer window appears. No
console window, no installation, nothing to configure.

If a blue "Windows protected your PC" box appears, click **More info** → **Run anyway**. Windows
shows that for downloaded files it has not seen before.

If a window flashes and disappears instead, Python is not on your PATH — go back to Step 1. The
`.bat` file prints a message and waits in that case, so read what it says.

### Step 4 — Try it safely, in its own box

Before aiming it at a real website, prove it to yourself:

1. Paste something into the big text box (Ctrl+V works, or click **Paste clipboard**).
2. Leave **Speed** at 40 wpm and **Switch to target after** at 3 seconds.
3. Click **Start typing (F8)**, then click inside Auto Typer's own text box.
4. Watch it type. Press **F8** to stop, press **F8** again or click **Start** to resume from where
   it stopped.

There is also a practice page for web editors: open `tests/editor_sim.html` in Edge or Chrome. It
behaves like a code editor whose suggestions popup eats the Enter key, so you can see both the
problem and the fix without touching a real site.

### Step 5 — Type into another window

1. Paste the text you want typed.
2. Set the speed and tick the options you need ([section 5](#5-recommended-settings-for-online-code-editors)).
3. Click **Start typing (F8)**.
4. During the countdown ("Starting in 3 s…"), click into the target window and leave the mouse and
   keyboard alone until it finishes. Auto Typer types into whatever has focus — including the
   wrong window if you click one.
5. **F8** stops it at any time; **Esc** does the same while the Auto Typer window is focused.

---

## 3. Using the app

### What happens when you press Start

1. Your text is prepared (line endings normalised, tabs optionally turned into spaces) and a timed
   plan is built from the speed settings.
2. A countdown runs for the number of seconds in **Switch to target after** (0 = start immediately).
   This is your window to click the target.
3. The app types. Progress is shown as "Typing… 123 / 701 characters", with a progress bar and the
   already-typed part highlighted in the box.
4. Press **F8** (or **Esc** with the app focused) to stop. The status line then says
   "Stopped at 156 / 701 characters" and the button becomes **Resume typing (F8)** — pressing it
   continues from that character, not from the beginning. **Reset progress** forgets the stopping
   point and starts fresh.

### The window, area by area

| Area | What it is |
|------|------------|
| Big text box (top) | The text that will be typed. Editing it after a stop re-plans the run, so keep it unchanged if you want to resume |
| **Paste clipboard** | Replaces the box's contents with the Windows clipboard |
| **Clear** | Empties the box |
| **Speed** slider | 10–400 words per minute, in steps of 5. The label next to it shows the current value; the estimate on the right shows how long the whole text will take |
| **Style** | *Word by word* types each word as a quick burst with a pause between words; *Character by character* is an even pace |
| **Human-like rhythm** | Adds ±40 % variation and longer pauses after `. , ; : ! ?` and line breaks |
| **Switch to target after** | Countdown length in seconds (0–30) |
| **Tab = n spaces** | With this on, tabs in your pasted text are typed as spaces (recommended for code). With it off, a real Tab key is sent |
| **Web code editors** | Three options for online editors — see the next section |
| **Minimize while typing** | Hides the Auto Typer window as typing starts |
| **Keep on top** | Keeps the setup window above other windows while it is idle; it steps aside when typing starts so you can see the target |
| **Start / Stop / Resume** button | The same as pressing F8 |
| **Reset progress** | Forgets the stopping point of the previous run |
| Status line + bar | Character count, errors, and "Done" when the whole text has been typed |

### Keyboard shortcuts

| Key | Where it works | What it does |
|-----|----------------|--------------|
| **F8** | Anywhere, globally | Start, stop, cancel the countdown, or resume — same as the big button |
| **Esc** | While the Auto Typer window is focused | Stop typing |

---

## 4. All options explained

| Option | Default | What it does | When to change it |
|--------|---------|--------------|-------------------|
| **Speed** | 40 wpm | How fast characters are typed | 100–150 wpm feels "fast human". Above ~200 wpm Windows timing gets rough and some editors start dropping characters |
| **Word by word** / **Character by character** | Word by word | Bursts with pauses, or a steady stream | Character mode looks more like careful typing; word mode looks more like real human typing |
| **Human-like rhythm** | On | Random small delays plus longer stops at punctuation and line ends | Turn it off when you want the estimated time to be exact |
| **Switch to target after** | 3 s | Countdown before typing starts | Increase if you need time to position a window; set 0 when you are already focused |
| **Tab = 4 spaces** | On | Tabs in your text are typed as spaces | Keep it on for Python/YAML/code. Turn it off if the target treats Tab as "next field" |
| **Press Esc before each line break** | Off | Sends Esc, then Enter, for every new line | **Turn on** for any web editor / online IDE whose autocomplete popup accepts Enter as "use this suggestion" and swallows your line breaks |
| **Clear the editor's auto-indent after each line break** | Off | After every Enter, removes the indentation the editor inserted on the fresh line before typing your own | **Turn on** when the target editor auto-indents and your lines creep further to the right as it types |
| **Compatibility pacing** | Off | Slows the engine to a floor of 25 ms per key and 120 ms per line break | Turn on when characters go missing or appear out of order in a browser editor |
| **Minimize while typing** | Off | Hides the app when typing begins | Useful when the target is behind the app's window |
| **Keep on top** | On | Keeps the setup window above others while idle | Turn off if it gets in the way |

Text and every setting are saved to `settings.json` next to the program, so you keep both between
launches. Delete that file to go back to defaults.

---

## 5. Recommended settings for online code editors

Autocomplete and auto-indent are what usually break automated typing. These settings are the
result of testing against a page that imitates both behaviours (`tests/editor_sim.html`):

| Setting | Value |
|---------|-------|
| Speed | 100 wpm (drop to ~60 if the site is slow to react) |
| Style | Word by word |
| Human-like rhythm | On |
| Tab = 4 spaces | On |
| Press Esc before each line break | **On** |
| Clear the editor's auto-indent after each line break | **On** |
| Compatibility pacing | On if characters still go missing |

Two symptoms, two causes:

- **Lines run together, and junk like `SUGGEST` or a half-word appears where the line break should
  be.** The editor's autocomplete popup is open and treats Enter as "accept this suggestion".
  **Fix: tick "Press Esc before each line break".**
- **Indentation drifts further right on every line** (`if x:` → 4 spaces → 8 spaces → 12 spaces).
  The editor auto-indents each new line by copying the previous line's leading whitespace, and your
  own indentation is typed after it, so the two stack up.
  **Fix: tick "Clear the editor's auto-indent after each line break".**

The auto-indent fix works by normalising the fresh line instead of guessing the editor's rule: it
presses Home twice (column 0 in plain and "smart home" editors), Shift+End to select whatever the
editor inserted, then a space and a Backspace to remove it — the space keeps that Backspace safe, so
lines can never be merged. Only then is your line typed, exactly as pasted.

If the site offers its own "disable autocomplete / auto indent" switch, use it as well: that removes
the problem at the source.

---

## 6. Troubleshooting

**Nothing is typed at all.**
The target window must keep the keyboard focus. Start the run, click the target once during the
countdown, and then do not touch the mouse or keyboard until it finishes — clicking anywhere else
sends the rest of the text there. If you are typing into a browser, click inside the text area, not
just the page.

**Nothing is typed and the status says Windows blocked the keystroke.**
The target window is running as administrator (or a UAC prompt is on screen). Close the UAC prompt,
or run the target application normally. Auto Typer deliberately does not try to bypass this.

**Lines run together in a code editor or assessment site.**
Tick **Press Esc before each line break** (see [section 5](#5-recommended-settings-for-online-code-editors)).

**The indentation keeps moving to the right.**
Tick **Clear the editor's auto-indent after each line break** (see the same section). If it is still
off by the time the whole file is typed, stop the run, clear the target editor, press **Reset
progress**, and start again — resuming cannot repair lines that were already typed wrong.

**Characters are missing, doubled, or appear in the wrong order.**
Browser editors drop input that arrives too fast. Tick **Compatibility pacing** and lower the speed
to 100 wpm or less.

**A double-click on `start_auto_typer.bat` shows a black window instead of the app.**
Read the message in it: it tells you Python is missing from PATH. Re-run the Python installer,
choose *Modify*, and enable the PATH option.

**Windows shows "Windows protected your PC".**
Click **More info** → **Run anyway**. That warning appears for any downloaded script Windows has not
seen before.

**Double-clicking `auto_typer.pyw` does nothing, but the `.bat` file works.**
`.pyw` files are associated with Python only if the installer's default file associations were kept.
Keep using `start_auto_typer.bat`, which finds Python itself.

**It typed into the wrong window.**
Everything typed goes to whatever has focus. Use a longer **Switch to target after** countdown, and
**Minimize while typing** so the Auto Typer window is out of the way.

**An app-level shortcut fired while typing (something opened/closed).**
Letters are sent as ordinary keystrokes, so single-key tool shortcuts in the target app still fire.
There is no way to avoid that from the outside; type into a plain editor instead of a tool with
single-key shortcuts.

**It stops by itself, or refuses to start.**
Clicking another window, pressing a key, or a popup appearing can steal focus. Press **F8** to
resume. If the status bar shows an error, read it — it says what Windows refused.

**It will not run on an elevated window no matter what.**
That is Windows' UIPI rule: a normal process cannot send keystrokes to an elevated one. Run Auto
Typer as administrator too, if you really need that — but note that doing so makes Auto Typer itself
elevated.

---

## 7. How it works (the short technical version)

- Keystrokes are injected with the Win32 **`SendInput`** API in **Unicode mode**
  (`KEYEVENTF_UNICODE`), so any character can be typed exactly as written regardless of the active
  keyboard layout.
- Enter and Tab are sent as a **virtual key plus the real hardware scan code** (`0x1C`, `0x0F`) and
  Home/End as **extended** keys (`0x47`/`0x4F` with the `E0` flag). Browser editors derive
  `event.code` from the scan code, so these arrive looking exactly like a real keyboard.
- The **typing plan** (`engine.build_plan`) is a list of timed chunks: character mode gives every
  character a delay derived from 5 characters per word; word mode makes each word a fast burst with
  a pause after it; the "human-like" option multiplies delays by a random 0.6–1.5 and adds longer
  pauses after `., ; : ! ?` and line breaks. Stopping is polled before every character, so a stop is
  honoured within one keystroke.
- `SendInput` reports how many events it actually inserted; Auto Typer treats a short count as an
  error and tells you why, instead of silently typing into the void.
- Nothing is sent over the network, no text is stored anywhere except your own `settings.json`, and
  there are no third-party packages — only `tkinter`, `ctypes` and the standard library.

---

## 8. Verify it on your own PC (optional)

Open a terminal in this folder (`Shift + right-click` → *Open PowerShell window here*, or `cmd`) and
run these. They are also useful when you change the code.

```bash
# 1) Unit and UI tests - nothing is injected, ~2 seconds
py -m unittest discover -s tests -v

# 2) End-to-end: real keystrokes into its own focused window, verifies every character
py tests/e2e_selfcheck.py
py tests/e2e_selfcheck.py --esc --indent-fix

# 3) Browser check: opens a throwaway Edge/Chrome window and types with real keystrokes
py tests/browser_enter_check.py --case popup --strategy enter       # reproduces the swallowed Enter
py tests/browser_enter_check.py --case popup --strategy esc_enter   # verifies the Esc fix
py tests/browser_enter_check.py --case autoindent                   # reproduces the drifting indentation
py tests/browser_enter_check.py --case autoindent --indent-fix      # verifies the auto-indent fix
```

What the checks do and what they print:

- **Unit/UI tests** finish with `OK`. They cover the timing plan, stop/resume, the Win32 key events
  (every virtual key, scan code and flag is asserted, no keystroke is injected), settings handling
  and the window's state machine with the window hidden.
- **`e2e_selfcheck.py`** takes the keyboard focus for about two seconds, types a string containing a
  line break and non-ASCII characters into its own window and prints
  `PASS: N characters including 1 line break(s) injected via SendInput and verified`. Add `--esc`
  and/or `--indent-fix` to exercise the editor options. It refuses to type unless it can confirm its
  own window is in front, so it never leaks characters into another window — **do not touch the
  keyboard or mouse while it runs.**
- **`browser_enter_check.py`** opens its own throwaway browser window (with a temporary profile,
  closed afterwards), types, and prints both the page's content and a verdict such as
  `BUG REPRODUCED` (the bug being reproduced, exit code 0) or `PASS`.

Exit codes for the two end-to-end scripts: `0` passed / expected outcome, `1` failed, `3`
inconclusive (focus unavailable), `4` skipped (not Windows, or no browser found).

---

## 9. Project files

| File | Purpose |
|------|---------|
| `auto_typer.pyw` | The app: window, global F8 hotkey, settings, progress |
| `engine.py` | The typing engine: timing plan and the Win32 `SendInput` keyboard |
| `start_auto_typer.bat` | Double-click launcher (finds Python, starts without a console window) |
| `tests/test_engine.py` | Plan timing, stop/resume, Win32 struct layout, key and scan codes |
| `tests/test_app_settings.py` | Settings load/save/sanitising |
| `tests/test_ui_flow.py` | Hidden-window UI flow: progress, errors, resume, close-and-persist |
| `tests/e2e_selfcheck.py` | Injects real keystrokes into its own window and verifies them |
| `tests/browser_enter_check.py` | Drives a real browser window and reports what the page received |
| `tests/editor_sim.html` | The page used by that check: eats Enter, and auto-indents. Open it by hand to play |
| `settings.json` | Your text and preferences (created when you close the app; not in version control) |

---

## 10. Build a standalone .exe

If you want a single file that runs on a PC without Python:

```bash
py -m pip install pyinstaller
py -m PyInstaller --noconsole --onefile --name AutoTyper auto_typer.pyw
```

The result is `dist/AutoTyper.exe`. Antivirus tools sometimes flag freshly built, unsigned
keyboard-injecting executables; that is a false positive, but be aware of it before sharing the file.

---

## 11. FAQ

**Does it need the internet?**
No. Nothing is uploaded, downloaded or tracked.

**Does it use my clipboard?**
Only when you click **Paste clipboard**, and only to read text into the box. Typing itself never
touches the clipboard — that is the point, since clipboard-based tools fail wherever paste is
blocked.

**Can it type emoji and other languages?**
Yes. Characters go through Unicode injection, so 😀, नमस्ते, 你好 and accented letters all arrive
regardless of your keyboard layout.

**Can it type into games or remote desktops?**
Remote Desktop windows behave like normal windows. Games that use DirectInput or anti-cheat
protection usually ignore synthetic keystrokes — Auto Typer cannot change that.

**Will the website know it is automated?**
The keystrokes are indistinguishable from a keyboard's at the Windows level, but a website can still
notice extremely regular timing or a superhuman speed. Human-like rhythm and a moderate speed exist
for that reason. Use this where it is allowed (see below).

**Can I run several copies?**
Yes, but only one should be typing at a time — they all send keystrokes to the focused window.

**Why is it Windows-only?**
It uses the Windows `SendInput` API. macOS and Linux have similar APIs, but this project has not
implemented them.

---

## 12. Limitations and responsible use

**Limitations**

- Windows 10/11 only.
- Cannot type into elevated windows, the UAC prompt or the lock screen.
- High speeds (200+ wpm) are approximate: Windows timer granularity is around 15 ms.
- If the target application binds single letters to shortcuts, those shortcuts still fire.
- Auto Typer cannot see the result. It reports what it sent, not what the page kept — verify with a
  short run before typing a whole document.

**Use it responsibly.** This tool automates typing on your own computer. Some websites and
assessment platforms prohibit automated input in their terms of service, and using it there can
invalidate your results or get your account closed — check the rules of whatever you use it with.
Do not use Auto Typer to enter text you have no right to submit, and remember that it types into
whatever window is focused, so keep private windows closed while a run is active.

## License

MIT — see [LICENSE](LICENSE). Free to use, change and share, with no warranty.
