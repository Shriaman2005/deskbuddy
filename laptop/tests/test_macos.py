#!/usr/bin/env python3
"""macOS backend checks that need no permissions (CI's macos job): the frameworks load through ctypes, keyboard
events carry exactly the text's UTF-16 units (set, then read back with CGEventKeyboardGetUnicodeString) in runs of
at most 20 without splitting a surrogate pair or carrying a modifier, idle_ms is a number, locked a bool, the
caps and stats are there, and without Accessibility type_text refuses with the message the phone shows.
Nothing is posted: real typing needs Accessibility, which only a person can give (the friend test).
Run: python3 -I laptop/tests/test_macos.py   (exit 0 = passed, 1 = a check failed, 77 = not macOS)"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # laptop/
from platforms import macos  # noqa: E402
from textclean import typable, utf16_units  # noqa: E402

MODIFIERS = 0x00FF0000  # caps lock, shift, control, option, command, help, fn
checks = []


def check(name, ok, detail=""):
    checks.append({"name": name, "ok": bool(ok), **({"detail": detail} if not ok else {})})
    return ok


def read_back(text):
    """[(down units, up units, down flags)] for the key events type_text would post for text."""
    cg = macos._libs()[0]
    events = macos.key_events(utf16_units(text))
    try:
        return [(macos.unicode_of(d), macos.unicode_of(u), cg.CGEventGetFlags(d) | cg.CGEventGetFlags(u))
                for d, u in events]
    finally:
        macos.release_events(events)


def main():
    if sys.platform != "darwin":
        print("not macOS: skipped")
        return 77
    if not check("CoreGraphics, CoreFoundation and ApplicationServices load", macos._libs() is not None):
        return report()

    samples = {
        "ascii": "Hello there, Chip",
        "accents + emoji": "héllo wörld 😀 ça va",
        "Hindi": "नमस्ते दुनिया",
        "Japanese": "こんにちは世界",
        "long, emoji on a 20-unit edge": "a" * 19 + "😀" + "b" * 45 + "👍🏽" * 7,
    }
    for name, text in samples.items():
        text = typable(text) + " "
        got = read_back(text)
        units = [u for d, _, _ in got for u in d]
        check(f"{name}: read back equals the text", units == utf16_units(text), [d for d, _, _ in got])
        check(f"{name}: key up carries what key down does", all(d == u for d, u, _ in got))
        check(f"{name}: at most 20 units per event", all(0 < len(d) <= macos.CHUNK for d, _, _ in got),
              [len(d) for d, _, _ in got])
        check(f"{name}: no surrogate pair split", all(not 0xD800 <= d[-1] <= 0xDBFF for d, _, _ in got))
        check(f"{name}: no modifier flags", all(not f & MODIFIERS for _, _, f in got), [hex(f) for _, _, f in got])
    check("never Enter, Tab or control keys", typable("a\nb\tc\r\n\x08d\x1b") == "a b c d")

    idle = macos.idle_ms()
    check("idle_ms is a number", isinstance(idle, int) and idle >= 0, idle)
    is_locked = macos.locked()
    check("locked is a bool", isinstance(is_locked, bool), is_locked)
    trusted = macos.trusted()
    check("trusted() answers without a prompt", isinstance(trusted, bool), trusted)
    caps = macos.caps()
    check("caps stats, idle, locked, typing", all(caps[k] for k in ("stats", "idle", "locked", "typing")), caps)
    s = macos.Sampler()
    s.sample()
    st = s.sample()
    check("stats: ram, uptime, disk, load", isinstance(st["ram"], int) and isinstance(st["uptime"], int)
          and isinstance(st["disk"], int) and isinstance(st["load"], list) and len(st["load"]) == 3,
          {k: st[k] for k in ("ram", "uptime", "disk", "load")})

    if not trusted:  # nothing would be typed: the refusal the phone shows (no prompt: it's marked as already asked)
        macos._asked.set()
        try:
            macos.type_text("x")
            check("without Accessibility type_text refuses", False, "it typed")
        except macos.TypingError as e:
            want = "locked" if is_locked else "accessibility"
            check(f"without Accessibility type_text refuses ({want})", e.code == want and str(e), f"{e.code}: {e}")
    return report(idle=idle, locked=is_locked, trusted=trusted, caps=caps)


def report(**info):
    failed = [c["name"] for c in checks if not c["ok"]]
    print(json.dumps({"ok": not failed, **info, "failed": failed, "checks": checks}, indent=1, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
