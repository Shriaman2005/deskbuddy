#!/usr/bin/env node
// Verifies phone/www/pack.json: sprites use only palette tokens, <=22 tokens, sprites <=128x96, mirror targets
// exist, and the palette derives inside sRGB for every accent. chip-pack/2 also: fallback chains end at a required
// frame, every eye style resolves all 24 eye frames and every frame moods, clips and states use, pupils stay on the
// visible eye or under the front layer at all 9 gaze positions and every size, skin slots fit 128x96.
// Usage: node laptop/check_pack.js [pack.json]
const fs = require("fs"), path = require("path");
const www = path.join(__dirname, "..", "phone", "www");
const P = require(path.join(www, "pack.js"));
const pack = JSON.parse(fs.readFileSync(process.argv[2] || path.join(www, "pack.json"), "utf8"));

const errs = [];
const err = (m) => errs.push(m);
if (!/^chip-pack\/[12]$/.test(pack.format)) err("format is " + pack.format);
const MAX_TOKENS = 22;   // chip-pack/2 adds pupil and eyelid to chip-pack/1's 20

// mirrors resolved, like pack.js does
const src = {};
function sprite(name, seen = []) {
  const sp = pack.sprites[name];
  if (!sp) return null;
  if (!sp.mirror) return sp;
  if (seen.includes(name)) { err(`${name}: mirror loop ${seen.join(" -> ")}`); return null; }
  if (!pack.sprites[sp.mirror]) { err(`${name}: mirrors missing sprite ${sp.mirror}`); return null; }
  const s = sprite(sp.mirror, [...seen, name]);
  return src[name] || (src[name] = s && P.mirrored(s));
}

const tokens = Object.keys(pack.palette);
const used = new Set();
let frames = 0;
for (const name of Object.keys(pack.sprites)) {
  const sp = sprite(name);
  if (!sp) continue;
  for (const [ch, tok] of Object.entries(sp.keys)) {
    used.add(tok);
    if (!tokens.includes(tok)) err(`${name}: key '${ch}' -> unknown token '${tok}'`);
    if (ch === ".") err(`${name}: '.' is reserved for clear`);
  }
  for (const [f, rows] of Object.entries(sp.frames)) {
    frames++;
    rows.forEach((r, y) => [...r].forEach((c, x) => {
      if (c !== "." && !sp.keys[c]) err(`${name}/${f}: char '${c}' at ${x},${y} has no token`);
    }));
  }
  const [w, h] = P.spriteSize(sp);
  if (w > 128 || h > 96) err(`${name}: ${w}x${h} exceeds 128x96`);
  if (sp.anchor[0] > w || sp.anchor[1] > h) err(`${name}: anchor outside sprite`);
}
if (used.size > MAX_TOKENS) err(`sprites use ${used.size} tokens (max ${MAX_TOKENS})`);
if (tokens.length > MAX_TOKENS) err(`palette defines ${tokens.length} tokens (max ${MAX_TOKENS})`);

const ids = new Set(pack.rig.map((l) => l.id));
for (const l of pack.rig) {
  if (l.sprite && !pack.sprites[l.sprite]) err(`rig ${l.id}: sprite ${l.sprite} missing`);
  if (l.sprite === null && !l.hidden) err(`rig ${l.id}: a sprite-less slot must be hidden`);
  if (l.parent && !ids.has(l.parent)) err(`rig ${l.id}: parent ${l.parent} missing`);
}

// every accent must derive valid hex; main is clamped into accentLightness
for (const acc of ["#2ee6f2", "#ee9358", "#b4d38c", "#ffffff", "#000000", "#ff0000"]) {
  const pal = P.derivePalette(pack, acc);
  for (const [t, v] of Object.entries(pal)) if (!/^#[0-9a-f]{6}$/.test(v)) err(`${acc}: ${t} = ${v}`);
  const l = P.hexToOklch(pal.main).l, [lo, hi] = pack.accentLightness;
  if (l < lo - 0.01 || l > hi + 0.01) err(`${acc}: main lightness ${l.toFixed(3)} outside [${lo},${hi}]`);
}

let placements = 0;
if (pack.eyes) {
  // fallback chains: no loops, each ends at a required frame
  const REQUIRED = { eye: ["open", "half", "shut"], mouth: ["neutral"] };
  const chain = (map, f) => {
    const out = [f];
    while (map && map[f] && out.length < 16) out.push((f = map[f]));
    return out;
  };
  for (const [kind, map] of Object.entries(pack.fallbacks || {})) for (const f of Object.keys(map)) {
    const ch = chain(map, f);
    if (ch.length >= 16) err(`fallbacks.${kind}: loop from ${f}`);
    else if (!REQUIRED[kind] || !REQUIRED[kind].includes(ch[ch.length - 1])) err(`fallbacks.${kind}: ${ch.join(" -> ")} ends off a required frame`);
  }

  // the eye and mouth frames in use: the 24 of chip-pack/1's eye sprites plus every one a mood, clip or state names
  const want = P.usedFrames(pack);
  if (want.eyeL.size < 24) err(`eyeL has ${want.eyeL.size} frames, expected at least 24`);
  const mouth = sprite("mouth");
  for (const f of want.mouth) if (!P.chain(pack.fallbacks && pack.fallbacks.mouth, f).some((n) => mouth.frames[n])) err(`mouth ${f} (${want.at["mouth" + f]}) does not resolve`);

  const LAYERS = ["eyeL", "eyeR", "pupilL", "pupilR", "frontL", "frontR"];
  if (!pack.eyes.styles[pack.eyes.default]) err(`eyes.default ${pack.eyes.default} is not a style`);
  for (const [sid, st] of Object.entries(pack.eyes.styles)) {
    for (const id of LAYERS) if (!sprite(st.sprites[id])) err(`style ${sid}: ${id} sprite ${st.sprites[id]} missing`);
    if (LAYERS.some((id) => !sprite(st.sprites[id]))) continue;
    if (!st.pupils.includes(st.pupilDefault)) err(`style ${sid}: pupilDefault ${st.pupilDefault} not in pupils`);
    const env = { style: st, names: st.sprites, fb: pack.fallbacks.eye, spr: sprite };
    for (const id of ["eyeL", "eyeR"]) for (const f of want[id]) {
      const at = `style ${sid} ${id} ${f}` + (want.at[id + f] ? ` (${want.at[id + f]})` : "");
      const look = P.eyeLook(env, id, f, st.pupilDefault);
      if (!look.key) { err(`${at}: no frame definition, directly or via fallbacks`); continue; }
      if (!sprite(st.sprites[id]).frames[look.back]) { err(`${at}: back frame ${look.back} missing`); continue; }
      if (!look.def.pupil) continue;
      if (!look.box && look.def.pupil === "auto") { err(`${at}: pupil without a box`); continue; }
      // every pupil pixel on a drawn back pixel or under a drawn front pixel; 9 gaze positions, every size, converge
      for (const size of look.def.pupil === "auto" ? st.pupils : [look.def.pupil]) placements += 9 * (st.converge ? 2 : 1);
      const fit = P.pupilFit(env, id, f);
      for (const m of fit.missing) err(`${at}: pupil frame ${m} missing`);
      for (const b of fit.bad) err(`${at}: pupil ${b.size} at gaze ${b.gx},${b.gy}${b.conv ? " converged" : ""} has ${b.px} px off the eye`);
    }
  }

  for (const [slot, [w, h]] of Object.entries(pack.skinSlots || {})) if (w > 128 || h > 96) err(`skinSlots.${slot}: ${w}x${h} exceeds 128x96`);
}

console.log(`${Object.keys(pack.sprites).length} sprites, ${frames} frames, ${used.size} tokens used / ${tokens.length} defined` +
  (pack.eyes ? `, ${Object.keys(pack.eyes.styles).length} eye styles, ${placements} pupil placements` : ""));
if (errs.length) { console.log(errs.slice(0, 30).join("\n") + (errs.length > 30 ? `\n... ${errs.length - 30} more` : "")); process.exit(1); }
console.log("pack OK");
