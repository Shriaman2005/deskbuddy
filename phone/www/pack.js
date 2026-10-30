// Chip pack loader (chip-pack/1): derives the OKLCH palette from one accent, bakes every sprite frame to a
// canvas once per accent change (glow included), and caches the result. Nothing here runs per frame.
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- OKLab / OKLCH
  const lin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const gam = (c) => (c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
  const clamp01 = (v) => Math.min(1, Math.max(0, v));

  function hexToOklch(hex) {
    const n = parseInt(hex.slice(1), 16);
    const r = lin(((n >> 16) & 255) / 255), g = lin(((n >> 8) & 255) / 255), b = lin((n & 255) / 255);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
    const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
    const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
    return { l: L, c: Math.hypot(A, B), h: (Math.atan2(B, A) * 180 / Math.PI + 360) % 360 };
  }

  // linear sRGB of an OKLCH colour, not clamped (used to test the gamut)
  function oklchToLinear(L, C, h) {
    const a = C * Math.cos(h * Math.PI / 180), b = C * Math.sin(h * Math.PI / 180);
    const l = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3);
    const m = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3);
    const s = Math.pow(L - 0.0894841775 * a - 1.291485548 * b, 3);
    return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  }

  const EPS = 1e-4;
  const inGamut = (rgb) => rgb.every((v) => v >= -EPS && v <= 1 + EPS);

  // gamut map: keep lightness and hue, pull chroma down until the colour fits sRGB
  function oklchToHex(L, C, h) {
    L = clamp01(L);
    let rgb = oklchToLinear(L, C, h);
    if (!inGamut(rgb)) {
      let lo = 0, hi = C;
      for (let i = 0; i < 24; i++) {
        const mid = (lo + hi) / 2;
        if (inGamut(oklchToLinear(L, mid, h))) lo = mid; else hi = mid;
      }
      rgb = oklchToLinear(L, lo, h);
    }
    return "#" + rgb.map((v) => Math.round(clamp01(gam(clamp01(v))) * 255).toString(16).padStart(2, "0")).join("");
  }

  // ---------------------------------------------------------------- palette
  // token = {from:"main", dl|l, c, dh} | {fixed:"#rrggbb"}; c is a multiple of the accent's chroma
  function derivePalette(pack, accentHex) {
    const a = hexToOklch(accentHex), lr = pack.accentLightness;
    const mainL = Math.min(lr[1], Math.max(lr[0], a.l));
    const out = {};
    for (const [name, t] of Object.entries(pack.palette)) {
      if (t === "accent") out[name] = oklchToHex(mainL, a.c, a.h);
      else if (t.fixed) out[name] = t.fixed.toLowerCase();
      else out[name] = oklchToHex(t.l !== undefined ? t.l : mainL + t.dl, a.c * t.c, a.h + (t.dh || 0));
    }
    return out;
  }

  // ---------------------------------------------------------------- sprites
  const CLEAR = ".";
  const PAD = 6;       // room around a sprite for its baked glow
  const GLOW_R = 3;    // box-blur radius in sprite pixels

  function spriteSize(sp) {
    let w = 0, h = 0;
    for (const rows of Object.values(sp.frames)) {
      h = Math.max(h, rows.length);
      for (const r of rows) w = Math.max(w, r.length);
    }
    return [w, h];
  }

  function rgbOf(hex) { const n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }

  function boxBlur(src, w, h, r) {
    const tmp = new Float32Array(w * h), out = new Float32Array(w * h), k = 2 * r + 1;
    for (let y = 0; y < h; y++) {
      let sum = 0;
      for (let x = -r; x <= r; x++) sum += src[y * w + Math.min(w - 1, Math.max(0, x))];
      for (let x = 0; x < w; x++) {
        tmp[y * w + x] = sum / k;
        sum += src[y * w + Math.min(w - 1, x + r + 1)] - src[y * w + Math.max(0, x - r)];
      }
    }
    for (let x = 0; x < w; x++) {
      let sum = 0;
      for (let y = -r; y <= r; y++) sum += tmp[Math.min(h - 1, Math.max(0, y)) * w + x];
      for (let y = 0; y < h; y++) {
        out[y * w + x] = sum / k;
        sum += tmp[Math.min(h - 1, y + r + 1) * w + x] - tmp[Math.max(0, y - r) * w + x];
      }
    }
    return out;
  }

  function makeCanvas(w, h) {
    if (typeof OffscreenCanvas !== "undefined") return new OffscreenCanvas(w, h);
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    return c;
  }

  // one frame -> canvas of (w + 2*PAD) x (h + 2*PAD); glow is a blurred, tinted halo drawn under the pixels
  function bakeFrame(sp, rows, size, pal) {
    const W = size[0] + 2 * PAD, H = size[1] + 2 * PAD;
    const px = new Uint8ClampedArray(W * H * 4), alpha = new Float32Array(W * H);
    const rgb = {};
    for (const [ch, tok] of Object.entries(sp.keys)) rgb[ch] = rgbOf(pal[tok]);
    let tr = 0, tg = 0, tb = 0, tn = 0;
    for (let y = 0; y < rows.length; y++) {
      const row = rows[y];
      for (let x = 0; x < row.length; x++) {
        const c = rgb[row[x]];
        if (!c) continue;
        const i = (y + PAD) * W + x + PAD;
        px[i * 4] = c[0]; px[i * 4 + 1] = c[1]; px[i * 4 + 2] = c[2]; px[i * 4 + 3] = 255;
        alpha[i] = 1; tr += c[0]; tg += c[1]; tb += c[2]; tn++;
      }
    }
    const glow = sp.glow || 0;
    if (glow > 0 && tn) {
      const g = boxBlur(boxBlur(alpha, W, H, GLOW_R), W, H, GLOW_R);   // two passes ~ soft falloff
      const c = [tr / tn, tg / tn, tb / tn];
      for (let i = 0; i < W * H; i++) {
        const ga = Math.min(1, g[i] * glow * 2.2);
        if (ga <= 0.01 || px[i * 4 + 3] === 255) continue;
        px[i * 4] = c[0]; px[i * 4 + 1] = c[1]; px[i * 4 + 2] = c[2]; px[i * 4 + 3] = Math.round(ga * 255);
      }
    }
    const cv = makeCanvas(W, H);
    cv.getContext("2d").putImageData(new ImageData(px, W, H), 0, 0);
    return cv;
  }

  // ---------------------------------------------------------------- player-facing cache
  const state = { pack: null, accent: null, palette: null, baked: null };

  function bakeAll(pack, pal) {
    const baked = {};
    for (const [name, sp] of Object.entries(pack.sprites)) {
      const size = spriteSize(sp), frames = {};
      for (const [fname, rows] of Object.entries(sp.frames)) frames[fname] = bakeFrame(sp, rows, size, pal);
      // anchor in canvas pixels: blit at (x - anchorX, y - anchorY)
      baked[name] = { frames, w: size[0] + 2 * PAD, h: size[1] + 2 * PAD, ax: sp.anchor[0] + PAD, ay: sp.anchor[1] + PAD };
    }
    return baked;
  }

  const ChipPack = {
    hexToOklch, oklchToHex, derivePalette, spriteSize,
    PAD,
    async load(url) {
      const res = await fetch(url, { cache: "no-cache" });
      state.pack = await res.json();
      if (state.pack.format !== "chip-pack/1") throw new Error("unsupported pack format " + state.pack.format);
      return state.pack;
    },
    use(pack) { state.pack = pack; },
    // re-derive and re-bake only when the accent really changed
    setAccent(hex) {
      hex = hex.toLowerCase();
      if (state.accent === hex && state.baked) return false;
      state.palette = derivePalette(state.pack, hex);
      state.baked = bakeAll(state.pack, state.palette);
      state.accent = hex;
      return true;
    },
    get pack() { return state.pack; },
    get palette() { return state.palette; },
    // baked sprite: {frames:{name:canvas}, w, h, ax, ay}
    sprite(name) { return state.baked && state.baked[name]; },
  };

  if (typeof module !== "undefined" && module.exports) module.exports = ChipPack;
  else root.ChipPack = ChipPack;
})(typeof window !== "undefined" ? window : globalThis);
