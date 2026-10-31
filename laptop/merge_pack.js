#!/usr/bin/env node
// Merges a design delta into Chip's pack: additions only. New keys are added, changed values are listed, and
// anything that would remove (null over a value) or rename (a rig id or sprite added twice with other content)
// stops the merge. rigAdd layers go into the rig at their `before` / `after` spot (those two keys are dropped).
// Running it again with the same delta changes nothing.
// Usage: node laptop/merge_pack.js <delta.json> [pack.json] [out.json]   (pack and out default to phone/www/pack.json)
const fs = require("fs"), path = require("path");
const [deltaPath, packPath = path.join(__dirname, "..", "phone", "www", "pack.json"), outPath = packPath] = process.argv.slice(2);
if (!deltaPath) { console.error("usage: node laptop/merge_pack.js <delta.json> [pack.json] [out.json]"); process.exit(2); }
const pack = JSON.parse(fs.readFileSync(packPath, "utf8")), delta = JSON.parse(fs.readFileSync(deltaPath, "utf8"));

const errs = [], changed = [];
let added = 0;
const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function add(base, d, at) {
  for (const [k, v] of Object.entries(d)) {
    const p = at ? at + "." + k : k;
    if (!(k in base)) { base[k] = v; added++; }
    else if (v === null && base[k] !== null) errs.push(`${p}: null would remove it`);
    else if (same(base[k], v)) continue;
    else if (at === "sprites" || at === "palette") errs.push(`${p}: already exists with other content (rename it in the delta)`);
    else if (isObj(base[k]) && isObj(v)) add(base[k], v, p);
    else { changed.push(`${p}: ${JSON.stringify(base[k]).slice(0, 60)} -> ${JSON.stringify(v).slice(0, 60)}`); base[k] = v; }
  }
}

// format: chip-pack/N only moves up
const ver = (f) => Number(String(f || "").split("/")[1]) || 0;
if (delta.format && ver(delta.format) < ver(pack.format)) errs.push(`format ${delta.format} is older than ${pack.format}`);

// rig layers, each placed next to the layer it names
const rig = pack.rig;
for (const layer of delta.rigAdd || []) {
  const { before, after, ...l } = layer;
  const have = rig.findIndex((r) => r.id === l.id);
  if (have >= 0) {
    if (!same(rig[have], l)) errs.push(`rigAdd ${l.id}: a layer with that id exists with other content`);
    continue;
  }
  if (l.parent && !rig.some((r) => r.id === l.parent)) { errs.push(`rigAdd ${l.id}: parent ${l.parent} not in the rig`); continue; }
  const ref = before || after, i = rig.findIndex((r) => r.id === ref);
  if (!ref || i < 0) { errs.push(`rigAdd ${l.id}: ${before ? "before" : "after"} ${ref} not in the rig`); continue; }
  rig.splice(before ? i : i + 1, 0, l);
  added++;
}

// the pack's own layout: a value on one line when it fits in 128 columns, sprite rows one per line
function pretty(v, ind = "", lead = 0) {
  const flat = JSON.stringify(v, null, 1).replace(/\n\s*/g, " ").replace(/([[{]) /g, "$1").replace(/ ([\]}])/g, "$1");
  const rows = (x) => Array.isArray(x) ? x.every((s) => typeof s === "string") && x.some((s) => !s || /[.#]/.test(s))
    : isObj(x) && Object.values(x).some(rows);
  if (!isObj(v) && !Array.isArray(v) || (!rows(v) && ind.length + lead + flat.length < 128)) return flat;
  const inner = ind + "  ";
  if (Array.isArray(v) && !rows(v) && v.every((x) => !isObj(x))) {   // keyframes: as many to a line as fit
    const lines = [""];
    for (const x of v.map((x) => pretty(x))) {
      if (lines[lines.length - 1] && inner.length + lines[lines.length - 1].length + x.length > 118) lines.push("");
      lines[lines.length - 1] += (lines[lines.length - 1] ? " " : "") + x + ",";
    }
    return "[\n" + lines.map((l) => inner + l).join("\n").slice(0, -1) + "\n" + ind + "]";
  }
  const items = Array.isArray(v) ? v.map((x) => inner + pretty(x, inner))
    : Object.entries(v).map(([k, x]) => inner + JSON.stringify(k) + ": " + pretty(x, inner, JSON.stringify(k).length + 2));
  return (Array.isArray(v) ? "[" : "{") + "\n" + items.join(",\n") + "\n" + ind + (Array.isArray(v) ? "]" : "}");
}

const { format, rigAdd, ...rest } = delta;
add(pack, rest, "");
if (errs.length) { console.error("merge refused:\n  " + errs.join("\n  ")); process.exit(1); }
if (format) pack.format = format;

fs.writeFileSync(outPath, pretty(pack));
console.log(`${path.basename(deltaPath)} -> ${outPath}: ${pack.format}, ${added} additions, ${changed.length} changes`);
changed.forEach((c) => console.log("  changed " + c));
