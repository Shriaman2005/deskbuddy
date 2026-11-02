#!/usr/bin/env python3
"""Tests for laptop/skin.js: the example passes, broken skins fail with the expected path and a fix.
Run: python3 -I laptop/test_skins.py"""
import copy
import http.client
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
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
sys.path.insert(0, HERE)  # python -I skips the script's folder
from platforms import paths  # noqa: E402
DEADPOOL = paths.config("skins", "deadpool-mask.json")
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


def make_pair(skin_id, cx, cup_in, yc, top, bottom=4, thick=6, prefix="hp"):
    """A small hand-made chip-phones/1: a band (the ring between two ellipses) and two cups, four colours of its own."""
    b = yc - top
    rows = [["."] * (2 * cx + 1) for _ in range(bottom - top + 1)]

    def put(x, y, c):
        rows[y - top][cx + x] = c
        rows[y - top][cx - x] = c
    for y in range(top, yc + 1):
        for x in range(cx + 1):
            o, i = math.hypot(x / cx, (y - yc) / b), math.hypot(x / (cx - thick), (y - yc) / (b - thick))
            if o <= 1 <= i:
                d = (1 - o) / ((1 - o) + (i - 1))
                put(x, y, "D" if d < 0.2 or d > 0.8 else "L" if d < 0.4 else "p")
    for y in range(yc - 2, bottom + 1):
        for x in range(cup_in, cx + 1):
            put(x, y, "D" if x in (cup_in, cx) or y in (yc - 2, bottom) else "c" if x < cup_in + 3 else "L" if x == cx - 1 else "p")
    n = lambda t: prefix + t
    return {"format": "chip-phones/1", "from": skin_id,
            "colors": {n("Edge"): "#15171c", n("Band"): "#444a58", n("Hi"): "#9aa3b5", n("Foam"): "#2b2f3a"},
            "sprites": {n("Pair"): {"keys": {"D": n("Edge"), "p": n("Band"), "L": n("Hi"), "c": n("Foam")}, "anchor": [cx, -top],
                                    "frames": {"on": ["".join(r) for r in rows]}}},
            "headphones": n("Pair")}


def host_skin():
    """An installed-skin stand-in with no headphones: the example (square eyes at x -39..-28 / 28..39) with a colour of its
    own and a 60x40 face plate (anchor 30,20), so the pair has a head to fit."""
    skin = copy.deepcopy(EXAMPLE)
    skin["id"], skin["name"] = "host-skin", "Host"
    skin["colors"]["mochi"] = "#aa5533"
    skin["sprites"]["facePlate"] = {"keys": {"#": "mochi"}, "anchor": [30, 20], "frames": {"on": ["#" * 60] * 40}}
    skin["faceBase"] = "facePlate"
    return skin


def good_pair(skin_id="host-skin"):
    return make_pair(skin_id, cx=48, cup_in=40, yc=-20, top=-50)


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


class PhonesTests(unittest.TestCase):
    """node laptop/skin.js prompt-phones / check-phones: headphones made for an installed skin."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def skin_file(self, skin=None):
        path = os.path.join(self.dir.name, "skin.json")
        with open(path, "w") as f:
            json.dump(skin or host_skin(), f)
        return path

    def phones(self, pair, skin=None, *flags):
        return json.loads(node("check-phones", self.skin_file(skin), "-", *flags, stdin=json.dumps(pair).encode()))

    def test_prompt_has_the_skins_colours_and_face(self):
        text = node("prompt-phones", self.skin_file())
        for want in ["chip-phones/1", '"host-skin"', "mochi: #aa5533", "snow: #f4f4ff", "Room left: 10 new colours",
                     'faceBase: sprite "facePlate", 60x40 px, anchor [30,20]', "  0 " + "#" * 60, " 39 " + "#" * 60,
                     "Start every new name with \"hp\"", "Reference: how Chip's own headphones are drawn", "between two ellipses"]:
            self.assertIn(want, text)
        self.assertNotIn("--write", text)
        # the headphones rules are the same paragraph the skin prompt gives (one shared function, not a copy)
        rules = next(l for l in node("prompt").split("\n") if l.startswith('Headphones, "headphones"'))
        self.assertIn(rules, text)
        self.assertIn("never on the eyes", text)

    def test_prompt_without_a_face_plate_says_so(self):
        def bare(s):
            del s["faceBase"], s["sprites"]["facePlate"]
        text = node("prompt-phones", self.skin_file(variant_of(host_skin(), bare)))
        self.assertIn("has no face plate: the eyes are the face", text)
        self.assertNotIn("faceBase: sprite", text)

    def test_good_pair_passes(self):
        r = self.phones(good_pair())
        self.assertTrue(r["ok"], r["message"])
        self.assertEqual((r["errors"], r["warnings"]), ([], []))     # and none of the skin's own notes (undrawn eye looks...)
        self.assertEqual(r["message"], "Your headphones passed the check.")
        r = self.phones(good_pair(), None, "--clean")
        merged = json.loads(r["clean"])
        self.assertEqual(merged["headphones"], "hpPair")
        self.assertIn("hpEdge", merged["colors"])
        self.assertIn("mochi", merged["colors"])                     # the skin's own are kept
        self.assertEqual(r["phones"]["from"], "host-skin")
        self.assertTrue(check(r["clean"])["ok"])                     # what gets stored is a skin that passes on its own
        self.assertTrue(self.phones(variant_of(good_pair(), lambda p: p.pop("from")))["ok"])   # "from" is optional

    def test_fenced_reply_passes(self):
        text = "Here you go!\n```json\n" + json.dumps(good_pair()) + "\n```\nEnjoy."
        r = json.loads(node("check-phones", self.skin_file(), "-", stdin=text.encode()))
        self.assertTrue(r["ok"], r["message"])

    def test_bad_pair_is_reported_in_the_skin_checks_words(self):
        def squash(p):
            p["sprites"]["hpPair"]["frames"]["on"][3] += "."
        r = self.phones(variant_of(good_pair(), squash))
        self.assertFalse(r["ok"])
        self.assertTrue(r["message"].startswith("Your headphones didn't pass the check. Fix exactly these problems, keep everything else, and send the complete chip-phones/1 JSON again:\n1. "))
        self.assertEqual(r["errors"][0]["path"], "$.sprites.hpPair.frames.on")

    def test_name_clash_says_which_and_how_to_rename(self):
        def clash(p):
            p["colors"]["mochi"] = "#000001"
            p["sprites"]["facePlate"] = copy.deepcopy(p["sprites"]["hpPair"])
        r = self.phones(variant_of(good_pair(), clash))
        self.assertFalse(r["ok"])
        paths = {e["path"]: e for e in r["errors"]}
        self.assertIn("$.colors.mochi", paths)
        self.assertIn("$.sprites.facePlate", paths)
        self.assertIn('"mochi" is already one of this skin\'s colours', paths["$.colors.mochi"]["problem"])
        self.assertIn('"hpMochi"', paths["$.colors.mochi"]["fix"])
        self.assertIn('"hpFacePlate"', paths["$.sprites.facePlate"]["fix"])

    def test_limits(self):
        def many_colours(p):
            p["colors"] = {f"hp{i}": "#%06x" % (i + 1) for i in range(12)}
        r = self.phones(variant_of(good_pair(), many_colours))
        self.assertFalse(r["ok"])
        e = next(e for e in r["errors"] if e["path"] == "$.colors")
        self.assertIn("over the 12-colour limit", e["problem"])
        self.assertIn("add at most 10", e["fix"])           # the skin has 2 (snow, mochi)

        def many_sprites(p):
            p["sprites"].update({f"hpM{i}": {"mirror": "hpPair"} for i in range(40)})
        r = self.phones(variant_of(good_pair(), many_sprites))
        e = next(e for e in r["errors"] if e["path"] == "$.sprites")
        self.assertIn("over the 40-sprite limit", e["problem"])
        self.assertIn("add at most 35", e["fix"])           # the skin has 5 (eyeL, eyeR, pupil, mouth, facePlate)

    def test_structure(self):
        for change, path in [(lambda p: p.update(format="chip-skin/1"), "$.format"),
                             (lambda p: p.update(headphones="nope"), "$.headphones"),
                             (lambda p: p.update(sprites={}), "$.sprites")]:
            r = self.phones(variant_of(good_pair(), change))
            self.assertFalse(r["ok"])
            self.assertIn(path, [e["path"] for e in r["errors"]])

        def outside_mirror(p):
            p["sprites"]["hpR"] = {"mirror": "eyeL"}          # eyeL belongs to the skin: the pair must be self-contained
        r = self.phones(variant_of(good_pair(), outside_mirror))
        self.assertIn("$.sprites.hpR.mirror", [e["path"] for e in r["errors"]])

    def test_existing_pair_needs_replace(self):
        merged = json.loads(self.phones(good_pair(), None, "--clean")["clean"])
        again = make_pair("host-skin", 48, 40, -20, -50, prefix="hq")
        r = self.phones(again, merged)
        self.assertFalse(r["ok"])
        self.assertEqual([e["path"] for e in r["errors"]], ["$.headphones"])            # only that, not the clashes it would cause
        self.assertIn("already has headphones", r["errors"][0]["problem"])
        r = self.phones(again, merged, "--replace", "--clean")
        self.assertTrue(r["ok"], r["message"])
        out = json.loads(r["clean"])
        self.assertEqual(out["headphones"], "hqPair")
        self.assertNotIn("hpPair", out["sprites"])                                       # the old pair is gone...
        self.assertNotIn("hpEdge", out["colors"])                                        # ...with the colours only it used
        # the same names again are fine when replacing: they were the old pair's
        self.assertTrue(self.phones(good_pair(), merged, "--replace")["ok"])

    def test_flat_pair_is_a_note_not_an_error(self):
        def flat(p):
            p["sprites"]["hpPair"]["keys"] = {k: ("hpEdge" if k == "D" else "hpBand") for k in "DpLc"}
        r = self.phones(variant_of(good_pair(), flat))
        self.assertTrue(r["ok"], r["message"])
        self.assertTrue(any("look flat" in w["problem"] for w in r["warnings"]), r["warnings"])


def variant_of(obj, change):
    obj = copy.deepcopy(obj)
    change(obj)
    return obj


class HeadphonesHttpTests(unittest.TestCase):
    """The bridge routes for headphones: dashboard only, and check -> draft -> install against a temp skins folder."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, HERE)
        import bridge
        cls.bridge = bridge
        cls.dir = tempfile.TemporaryDirectory()
        cls.real = bridge.SKINS_DIR
        bridge.SKINS_DIR = cls.dir.name
        cls.server = bridge.ThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.bridge.SKINS_DIR = cls.real
        cls.dir.cleanup()

    def setUp(self):
        self.path = os.path.join(self.dir.name, "host-skin.json")
        with open(self.path, "w") as f:
            json.dump(host_skin(), f, separators=(",", ":"))
        with open(self.path) as f:
            self.before = f.read()
        self.addCleanup(lambda: [os.remove(os.path.join(self.dir.name, n)) for n in os.listdir(self.dir.name)])

    def call(self, method, url, body=None, origin="http://127.0.0.1:8765"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        headers = {"Host": "127.0.0.1:8765"}     # the bridge's own host name (it refuses others)
        if origin is not None:
            headers["Origin"] = origin
        conn.request(method, url, body=body, headers=headers)
        r = conn.getresponse()
        data = r.read().decode()
        conn.close()
        return r.status, data

    def test_only_the_dashboard_may_use_the_routes(self):
        pair = json.dumps(good_pair())
        for origin in ("http://127.0.0.1:8080", "http://localhost:8765", None):      # the phone's page, another name, no Origin
            for url, body in (("/skins/host-skin/headphones/check", pair), ("/skins/host-skin/headphones/install", None)):
                status, data = self.call("POST", url, body, origin)
                self.assertEqual(status, 403, (origin, url, data))
        status, _ = self.call("GET", "/skins/host-skin/phones-prompt", origin="http://127.0.0.1:8080")
        self.assertEqual(status, 403)
        status, _ = self.call("GET", "/skins/host-skin/with-headphones.json", origin="http://127.0.0.1:8080")
        self.assertEqual(status, 403)
        self.assertFalse(os.path.exists(self.bridge.skins.phones_draft_path("host-skin")))   # nothing was kept
        with open(self.path) as f:
            self.assertEqual(f.read(), self.before)

    def test_install_with_a_wrong_origin_leaves_the_skin_alone(self):
        status, data = self.call("POST", "/skins/host-skin/headphones/check", json.dumps(good_pair()))
        self.assertEqual(status, 200, data)
        self.assertTrue(json.loads(data)["ok"])
        self.assertTrue(os.path.exists(self.bridge.skins.phones_draft_path("host-skin")))   # a pass is kept as the draft
        for origin in ("http://127.0.0.1:8080", None, "http://evil.example"):
            status, _ = self.call("POST", "/skins/host-skin/headphones/install", origin=origin)
            self.assertEqual(status, 403, origin)
        with open(self.path) as f:
            self.assertEqual(f.read(), self.before)                                          # not merged

    def test_check_preview_install(self):
        status, data = self.call("GET", "/skins/host-skin/phones-prompt")
        self.assertEqual(status, 200)
        self.assertIn("mochi: #aa5533", data)
        self.assertEqual(self.call("GET", "/skins/nope/phones-prompt")[0], 404)
        self.assertEqual(self.call("GET", "/skins/host-skin/with-headphones.json")[0], 404)  # no draft yet
        bad = json.loads(self.call("POST", "/skins/host-skin/headphones/check", json.dumps(dict(good_pair(), format="x")))[1])
        self.assertFalse(bad["ok"])
        self.assertEqual(self.call("POST", "/skins/host-skin/headphones/install")[0], 404)   # a failed check keeps no draft
        self.assertEqual(self.call("POST", "/skins/nope/headphones/check", json.dumps(good_pair()))[0], 404)
        self.assertTrue(json.loads(self.call("POST", "/skins/host-skin/headphones/check", json.dumps(good_pair()))[1])["ok"])
        status, data = self.call("GET", "/skins/host-skin/with-headphones.json")           # the preview's skin: installed + draft
        self.assertEqual((status, json.loads(data)["headphones"]), (200, "hpPair"))
        with open(self.path) as f:
            self.assertEqual(f.read(), self.before)                                          # still not saved
        rev = self.bridge.skins.rev
        status, data = self.call("POST", "/skins/host-skin/headphones/install")
        self.assertEqual(status, 200, data)
        listing = json.loads(data)
        self.assertEqual([(k["id"], k["hasHeadphones"]) for k in listing], [("host-skin", True)])
        with open(self.path) as f:
            saved = json.load(f)
        self.assertEqual(saved["headphones"], "hpPair")
        self.assertEqual(saved["name"], "Host")
        self.assertGreater(self.bridge.skins.rev, rev)                                       # the phone is told to read it again
        self.assertFalse(os.path.exists(self.bridge.skins.phones_draft_path("host-skin")))  # the draft is spent
        self.assertEqual(self.call("GET", "/skins/host-skin/headphones.json")[0], 200)       # and others can borrow it
        # a second pair needs ?replace=1
        again = json.dumps(make_pair("host-skin", 48, 40, -20, -50, prefix="hq"))
        self.assertFalse(json.loads(self.call("POST", "/skins/host-skin/headphones/check", again)[1])["ok"])
        self.assertTrue(json.loads(self.call("POST", "/skins/host-skin/headphones/check?replace=1", again)[1])["ok"])
        self.assertEqual(self.call("POST", "/skins/host-skin/headphones/install")[0], 200)
        with open(self.path) as f:
            self.assertEqual(json.load(f)["headphones"], "hqPair")

    def test_delete_drops_the_draft(self):
        self.call("POST", "/skins/host-skin/headphones/check", json.dumps(good_pair()))
        self.assertTrue(os.path.exists(self.bridge.skins.phones_draft_path("host-skin")))
        self.call("POST", "/skins/host-skin/delete")
        self.assertFalse(os.path.exists(self.bridge.skins.phones_draft_path("host-skin")))


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
