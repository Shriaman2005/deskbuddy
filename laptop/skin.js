#!/usr/bin/env node
// Chip skins (chip-skin/1): checks a skin file, writes the chatbot prompt that makes one, prints the smallest valid one.
// Reuses phone/www/pack.js (eye resolution, pupil fit, mirrors), so a skin that passes here draws the way the phone draws it.
//   node laptop/skin.js check -|<file> [--clean]   JSON {ok, errors:[{path,problem,fix}], warnings, message, skin}
//                                                  (--clean adds the skin as minified JSON; the bridge stores that)
//   node laptop/skin.js prompt                     the master prompt for the chatbot (one for every subject and screen)
//   node laptop/skin.js example
//   node laptop/skin.js prompt-phones <skinfile>   the chatbot prompt for headphones only, fitted to that skin
//   node laptop/skin.js check-phones <skinfile> -|<file> [--replace] [--clean]
//                                                  merges a chip-phones/1 reply into a copy of the skin, runs check() on it
const fs = require("fs"), path = require("path");
const www = path.join(__dirname, "..", "phone", "www");
const P = require(path.join(www, "pack.js"));
const pack = JSON.parse(fs.readFileSync(path.join(www, "pack.json"), "utf8"));

const MAX_BYTES = 600 * 1024, MAX_ENTRIES = 25, MAX_SPRITES = 40, MAX_COLORS = 12, MAX_KEYS = 8, MAX_DEPTH = 12;
const ID_RE = /^[a-z0-9-]{1,32}$/, NAME_RE = /^[A-Za-z][A-Za-z0-9@_-]{0,31}$/, FRAME_RE = /^[A-Za-z0-9_-]{1,32}$/, HEX_RE = /^#[0-9a-fA-F]{6}$/;
const FORBIDDEN = ["__proto__", "constructor", "prototype"];
const LAYERS = ["eyeL", "eyeR", "pupilL", "pupilR", "frontL", "frontR"];
const SLOT_OF = { eyeL: "eye", eyeR: "eye", pupilL: "pupil", pupilR: "pupil", frontL: "front", frontR: "front", mouth: "mouth", faceBase: "faceBase", faceTop: "faceTop", headphones: "headphones" };
const TOP = ["format", "id", "name", "author", "accent", "colors", "sprites", "eyes", "mouth", "faceBase", "faceTop", "headphones"];
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

// ---------------------------------------------------------------- headphones fit (the check's warnings, the prompt's numbers)
const rigAt = (id) => (pack.rig.find((r) => r.id === id) || {}).at || [0, 0];
const EYE_ROWS = 8;   // "eye height": the eye anchors' row +-8 px
const EYE_COVER = 0.02;   // the share of the eyes' inside the headphones may cover before the check warns
const firstFrame = (sp) => Object.keys(sp.frames)[0];
// [x, y, char] of every drawn pixel, relative to the head's centre, with the sprite's anchor placed at `at`
const inkOf = (sp, frame, at = [0, 0]) => {
  const out = [], rows = sp && sp.frames && sp.frames[frame];
  if (Array.isArray(rows)) rows.forEach((r, y) => [...r].forEach((c, x) => { if (c !== ".") out.push([at[0] + x - sp.anchor[0], at[1] + y - sp.anchor[1], c]); }));
  return out;
};
// hp: the headphones sprite; eyes: {eyeL, eyeR, frontL, frontR} sprites (mirrors resolved, fronts optional);
// face: the faceBase/faceTop sprites (may be none). All at the default gaps, eyes in their "open" look.
function phonesFit(hp, eyes, face) {
  const eyeY = rigAt("eyeL")[1], y0 = eyeY - EYE_ROWS, y1 = eyeY + EYE_ROWS;
  const eyeSet = new Set();
  for (const s of ["L", "R"]) for (const l of ["eye", "front"]) for (const [x, y] of inkOf(eyes[l + s], "open", rigAt("eye" + s))) eyeSet.add(x + "," + y);
  // the inside of the eyes = not their 1 px outline. Chip's own band rests on the outline at the top of its eyes;
  // a band that follows a slanted eye edge may nick its corner (deadpool-mask: 13 px, 0.7%), hence EYE_COVER
  const inside = (x, y) => [[0, 0], [1, 0], [-1, 0], [0, 1], [0, -1]].every(([dx, dy]) => eyeSet.has(`${x + dx},${y + dy}`));
  const ink = inkOf(hp, firstFrame(hp));
  const covered = ink.filter(([x, y]) => inside(x, y)), eyePx = eyeSet.size;
  const atEyes = (pts) => pts.filter(([, y]) => y >= y0 && y <= y1);
  let head = atEyes(face.flatMap((sp) => inkOf(sp, firstFrame(sp))));
  if (!head.length) head = atEyes([...eyeSet].map((k) => k.split(",").map(Number)));   // no face sprite: the eyes are the face
  const edge = head.length ? [Math.min(...head.map((p) => p[0])), Math.max(...head.map((p) => p[0]))] : null;
  const near = atEyes(ink);
  const reach = edge ? { left: near.some(([x]) => x <= edge[0]), right: near.some(([x]) => x >= edge[1]) } : { left: true, right: true };
  const colours = [...new Set(ink.map(([, , c]) => hp.keys[c]))];
  return { covered, eyePx, coversEyes: covered.length > EYE_COVER * eyePx, rows: [y0, y1], edge, reach, colours };
}

// ---------------------------------------------------------------- reports and text, shared by check() and checkPhones()
// the report both checks print; `what` / `again` word the message the user pastes back to the chatbot
function buildReport(errors, warnings, skin, what = "Your Chip skin", again = "the complete JSON") {
  const shown = errors.slice(0, MAX_ENTRIES), more = errors.length - shown.length;
  const entries = shown.map((e, i) => `${i + 1}. ${e.path}: ${e.problem.replace(/\.$/, "")}. Fix: ${e.fix.replace(/\.$/, "")}.`);
  if (more > 0) entries.push(`(${more} more problems will show after you fix these.)`);
  const ok = errors.length === 0;
  const message = ok
    ? `${what} passed the check.` + (warnings.length ? ` ${warnings.length} optional ${warnings.length === 1 ? "note" : "notes"}: it is fine to leave them.` : "")
    : `${what} didn't pass the check. Fix exactly these problems, keep everything else, and send ${again} again:\n` + entries.join("\n");
  return { ok, errors: shown, omitted: more > 0 ? more : 0, warnings: warnings.slice(0, MAX_ENTRIES), message, skin: ok ? skin : null };
}

// a chatbot reply pasted whole: keep only the first ``` block, with the other lines blanked so line numbers stay true
function unfence(text) {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const lines = text.split("\n"), open = lines.findIndex((l) => /^\s*```/.test(l));
  if (open < 0) return text;
  let close = lines.findIndex((l, i) => i > open && /^\s*```\s*$/.test(l));
  if (close < 0) close = lines.length;
  return lines.map((l, i) => (i > open && i < close ? l : "")).join("\n");
}

// {value} or {problem, fix} in the checks' words
function parseJson(text) {
  try {
    return { value: JSON.parse(text) };
  } catch (e) {
    const pos = Number((/position (\d+)/.exec(e.message) || [])[1]);
    let where = "";
    if (Number.isFinite(pos)) { const before = text.slice(0, pos).split("\n"); where = ` at line ${before.length}, column ${before[before.length - 1].length + 1}`; }
    return {
      problem: text.trim() ? `not valid JSON${where}: ${e.message.replace(/ in JSON at position.*$/, "").replace(/ \(line.*$/, "")}` : "the file is empty",
      fix: "fix the syntax at that spot (a missing comma, quote or bracket) and send plain JSON: no comments, no trailing commas, nothing before or after it",
    };
  }
}

// ---------------------------------------------------------------- check
function check(buf, opts = {}) {
  const errors = [], warnings = [];
  const E = (p, problem, fix) => { errors.push({ path: jp(p), problem, fix }); };
  const W = (p, problem, fix) => { warnings.push({ path: jp(p), problem, fix }); };
  const report = (skin) => buildReport(errors, warnings, skin);

  // --- size and text
  if (buf.length > MAX_BYTES) {
    E([], `the file is ${Math.round(buf.length / 1024)} KB, over the ${MAX_BYTES / 1024} KB limit`, "shrink it: fewer or smaller sprites, fewer frames, no extra spaces or blank lines");
    return report();
  }
  const parsed = parseJson(unfence(buf.toString("utf8")));
  if (parsed.problem) { E([], parsed.problem, parsed.fix); return report(); }
  const skin = parsed.value;
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
    if (!hasPupil) W([...stylePath, "sprites"], `has no pupil sprite, so the dashboard's Small / Medium / Large pupil size does nothing`, `add a pupil sprite with frames "S", "M" and "L", name it in "pupilL" and "pupilR" and set "pupils": ["S", "M", "L"] (leave it out only if the character has no pupils, e.g. blank lenses)`);
    else if (Array.isArray(eyes.pupils) && eyes.pupils.every((s) => SIZES.includes(s)) && eyes.pupils.length < SIZES.length)
      W([...stylePath, "pupils"], `only ${quoted(eyes.pupils).join(", ")} ${eyes.pupils.length === 1 ? "is" : "are"} drawn, so picking ${quoted(SIZES.filter((s) => !eyes.pupils.includes(s))).join(" or ")} on the dashboard changes nothing`, `draw all three sizes: "pupils": ["S", "M", "L"], with an "S", "M" and "L" frame in the pupil sprite`);
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

  // --- mouth, faceBase, faceTop, headphones
  const extra = {};
  for (const slot of ["mouth", "faceBase", "faceTop", "headphones"]) {
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
  if (unusedSprites.length) W(["sprites"], `${quoted(unusedSprites).join(", ")} ${unusedSprites.length === 1 ? "is" : "are"} not used by the eye style, mouth, faceBase, faceTop or headphones`, "remove the sprite, or name it in eyes.sprites / mouth / faceBase / faceTop / headphones");
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
    if (extra.headphones) {   // the ear-cup gap setting splits the sprite at its anchor column
      const sp = resolve(extra.headphones), [w] = P.spriteSize(sp), mid = (w - 1) / 2, o = owner(extra.headphones);
      if (Math.abs(sp.anchor[0] - mid) > 1) W(["sprites", o, "anchor"], `the anchor's x is ${sp.anchor[0]}, but the headphones are ${w} px wide, so their middle is ${mid}`, `put the anchor on the middle column (x ${Math.floor(mid)}) and the head's centre height: the user's ear-cup gap setting widens and narrows the headphones there`);
      else {
        const rows = sp.frames[Object.keys(sp.frames)[0]], mask = (r) => r.padEnd(w, ".").replace(/[^.]/g, "#");
        const lop = rows.filter((r) => mask(r) !== [...mask(r)].reverse().join("")).length;   // the outline, colours may differ
        if (lop > rows.length / 4) W(["sprites", o, "frames"], `${lop} of the ${rows.length} rows aren't the same shape left and right`, "draw the headphones symmetric around the middle column (the ear-cup gap setting moves both cups by the same amount)");
      }
      // how they sit on this face: off the eyes, cups on the ears, shaded
      const fit = phonesFit(sp, { eyeL: resolve(names.eyeL), eyeR: resolve(names.eyeR), frontL: names.frontL && resolve(names.frontL), frontR: names.frontR && resolve(names.frontR) },
        ["faceBase", "faceTop"].filter((k) => extra[k]).map((k) => resolve(extra[k])));
      const f0 = ["sprites", o, "frames", firstFrame(sp)], col = (X) => X + sp.anchor[0], row = (Y) => Y + sp.anchor[1];
      if (fit.coversEyes) {
        const ys = fit.covered.map((p) => p[1]);
        W(f0, `at the default ear-cup gap, ${fit.covered.length} pixels of the headphones (${Math.round(100 * fit.covered.length / fit.eyePx)}% of the eyes) cover the inside of the eyes (open look, eyes anchored at (${rigAt("eyeL")}) and (${rigAt("eyeR")}) from the head's centre), at y ${Math.min(...ys)} to ${Math.max(...ys)} (sprite ${rowsText([...new Set(ys.map(row))].sort((a, b) => a - b))})`,
          "keep the band above the eyes and the cups outside them: raise or narrow the band, or move the cups out (touching the eyes' 1 px outline is fine)");
      }
      if (!fit.reach.left || !fit.reach.right) {
        const sides = !fit.reach.left && !fit.reach.right ? "either side" : !fit.reach.left ? "the left side" : "the right side";
        W(f0, `around eye height (y ${fit.rows[0]} to ${fit.rows[1]} from the head's centre) no pixel reaches the head's edge on ${sides} (x ${fit.edge[0]} and ${fit.edge[1]}, the ${extra.faceBase || extra.faceTop ? "face's" : "eyes'"} outermost pixels there), so the ear cups don't sit on the ears`,
          `draw the ear cups at eye height reaching at least x ${fit.edge[0]} and ${fit.edge[1]} (sprite columns ${col(fit.edge[0])} and ${col(fit.edge[1])}, rows ${row(fit.rows[0])}-${row(fit.rows[1])}), just outside the face`);
      }
      if (fit.colours.length < 3) W(["sprites", o, "keys"], `the headphones use only ${fit.colours.length} ${fit.colours.length === 1 ? "colour" : "colours"} (${quoted(fit.colours).join(", ")}), so they'll look flat`,
        "shade each material with 3 tones (shadow, base, highlight) and give every shape a 1-2 px dark outline");
    }
    for (const slot of ["faceBase", "faceTop", "headphones"]) if (extra[slot]) {
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
// design/headphones.js as the chatbot needs it, read now so it stays in sync: without its first two lines, usage,
// "Fit:" line (the prompt gives the numbers), pack-only palette note, --write branch or alignment padding
function phonesSource() {
  let s = fs.readFileSync(path.join(__dirname, "..", "design", "headphones.js"), "utf8");
  const cut = s.indexOf('\nif (process.argv.includes("--write"))');
  if (cut >= 0) s = s.slice(0, cut) + "\nconsole.log(rows.join(\"\\n\"));\n";
  s = s.split("\n").filter((l, i) => i > 1 && !/^\/\/( {3}node |$| Fit: )|require\(/.test(l)).join("\n");
  return s.replace(/\n\/\/ Palette:[^]*?(?=\n\S*const )/, "").replace(/ {2,}\/\//g, "  //").replace(/\n{3,}/g, "\n\n").trim();
}

// the numbers for a skin's headphones, measured on Chip's own pack so they follow it
function phonesNumbers() {
  const style = pack.eyes.styles[pack.eyes.default].sprites, eye = (k) => pack.sprites[style[k]];
  const hp = pack.sprites.headphones;
  const fit = phonesFit(hp, { eyeL: eye("eyeL"), eyeR: eye("eyeR"), frontL: eye("frontL"), frontR: eye("frontR") }, []);
  const ink = inkOf(hp, firstFrame(hp)), cups = ink.filter(([x, y]) => x > 0 && y >= fit.rows[0] && y <= fit.rows[1]);
  const eyeInk = [...inkOf(eye("eyeL"), "open", rigAt("eyeL")), ...inkOf(eye("frontL"), "open", rigAt("eyeL"))];
  const [ew, eh] = pack.skinSlots.eye, [lx, ly] = rigAt("eyeL"), [rx] = rigAt("eyeR");
  const gap = (/"phonesGap":\s*\((-?\d+),\s*(-?\d+)\)/.exec(fs.readFileSync(path.join(__dirname, "bridge.py"), "utf8")) || [0, -16, 24]).slice(1).map(Number);
  return {
    eyes: `(${lx}, ${ly}) and (${rx}, ${ly})`, eyeBox: `x ${lx - (ew >> 1)}..${lx + (ew >> 1) - 1} and ${rx - (ew >> 1) + 1}..${rx + (ew >> 1)}, y ${ly - (eh >> 1)}..${ly + (eh >> 1) - 1}`,
    eyeSize: `${ew}x${eh}`, rows: fit.rows, half: fit.edge[1], cupIn: Math.min(...cups.map((p) => p[0])), cupOut: Math.max(...cups.map((p) => p[0])),
    band: Math.max(...ink.filter((p) => p[0] === 0).map((p) => p[1])), headTop: Math.min(...eyeInk.map((p) => p[1])),
    top: Math.min(...ink.map((p) => p[1])), gap, colours: fit.colours.length,
  };
}

// the roles list in the prompts: Chip's built-in colour names, as the palette defines them
function builtinColours() {
  return ROLES.map((r) => {
    const t = pack.palette[r];
    return `${r}${t === "accent" ? " (the accent itself)" : t.fixed ? ` (fixed ${t.fixed})` : ""}`;
  });
}

// the sprite format, shared by the skin prompt and the headphones prompt
function spriteRules(roles) {
  return `- "sprites": up to ${MAX_SPRITES}. Each is {"keys": {"<one character>": "<colour>"}, "anchor": [x, y], "glow": 0-1 (optional), "frames": {"<frame>": ["row", "row"]}} or {"mirror": "<other sprite>"} (flips it left-right; use it for the right eye).
  - A row is text, one character per pixel. "." is transparent; every other character must be a key. All rows of a frame have exactly the same length. In error messages the first row is row 0.
  - A key's colour is one of Chip's built-in colours or one of your "colors". Built-in colours: ${roles.join(", ")}. Most follow the accent, so a skin with an accent recolours itself.
  - "anchor" is the pixel of the sprite that sits on the spot where Chip places it; it must be inside the sprite.`;
}

// the headphones rules: where the pair sits, symmetry, the ear-cup gap (shared by the skin prompt and the headphones prompt)
function phonesRules() {
  return `Headphones, "headphones" (optional, but make them: they're part of the character): Chip wears them while music plays. Draw a pair that belongs to this character: their colours, materials and style (armour plates for an armoured hero, a dark matte set for a dark caped one, fur muffs for an animal, a patterned band for a patterned costume, ...), not generic ones.
- At most 128x72 px. The anchor is the head's centre, on the exact middle column of the sprite, at the height of the head's centre; the band arches over the top of faceBase/faceTop and the ear cups sit on the sides of the head at about eye height, just outside the face's edge.
- Left-right symmetric in shape. The middle column holds only the headband: the user's "gap between the ear cups" setting repeats or removes that column to move both cups out or in.
`;
}

// the reference section: how Chip's own pair is drawn, with its code and the numbers to meet (shared likewise)
function phonesReference(hp) {
  return `Reference: how Chip's own headphones are drawn
This program draws Chip's pink pair; its comments teach the method. Reuse the method and geometry, but adapt
the shapes, materials and colour keys to my subject (don't copy the pink style). If you can run code, adapt it,
run it and emit the rows as the "headphones" sprite (one frame, anchor = [middle column, head-centre row]).
Numbers, in px from the head's centre:
- Eyes: anchors ${hp.eyes}, each up to ${hp.eyeSize} (${hp.eyeBox}). Never cover the
  eyes' inside; resting on their top edge is fine.
- Ear cups at eye height (y ${hp.rows[0]}..${hp.rows[1]}), reaching the head's edge on both sides: your faceBase/faceTop's
  outermost pixel at those rows (Chip has none, so its eyes: ${hp.half} px either side; its cups span x ${hp.cupIn}..${hp.cupOut}).
- Band: underside on the middle column at least ${hp.headTop - hp.band} px above the head's highest pixel (faceTop, else faceBase).
  Chip's: underside y ${hp.band}, top y ${hp.top}, eyes from y ${hp.headTop}.
- At least 3 colours (Chip's has ${hp.colours}). The user sets the ear-cup gap from ${hp.gap[0]} to ${hp.gap[1]} px (each cup moves that far
  out); fit the cups at gap 0.
The checker warns about covered eyes, cups that miss the ears, and fewer than 3 colours.
\`\`\`js
${phonesSource()}
\`\`\``;
}

function prompt() {
  const roles = builtinColours();
  const slotLine = Object.entries(pack.skinSlots).map(([k, [w, h]]) => `${k} ${w}x${h}`).join(", ");
  const eyeFrames = Object.keys(pack.sprites.eyeL.frames), mouthFrames = Object.keys(pack.sprites.mouth.frames);
  const fb = (m) => Object.entries(m).map(([a, b]) => `${a} -> ${b}`).join(", ");
  const [lo, hi] = pack.accentLightness;
  const guide = Array.isArray(pack.skinGuide) ? pack.skinGuide.join("\n") : pack.skinGuide || "";
  const hp = phonesNumbers();
  const generated = `
chip-skin/1 is one JSON object. Fields:
- "format": "chip-skin/1"
- "id": 1-32 lowercase letters, digits or "-" (not "draft"). "name": 1-40 characters. "author": optional, at most 40.
- "accent": "#rrggbb" or null. Chip's main colour; every colour derived from it follows. Its lightness is kept between ${lo} and ${hi} (anything else is clamped, and the check warns).
- "colors": up to ${MAX_COLORS} colours of your own, {"name": "#rrggbb"}. A name must not be one of Chip's built-in colours.
${spriteRules(roles)}
- "eyes": one eye style (below). Required.
- "mouth", "faceBase", "faceTop", "headphones": the name of one of your sprites. Optional; Chip keeps its own mouth and headphones and shows no faceBase/faceTop without them. faceBase, faceTop and headphones are drawn from their first frame.
- "name" is the character's name: the phone greets with "Hi! I'm <name>", so use the character's own name (the user can change it when installing).

Where things go (all relative to the head's centre, in pixels; x grows to the right, y downwards):
- faceBase and headphones are placed with their anchor on the head's centre; faceTop's anchor goes there too.
- The eyes are placed with their anchors at (-33, -7) and (33, -7), the mouth's anchor (its top centre) at (0, 21). The user can move each eye up to 12 px inward or 24 px outward, so leave some face around them.
- So draw faceBase with its anchor at the point between the eyes, 7 px below eye level, and leave the eye spots for the eye sprites (they draw on top of it).

${phonesRules()}
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
- PUPIL SIZES (required, the user picks Small, Medium or Large in the dashboard, so draw all three): give the eye a pupil sprite (pupilL/pupilR in "eyes.sprites"), set "pupils": ["S", "M", "L"] and "pupilDefault": "M", and draw exactly three frames in that pupil sprite, named "S", "M" and "L".
  - All three are solid blobs of the same shape in the same colour, drawn on one shared grid and centred on the same anchor (the grid's centre), so switching size only grows or shrinks the pupil around the same point. Make them clearly different: with a grid of N px, use about N/3 for S, N*2/3 for M and the full N for L (for example 2, 4 and 6 px on a 6x6 grid). S must be visibly smaller than M, and M than L.
  - "box" is sized for L: if L fits inside the eye at every gaze position, S and M do too. Never leave out a size or a pupil sprite, or the user's size choice does nothing. Only looks with "pupil": null ignore the size.
- Mouth looks: ${mouthFrames.join(", ")}. Required: neutral. Others fall back: ${fb(pack.fallbacks.mouth)}.

Where the art guide below and these rules differ (for example which eye looks you must draw), these rules win: the checker enforces them.`;

  return `You are making a pixel-art skin for Chip, my desk buddy: a small animated face on an old phone that
stands next to my monitors. It runs on phones and tablets, in landscape and portrait. Read my message and any
pictures I attach, then make ONE chip-skin/1 JSON file that draws my subject, and reply with it. The full spec is below.

What to draw
- My subject can be a character from a film, series, game, comic, anime or a superhero, a pet, a person (me),
  my own concept art, or an idea I describe. Draw it as it really looks: its real head or mask shape, eyes, hair
  or fur, colours, signature details and headphones. It must be recognisable at a glance.
- Don't make the head round, don't put the face in a circle, and don't simplify it or make it cuter than the
  subject, unless the subject itself is round.
- "name": the subject's own name, unless I give one. Eyes: draw the subject's own eye shape.
- Pupil sizes: Chip's Small, Medium and Large settings are part of the spec below. Draw all three.
- Headphones: always draw a pair in the subject's style (armour plates, matte black, fur muffs, a patterned band...).

Screens: phones and tablets, landscape and portrait
- Chip's face is always a 320 x 180 pixel grid. It is scaled up to fit each screen with black bars around it, so
  one file works on a small phone, a large phone and a tablet. Don't draw separate sizes.
- Every pixel of art must be inside the 320 x 180 grid. Keep the face between about y 22 and y 150. The middle of
  the head is at (167, 74). The speech bubble covers the top rows and the status bar the bottom ~30 rows.
- A pixel is about 0.65 mm on a phone and larger on a tablet, so details under 2 px disappear. Use bold shapes,
  flat colours and clean outlines, and check that it reads at arm's length and in peripheral vision.
- On a portrait tablet the face is smaller with more black around it. Avoid thin edges and tiny decorations that
  depend on the full width.

How to work
1. Reply with at most three short lines of notes (what you took from my text and pictures, and any choice you
   made), then the complete JSON in one \`\`\`json code block, or as a downloadable file named <id>.json. Nothing else.
2. Don't ask questions unless something essential is missing. Choose sensible defaults and say so in one line.
3. If you can run code, build the JSON with code (shrink pictures and reduce them to the colours) and check every
   rule below before you reply: row lengths, colour keys, sprite sizes, anchors, all three pupil sizes, symmetric
   headphones, and file size.
4. If I paste validation errors back, fix exactly those, keep everything else, and send the whole JSON again.

Format, slots, frames, colours:
${generated}

Art guide from Chip's designer:
${guide}

${phonesReference(hp)}

Smallest valid example. It only shows the format: its square eyes and missing face are not a style to copy;
yours has the subject's own head, eyes and headphones:
\`\`\`json
${pretty(example())}
\`\`\`
`;
}

// ---------------------------------------------------------------- headphones for an installed skin (chip-phones/1)
// {"format": "chip-phones/1", "from": "<skin id>", "colors": {...}, "sprites": {...}, "headphones": "<sprite>"}: the same
// shape GET /skins/<id>/headphones.json serves. The chatbot draws one to fit an installed skin's head; check-phones merges
// it into a copy of the skin and runs the full check() on the result.
const PHONES_FORMAT = "chip-phones/1", PHONES_KEYS = ["format", "from", "colors", "sprites", "headphones"];
const cap = (n) => n.charAt(0).toUpperCase() + n.slice(1);

// the sprite called `name` as the phone sees it (mirrors flipped), or undefined
function spriteOf(skin, name, depth = 0) {
  const sp = isObj(skin.sprites) && own(skin.sprites, name) ? skin.sprites[name] : null;
  if (!isObj(sp) || depth > 9) return undefined;
  if (typeof sp.mirror === "string") { const t = spriteOf(skin, sp.mirror, depth + 1); return t && P.mirrored(t); }
  return sp;
}
// a sprite and the sprites its mirror chain reaches
function chainOf(skin, name) {
  const out = [];
  while (typeof name === "string" && isObj(skin.sprites) && isObj(skin.sprites[name]) && !out.includes(name) && out.length < 10) { out.push(name); name = skin.sprites[name].mirror; }
  return out;
}
const keyColours = (sp) => (isObj(sp) && isObj(sp.keys) ? Object.values(sp.keys).filter((c) => typeof c === "string") : []);

// the skin without its headphones: the pair's sprites (unless another slot draws with them) and the colours only they used
function withoutPhones(skin) {
  const out = { ...skin, colors: { ...(isObj(skin.colors) ? skin.colors : {}) }, sprites: { ...(isObj(skin.sprites) ? skin.sprites : {}) } };
  delete out.headphones;
  const mine = chainOf(skin, skin.headphones);
  const others = new Set([...Object.values(isObj(skin.eyes) && isObj(skin.eyes.sprites) ? skin.eyes.sprites : {}), skin.mouth, skin.faceBase, skin.faceTop].filter((n) => typeof n === "string").flatMap((n) => chainOf(skin, n)));
  for (const [n, sp] of Object.entries(skin.sprites || {})) if (!mine.includes(n) && isObj(sp) && typeof sp.mirror === "string") chainOf(skin, sp.mirror).forEach((m) => others.add(m));
  const removed = mine.filter((n) => !others.has(n)), dropped = new Set(removed.flatMap((n) => keyColours(skin.sprites[n])));
  removed.forEach((n) => delete out.sprites[n]);
  const kept = new Set(Object.values(out.sprites).flatMap(keyColours));
  for (const c of dropped) if (!kept.has(c)) delete out.colors[c];
  return out;
}

// {errors, warnings, merged, phones}: the skin with this pair put on, or what stops it. paths are those of the chip-phones
// file, which are also the merged skin's ($.colors.x, $.sprites.x, $.headphones)
function mergePhones(skin, ph, replace) {
  const errors = [], warnings = [], E = (p, problem, fix) => errors.push({ path: jp(p), problem, fix });
  if (!isObj(ph)) { E([], "the top level must be one JSON object { ... }", `wrap everything in a single object starting with {"format": "${PHONES_FORMAT}", ...}`); return { errors, warnings }; }
  if (ph.format !== PHONES_FORMAT) E(["format"], `is ${JSON.stringify(ph.format)}`, `set "format": "${PHONES_FORMAT}"`);
  const extra = Object.keys(ph).filter((k) => !PHONES_KEYS.includes(k));
  if (extra.length) warnings.push({ path: jp([]), problem: `unknown ${extra.length === 1 ? "field" : "fields"} ${quoted(extra).join(", ")} will be ignored`, fix: `remove ${extra.length === 1 ? "it" : "them"} (allowed here: ${PHONES_KEYS.join(", ")})` });
  const colors = ph.colors === undefined ? {} : ph.colors;
  if (!isObj(colors)) E(["colors"], "must be an object {\"name\": \"#rrggbb\"}", `use {} if you add no colours, or e.g. {"hpMetal": "#8a8f98"}`);
  if (!isObj(ph.sprites) || !Object.keys(ph.sprites).length) E(["sprites"], "must be an object with the headphones sprite and the sprites it mirrors", `add "sprites": {"<name>": {"keys": {...}, "anchor": [x, y], "frames": {"on": [rows]}}}`);
  if (typeof ph.headphones !== "string" || !isObj(ph.sprites) || !own(ph.sprites, ph.headphones))
    E(["headphones"], `${typeof ph.headphones === "string" ? JSON.stringify(ph.headphones) + " isn't" : "isn't"} the name of a sprite in this file`, `set "headphones" to the name of the pair's sprite, one of ${isObj(ph.sprites) ? quoted(Object.keys(ph.sprites)).join(", ") : "your sprites"}`);
  if (errors.length) return { errors, warnings };
  for (const [n, sp] of Object.entries(ph.sprites)) if (isObj(sp) && typeof sp.mirror === "string" && !own(ph.sprites, sp.mirror))
    E(["sprites", n, "mirror"], `mirrors ${JSON.stringify(sp.mirror)}, which isn't in this file (the pair must be self-contained)`, `mirror one of your own sprites, or draw ${JSON.stringify(n)} out in full`);

  const hasPair = typeof skin.headphones === "string";
  if (hasPair && !replace) {
    E(["headphones"], `this skin already has headphones (the sprite ${JSON.stringify(skin.headphones)})`, "choose Redo headphones to replace them (on the command line: --replace)");
    return { errors, warnings };
  }
  const base = hasPair && replace ? withoutPhones(skin) : skin;
  const baseColors = isObj(base.colors) ? base.colors : {}, baseSprites = isObj(base.sprites) ? base.sprites : {};
  const free = (taken, name) => { let n = "hp" + cap(name.replace(/^hp(?=[A-Z])/, "")), i = 2; const stem = n; while (own(taken, n) || own(colors, n) || own(ph.sprites, n)) n = stem + i++; return n; };
  if (isObj(colors)) for (const n of Object.keys(colors)) if (own(baseColors, n))
    E(["colors", n], `the colour name ${JSON.stringify(n)} is already one of this skin's colours (${JSON.stringify(baseColors[n])})`,
      `rename it, e.g. to ${JSON.stringify(free(baseColors, n))}, in "colors" and in every sprite key that uses it; or delete it here and use the skin's ${JSON.stringify(n)} by name`);
  for (const n of Object.keys(ph.sprites)) if (own(baseSprites, n))
    E(["sprites", n], `the sprite name ${JSON.stringify(n)} is already one of this skin's sprites`,
      `rename it, e.g. to ${JSON.stringify(free(baseSprites, n))}, here and wherever "headphones" or a "mirror" names it`);
  const nc = isObj(colors) ? Object.keys(colors).length : 0, ns = Object.keys(ph.sprites).length, bc = Object.keys(baseColors).length, bs = Object.keys(baseSprites).length;
  if (bc + nc > MAX_COLORS) E(["colors"], `adds ${nc} ${nc === 1 ? "colour" : "colours"} to the skin's ${bc}, over the ${MAX_COLORS}-colour limit`,
    `add at most ${Math.max(0, MAX_COLORS - bc)} new ${MAX_COLORS - bc === 1 ? "colour" : "colours"}: draw with the skin's own colours by name (shade with them) instead of new ones`);
  if (bs + ns > MAX_SPRITES) E(["sprites"], `adds ${ns} ${ns === 1 ? "sprite" : "sprites"} to the skin's ${bs}, over the ${MAX_SPRITES}-sprite limit`,
    `add at most ${Math.max(0, MAX_SPRITES - bs)}: one sprite for the pair, plus its mirror if you need one`);
  if (errors.length) return { errors, warnings };
  const merged = { ...base, colors: { ...baseColors, ...colors }, sprites: { ...baseSprites, ...ph.sprites }, headphones: ph.headphones };
  return { errors, warnings, merged, phones: { format: PHONES_FORMAT, from: skin.id, colors, sprites: ph.sprites, headphones: ph.headphones } };
}

// the report for a chip-phones/1 reply against an installed skin (skinBuf = its file). A pass carries the merged skin as
// `clean` (minified, for the bridge to store) and the normalised pair as `phones` when opts.clean is set.
function checkPhones(skinBuf, phonesBuf, opts = {}) {
  const errors = [], E = (p, problem, fix) => errors.push({ path: jp(p), problem, fix });
  const done = (warnings = [], skin = null) => buildReport(errors, warnings, skin, "Your headphones", "the complete chip-phones/1 JSON");
  let skin;
  try { skin = JSON.parse(skinBuf.toString("utf8")); } catch (e) { skin = null; }
  if (!isObj(skin)) { E([], "the skin file to put the headphones on isn't valid JSON", "check that the skin is installed"); return done(); }
  if (phonesBuf.length > MAX_BYTES) { E([], `the file is ${Math.round(phonesBuf.length / 1024)} KB, over the ${MAX_BYTES / 1024} KB limit`, "shrink it: fewer or smaller sprites, no extra spaces or blank lines"); return done(); }
  const parsed = parseJson(unfence(phonesBuf.toString("utf8")));
  if (parsed.problem) { E([], parsed.problem, parsed.fix); return done(); }
  const m = mergePhones(skin, parsed.value, !!opts.replace);
  errors.push(...m.errors);
  if (errors.length) return done(m.warnings);
  const r = check(Buffer.from(JSON.stringify(m.merged)), { clean: true });
  // the merged skin's own notes (eye looks it doesn't draw, ...) aren't about the pair: keep what names its sprites or colours
  const paths = Object.keys(m.phones.sprites).map((n) => jp(["sprites", n])), names = [...Object.keys(m.phones.sprites), ...Object.keys(m.phones.colors)].map((n) => JSON.stringify(n));
  const mine = (w) => paths.some((q) => w.path === q || w.path.startsWith(q + ".") || w.path.startsWith(q + "[")) || w.path === "$.headphones" || names.some((n) => w.problem.includes(n));
  if (!r.ok) { errors.push(...r.errors.map((e) => ({ ...e }))); const out = done(m.warnings.concat(r.warnings.filter(mine))); out.omitted += r.omitted; return out; }
  const out = done(m.warnings.concat(r.warnings.filter(mine)), r.skin);
  if (opts.clean && out.ok) { out.clean = r.clean; out.phones = m.phones; }
  return out;
}

// ---------------------------------------------------------------- prompt-phones: the chatbot prompt for headphones only
// what the prompt tells about one skin: its colours, the face plate rows and how its head measures
function promptPhones(skin) {
  const resolve = (n) => (typeof n === "string" ? spriteOf(skin, n) : undefined);
  const sprites = isObj(skin.sprites) ? skin.sprites : {}, colors = isObj(skin.colors) ? skin.colors : {};
  const es = isObj(skin.eyes) && isObj(skin.eyes.sprites) ? skin.eyes.sprites : {};
  const faces = ["faceBase", "faceTop"].filter((k) => resolve(skin[k]));
  const fit = phonesFit({ keys: {}, anchor: [0, 0], frames: { on: [] } }, { eyeL: resolve(es.eyeL), eyeR: resolve(es.eyeR), frontL: resolve(es.frontL), frontR: resolve(es.frontR) }, faces.map((k) => resolve(skin[k])));
  const pts = (sp, at = [0, 0]) => inkOf(sp, firstFrame(sp), at);
  const faceInk = faces.flatMap((k) => pts(resolve(skin[k])));
  const eyeInk = ["L", "R"].flatMap((side) => ["eye", "front"].flatMap((l) => (resolve(es[l + side]) ? inkOf(resolve(es[l + side]), "open", rigAt("eye" + side)) : [])));
  const top = Math.min(...(faceInk.length ? faceInk : eyeInk).map((p) => p[1]));
  const eyeOut = Math.max(0, ...eyeInk.map((p) => Math.abs(p[0])));   // how far out the eyes reach
  const cupFrom = Math.max(fit.edge ? Math.max(Math.abs(fit.edge[0]), fit.edge[1]) : 0, eyeOut + 1);
  const box = (ink, sign) => { const q = ink.filter((p) => Math.sign(p[0]) === sign); return q.length ? `x ${Math.min(...q.map((p) => p[0]))}..${Math.max(...q.map((p) => p[0]))}, y ${Math.min(...q.map((p) => p[1]))}..${Math.max(...q.map((p) => p[1]))}` : "none"; };
  const rows = (k) => {
    const sp = resolve(skin[k]), name = skin[k], fr = firstFrame(sp), legend = Object.entries(sp.keys || {}).map(([c, v]) => `${c} = ${v}`).join(", ");
    return `${k}: sprite ${JSON.stringify(name)}, ${P.spriteSize(sp).join("x")} px, anchor [${sp.anchor}] (a pixel at row r, column c lies at x ${"c"} - ${sp.anchor[0]}, y r - ${sp.anchor[1]} from the head's centre), keys: ${legend}\n` +
      sp.frames[fr].map((r, i) => `${String(i).padStart(3)} ${r}`).join("\n");
  };
  const used = Object.keys(colors).length, roles = builtinColours(), hp = phonesNumbers();
  const left = (n, max) => Math.max(0, max - n);
  const colorLines = Object.entries(colors).map(([k, v]) => `  ${k}: ${v}`).join("\n") || "  (none: the skin only uses Chip's built-in colours)";
  return `You are drawing headphones for an existing character on Chip, my desk buddy: a small animated pixel-art face on an old
phone next to my monitors. The character is already made: "${skin.name}" (id ${JSON.stringify(skin.id)}). Make ONLY its headphones,
so they fit its head, and reply with ONE chip-phones/1 JSON file. Don't change or resend the skin.

How to work
1. Reply with at most three short lines of notes, then the complete JSON in one \`\`\`json code block, or as a downloadable
   file named ${skin.id}-headphones.json. Nothing else. Don't ask questions: choose sensible defaults and say so in one line.
2. If you can run code, build the sprite with code and check every rule below before you reply.
3. If I paste validation errors back, fix exactly those, keep everything else, and send the whole JSON again.

The reply, chip-phones/1:
{"format": "${PHONES_FORMAT}", "from": ${JSON.stringify(skin.id)}, "colors": {"<new colour>": "#rrggbb"}, "sprites": {"<name>": <sprite>}, "headphones": "<name of the pair's sprite>"}
${spriteRules(roles)}
  - "colors" holds only NEW colours. A key may also name one of the skin's colours (below) or a built-in one, without listing it.
  - Names must be new: they get merged into the skin, so a colour or sprite name the skin already has is refused. Start every new name with "hp" (hpBand, hpFoam, hpPair, ...).
  - Self-contained: "headphones" names a sprite in this file, and a "mirror" may only name another sprite of this file. At most 1 frame is drawn (the first).

${phonesRules()}
This character
- Accent: ${skin.accent ? skin.accent : "none (it follows the accent I pick, so built-in colours that follow the accent change with it)"}.
- The skin's own colours (use them by name to match the character; add new ones only for what it lacks):
${colorLines}
- Room left: ${left(used, MAX_COLORS)} new colours (the skin has ${used} of ${MAX_COLORS}) and ${left(Object.keys(sprites).length, MAX_SPRITES)} new sprites (${Object.keys(sprites).length} of ${MAX_SPRITES} used).
- Sprites already in the skin (don't reuse these names): ${quoted(Object.keys(sprites)).join(", ")}.
- Measured on this head (px from its centre, x right, y down; the checker uses the same numbers):
  - eyes: left ${box(eyeInk, -1)}; right ${box(eyeInk, 1)} (open look, anchored at (${rigAt("eyeL")}) and (${rigAt("eyeR")})).
  - the head ${faces.length ? `is the ${faces.join(" and ")} plate: its highest pixel is at y ${top}` : `has no face plate: the eyes are the face, their highest pixel is at y ${top}`}.
  - at eye height (y ${fit.rows[0]}..${fit.rows[1]}) the head's edge is at x ${fit.edge ? fit.edge[0] + " and " + fit.edge[1] : "?"} and the eyes reach out to x ${-eyeOut} and ${eyeOut}: the ear cups sit outside both, so their inner side starts at |x| ${cupFrom} or more (never on the eyes), on both sides.
  - the band's underside on the middle column goes at least 5 px above y ${top}. The whole pair must fit in 72 rows: with a band about 9 px thick, keep it within y ${top - 14} to y ${top - 14 + 71}.
${faces.length ? "\n" + faces.map(rows).join("\n\n") + "\n" : ""}
${phonesReference(hp)}
`;
}

// ---------------------------------------------------------------- main
const [cmd, arg, ...rest] = process.argv.slice(2);
if (cmd === "check" && arg) {
  process.stdout.write(JSON.stringify(check(arg === "-" ? fs.readFileSync(0) : fs.readFileSync(arg), { clean: rest.includes("--clean") })));
} else if (cmd === "prompt") {
  process.stdout.write(prompt());
} else if (cmd === "prompt-phones" && arg) {
  let skin;
  try { skin = JSON.parse(fs.readFileSync(arg, "utf8")); } catch (e) { console.error(`can't read the skin ${arg}: ${e.message}`); process.exit(1); }
  if (!isObj(skin) || typeof skin.id !== "string") { console.error(`${arg} isn't a skin file`); process.exit(1); }
  process.stdout.write(promptPhones(skin));
} else if (cmd === "check-phones" && arg && rest.some((a) => !a.startsWith("--"))) {
  const src = rest.find((a) => !a.startsWith("--"));
  let skinBuf;
  try { skinBuf = fs.readFileSync(arg); } catch (e) { console.error(`can't read the skin ${arg}: ${e.message}`); process.exit(1); }
  process.stdout.write(JSON.stringify(checkPhones(skinBuf, src === "-" ? fs.readFileSync(0) : fs.readFileSync(src), { replace: rest.includes("--replace"), clean: rest.includes("--clean") })));
} else if (cmd === "example") {
  process.stdout.write(pretty(example()) + "\n");
} else {
  console.error("usage: node laptop/skin.js check -|<file> [--clean] | prompt | example | prompt-phones <skin> | check-phones <skin> -|<file> [--replace] [--clean]");
  process.exit(2);
}
