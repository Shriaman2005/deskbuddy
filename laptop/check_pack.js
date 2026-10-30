#!/usr/bin/env node
// Verifies phone/www/pack.json: sprites use only palette tokens, <=20 tokens, sprites <=128x96,
// and the palette derives inside sRGB for every accent. Usage: node laptop/check_pack.js [pack.json]
const fs = require("fs"), path = require("path");
const www = path.join(__dirname, "..", "phone", "www");
const P = require(path.join(www, "pack.js"));
const pack = JSON.parse(fs.readFileSync(process.argv[2] || path.join(www, "pack.json"), "utf8"));

const errs = [];
const err = (m) => errs.push(m);
if (pack.format !== "chip-pack/1") err("format is " + pack.format);

const tokens = Object.keys(pack.palette);
const used = new Set();
let frames = 0;
for (const [name, sp] of Object.entries(pack.sprites)) {
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
if (used.size > 20) err(`sprites use ${used.size} tokens (max 20)`);
if (tokens.length > 20) err(`palette defines ${tokens.length} tokens (max 20)`);

// every accent must derive valid hex; main is clamped into accentLightness
for (const acc of ["#2ee6f2", "#ee9358", "#b4d38c", "#ffffff", "#000000", "#ff0000"]) {
  const pal = P.derivePalette(pack, acc);
  for (const [t, v] of Object.entries(pal)) if (!/^#[0-9a-f]{6}$/.test(v)) err(`${acc}: ${t} = ${v}`);
  const l = P.hexToOklch(pal.main).l, [lo, hi] = pack.accentLightness;
  if (l < lo - 0.01 || l > hi + 0.01) err(`${acc}: main lightness ${l.toFixed(3)} outside [${lo},${hi}]`);
}

console.log(`${Object.keys(pack.sprites).length} sprites, ${frames} frames, ${used.size} tokens used / ${tokens.length} defined`);
if (errs.length) { console.log(errs.slice(0, 20).join("\n")); process.exit(1); }
console.log("pack OK");
