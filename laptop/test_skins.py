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

    def test_prompts(self):
        for basis in ("pet", "me", "character", "art", "idea"):
            text = node("prompt", basis)
            self.assertIn("standing on my desk next to my monitors.", text)
            self.assertIn("When I paste validation errors", text)
            self.assertIn("Making a Chip skin", text)          # the pack's own guide
            self.assertIn("wide -> open", text)                 # the pack's fallbacks
            self.assertIn("faceTop 128x26", text)               # the pack's skinSlots
            block = re.search(r"```json\n(.*?)\n```", text, re.S).group(1)
            self.assertTrue(check(block)["ok"])                 # the example inside the prompt passes
        with self.assertRaises(RuntimeError):
            node("prompt", "nope")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
