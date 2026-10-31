#!/usr/bin/env node
// Chip skins (chip-skin/1): checks a skin file, writes the chatbot prompt that makes one, prints the smallest valid one.
// Reuses phone/www/pack.js (eye resolution, pupil fit, mirrors), so a skin that passes here draws the way the phone draws it.
//   node laptop/skin.js check -|<file> [--clean]   JSON {ok, errors:[{path,problem,fix}], warnings, message, skin}
//                                                  (--clean adds the skin as minified JSON; the bridge stores that)
//   node laptop/skin.js prompt pet|me|character|art|idea
//   node laptop/skin.js example
const fs = require("fs"), path = require("path");
const www = path.join(__dirname, "..", "phone", "www");
const P = require(path.join(www, "pack.js"));
const pack = JSON.parse(fs.readFileSync(path.join(www, "pack.json"), "utf8"));

const MAX_BYTES = 600 * 1024, MAX_ENTRIES = 25, MAX_SPRITES = 40, MAX_COLORS = 12, MAX_KEYS = 8, MAX_DEPTH = 12;
const ID_RE = /^[a-z0-9-]{1,32}$/, NAME_RE = /^[A-Za-z][A-Za-z0-9@_-]{0,31}$/, FRAME_RE = /^[A-Za-z0-9_-]{1,32}$/, HEX_RE = /^#[0-9a-fA-F]{6}$/;
const FORBIDDEN = ["__proto__", "constructor", "prototype"];
const LAYERS = ["eyeL", "eyeR", "pupilL", "pupilR", "frontL", "frontR"];
const SLOT_OF = { eyeL: "eye", eyeR: "eye", pupilL: "pupil", pupilR: "pupil", frontL: "front", frontR: "front", mouth: "mouth", faceBase: "faceBase", faceTop: "faceTop" };
const TOP = ["format", "id", "name", "author", "accent", "colors", "sprites", "eyes", "mouth", "faceBase", "faceTop"];
const STYLE = ["label", "blurb", "sprites", "shift", "converge", "pupils", "pupilDefault", "frames"];
const DEF = ["pupil", "box", "boxR", "back", "shift"];
const SPRITE = ["keys", "anchor", "glow", "frames"];
const REQUIRED_EYE = ["open", "half", "shut"], REQUIRED_MOUTH = "neutral", SIZES = ["S", "M", "L"];
const ROLES = Object.keys(pack.palette);

const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const isObj = (v) => !!v && typeof v === "object" && !Array.isArray(v);
const isInt = Number.isInteger;
const len = (s) => [...s].length;

// "$.sprites.eyeL.frames.open[12]"
const jp = (parts) => "$" + parts.map((p) => (typeof p === "number" ? `[${p}]` : /^[A-Za-z_][A-Za-z0-9_]*$/.test(p) ? "." + p : `[${JSON.stringify(p)}]`)).join("");
const list = (a) => (a.length < 2 ? a.join("") : a.slice(0, -1).join(", ") + " and " + a[a.length - 1]);
const rowsText = (rows) => (rows.length === 1 ? "row " : "rows ") + list(rows.length > 8 ? [...rows.slice(0, 8), `${rows.length - 8} more`] : rows.map(String));
const quoted = (a) => a.map((s) => JSON.stringify(s));

// ---------------------------------------------------------------- check
function check(buf, opts = {}) {
  const errors = [], warnings = [];
  const E = (p, problem, fix) => { errors.push({ path: jp(p), problem, fix }); };
  const W = (p, problem, fix) => { warnings.push({ path: jp(p), problem, fix }); };
  const report = (skin) => {
    const shown = errors.slice(0, MAX_ENTRIES), more = errors.length - shown.length;
    const entries = shown.map((e, i) => `${i + 1}. ${e.path}: ${e.problem.replace(/\.$/, "")}. Fix: ${e.fix.replace(/\.$/, "")}.`);
    if (more > 0) entries.push(`(${more} more problems will show after you fix these.)`);
    const ok = errors.length === 0;
    const message = ok
      ? "Your Chip skin passed the check." + (warnings.length ? ` ${warnings.length} optional ${warnings.length === 1 ? "note" : "notes"}: it is fine to leave them.` : "")
      : "Your Chip skin didn't pass the check. Fix exactly these problems, keep everything else, and send the complete JSON again:\n" + entries.join("\n");
    return { ok, errors: shown, omitted: more > 0 ? more : 0, warnings: warnings.slice(0, MAX_ENTRIES), message, skin: ok ? skin : null };
  };

  // --- size and text
  if (buf.length > MAX_BYTES) {
    E([], `the file is ${Math.round(buf.length / 1024)} KB, over the ${MAX_BYTES / 1024} KB limit`, "shrink it: fewer or smaller sprites, fewer frames, no extra spaces or blank lines");
    return report();
  }
  let text = buf.toString("utf8");
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  // a chatbot reply pasted whole: keep only the first ``` block, with the other lines blanked so line numbers stay true
  const lines = text.split("\n"), open = lines.findIndex((l) => /^\s*```/.test(l));
  if (open >= 0) {
    let close = lines.findIndex((l, i) => i > open && /^\s*```\s*$/.test(l));
    if (close < 0) close = lines.length;
    text = lines.map((l, i) => (i > open && i < close ? l : "")).join("\n");
  }
  let skin;
  try {
    skin = JSON.parse(text);
  } catch (e) {
    const pos = Number((/position (\d+)/.exec(e.message) || [])[1]);
    let where = "";
    if (Number.isFinite(pos)) { const before = text.slice(0, pos).split("\n"); where = ` at line ${before.length}, column ${before[before.length - 1].length + 1}`; }
    E([], text.trim() ? `not valid JSON${where}: ${e.message.replace(/ in JSON at position.*$/, "").replace(/ \(line.*$/, "")}` : "the file is empty",
      "fix the syntax at that spot (a missing comma, quote or bracket) and send plain JSON: no comments, no trailing commas, nothing before or after it");
    return report();
  }
  if (!isObj(skin)) { E([], "the top level must be one JSON object { ... }", "wrap everything in a single object starting with {\"format\": \"chip-skin/1\", ...}"); return report(); }

  // --- keys that must never appear, and nesting
  let tooDeep = false;
  (function walk(v, p) {
    if (p.length > MAX_DEPTH) { if (!tooDeep) E(p, `nested more than ${MAX_DEPTH} levels deep`, "flatten it; chip-skin/1 never nests that deep"); tooDeep = true; return; }
    if (Array.isArray(v)) v.forEach((x, i) => walk(x, [...p, i]));
    else if (isObj(v)) for (const k of Object.keys(v)) {
      if (FORBIDDEN.includes(k)) E([...p, k], `the key ${JSON.stringify(k)} is not allowed anywhere`, "rename or remove it");
      walk(v[k], [...p, k]);
    }
  })(skin, []);
  if (errors.length) return report();

  const unknown = (obj, known, p) => {
    const extra = Object.keys(obj).filter((k) => !known.includes(k));
    if (extra.length) W(p, `unknown ${extra.length === 1 ? "field" : "fields"} ${quoted(extra).join(", ")} will be ignored`, `remove ${extra.length === 1 ? "it" : "them"}, or check the spelling (allowed here: ${known.join(", ")})`);
  };

  // --- identity
  if (skin.format !== "chip-skin/1") E(["format"], `is ${JSON.stringify(skin.format)}`, `set "format": "chip-skin/1"`);
  if (typeof skin.id !== "string" || !ID_RE.test(skin.id)) E(["id"], `${JSON.stringify(skin.id)} isn't a valid id (1-32 lowercase letters, digits and dashes)`, `use something like "my-chip" (letters a-z, digits 0-9, "-")`);
  else if (skin.id === "draft") E(["id"], `"draft" is reserved`, "pick another id");
  if (typeof skin.name !== "string" || !skin.name.trim() || len(skin.name) > 40) E(["name"], "must be a text of 1-40 characters", `set "name" to a short title, e.g. "Mochi"`);
  if (skin.author !== undefined && (typeof skin.author !== "string" || len(skin.author) > 40)) E(["author"], "must be a text of at most 40 characters", `shorten it or remove "author"`);
  if (skin.accent !== undefined && skin.accent !== null) {
    if (typeof skin.accent !== "string" || !HEX_RE.test(skin.accent)) E(["accent"], `${JSON.stringify(skin.accent)} isn't a #rrggbb colour`, `use six hex digits like "#ee9358", or null to keep the user's accent`);
    else {
      const [lo, hi] = pack.accentLightness, l = P.hexToOklch(skin.accent).l;
      if (l < lo - 0.005 || l > hi + 0.005) {
        const used = P.derivePalette(pack, skin.accent).main;
        W(["accent"], `its lightness is ${l.toFixed(2)}, but Chip keeps its accent between ${lo} and ${hi}, so ${skin.accent} will show as ${used}`, `use ${used} (or another colour with lightness ${lo}-${hi}) so what you see is what Chip draws`);
      }
    }
  }
  unknown(skin, TOP, []);

  // --- own colours
  const colors = {};
  if (skin.colors !== undefined && !isObj(skin.colors)) E(["colors"], "must be an object of name: #rrggbb", `use "colors": {"fur": "#c8955a"}`);
  else {
    const names = Object.keys(skin.colors || {});
    if (names.length > MAX_COLORS) E(["colors"], `has ${names.length} colours, the limit is ${MAX_COLORS}`, `remove ${names.length - MAX_COLORS} (merge similar shades)`);
    for (const n of names) {
      const v = skin.colors[n];
      if (!NAME_RE.test(n) || n.includes("@")) E(["colors", n], `${JSON.stringify(n)} isn't a valid colour name (a letter, then letters, digits, "_" or "-", at most 32)`, "rename it, e.g. \"fur\"");
      else if (ROLES.some((r) => r.toLowerCase() === n.toLowerCase())) E(["colors", n], `${JSON.stringify(n)} is the name of one of Chip's built-in colours (${ROLES.join(", ")})`, `rename it (e.g. "my${n[0].toUpperCase()}${n.slice(1)}") and use the new name in your sprites' keys`);
      else if (typeof v !== "string" || !HEX_RE.test(v)) E(["colors", n], `${JSON.stringify(v)} isn't a #rrggbb colour`, `use six hex digits like "#c8955a"`);
      else colors[n] = v;
    }
  }
  const tokenOk = (t) => typeof t === "string" && (ROLES.includes(t) || own(colors, t));

  // --- sprites
  const S = {};   // name -> {kind, ok, data}
  const usedTokens = new Set();
  if (!isObj(skin.sprites)) E(["sprites"], "is missing or isn't an object", `add "sprites": {"eyeL": {...}, ...}`);
  else {
    const names = Object.keys(skin.sprites);
    if (names.length > MAX_SPRITES) E(["sprites"], `has ${names.length} sprites, the limit is ${MAX_SPRITES}`, `remove ${names.length - MAX_SPRITES} sprites you don't need (a right eye can be {"mirror": "<left eye>"})`);
    for (const name of names) {
      const sp = skin.sprites[name], p = ["sprites", name];
      if (!NAME_RE.test(name)) { E(p, `${JSON.stringify(name)} isn't a valid sprite name (a letter, then letters, digits, "@", "_" or "-", at most 32)`, "rename it"); continue; }
      if (!isObj(sp)) { E(p, "must be an object", `use {"keys": ..., "anchor": [x, y], "frames": {...}} or {"mirror": "<sprite>"}`); continue; }
      if (own(sp, "mirror")) {
        S[name] = { kind: "mirror", ok: typeof sp.mirror === "string", data: sp };
        if (typeof sp.mirror !== "string") E([...p, "mirror"], "must be the name of another sprite", `e.g. "mirror": "eyeL"`);
        unknown(sp, ["mirror"], p);
        continue;
      }
      S[name] = { kind: "art", ok: true, data: sp };
      const bad = (path, problem, fix) => { S[name].ok = false; E(path, problem, fix); };
      unknown(sp, SPRITE, p);
      // keys
      const keys = isObj(sp.keys) ? Object.keys(sp.keys) : null;
      if (!keys || !keys.length) bad([...p, "keys"], "is missing or empty", `add "keys": {"#": "main"} mapping each character you draw with to a colour`);
      else {
        for (const k of keys) {
          if (len(k) !== 1 || k === "." || /\s/.test(k)) bad([...p, "keys", k], `${JSON.stringify(k)} can't be a key: a key is one visible character other than "."`, `use a letter, digit or symbol such as "#", "+", "o"; "." is reserved for transparent pixels`);
          else if (!tokenOk(sp.keys[k])) bad([...p, "keys", k], `${JSON.stringify(sp.keys[k])} is neither one of Chip's colours nor one of your "colors"`, `use one of ${ROLES.join(", ")}${Object.keys(colors).length ? ", " + Object.keys(colors).join(", ") : ""}, or add it to "colors" as a #rrggbb`);
          else usedTokens.add(sp.keys[k]);
        }
        if (keys.length > MAX_KEYS) W([...p, "keys"], `has ${keys.length} colour keys; the art guide asks for at most ${MAX_KEYS} per sprite`, "merge similar colours");
      }
      // glow
      if (sp.glow !== undefined && !(typeof sp.glow === "number" && sp.glow >= 0 && sp.glow <= 1)) bad([...p, "glow"], `${JSON.stringify(sp.glow)} isn't a number from 0 to 1`, "use 0 for no glow, 0.65 for Chip's own eyes");
      // frames
      if (!isObj(sp.frames) || !Object.keys(sp.frames).length) { bad([...p, "frames"], "is missing or empty", `add "frames": {"open": ["row", "row", ...]}`); continue; }
      for (const [f, rows] of Object.entries(sp.frames)) {
        const fp = [...p, "frames", f];
        if (!FRAME_RE.test(f)) { bad(fp, `${JSON.stringify(f)} isn't a valid frame name`, "use letters, digits, - and _ (at most 32)"); continue; }
        if (!Array.isArray(rows) || !rows.length || rows.some((r) => typeof r !== "string")) { bad(fp, "must be a list of rows (texts), one per pixel row", `use ["..##..", "..##.."]`); continue; }
        const counts = {};
        rows.forEach((r) => { counts[r.length] = (counts[r.length] || 0) + 1; });
        const width = Number(Object.keys(counts).sort((a, b) => counts[b] - counts[a] || b - a)[0]);
        const byLen = {};
        rows.forEach((r, y) => { if (r.length !== width) (byLen[r.length] = byLen[r.length] || []).push(y); });
        for (const [l, ys] of Object.entries(byLen)) bad(fp, `${rowsText(ys)} ${ys.length === 1 ? "has" : "have"} ${l} characters, but the other rows have ${width}`, `pad ${ys.length === 1 ? "that row" : "those rows"} with "." (or trim ${ys.length === 1 ? "it" : "them"}) to exactly ${width} characters`);
        if (keys) {
          const chars = {};
          rows.forEach((r, y) => [...r].forEach((c) => { if (c !== "." && !own(sp.keys, c)) (chars[c] = chars[c] || new Set()).add(y); }));
          for (const [c, ys] of Object.entries(chars)) bad(fp, `${rowsText([...ys])} ${ys.size === 1 ? "uses" : "use"} the character ${JSON.stringify(c)}, which is not in "keys"`, `add ${JSON.stringify(c)}: "<colour>" to this sprite's keys, or replace ${JSON.stringify(c)} with "." for a transparent pixel`);
        }
      }
      // size and anchor
      const w = Math.max(...Object.values(sp.frames).flatMap((rows) => (Array.isArray(rows) ? rows.map((r) => (typeof r === "string" ? r.length : 0)) : [0]))),
        h = Math.max(...Object.values(sp.frames).map((rows) => (Array.isArray(rows) ? rows.length : 0)));
      if (!Array.isArray(sp.anchor) || sp.anchor.length !== 2 || !sp.anchor.every(isInt)) bad([...p, "anchor"], `${JSON.stringify(sp.anchor)} isn't [x, y] with two whole numbers`, `use e.g. "anchor": [${w >> 1}, ${h >> 1}]`);
      else if (S[name].ok && (sp.anchor[0] < 0 || sp.anchor[1] < 0 || sp.anchor[0] >= w || sp.anchor[1] >= h))
        bad([...p, "anchor"], `[${sp.anchor}] is outside the ${w}x${h} sprite`, `use x from 0 to ${w - 1} and y from 0 to ${h - 1}, e.g. [${w >> 1}, ${h >> 1}]`);
    }
  }

  // mirrors: the target must exist and be drawn art, no loops
  for (const [name, rec] of Object.entries(S)) {
    if (rec.kind !== "mirror" || !rec.ok) continue;
    const seen = [name];
    let t = rec.data.mirror, bad = null;
    while (!bad) {
      if (!own(S, t)) bad = `there is no sprite called ${JSON.stringify(t)}`;
      else if (seen.includes(t)) bad = `it loops back to itself (${[...seen, t].join(" -> ")})`;
      else if (S[t].kind === "art") break;
      else { seen.push(t); t = S[t].data.mirror; if (typeof t !== "string") bad = "its target isn't a drawn sprite"; }
    }
    if (bad) { rec.ok = false; E(["sprites", name, "mirror"], `cannot mirror ${JSON.stringify(rec.data.mirror)}: ${bad}`, `mirror a sprite that is drawn with "keys", "anchor" and "frames" (keep ${JSON.stringify(rec.data.mirror)} spelled exactly as in "sprites")`); }
    else if (!S[t].ok) rec.ok = false;   // the target's own errors come first
  }
  const owner = (name) => { while (S[name] && S[name].kind === "mirror") name = S[name].data.mirror; return name; };
  const memo = {};
  const resolve = (name) => {   // the sprite as the phone sees it (mirrors flipped), or undefined
    if (!own(S, name) || !S[name].ok) return undefined;
    if (!own(memo, name)) memo[name] = S[name].kind === "art" ? S[name].data : P.mirrored(resolve(S[name].data.mirror));
    return memo[name];
  };
  const sizeOf = (name) => P.spriteSize(resolve(name));

  // --- eye style
  const eyes = skin.eyes, names = {};
  const stylePath = ["eyes"];
  let styleOk = false;
  const ref = (slot, name, p, required) => {   // a slot's sprite name: it must be a drawn sprite of this skin
    if (name === undefined) { if (required) E(p, "is missing", `name one of your sprites, e.g. ${JSON.stringify(slot)}`); return null; }
    if (typeof name !== "string" || !own(S, name)) { E(p, `${JSON.stringify(name)} is not a sprite in "sprites"`, `use one of your sprite names: ${quoted(Object.keys(S)).join(", ") || "(none yet)"}`); return null; }
    if (!S[name].ok) return null;
    return name;
  };
  if (!isObj(eyes)) E(stylePath, "is missing: every skin needs an eye style", `add "eyes": {...} like the example`);
  else {
    styleOk = true;
    const bad = (p, problem, fix) => { styleOk = false; E(p, problem, fix); };
    unknown(eyes, STYLE, stylePath);
    if (typeof eyes.label !== "string" || !eyes.label.trim() || len(eyes.label) > 40) bad([...stylePath, "label"], "must be a text of 1-40 characters", `e.g. "label": "Mochi"`);
    if (eyes.blurb !== undefined && (typeof eyes.blurb !== "string" || len(eyes.blurb) > 160)) bad([...stylePath, "blurb"], "must be a text of at most 160 characters", "shorten it");
    if (!isObj(eyes.sprites)) bad([...stylePath, "sprites"], "is missing or isn't an object", `list the sprites of each layer: ${LAYERS.map((l) => `"${l}"`).join(", ")}`);
    else {
      const extra = Object.keys(eyes.sprites).filter((k) => !LAYERS.includes(k));
      if (extra.length) W([...stylePath, "sprites"], `unknown ${extra.length === 1 ? "layer" : "layers"} ${quoted(extra).join(", ")} will be ignored`, `the layers are ${LAYERS.join(", ")}`);
      for (const l of LAYERS) {
        const required = l === "eyeL" || l === "eyeR", v = eyes.sprites[l];
        const r = v === undefined ? (required ? ref(l, v, [...stylePath, "sprites", l], true) : null) : ref(l, v, [...stylePath, "sprites", l], required);
        if (r) names[l] = r; else if (required || v !== undefined) styleOk = false;
      }
      for (const [a, b] of [["pupilL", "pupilR"], ["frontL", "frontR"]]) {
        if (eyes.sprites[a] !== undefined && eyes.sprites[b] === undefined) bad([...stylePath, "sprites", b], "is missing while " + a + " is given", `give both sides; the same sprite name works for both: "${b}": ${JSON.stringify(eyes.sprites[a])}`);
        if (eyes.sprites[b] !== undefined && eyes.sprites[a] === undefined) bad([...stylePath, "sprites", a], "is missing while " + b + " is given", `give both sides; the same sprite name works for both: "${a}": ${JSON.stringify(eyes.sprites[b])}`);
      }
    }
    const hasPupil = !!(isObj(eyes.sprites) && eyes.sprites.pupilL !== undefined);
    const pair = (v) => Array.isArray(v) && v.length === 2 && v.every((n) => typeof n === "number" && Number.isFinite(n) && n >= 0 && n <= 12);
    if (!pair(eyes.shift)) bad([...stylePath, "shift"], `${JSON.stringify(eyes.shift)} isn't [x, y] with two numbers from 0 to 12`, `use "shift": [2, 1] (how far the whole eye moves, in pixels, when Chip looks to the edge)`);
    if (eyes.converge !== undefined && !(typeof eyes.converge === "number" && eyes.converge >= 0 && eyes.converge <= 3)) bad([...stylePath, "converge"], `${JSON.stringify(eyes.converge)} isn't a number from 0 to 3`, `use 1 (pupils move 1 px inward when the target is near) or 0`);
    if (hasPupil) {
      if (!Array.isArray(eyes.pupils) || !eyes.pupils.length || !eyes.pupils.every((s) => SIZES.includes(s)) || new Set(eyes.pupils).size !== eyes.pupils.length) bad([...stylePath, "pupils"], `${JSON.stringify(eyes.pupils)} isn't a list of sizes from "S", "M", "L"`, `use "pupils": ["S", "M", "L"]; the pupil sprite needs one frame for each`);
      else if (!eyes.pupils.includes(eyes.pupilDefault)) bad([...stylePath, "pupilDefault"], `${JSON.stringify(eyes.pupilDefault)} isn't one of "pupils"`, `use one of ${quoted(eyes.pupils).join(", ")}, e.g. "pupilDefault": ${JSON.stringify(eyes.pupils.includes("M") ? "M" : eyes.pupils[0])}`);
    }
    if (!isObj(eyes.frames)) bad([...stylePath, "frames"], "is missing or isn't an object", `add "frames": {"open": {...}, "half": {...}, "shut": {...}}`);
    else {
      for (const f of REQUIRED_EYE) if (!own(eyes.frames, f)) bad([...stylePath, "frames", f], `the required frame ${JSON.stringify(f)} is missing`, `add "${f}": {${f === "shut" ? `"pupil": null` : `"pupil": "auto", "box": [x0, y0, x1, y1]`}}`);
      const boxOk = (b) => Array.isArray(b) && b.length === 4 && b.every(isInt) && b[0] <= b[2] && b[1] <= b[3];
      for (const [f, d] of Object.entries(eyes.frames)) {
        const p = [...stylePath, "frames", f];
        if (!FRAME_RE.test(f)) { bad(p, `${JSON.stringify(f)} isn't a valid frame name`, "use letters, digits, - and _"); continue; }
        if (!isObj(d)) { bad(p, "must be an object", `use {"pupil": "auto", "box": [x0, y0, x1, y1]} or {"pupil": null}`); continue; }
        unknown(d, DEF, p);
        if (d.pupil !== undefined && d.pupil !== null && (typeof d.pupil !== "string" || !FRAME_RE.test(d.pupil))) bad([...p, "pupil"], `${JSON.stringify(d.pupil)} must be "auto", null or the name of a pupil frame`, `use "auto" (the user's pupil size) or null (no pupil, e.g. shut eyes)`);
        if (d.pupil && !hasPupil) bad([...p, "pupil"], `asks for a pupil, but the style has no "pupilL"/"pupilR" sprites`, `add the pupil sprites to "sprites" and name them in eyes.sprites, or set "pupil": null`);
        for (const k of ["box", "boxR"]) if (d[k] !== undefined && !boxOk(d[k])) bad([...p, k], `${JSON.stringify(d[k])} isn't [x0, y0, x1, y1] with whole numbers and x0 <= x1, y0 <= y1`, `use e.g. [13, 17, 27, 31]: where the pupil's anchor sits at gaze -1 and +1, in pixels of the eye sprite`);
        if (d.pupil && d.box === undefined && hasPupil) bad([...p, "box"], "is missing: a frame with a pupil needs a box", `add "box": [x0, y0, x1, y1] (the pupil anchor at gaze -1 and +1; [x, y, x, y] for a pupil that never moves)`);
        if (d.back !== undefined && (typeof d.back !== "string" || !FRAME_RE.test(d.back))) bad([...p, "back"], `${JSON.stringify(d.back)} isn't a frame name`, `use the name of the eye sprite frame to show under this one, e.g. "open"`);
        if (d.shift !== undefined && !pair(d.shift)) bad([...p, "shift"], `${JSON.stringify(d.shift)} isn't [x, y] with two numbers from 0 to 12`, `e.g. [5, 3]`);
      }
    }
  }

  // --- mouth, faceBase, faceTop
  const extra = {};
  for (const slot of ["mouth", "faceBase", "faceTop"]) {
    if (skin[slot] === undefined) continue;
    const r = ref(slot, skin[slot], [slot], false);
    if (r) extra[slot] = r;
  }

  // --- what each slot's sprite must look like
  const done = new Set();   // path + problem, so a shared sprite is reported once
  const once = (p, problem, fix) => { const k = jp(p) + problem; if (!done.has(k)) { done.add(k); E(p, problem, fix); } };
  const slotNames = { ...names, ...extra };
  const slots = pack.skinSlots || {};
  for (const [slot, name] of Object.entries(slotNames)) {
    const [mw, mh] = slots[SLOT_OF[slot]] || [128, 96], sp = resolve(name);
    if (!sp) continue;
    const [w, h] = P.spriteSize(sp), own_ = owner(name);
    if (w > mw || h > mh) once(["sprites", own_], `is ${w}x${h} px, but the ${SLOT_OF[slot]} slot allows at most ${mw}x${mh}`, `redraw it at most ${mw} wide and ${mh} tall (trim empty rows and columns first; ${slot} is where this sprite is used)`);
  }
  for (const [name, rec] of Object.entries(S)) {
    if (rec.kind !== "art" || !rec.ok) continue;
    const [w, h] = sizeOf(name);
    if (w > 128 || h > 96) once(["sprites", name], `is ${w}x${h} px, but no sprite may be larger than 128x96`, "make it smaller");
  }
  // unused sprites and colours
  const used = new Set(Object.values(slotNames).map(owner));
  const unusedSprites = Object.keys(S).filter((n) => !used.has(n) && !Object.values(slotNames).includes(n) && !Object.values(S).some((r) => r.kind === "mirror" && r.data.mirror === n));
  if (unusedSprites.length) W(["sprites"], `${quoted(unusedSprites).join(", ")} ${unusedSprites.length === 1 ? "is" : "are"} not used by the eye style, mouth, faceBase or faceTop`, "remove the sprite, or name it in eyes.sprites / mouth / faceBase / faceTop");
  const unusedColors = Object.keys(colors).filter((c) => !usedTokens.has(c));
  if (unusedColors.length) W(["colors"], `${quoted(unusedColors).join(", ")} ${unusedColors.length === 1 ? "is" : "are"} not used by any sprite`, "remove the colour or use it as a key");

  // --- eye frames
  const eyeReady = styleOk && names.eyeL && names.eyeR && (!eyes.sprites.pupilL || (names.pupilL && names.pupilR)) && (!eyes.sprites.frontL || (names.frontL && names.frontR));
  if (eyeReady) {
    for (const id of ["eyeL", "eyeR"]) {
      const sp = resolve(names[id]);
      for (const f of REQUIRED_EYE) if (!own(sp.frames, f)) once(["sprites", owner(names[id]), "frames", f], `the required frame ${JSON.stringify(f)} is missing (used by ${id})`, `add a "${f}" frame to this sprite, drawn like the other frames (same width and height)`);
    }
    if (names.pupilL) for (const id of ["pupilL", "pupilR"]) {
      const sp = resolve(names[id]);
      for (const s of eyes.pupils) if (!own(sp.frames, s)) once(["sprites", owner(names[id]), "frames", s], `has no frame ${JSON.stringify(s)}, but "pupils" lists it`, `add a "${s}" frame (a solid blob; S small, M medium, L large, centred in the same box), or remove "${s}" from "pupils"`);
      for (const [f, d] of Object.entries(eyes.frames)) if (typeof d.pupil === "string" && d.pupil !== "auto" && !own(sp.frames, d.pupil)) once(["eyes", "frames", f, "pupil"], `${JSON.stringify(d.pupil)} is not a frame of the pupil sprite`, `use "auto" or one of ${quoted(Object.keys(sp.frames)).join(", ")}`);
    }
    // the front layer shares its eye's anchor
    if (names.frontL) for (const side of ["L", "R"]) {
      const eye = resolve(names["eye" + side]), front = resolve(names["front" + side]);
      if (eye.anchor[0] !== front.anchor[0] || eye.anchor[1] !== front.anchor[1]) {
        const n = names["front" + side], art = S[n].kind === "art";
        once(art ? ["sprites", n, "anchor"] : ["sprites", n], `front${side} anchor [${front.anchor}] differs from eye${side}'s [${eye.anchor}], so the front layer would sit off the eye`,
          art ? `set the anchor to [${eye.anchor}] (a front sprite shares its eye's anchor, and must be drawn on the same grid as the eye${side === "R" ? "; the right eye's anchor is the left's mirrored, so give frontR its own {\"mirror\": \"<frontL sprite>\"} sprite" : ""})` : `its anchor comes from "${S[n].data.mirror}", mirrored: make the eye and front sprites equally wide with the same anchor`);
      }
    }
  }

  const want = P.usedFrames(pack);
  if (eyeReady && !errors.length) {
    const env = { style: eyes, names, fb: pack.fallbacks.eye, spr: resolve };
    // frames you didn't draw, and what Chip shows instead
    const falls = [];
    for (const f of want.eyeL) {
      const l = P.eyeLook(env, "eyeL", f, eyes.pupilDefault), r = P.eyeLook(env, "eyeR", f, eyes.pupilDefault);
      const native = (k) => k.key === f && (k.back === f || k.def.back);
      if (!native(l) || !native(r)) falls.push(`${f} -> ${!native(l) ? l.back : r.back}`);
    }
    if (falls.length) W(["eyes", "frames"], `${falls.length} eye ${falls.length === 1 ? "look isn't" : "looks aren't"} drawn. Chip shows the look after each arrow instead (happy -> shut means a happy look shows as closed): ${falls.join(", ")}`, "optional: add those frames (to the eye sprites and eyes.frames) for more expression");
    const mouth = extra.mouth ? resolve(extra.mouth) : null;
    if (mouth) {
      if (!own(mouth.frames, REQUIRED_MOUTH)) once(["sprites", owner(extra.mouth), "frames", REQUIRED_MOUTH], `the required frame ${JSON.stringify(REQUIRED_MOUTH)} is missing`, `add a "neutral" frame: the mouth Chip shows when nothing else applies`);
      else {
        const miss = [...want.mouth].filter((f) => !own(mouth.frames, f)).map((f) => `${f} -> ${P.chain(pack.fallbacks.mouth, f).find((n) => own(mouth.frames, n)) || REQUIRED_MOUTH}`);
        if (miss.length) W(["sprites", owner(extra.mouth), "frames"], `${miss.length} mouth ${miss.length === 1 ? "shape isn't" : "shapes aren't"} drawn. Chip shows the shape after each arrow instead: ${miss.join(", ")}`, "optional: add those frames for more expression");
      }
    }
    for (const slot of ["faceBase", "faceTop"]) if (extra[slot]) {
      const sp = resolve(extra[slot]), fs_ = Object.keys(sp.frames);
      if (fs_.length > 1) W(["sprites", owner(extra[slot]), "frames"], `${slot} shows only its first frame (${JSON.stringify(fs_[0])}); ${quoted(fs_.slice(1)).join(", ")} will never be drawn`, "remove the extra frames");
    }

    // pupils: every size at all 9 gaze positions must stay on the eye (or under the front layer)
    if (names.pupilL && !errors.length) {
      const groups = {};   // "key|boxField" -> {key, field, sizes, spots, px, sides}
      const fitFor = (e2, only) => {
        const bad = [];
        for (const id of ["eyeL", "eyeR"]) for (const f of want[id]) {
          const look = P.eyeLook(e2, id, f, eyes.pupilDefault);
          if (only && look.key !== only) continue;
          for (const b of P.pupilFit(e2, id, f).bad) bad.push({ ...b, id, f, field: id === "eyeR" && look.def.boxR ? "boxR" : "box" });
        }
        return bad;
      };
      for (const b of fitFor(env)) {
        const g = groups[b.key + "|" + b.field] = groups[b.key + "|" + b.field] || { key: b.key, field: b.field, sizes: new Set(), spots: new Set(), px: 0 };
        g.sizes.add(b.size); g.spots.add(`${b.gx},${b.gy}`); g.px = Math.max(g.px, b.px);
      }
      for (const g of Object.values(groups)) {
        const def = eyes.frames[g.key], box = def[g.field];
        let suggestion = null;
        for (let k = 1; k <= 12 && !suggestion; k++) {
          const nb = [box[0] + k, box[1] + k, box[2] - k, box[3] - k];
          if (nb[0] > nb[2] || nb[1] > nb[3]) break;
          const e2 = { ...env, style: { ...eyes, frames: { ...eyes.frames, [g.key]: { ...def, [g.field]: nb } } } };
          if (!fitFor(e2, g.key).some((b) => b.key === g.key && b.field === g.field)) suggestion = nb;
        }
        const spots = [...g.spots], sizes = [...g.sizes];
        E(["eyes", "frames", g.key, g.field],
          `the ${list(sizes)} pupil sticks out of the eye by up to ${g.px} pixels when Chip looks at ${list(spots.slice(0, 4).map((s) => `(${s})`))}${spots.length > 4 ? ` and ${spots.length - 4} more of the 9 positions` : ""} (x and y run from -1 = far left or top to 1 = far right or bottom)`,
          suggestion ? `shrink the box to [${suggestion}] so the pupil stays inside the eye or under the front layer (or draw smaller pupils)`
            : `the pupil doesn't fit inside this eye even at rest. For a blink or lid look, set "pupil": null; otherwise draw smaller pupils, a larger eye, or move the box so the pupil sits inside the eye's drawn pixels`);
      }
    }
  }

  const info = errors.length ? null : { id: skin.id, name: skin.name, author: typeof skin.author === "string" ? skin.author : "", bytes: buf.length };
  const out = report(info);
  if (opts.clean && out.ok) out.clean = JSON.stringify(skin);
  return out;
}

// ---------------------------------------------------------------- example: the smallest valid skin
function example() {
  const pad = (rows, w, h) => { const out = rows.map((r) => r.padEnd(w, ".")); while (out.length < h) out.push(".".repeat(w)); return out; };
  const fill = (w, h, from = 0) => Array.from({ length: h }, (_, y) => (y < from ? ".".repeat(w) : "#".repeat(w)));
  const dot = (n) => { const m = 6 - n, a = m >> 1; return Array.from({ length: 6 }, (_, y) => (y >= a && y < a + n ? ".".repeat(a) + "o".repeat(n) + ".".repeat(6 - a - n) : "......")); };
  return {
    format: "chip-skin/1", id: "example", name: "Example", author: "you", accent: "#ee9358",
    colors: { snow: "#f4f4ff" },
    sprites: {
      eyeL: { keys: { "#": "main" }, anchor: [6, 7], glow: 0.5, frames: {
        open: fill(12, 14), half: fill(12, 14, 6), shut: pad([".".repeat(12), ".".repeat(12), ".".repeat(12), ".".repeat(12), ".".repeat(12), ".".repeat(12), "#".repeat(12), "#".repeat(12)], 12, 14) } },
      eyeR: { mirror: "eyeL" },
      pupil: { keys: { o: "pupil" }, anchor: [3, 3], frames: { S: dot(2), M: dot(4), L: dot(6) } },
      mouth: { keys: { "#": "snow" }, anchor: [4, 0], frames: { neutral: ["########", "########"] } },
    },
    eyes: {
      label: "Example", blurb: "Two square eyes and a small mouth.",
      sprites: { eyeL: "eyeL", eyeR: "eyeR", pupilL: "pupil", pupilR: "pupil" },
      shift: [2, 1], converge: 1, pupils: ["S", "M", "L"], pupilDefault: "M",
      frames: { open: { pupil: "auto", box: [4, 4, 7, 9] }, half: { pupil: "auto", box: [4, 9, 7, 10] }, shut: { pupil: null, shift: [5, 3] } },
    },
    mouth: "mouth",
  };
}

// compact JSON for the prompt: one frame (a list of row texts) per line
function pretty(v) {
  return JSON.stringify(v, null, 2).replace(/\[\s*("(?:[^"\\]|\\.)*"(?:,\s*"(?:[^"\\]|\\.)*")*)\s*\]/g, (m, inner) => "[" + inner.replace(/\s*\n\s*/g, " ") + "]");
}

// ---------------------------------------------------------------- the chatbot prompt, built from the pack
const BASIS = {
  pet: "I'm attaching photos of my pet: make Chip a cute pixel-art version of them (colours, markings, ears, eye colour), readable from a metre away, not a photo.",
  me: "I'm attaching a photo of myself: make a friendly pixel-art Chip inspired by me (hair, colours, glasses), simple and cute, not a portrait.",
  character: "I'll name or attach a character, film or theme I love: make an original Chip inspired by its colours and mood, without copying logos or exact designs.",
  art: "I'm attaching my concept art: turn it into a Chip skin, staying close to it.",
  idea: "I'll describe my idea below.",
};

function prompt(basis) {
  const roles = ROLES.map((r) => {
    const t = pack.palette[r];
    return `${r}${t === "accent" ? " (the accent itself)" : t.fixed ? ` (fixed ${t.fixed})` : ""}`;
  });
  const slotLine = Object.entries(pack.skinSlots).map(([k, [w, h]]) => `${k} ${w}x${h}`).join(", ");
  const eyeFrames = Object.keys(pack.sprites.eyeL.frames), mouthFrames = Object.keys(pack.sprites.mouth.frames);
  const fb = (m) => Object.entries(m).map(([a, b]) => `${a} -> ${b}`).join(", ");
  const [lo, hi] = pack.accentLightness;
  const guide = Array.isArray(pack.skinGuide) ? pack.skinGuide.join("\n") : pack.skinGuide || "";
  const generated = `
chip-skin/1 is one JSON object. Fields:
- "format": "chip-skin/1"
- "id": 1-32 lowercase letters, digits or "-" (not "draft"). "name": 1-40 characters. "author": optional, at most 40.
- "accent": "#rrggbb" or null. Chip's main colour; every colour derived from it follows. Its lightness is kept between ${lo} and ${hi} (anything else is clamped, and the check warns).
- "colors": up to ${MAX_COLORS} colours of your own, {"name": "#rrggbb"}. A name must not be one of Chip's built-in colours.
- "sprites": up to ${MAX_SPRITES}. Each is {"keys": {"<one character>": "<colour>"}, "anchor": [x, y], "glow": 0-1 (optional), "frames": {"<frame>": ["row", "row"]}} or {"mirror": "<other sprite>"} (flips it left-right; use it for the right eye).
  - A row is text, one character per pixel. "." is transparent; every other character must be a key. All rows of a frame have exactly the same length. In error messages the first row is row 0.
  - A key's colour is one of Chip's built-in colours or one of your "colors". Built-in colours: ${roles.join(", ")}. Most follow the accent, so a skin with an accent recolours itself.
  - "anchor" is the pixel of the sprite that sits on the spot where Chip places it; it must be inside the sprite.
- "eyes": one eye style (below). Required.
- "mouth", "faceBase", "faceTop": the name of one of your sprites. Optional; Chip keeps its own mouth and shows no faceBase/faceTop without them. faceBase and faceTop are drawn from their first frame.

Maximum sprite sizes in pixels: ${slotLine}. No sprite may exceed 128x96. The file must stay under ${MAX_BYTES / 1024} KB.

The eye style, "eyes": {"label": 1-40 characters, "blurb": optional, "sprites": {...}, "shift": [x, y], "converge": number, "pupils": [...], "pupilDefault": "M", "frames": {...}}
- "sprites" names the sprite of each layer: eyeL, eyeR (required), pupilL, pupilR, frontL, frontR (optional, given in pairs; the same sprite may serve both sides). Drawn in that order: eye, then pupil, then front.
  - The eye sprite's frames are the eye shapes. The pupil sprite has one frame per size in "pupils" (S, M, L), each a solid blob centred in one shared box, anchored at the box centre. The front sprite draws over the pupil: use it for eyelids and catchlights; it has the same frame names as the eye looks and shares its eye's anchor exactly (give both the same anchor and draw them on the same grid).
- The eye looks (frames) are: ${eyeFrames.join(", ")}.
  - Required: ${REQUIRED_EYE.join(", ")}, in the eye sprites (both sides) AND in "eyes.frames". Any look you don't draw is replaced, following these fallbacks until a drawn one is found: ${fb(pack.fallbacks.eye)}.
  - "eyes.frames.<look>" = {"pupil": "auto" | null, "box": [x0, y0, x1, y1], "boxR": [...] (optional, the right eye's own box), "back": "<eye frame to draw underneath>" (optional), "shift": [x, y] (optional, replaces the style's shift)}.
    "auto" shows the pupil in the size the user picked; null hides it (shut, happy, hearts, stars, spirals, and a blink band too thin for a pupil, such as half). "box" is where the pupil's anchor sits when Chip looks to the far left/top (x0, y0) and to the far right/bottom (x1, y1), in pixels of the eye sprite; looking straight ahead is the middle of the box. Smaller pupils are centred inside the box of the largest, so size L sets the limits.
  - "shift" is how far the whole eye moves (px) when Chip looks to the edge, for looks that have a pupil. A look without a pupil usually shifts more, e.g. [5, 3]. "converge": the pupils move this many px toward each other when the target is close or Chip is idle.
  - At all 9 gaze positions (left/centre/right x top/centre/bottom), with every pupil size and with converge applied, every pixel of the pupil must lie on the eye's drawn pixels or under the front layer's drawn pixels. Keep at least 8 px of eye around the pupil at rest.
- Mouth looks: ${mouthFrames.join(", ")}. Required: neutral. Others fall back: ${fb(pack.fallbacks.mouth)}.

Where the art guide below and these rules differ (for example which eye looks you must draw), these rules win: the checker enforces them.`;

  return `You're designing a custom look ("skin") for Chip, a small pixel-art buddy that lives on an old phone
standing on my desk next to my monitors. ${BASIS[basis]} Chip keeps all its animations, moods and
behaviour; you only make the art, in the exact JSON format below.

How to work:
1. First tell me in 3-5 short lines what you'll take from my pictures or idea. Ask at most 2
   questions, only if something important is unclear.
2. If you can run code, build the JSON with code (shrink pictures and reduce them to your colours,
   draw shapes with code) and check every rule below before answering. If you can't, draw
   carefully and count every row.
3. Reply with the complete JSON in one \`\`\`json block (or a downloadable .json file), nothing after.
4. When I paste validation errors, fix exactly those, keep the rest, send the whole JSON again.

Format, slots, frames, colours:
${generated}

Art guide from Chip's designer:
${guide}

Smallest valid example (make yours much richer):
\`\`\`json
${pretty(example())}
\`\`\`
`;
}

// ---------------------------------------------------------------- main
const [cmd, arg, ...rest] = process.argv.slice(2);
if (cmd === "check" && arg) {
  process.stdout.write(JSON.stringify(check(arg === "-" ? fs.readFileSync(0) : fs.readFileSync(arg), { clean: rest.includes("--clean") })));
} else if (cmd === "prompt" && own(BASIS, arg || "")) {
  process.stdout.write(prompt(arg));
} else if (cmd === "example") {
  process.stdout.write(pretty(example()) + "\n");
} else {
  console.error("usage: node laptop/skin.js check -|<file> [--clean] | prompt " + Object.keys(BASIS).join("|") + " | example");
  process.exit(2);
}
