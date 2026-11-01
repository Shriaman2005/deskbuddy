#!/usr/bin/env python3
"""Tests for laptop/skin.js: the example passes, broken skins fail with the expected path and a fix.
Run: python3 -I laptop/test_skins.py"""
import copy
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKIN = os.path.join(HERE, "skin.js")


def node(*args, stdin=b""):
    done = subprocess.run(["node", SKIN, *args], input=stdin, capture_output=True, timeout=10)
    if done.returncode:
        raise RuntimeError(done.stderr.decode())
    return done.stdout.decode()


def check(skin):
    """Report for a dict, or for raw text/bytes."""
    raw = skin if isinstance(skin, (str, bytes)) else json.dumps(skin)
    return json.loads(node("check", "-", stdin=raw.encode() if isinstance(raw, str) else raw))


EXAMPLE = json.loads(node("example"))
PACK = json.load(open(os.path.join(HERE, "..", "phone", "www", "pack.json")))
DEADPOOL = os.path.expanduser("~/.config/deskbuddy/skins/deadpool-mask.json")
FIT_WARNINGS = ("cover the inside of the eyes", "don't sit on the ears", "look flat")   # the headphones-fit warnings


def chip_skin():
    """Chip's own default eyes and headphones from the pack, as a skin. The pack stores ragged rows (pack.js pads them),
    and its eyeR is drawn on a 42x49 grid, over the eye slot: so rows are padded and the right side mirrors the left."""
    style = PACK["eyes"]["styles"][PACK["eyes"]["default"]]
    names, width = style["sprites"], PACK["skinSlots"]["eye"][0]

    def padded(name, w=0):
        sp = copy.deepcopy(PACK["sprites"][name])
        sp["frames"] = {k: [r.ljust(max(w, *map(len, rows)), ".") for r in rows] for k, rows in sp["frames"].items()}
        return sp
    return {
        "format": "chip-skin/1", "id": "chip-own", "name": "Chip", "accent": None,
        "sprites": {names["eyeL"]: padded(names["eyeL"], width), "eyeR": {"mirror": names["eyeL"]},
                    names["frontL"]: padded(names["frontL"], width), names["frontR"]: {"mirror": names["frontL"]},
                    names["pupilL"]: padded(names["pupilL"]), "headphones": padded("headphones")},
        "eyes": {**style, "sprites": {**names, "eyeR": "eyeR"},
                 "frames": {k: {a: b for a, b in v.items() if a != "boxR"} for k, v in style["frames"].items()}},
        "headphones": "headphones",
    }


def fit_warnings(report):
    return [w for w in report["warnings"] if any(t in w["problem"] for t in FIT_WARNINGS)]


def variant(change):
    skin = copy.deepcopy(EXAMPLE)
    change(skin)
    return skin


class SkinTests(unittest.TestCase):
    def failing(self, skin, path, *words):
        r = check(skin)
        self.assertFalse(r["ok"], r["message"])
        hits = [e for e in r["errors"] if e["path"] == path]
        self.assertTrue(hits, f"no error at {path}; got {[e['path'] for e in r['errors']]}")
        for e in hits:
            self.assertTrue(e["problem"] and e["fix"], e)
        for w in words:
            self.assertIn(w, " ".join(e["problem"] + " " + e["fix"] for e in hits))
        self.assertTrue(r["message"].startswith("Your Chip skin didn't pass the check. Fix exactly these problems, keep everything else, and send the complete JSON again:\n1. "))
        return r

    def test_example_passes(self):
        r = check(EXAMPLE)
        self.assertTrue(r["ok"], r["message"])
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["skin"]["id"], "example")

    def test_example_pretty_text_passes(self):
        self.assertTrue(check(node("example"))["ok"])

    def test_fenced_reply_passes(self):
        text = "Here is your skin!\n```json\n" + node("example") + "```\nEnjoy."
        self.assertTrue(check(text)["ok"])

    def test_row_length(self):
        def change(s):
            s["sprites"]["eyeL"]["frames"]["open"][3] += "."
            s["sprites"]["eyeL"]["frames"]["open"][4] += "."
            s["sprites"]["eyeL"]["frames"]["open"][9] = s["sprites"]["eyeL"]["frames"]["open"][9][:-1]
        r = self.failing(variant(change), "$.sprites.eyeL.frames.open", "rows 3 and 4", "13 characters", "the other rows have 12")
        self.assertEqual(len([e for e in r["errors"] if e["path"] == "$.sprites.eyeL.frames.open"]), 2)  # grouped per length

    def test_unknown_char(self):
        def change(s):
            rows = s["sprites"]["eyeL"]["frames"]["open"]
            rows[2] = "#####z######"
        self.failing(variant(change), "$.sprites.eyeL.frames.open", '"z"', "not in \"keys\"")

    def test_oversize_sprite(self):
        def change(s):
            for f, rows in s["sprites"]["eyeL"]["frames"].items():
                s["sprites"]["eyeL"]["frames"][f] = [r + "." * 32 for r in rows]
        self.failing(variant(change), "$.sprites.eyeL", "44x14", "at most 40x48")

    def test_missing_open_frame(self):
        self.failing(variant(lambda s: s["sprites"]["eyeL"]["frames"].pop("open")), "$.sprites.eyeL.frames.open", '"open"')

    def test_missing_open_style_frame(self):
        self.failing(variant(lambda s: s["eyes"]["frames"].pop("open")), "$.eyes.frames.open", "required")

    def test_bad_id(self):
        self.failing(variant(lambda s: s.update(id="Bad ID")), "$.id", "lowercase")

    def test_reserved_id(self):
        self.failing(variant(lambda s: s.update(id="draft")), "$.id", "reserved")

    def test_proto_key(self):
        text = json.dumps(EXAMPLE).replace('"sprites": {', '"sprites": {"__proto__": {"x": 1}, ', 1)
        self.failing(text, "$.sprites.__proto__", "not allowed")

    def test_constructor_key_anywhere(self):
        def change(s):
            s["eyes"]["frames"]["open"]["constructor"] = 1
        self.failing(variant(change), "$.eyes.frames.open.constructor", "not allowed")

    def test_pupil_leaves_eye(self):
        def change(s):
            s["eyes"]["frames"]["open"]["box"] = [0, 0, 11, 13]
        r = self.failing(variant(change), "$.eyes.frames.open.box", "sticks out of the eye", "shrink the box to [")
        # the suggested box really fixes it
        box = json.loads(re.search(r"shrink the box to (\[[^\]]*\])", [e for e in r["errors"] if e["path"].endswith("open.box")][0]["fix"]).group(1))
        self.assertTrue(check(variant(lambda s: s["eyes"]["frames"]["open"].update(box=box)))["ok"])

    def test_pupil_under_front_is_fine(self):
        def notched(s, front):   # the top two rows of the eye are empty; the pupil reaches them at the top of its box
            s["sprites"]["eyeL"]["frames"]["open"][0:2] = ["." * 12] * 2
            s["eyes"]["frames"]["open"]["box"] = [4, 3, 7, 9]
            if front:
                s["sprites"]["front"] = {"keys": {"x": "eyelid"}, "anchor": [6, 7], "frames": {"open": ["x" * 12] * 14}}
                s["sprites"]["frontR"] = {"mirror": "front"}
                s["eyes"]["sprites"].update(frontL="front", frontR="frontR")
        self.failing(variant(lambda s: notched(s, False)), "$.eyes.frames.open.box")
        r = check(variant(lambda s: notched(s, True)))
        self.assertTrue(r["ok"], r["message"])

    def test_front_anchor_must_match_eye(self):
        def change(s):
            s["sprites"]["front"] = {"keys": {"x": "eyelid"}, "anchor": [0, 0], "frames": {"open": ["x" * 12] * 14}}
            s["eyes"]["sprites"].update(frontL="front", frontR="front")
        r = self.failing(variant(change), "$.sprites.front.anchor", "[6,7]")

    def test_invalid_json(self):
        text = '{\n  "format": "chip-skin/1",\n  "id": "x",\n}\n'
        r = self.failing(text, "$", "line 4")
        self.assertIn("column", r["errors"][0]["problem"])

    def test_empty_and_not_object(self):
        self.failing("", "$", "empty")
        self.failing("[1, 2]", "$", "single object")

    def test_oversize_file(self):
        self.failing(variant(lambda s: s.update(blurb="x" * 700_000)), "$", "KB")

    def test_mirror_errors(self):
        self.failing(variant(lambda s: s["sprites"]["eyeR"].update(mirror="nope")), "$.sprites.eyeR.mirror", "no sprite")
        def loop(s):
            s["sprites"]["a1"] = {"mirror": "a2"}
            s["sprites"]["a2"] = {"mirror": "a1"}
        self.failing(variant(loop), "$.sprites.a1.mirror", "loops")

    def test_colour_names_and_keys(self):
        self.failing(variant(lambda s: s["colors"].update(main="#ffffff")), "$.colors.main", "built-in")
        self.failing(variant(lambda s: s["sprites"]["eyeL"]["keys"].update({"#": "nope"})), "$.sprites.eyeL.keys[\"#\"]", "neither")
        self.failing(variant(lambda s: s["sprites"]["eyeL"]["keys"].update({".": "main"})), "$.sprites.eyeL.keys[\".\"]", "reserved")

    def test_anchor_outside(self):
        self.failing(variant(lambda s: s["sprites"]["eyeL"].update(anchor=[12, 7])), "$.sprites.eyeL.anchor", "outside")

    def test_format_and_glow(self):
        self.failing(variant(lambda s: s.update(format="chip-skin/2")), "$.format")
        self.failing(variant(lambda s: s["sprites"]["eyeL"].update(glow=2)), "$.sprites.eyeL.glow", "0 to 1")

    def test_limits(self):
        def many(s):
            for i in range(41):
                s["sprites"][f"x{i}"] = {"mirror": "eyeL"}
        self.failing(variant(many), "$.sprites", "limit is 40")
        self.failing(variant(lambda s: s.update(colors={f"c{i}": "#000000" for i in range(13)})), "$.colors", "limit is 12")

    def test_missing_mouth_neutral(self):
        self.failing(variant(lambda s: s["sprites"]["mouth"]["frames"].update(happy=s["sprites"]["mouth"]["frames"].pop("neutral"))),
                     "$.sprites.mouth.frames.neutral", "neutral")

    def test_unknown_fields_warn(self):
        r = check(variant(lambda s: s.update(sparkle=True)))
        self.assertTrue(r["ok"])
        self.assertTrue(any(w["path"] == "$" and "sparkle" in w["problem"] for w in r["warnings"]))

    def test_accent_clamp_warning(self):
        r = check(variant(lambda s: s.update(accent="#ffffff")))
        self.assertTrue(r["ok"])
        w = [w for w in r["warnings"] if w["path"] == "$.accent"]
        self.assertTrue(w and "will show as #" in w[0]["problem"], r["warnings"])

    def test_at_most_25_entries(self):
        def change(s):
            for i in range(40):
                s["sprites"][f"s{i}"] = {"keys": {"#": "main"}, "anchor": [0, 0], "frames": {"a": ["#", "##"], "b": ["#", "##"]}}
        r = check(variant(change))
        self.assertLessEqual(len(r["errors"]), 25)
        self.assertGreater(r["omitted"], 0)

    def test_headphones_slot(self):
        band = ["#" * 21] + ["#" + "." * 19 + "#"] * 6
        def ok(s):
            s["sprites"]["phones"] = {"keys": {"#": "main"}, "anchor": [10, 6], "frames": {"on": band}}
            s["headphones"] = "phones"
        r = check(variant(ok))
        self.assertTrue(r["ok"], r)
        self.assertFalse([w for w in r["warnings"] if "phones" in w["path"] and w not in fit_warnings(r)], r["warnings"])
        def off_centre(s):
            ok(s); s["sprites"]["phones"]["anchor"] = [3, 6]
        r = check(variant(off_centre))
        self.assertTrue(r["ok"])
        self.assertTrue(any("middle column" in w["fix"] for w in r["warnings"]), r["warnings"])
        def lopsided(s):
            ok(s); s["sprites"]["phones"]["frames"]["on"] = ["#" * 21] + ["##" + "." * 19] * 6
        self.assertTrue(any("same shape left and right" in w["problem"] for w in check(variant(lopsided))["warnings"]))
        def too_big(s):
            ok(s); s["sprites"]["phones"]["frames"]["on"] = ["#" * 21] * 80
        self.assertFalse(check(variant(too_big))["ok"])
        def missing(s):
            s["headphones"] = "nope"
        self.assertFalse(check(variant(missing))["ok"])

    def test_chip_headphones_fit(self):
        r = check(chip_skin())
        self.assertTrue(r["ok"], r["message"])
        self.assertEqual(fit_warnings(r), [])

    def headphones_variant(self, change):
        skin = chip_skin()
        hp = skin["sprites"]["headphones"]
        ax, ay = hp["anchor"]
        rows = [list(r) for r in hp["frames"]["on"]]
        change(rows, ax, ay)
        hp["frames"]["on"] = ["".join(r) for r in rows]
        r = check(skin)
        self.assertTrue(r["ok"], r["message"])       # warnings only: an installed skin keeps working
        return r

    def assertFit(self, r, text, path, *words):
        hits = [w for w in r["warnings"] if text in w["problem"]]
        self.assertEqual(len(hits), 1, r["warnings"])
        self.assertEqual(hits[0]["path"], path)
        self.assertTrue(hits[0]["fix"])
        for w in words:
            self.assertIn(w, hits[0]["problem"] + " " + hits[0]["fix"])
        self.assertEqual(len(fit_warnings(r)), 1, fit_warnings(r))   # only this one fires

    def test_headphones_cover_eyes(self):
        def bar(rows, ax, ay):   # a strap across both eyes at eye level
            for y in range(ay - 9, ay - 4):
                for x in range(ax - 46, ax + 47):
                    if abs(x - ax) >= 20:
                        rows[y][x] = "p"
        r = self.headphones_variant(bar)
        self.assertFit(r, "cover the inside of the eyes", "$.sprites.headphones.frames.on", "(-33,-7)", "1 px outline")

    def test_headphones_miss_ears(self):
        def no_cups(rows, ax, ay):   # band only: nothing beyond |x| 40
            for r in rows:
                for x in range(len(r)):
                    if abs(x - ax) > 40:
                        r[x] = "."
        r = self.headphones_variant(no_cups)
        self.assertFit(r, "don't sit on the ears", "$.sprites.headphones.frames.on", "either side", "x -50 and 50")

    def test_headphones_flat(self):
        def two_tones(rows, ax, ay):
            for r in rows:
                for x, c in enumerate(r):
                    if c != ".":
                        r[x] = "D" if c == "D" else "p"
        r = self.headphones_variant(two_tones)
        self.assertFit(r, "look flat", "$.sprites.headphones.keys", "only 2 colours", "3 tones")

    @unittest.skipUnless(os.path.exists(DEADPOOL), "deadpool-mask.json isn't installed")
    def test_installed_deadpool_no_fit_warnings(self):
        with open(DEADPOOL, "rb") as f:
            r = check(f.read())
        self.assertTrue(r["ok"], r["message"])
        self.assertEqual(fit_warnings(r), [])

    def test_pupil_sizes_warn(self):
        def two(s):
            s["eyes"]["pupils"] = ["S", "M"]
        r = check(variant(two))
        self.assertTrue(r["ok"])
        self.assertTrue(any("changes nothing" in w["problem"] for w in r["warnings"]), r["warnings"])

    def test_prompt(self):
        text = node("prompt")
        self.assertIn("phones and tablets", text)              # the screens it must obey
        self.assertIn("320 x 180", text)
        self.assertIn("Don't make the head round", text)       # the subject's own shape, not a round default
        self.assertIn("If I paste validation errors back", text)
        self.assertIn("Making a Chip skin", text)              # the pack's own guide
        self.assertIn("wide -> open", text)                    # the pack's fallbacks
        self.assertIn("faceTop 128x26", text)                  # the pack's skinSlots
        self.assertIn("headphones 128x72", text)
        ref = text.index("Reference: how Chip's own headphones are drawn")   # design/headphones.js, read at prompt time
        code = re.search(r"```js\n(.*?)\n```", text[ref:], re.S).group(1)
        with open(os.path.join(HERE, "..", "design", "headphones.js")) as f:
            self.assertIn(code.split("\n")[-2], f.read())               # its own code, not a copy
        self.assertIn("between two ellipses", code)
        self.assertNotIn("--write", code)
        self.assertNotIn("pack.json", code)
        for n in ["(-33, -7) and (33, -7)", "40x48", "from -16 to 24 px", "cups span x 51..63", "y -33"]:
            self.assertIn(n, text[ref:])
        block = re.search(r"```json\n(.*?)\n```", text, re.S).group(1)
        self.assertTrue(check(block)["ok"])                    # the example inside the prompt passes


class DeleteResetTests(unittest.TestCase):
    """Deleting an installed skin puts "skin" and "phonesDefault" back when they pointed at it (bridge.Skins.delete,
    against a temp skins folder and a stand-in settings object; nothing real is touched)."""

    def test_delete_resets_settings_that_point_at_it(self):
        import tempfile
        sys.path.insert(0, HERE)
        import bridge

        class Fake:
            def __init__(self, **v): self.v = {"skin": "", "phonesDefault": "", **v}
            def get(self): return dict(self.v)
            def update(self, ch): self.v.update(ch)

        real = (bridge.SKINS_DIR, bridge.settings)
        with tempfile.TemporaryDirectory() as d:
            bridge.SKINS_DIR = d
            try:
                for sid in ("aa-one", "bb-two"):
                    with open(os.path.join(d, sid + ".json"), "w") as f:
                        f.write("{}")
                bridge.settings = Fake(skin="aa-one", phonesDefault="bb-two")
                self.assertTrue(bridge.skins.delete("bb-two"))
                self.assertEqual(bridge.settings.v, {"skin": "aa-one", "phonesDefault": ""})   # only what pointed at it
                bridge.settings = Fake(skin="bb-two", phonesDefault="aa-one")
                self.assertTrue(bridge.skins.delete("aa-one"))
                self.assertEqual(bridge.settings.v, {"skin": "bb-two", "phonesDefault": ""})
                self.assertFalse(bridge.skins.delete("aa-one"))                                 # already gone
            finally:
                bridge.SKINS_DIR, bridge.settings = real


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
