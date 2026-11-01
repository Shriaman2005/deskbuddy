#!/usr/bin/env node
// Draws Chip's default headphones (pack.json sprites.headphones) from a few shapes, so the art is easy to tweak.
//   node design/headphones.js            prints the rows
//   node design/headphones.js --write    writes the sprite into phone/www/pack.json
//
// The method (works for any character: keep the geometry, change shapes, materials and colour keys):
// 1. X, Y = px from the head's centre (the anchor), y down. Draw the right half and mirror it with both(): the
//    pair is symmetric around column X = 0, which holds only the band (the ear-cup gap setting repeats or cuts it).
// 2. Band = the area between two ellipses (OUT, IN). depth() runs 0 (outer edge) .. 1 (inner edge) and picks
//    the colour, so stripes follow the curve: outline / sheen / main / accent stripe / main / outline.
// 3. Cushion under the band: inside IN, outside a smaller PAD ellipse, outlined, stitched every 4th px.
// 4. Ear cups = rounded boxes (inBox): shell (main colour), rim (accent, face side and bottom), cushion
//    against the face (dark, with a crease), highlight (sheen stripe, glint on the badge). Sliders join band and cups.
// 5. Shading: 3 tones per material (shadow / base / highlight), never one flat colour.
// 6. Outline: 1 px dark edge on every shape (edgeOf), 2 px where a curve steps diagonally so it never breaks.
// Fit: cups at |X| 51..63, Y -12..10 (just outside the eyes at (-33,-7)/(33,-7)); band underside at Y -33.
// Palette: the pack's 22 tokens are all taken, so the shell is the fixed pink, trims follow the accent, and the
// metal and cushions use the accent-tinted greys of the laptop lid.
const fs = require("fs"), path = require("path");

const CX = 63, TOP = 42, BOTTOM = 10;     // anchor = the head's centre; rows run from y = -42 to +10
const W = 2 * CX + 1, H = TOP + BOTTOM + 1;
const g = Array.from({ length: H }, () => Array(W).fill("."));
const put = (X, Y, c) => { const x = CX + X, y = TOP + Y; if (x >= 0 && x < W && y >= 0 && y < H) g[y][x] = c; };
const at = (X, Y) => (g[TOP + Y] || [])[CX + X];
const both = (X, Y, c) => { put(-X, Y, c); put(X, Y, c); };   // X >= 0, mirrored to the left

// ---- 2. band: D outline, L sheen (top only), p pink, a accent stripe, p, D
const YC = -8, OUT = [64, 33.5], IN = [58.5, 28.5];
const ell = (X, Y, [a, b]) => Math.hypot(X / a, (Y - YC) / b);
const depth = (X, Y) => { const o = ell(X, Y, OUT), i = ell(X, Y, IN); return (1 - o) / ((1 - o) + (i - 1)); };  // 0 outer .. 1 inner
const BAND_END = -20;
for (let Y = -TOP; Y <= BAND_END; Y++) for (let X = 0; X <= CX; X++) {
  if (ell(X, Y, OUT) > 1 || ell(X, Y, IN) < 1) continue;
  const d = depth(X, Y);
  both(X, Y, d < 0.17 || d > 0.83 ? "D" : d < 0.36 ? (Y < -28 ? "L" : "p") : d > 0.5 && d < 0.66 && Y < -24 ? "a" : "p");
}

// ---- 3. cushion under the band: c fill, D outline (bottom and end column), k stitches
const PAD = [53.5, 24.5];
for (let Y = -TOP; Y <= -24; Y++) for (let X = 0; X <= 34; X++) {
  if (at(X, Y) !== "." || ell(X, Y, IN) >= 1 || ell(X, Y, PAD) < 1) continue;
  const edge = X === 34 || ell(X, Y + 1, PAD) < 1 && ell(X, Y, PAD) < 1.04;
  const mid = Math.abs(ell(X, Y, [56, 26.5]) - 1) < 0.022;
  both(X, Y, edge ? "D" : mid && X % 4 === 2 ? "k" : "c");
}
for (let Y = -TOP; Y <= -24; Y++) if (at(34, Y) === "c") both(34, Y, "D");

// ---- sliders: metal bars from the band's ends to the yokes, notched every other pixel
for (let Y = BAND_END - 1; Y <= -15; Y++) for (let X = 57; X <= 60; X++) {
  if (at(X, Y) === "p" || at(X, Y) === "L") continue;
  both(X, Y, X === 57 || X === 60 ? "D" : Y % 2 ? "m" : "M");
}
// yokes: a hinge plate on top of each cup
for (let X = 55; X <= 62; X++) { both(X, -14, X === 55 || X === 62 ? "D" : "m"); both(X, -13, X === 55 || X === 62 ? "D" : "M"); }

// ---- 4. ear cups: inBox = a box with rounded corners; edgeOf = a pixel next to the outside (the outline)
const CUP_T = -12, CUP_B = 10;
const inBox = (X, Y, x0, x1, t, b, rad) => {
  if (X < x0 || X > x1 || Y < t || Y > b) return false;
  const dx = X < x0 + rad ? x0 + rad - X : X > x1 - rad ? X - (x1 - rad) : 0;
  const dy = Y < t + rad ? t + rad - Y : Y > b - rad ? Y - (b - rad) : 0;
  return dx * dx + dy * dy <= rad * rad + 1;
};
const edgeOf = (f, X, Y) => !f(X - 1, Y) || !f(X + 1, Y) || !f(X, Y - 1) || !f(X, Y + 1);
const cushion = (X, Y) => inBox(X, Y, 51, 56, CUP_T + 2, CUP_B - 2, 2);
// cushion against the face: c fill, D outline, k crease
for (let X = 51; X <= 56; X++) for (let Y = CUP_T; Y <= CUP_B; Y++) {
  if (!cushion(X, Y)) continue;
  both(X, Y, edgeOf(cushion, X, Y) ? "D" : X === 53 && Y > CUP_T + 4 && Y < CUP_B - 4 ? "k" : "c");
}
const shell = (X, Y) => inBox(X, Y, 55, 63, CUP_T, CUP_B, 3);
// shell, over the cushion's outer edge: D outline, p pink, a rim, L sheen
for (let X = 55; X <= 63; X++) for (let Y = CUP_T; Y <= CUP_B; Y++) {
  if (!shell(X, Y)) continue;
  let c = edgeOf(shell, X, Y) ? "D" : "p";
  if (c === "p" && X === 56) c = "a";                                   // accent trim against the cushion
  else if (c === "p" && Y >= CUP_B - 2) c = "a";                        // and along the bottom
  else if (c === "p" && X === 62 && Y > CUP_T + 2 && Y < CUP_B - 4) c = "L";   // sheen on the outer side
  both(X, Y, c);
}
// badge: a metal ring with an accent light and a glint, centred on the shell
const BX = 59, BY = -2;
for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) {
  if (Math.abs(dx) === 2 && Math.abs(dy) === 2) continue;
  both(BX + dx, BY + dy, Math.max(Math.abs(dx), Math.abs(dy)) === 2 ? "M" : "a");
}
both(BX, BY, "L"); both(BX - 1, BY - 1, "L");

const rows = g.map((r) => r.join(""));
const sprite = {
  keys: { p: "pink", D: "dark", L: "glove", a: "main", m: "lidEdge", M: "lidBottom", c: "keyGap", k: "lid" },
  anchor: [CX, TOP], glow: 0.3, frames: { on: rows },
};
if (process.argv.includes("--write")) {
  const file = path.join(__dirname, "..", "phone", "www", "pack.json"), pack = JSON.parse(fs.readFileSync(file, "utf8"));
  pack.sprites.headphones = sprite;
  // the pack's own layout (merge_pack.js's pretty printer: sprite rows one per line)
  const src = fs.readFileSync(path.join(__dirname, "..", "laptop", "merge_pack.js"), "utf8");
  const body = src.slice(src.indexOf("function pretty("), src.indexOf("\n}\n", src.indexOf("function pretty(")) + 3);
  const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
  const pretty = new Function("isObj", body + "; return pretty;")(isObj);
  fs.writeFileSync(file, pretty(pack));
  console.log("wrote", path.relative(process.cwd(), file), `headphones ${W}x${H}`);
} else console.log(rows.join("\n"));
