// Chip pack loader (chip-pack/1 and /2): derives the OKLCH palette from one accent, bakes sprite frames to canvases
// once per accent change (glow included), and caches the result. Nothing here runs per frame. Eye-style sprites are
// baked only for the active style (Android Go: startup time and memory); everything else is shared.
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

  // {"mirror": "<sprite>"}: W is the longest source row, each row flips within W, anchor x becomes W - 1 - x
  function mirrored(src) {
    let W = 0;
    for (const rows of Object.values(src.frames)) for (const r of rows) W = Math.max(W, r.length);
    const frames = {};
    for (const [f, rows] of Object.entries(src.frames)) frames[f] = rows.map((r) => [...r.padEnd(W, CLEAR)].reverse().join("").replace(/\.+$/, ""));
    return Object.assign({}, src, { frames, anchor: [W - 1 - src.anchor[0], src.anchor[1]] });
  }
  const sources = new WeakMap();   // pack -> {name: resolved sprite}
  function source(pack, name) {
    const sp = pack.sprites[name];
    if (!sp || !sp.mirror) return sp;
    let m = sources.get(pack);
    if (!m) sources.set(pack, (m = {}));
    return m[name] || (m[name] = mirrored(source(pack, sp.mirror)));
  }
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
  function bakeFrame(sp, rows, size, pal, glowScale) {
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
    const glow = (sp.glow || 0) * glowScale;
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

  // ---------------------------------------------------------------- skins (chip-skin/1, see laptop/skin.js)
  // A skin adds sprites, an eye style, colours and mouth/faceBase/faceTop sprites to a copy of the base pack. Nothing
  // else is copied from it (never rig, clips, moods, states), every part is rebuilt field by field with its type
  // checked, and the maps are prototype-less, so a hostile file cannot reach Object.prototype. It throws on anything
  // wrong and leaves the base pack as it was (the caller falls back to the base pack).
  const SKIN_ID = /^[a-z0-9-]{1,32}$/, SKIN_NAME = /^[A-Za-z][A-Za-z0-9@_-]{0,31}$/, FRAME_NAME = /^[A-Za-z0-9_-]{1,32}$/;
  const HEX = /^#[0-9a-fA-F]{6}$/, EYE_LAYERS = ["eyeL", "eyeR", "pupilL", "pupilR", "frontL", "frontR"], SKIN_LAYERS = ["mouth", "faceBase", "faceTop"];
  const isObj = (v) => !!v && typeof v === "object" && !Array.isArray(v);
  const num = (v, lo, hi) => typeof v === "number" && isFinite(v) && v >= lo && v <= hi;
  const bad = (msg) => { throw new Error(msg); };

  function mergeSkin(base, skin) {
    if (!base.eyes) bad("the pack has no eye styles");
    if (!isObj(skin) || skin.format !== "chip-skin/1") bad("not a chip-skin/1 file");
    const id = skin.id;
    if (typeof id !== "string" || !SKIN_ID.test(id)) bad("bad skin id");
    const ns = (n) => "skin:" + id + ":" + n;
    const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

    const palette = Object.assign(Object.create(null), base.palette), roles = Object.keys(base.palette).map((r) => r.toLowerCase());
    if (skin.colors !== undefined) {
      if (!isObj(skin.colors)) bad("colors must be an object");
      const names = Object.keys(skin.colors);
      if (names.length > 12) bad("more than 12 colours");
      for (const n of names) {
        if (!SKIN_NAME.test(n) || roles.includes(n.toLowerCase()) || typeof skin.colors[n] !== "string" || !HEX.test(skin.colors[n])) bad("bad colour " + n.slice(0, 32));
        palette[n] = { fixed: skin.colors[n].toLowerCase() };
      }
    }

    const sprites = Object.assign(Object.create(null), base.sprites);
    if (!isObj(skin.sprites)) bad("sprites must be an object");
    const names = Object.keys(skin.sprites);
    if (names.length > 40) bad("more than 40 sprites");
    for (const n of names) {
      const sp = skin.sprites[n];
      if (!SKIN_NAME.test(n) || !isObj(sp)) bad("bad sprite " + n.slice(0, 32));
      if (own(sp, "mirror")) {
        if (typeof sp.mirror !== "string" || !SKIN_NAME.test(sp.mirror)) bad(n + ": bad mirror");
        sprites[ns(n)] = { mirror: ns(sp.mirror) };
        continue;
      }
      const keys = Object.create(null);
      if (!isObj(sp.keys)) bad(n + ": no keys");
      for (const k of Object.keys(sp.keys)) {
        if ([...k].length !== 1 || k === "." || typeof sp.keys[k] !== "string" || !own(palette, sp.keys[k])) bad(n + ": bad key " + k.slice(0, 4));
        keys[k] = sp.keys[k];
      }
      if (!Array.isArray(sp.anchor) || sp.anchor.length !== 2 || !sp.anchor.every(Number.isInteger)) bad(n + ": bad anchor");
      if (sp.glow !== undefined && !num(sp.glow, 0, 1)) bad(n + ": bad glow");
      if (!isObj(sp.frames) || !Object.keys(sp.frames).length) bad(n + ": no frames");
      const frames = Object.create(null);
      for (const f of Object.keys(sp.frames)) {
        const rows = sp.frames[f];
        if (!FRAME_NAME.test(f) || !Array.isArray(rows) || rows.length > 96 || !rows.every((r) => typeof r === "string" && r.length <= 128)) bad(n + ": bad frame " + f.slice(0, 32));
        frames[f] = rows.slice();
      }
      sprites[ns(n)] = { keys, anchor: sp.anchor.slice(), glow: sp.glow || 0, frames };
    }
    // a mirror needs a drawn sprite at the end of its chain
    for (const n of names) {
      let t = ns(n), hops = 0;
      while (sprites[t] && sprites[t].mirror && hops++ < 8) t = sprites[t].mirror;
      if (!sprites[t] || sprites[t].mirror) bad(n + ": cannot mirror");
    }

    // the eye style, rebuilt
    const e = skin.eyes;
    if (!isObj(e) || !isObj(e.sprites) || !isObj(e.frames)) bad("eyes: missing parts");
    const st = { label: typeof e.label === "string" ? e.label.slice(0, 40) : id, blurb: typeof e.blurb === "string" ? e.blurb.slice(0, 160) : "",
      sprites: Object.create(null), shift: null, converge: e.converge === undefined ? 0 : e.converge, pupils: [], pupilDefault: "M", frames: Object.create(null) };
    for (const l of EYE_LAYERS) if (typeof e.sprites[l] === "string" && own(skin.sprites, e.sprites[l])) st.sprites[l] = ns(e.sprites[l]);
    if (!st.sprites.eyeL || !st.sprites.eyeR) bad("eyes: eyeL and eyeR sprites are required");
    const pair = (v) => Array.isArray(v) && v.length === 2 && v.every((x) => num(x, 0, 12));
    if (!pair(e.shift)) bad("eyes: bad shift");
    st.shift = e.shift.slice();
    if (!num(st.converge, 0, 3)) bad("eyes: bad converge");
    if (st.sprites.pupilL) {
      st.pupils = ["S", "M", "L"].filter((z) => Array.isArray(e.pupils) && e.pupils.includes(z));
      if (!st.pupils.length) bad("eyes: no pupil sizes");
      st.pupilDefault = st.pupils.includes(e.pupilDefault) ? e.pupilDefault : st.pupils[0];
    }
    const box = (b) => Array.isArray(b) && b.length === 4 && b.every(Number.isInteger) && b[0] <= b[2] && b[1] <= b[3];
    for (const f of Object.keys(e.frames)) {
      const d = e.frames[f], out = {};
      if (!FRAME_NAME.test(f) || !isObj(d)) bad("eyes: bad frame " + f.slice(0, 32));
      if (d.pupil === "auto" || d.pupil === null) out.pupil = d.pupil;
      else if (typeof d.pupil === "string" && FRAME_NAME.test(d.pupil)) out.pupil = d.pupil;
      else if (d.pupil !== undefined) bad("eyes: bad pupil in " + f);
      for (const k of ["box", "boxR"]) if (d[k] !== undefined) { if (!box(d[k])) bad("eyes: bad " + k + " in " + f); out[k] = d[k].slice(); }
      if (out.pupil && !out.box) bad("eyes: " + f + " has a pupil but no box");
      if (d.back !== undefined) { if (typeof d.back !== "string" || !FRAME_NAME.test(d.back)) bad("eyes: bad back in " + f); out.back = d.back; }
      if (d.shift !== undefined) { if (!pair(d.shift)) bad("eyes: bad shift in " + f); out.shift = d.shift.slice(); }
      st.frames[f] = out;
    }
    const merged = Object.assign(Object.create(null), base, { sprites, palette,
      eyes: { default: base.eyes.default, styles: Object.assign(Object.create(null), base.eyes.styles, { ["skin:" + id]: st }) } });
    for (const id2 of ["eyeL", "eyeR"]) {
      const sp = source(merged, st.sprites[id2]);
      for (const f of ["open", "half", "shut"]) if (!own(st.frames, f) || !own(sp.frames, f)) bad("eyes: required frame " + f + " missing");
    }

    const layers = {};
    for (const slot of SKIN_LAYERS) {
      if (skin[slot] === undefined) continue;
      if (typeof skin[slot] !== "string" || !own(skin.sprites, skin[slot])) bad(slot + ": not a sprite of the skin");
      layers[slot] = ns(skin[slot]);
      const sp = source(merged, layers[slot]);
      if (slot === "mouth" && !own(sp.frames, "neutral")) bad("mouth: neutral frame missing");
    }
    if (skin.accent !== undefined && skin.accent !== null && (typeof skin.accent !== "string" || !HEX.test(skin.accent))) bad("bad accent");
    return { pack: merged, id, layers, accent: skin.accent ? skin.accent.toLowerCase() : null };
  }

  // ---------------------------------------------------------------- player-facing cache
  const state = { pack: null, base: null, skin: null, skinRev: 0, accent: null, glow: 1, palette: null, baked: null, style: null };

  function bake(pack, name, pal, glowScale) {
    const sp = source(pack, name), size = spriteSize(sp), frames = {};
    for (const [fname, rows] of Object.entries(sp.frames)) frames[fname] = bakeFrame(sp, rows, size, pal, glowScale);
    // anchor in canvas pixels: blit at (x - anchorX, y - anchorY)
    return { frames, w: size[0] + 2 * PAD, h: size[1] + 2 * PAD, ax: sp.anchor[0] + PAD, ay: sp.anchor[1] + PAD };
  }

  // sprites an eye style owns (any style's), and the ones the active style needs
  const styles = () => (state.pack.eyes && state.pack.eyes.styles) || {};
  const styleSprites = (id) => new Set(Object.values((styles()[id] || {}).sprites || {}));
  function wanted() {
    const owned = new Set(Object.keys(styles()).flatMap((id) => [...styleSprites(id)])), mine = styleSprites(state.style);
    return Object.keys(state.pack.sprites).filter((n) => !owned.has(n) || mine.has(n));
  }
  function bakeWanted() {
    const keep = new Set(wanted());
    for (const n of Object.keys(state.baked)) if (!keep.has(n)) delete state.baked[n];
    for (const n of keep) if (!state.baked[n]) state.baked[n] = bake(state.pack, n, state.palette, state.glow);
  }

  // ---------------------------------------------------------------- eyes (chip-pack/2 styles)
  // The one place that decides what an eye frame draws, shared by player.js, check_pack.js and skin.js so the checks
  // match the phone. env = {style, names (layer id -> sprite name), fb (pack.fallbacks.eye), spr (name -> source sprite)}.
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const chain = (map, f) => {   // f, then what it falls back to, until a frame with no fallback
    const out = [f];
    while (map && has(map, f) && out.length < 16) out.push((f = map[f]));
    return out;
  };

  // eye layer `id` (eyeL|eyeR) showing frame f with pupil size `size`:
  // {key (the style frame that applies), def, back (frame of the eye sprite), front, pupil (frame or null), box, shift, anchor}
  function eyeLook(env, id, f, size) {
    const st = env.style, side = id.slice(-1), back = env.spr(env.names[id]);
    const ch = chain(env.fb, f), key = st && ch.find((n) => has(st.frames, n)), def = key ? st.frames[key] : {};
    const look = { key, def, front: null, pupil: null, box: null, anchor: back.anchor,
      back: def.back && back.frames[def.back] ? def.back : ch.find((n) => back.frames[n]) || Object.keys(back.frames)[0],
      shift: def.shift || (st ? st.shift : [6, 4]) };
    if (st) {
      const front = env.spr(env.names["front" + side]), pupil = env.spr(env.names["pupil" + side]);
      if (front && key && front.frames[key]) look.front = key;
      const pf = def.pupil === "auto" ? size : def.pupil, box = side === "R" ? def.boxR || def.box : def.box;
      if (pf && pupil && pupil.frames[pf] && box) { look.pupil = pf; look.box = box; }
    }
    return look;
  }

  // where the pupil anchor sits in eye-sprite px: the box point for the gaze, moved `conv` px inward
  function pupilPoint(box, side, gx, gy, conv) {
    return [Math.round(box[0] + (box[2] - box[0]) * (gx + 1) / 2) + (side === "L" ? conv : -conv),
      Math.round(box[1] + (box[3] - box[1]) * (gy + 1) / 2)];
  }

  // Every pupil size at all 9 gaze positions, converged or not: pixels that are neither on the eye's drawn frame nor
  // under the front layer's. -> {bad: [{key, size, gx, gy, conv, px}], missing: [pupil frame names the sprite lacks]}
  function pupilFit(env, id, f) {
    const st = env.style, side = id.slice(-1), out = { bad: [], missing: [] };
    const first = eyeLook(env, id, f, st.pupilDefault), def = first.def;
    if (!def.pupil) return out;
    const sizes = def.pupil === "auto" ? st.pupils : [def.pupil];
    const pupil = env.spr(env.names["pupil" + side]), back = env.spr(env.names[id]), front = env.spr(env.names["front" + side]);
    const filled = (sp, fr, x, y) => { const r = sp.frames[fr][y]; return !!r && x >= 0 && x < r.length && r[x] !== "."; };
    for (const size of sizes) {
      const look = eyeLook(env, id, f, size);
      if (!look.pupil) { if (pupil && look.box) out.missing.push(def.pupil === "auto" ? size : def.pupil); continue; }
      for (const gx of [-1, 0, 1]) for (const gy of [-1, 0, 1]) for (const conv of st.converge ? [0, st.converge] : [0]) {
        const [bx, by] = pupilPoint(look.box, side, gx, gy, conv);
        let px = 0;
        pupil.frames[look.pupil].forEach((r, y) => { for (let x = 0; x < r.length; x++) {
          if (r[x] === ".") continue;
          const ex = bx + x - pupil.anchor[0], ey = by + y - pupil.anchor[1];
          const onFront = look.front && front && filled(front, look.front, ex - back.anchor[0] + front.anchor[0], ey - back.anchor[1] + front.anchor[1]);
          if (!filled(back, look.back, ex, ey) && !onFront) px++;
        } });
        if (px) out.bad.push({ key: look.key, size, gx, gy, conv, px });
      }
    }
    return out;
  }

  // the eye and mouth frames the pack's moods, clips and states use (plus every frame the eye sprites draw), with
  // where each was named: {eyeL:Set, eyeR:Set, mouth:Set, at: {"eyeLwide": "mood surprised"}}
  function usedFrames(pack) {
    const want = { eyeL: new Set(Object.keys(pack.sprites.eyeL.frames)), eyeR: new Set(Object.keys(pack.sprites.eyeR.frames)), mouth: new Set(), at: {} };
    const need = (id, f, where) => { if (want[id] && typeof f === "string") { want[id].add(f); want.at[id + f] = want.at[id + f] || where; } };
    for (const [m, d] of Object.entries(pack.moods)) for (const id of ["eyeL", "eyeR", "mouth"]) need(id, d[id], "mood " + m);
    for (const [c, clip] of Object.entries(pack.clips)) for (const id of ["eyeL", "eyeR", "mouth"]) {
      for (const [, f] of ((clip.tracks[id] || {}).frame || [])) need(id, f, "clip " + c);
    }
    for (const [s, st] of Object.entries(pack.states)) for (const id of ["eyeL", "eyeR", "mouth"]) need(id, ((st.pose || {})[id] || {}).frame, "state " + s);
    return want;
  }

  const ChipPack = {
    hexToOklch, oklchToHex, derivePalette, spriteSize, mirrored,
    chain, eyeLook, pupilPoint, pupilFit, usedFrames,
    PAD,
    async load(url) {
      const res = await fetch(url, { cache: "no-cache" });
      state.pack = state.base = await res.json();
      if (!/^chip-pack\/[12]$/.test(state.pack.format)) throw new Error("unsupported pack format " + state.pack.format);
      return state.pack;
    },
    use(pack) { state.pack = state.base = pack; },
    // Merge a skin over the base pack (null = back to the base pack). Throws, with nothing changed, if the skin is bad.
    // Nothing is baked until the next setAccent, which the caller makes (the palette may change with the skin).
    setSkin(skin) {
      const m = skin ? mergeSkin(state.base, skin) : null;
      state.skin = m && { id: m.id, layers: m.layers, accent: m.accent };
      state.skinRev++;
      state.pack = m ? m.pack : state.base;
      state.baked = null;
      if (state.style && !state.pack.eyes.styles[state.style]) state.style = state.pack.eyes.default;
    },
    get skin() { return state.skin; },
    get skinRev() { return state.skinRev; },
    get skinLayers() { return state.skin ? state.skin.layers : {}; },
    // the eye style whose sprites get baked (unknown ids mean the pack's default); bakes now if the palette exists
    setStyle(id) {
      const eyes = state.pack.eyes;
      id = eyes ? (typeof id === "string" && has(eyes.styles, id) ? id : eyes.default) : null;
      if (state.style === id) return false;
      state.style = id;
      if (state.baked) bakeWanted();
      return true;
    },
    // re-derive and re-bake only when the accent or the glow level (1 = the pack's own) really changed
    setAccent(hex, glow = 1) {
      hex = hex.toLowerCase();
      if (state.accent === hex && state.glow === glow && state.baked) return false;
      if (state.style === null && state.pack.eyes) state.style = state.pack.eyes.default;
      state.palette = derivePalette(state.pack, hex);
      state.accent = hex;
      state.glow = glow;
      state.baked = {};
      bakeWanted();
      return true;
    },
    get pack() { return state.pack; },
    get palette() { return state.palette; },
    get style() { return state.style; },
    // baked sprite: {frames:{name:canvas}, w, h, ax, ay}; one outside the active style is baked on first use
    sprite(name) {
      if (!state.baked || !name) return undefined;
      return state.baked[name] || (state.pack.sprites[name] ? (state.baked[name] = bake(state.pack, name, state.palette, state.glow)) : undefined);
    },
    // the sprite's JSON with mirrors resolved: {keys, anchor, frames, ...}
    source(name) { return state.pack && name ? source(state.pack, name) : undefined; },
  };

  if (typeof module !== "undefined" && module.exports) module.exports = ChipPack;
  else root.ChipPack = ChipPack;
})(typeof window !== "undefined" ? window : globalThis);
