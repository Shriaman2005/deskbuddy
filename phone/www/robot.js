// Chip's focus and typing scenes, from the "Robot Focus" and "Robot Typing" designs made in Claude Design
// (robot.jsx there): the same 320×180 grid, palettes, sprites, easing and choreography, drawn on a canvas
// instead of React/SVG so the phone keeps up. The designs are fixed loops; here what happens drives them:
// - a focus session starts: Switch (a long blink, the room dims, a moon), then Deep typing, or Flow while you
//   type fast on the laptop; notifications that arrive meanwhile pop up muted and fade; Release when it ends;
// - you've been typing on the laptop for a while: Boot (the face powers on like a CRT), then Typing; Stuck
//   when you pause, Idea when you go on, Burst when you type fast; Done (a big Enter, a grin) and Sleep when
//   you stop.
// buddy.js sets data-focus, data-typing, data-wpm, data-idle and data-accent on #app and fires "chip:notify";
// this adds #app.scene while a scene plays (the normal face steps aside) and follows #app.pixel for the look.
(() => {
  "use strict";
  const app = document.getElementById("app"), faceScreen = document.getElementById("s-face");
  const wrap = document.getElementById("scene"), cv = wrap.querySelector("canvas"), vg = cv.getContext("2d");
  const GW = 320, GH = 180, PX = 6;
  const ZOOM = 0.86;  // at camera scale 1 the grid fills this much of the screen's height

  // ---------------------------------------------------------------- motion: the only three curves in the piece
  const Easing = {
    easeInOutCubic: (t) => (t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1),
    easeOutBack: (t) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
    easeOutExpo: (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)),
  };
  const EASE = { move: Easing.easeInOutCubic, pop: Easing.easeOutBack, snap: Easing.easeOutExpo };
  function seq(T, k) {
    if (T <= k[0][0]) return k[0][1];
    for (let i = 0; i < k.length - 1; i++) {
      const a = k[i], b = k[i + 1];
      if (T < b[0]) {
        const span = b[0] - a[0];
        if (span <= 0) return b[1];
        return a[1] + (b[1] - a[1]) * EASE[b[2] || "move"]((T - a[0]) / span);
      }
    }
    return k[k.length - 1][1];
  }
  const blinkAt = (T, at) => seq(T, [[at, 0], [at + 0.06, 1, "snap"], [at + 0.17, 0, "move"]]);
  const hash = (n) => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };
  const R = Math.round;

  // ---------------------------------------------------------------- accent palettes (the design's glow colours)
  const PALETTES = {
    cyan: { main: "#2ee6f2", light: "#8ef6fc", dark: "#17a3ba", deep: "#0e6a80", hi: "#effeff", rim: "#5fe8ff", bg: "#020609", floor: "#0e9ab8",
      smoothBg: "#140b1d", smoothCenter: "#2a1838", eyeTop: "#74f0ff", eyeBot: "#2cc4dd",
      key: "#1a8db0", keyFace: "#27bfd9", keyLip: "#0f5f7a", keyGap: "#0b1a33", deck: "#14223f", deckRim: "#7489bb", lid: "#4a5a86", lidLine: "#53648f", lidEdge: "#a9bae0", lidEdgeDark: "#6f82b3", lidBottom: "#28335a", baseFront: "#8397c8", baseFrontDark: "#56689c" },
    terracotta: { main: "#ee9358", light: "#f9c49b", dark: "#b8622f", deep: "#73391a", hi: "#fff3e8", rim: "#f2a46e", bg: "#080504", floor: "#a8582a",
      smoothBg: "#130a07", smoothCenter: "#2a1710", eyeTop: "#ffbd8f", eyeBot: "#d8743a",
      key: "#a8582a", keyFace: "#d57a40", keyLip: "#6b3517", keyGap: "#1e1210", deck: "#2a1d19", deckRim: "#a08a80", lid: "#655550", lidLine: "#6e5e58", lidEdge: "#cdbab0", lidEdgeDark: "#8e7b72", lidBottom: "#3a2d29", baseFront: "#ab978d", baseFrontDark: "#776760" },
    sage: { main: "#b4d38c", light: "#dcefc4", dark: "#7a9a5c", deep: "#465c33", hi: "#f7ffee", rim: "#c3dda2", bg: "#040604", floor: "#6f8f52",
      smoothBg: "#0a0d09", smoothCenter: "#18211a", eyeTop: "#d6efb8", eyeBot: "#91b46b",
      key: "#6f8f52", keyFace: "#94b870", keyLip: "#465c33", keyGap: "#111a10", deck: "#1c2619", deckRim: "#8c9a84", lid: "#525c4d", lidLine: "#5b6556", lidEdge: "#bcc8b2", lidEdgeDark: "#7d8a74", lidBottom: "#2c3328", baseFront: "#98a68f", baseFrontDark: "#69765f" },
  };
  window.CHIP_PALETTES = PALETTES;  // buddy.js colours the normal face from the same palettes
  const HAND = { o: "#0a1426", w: "#f2f7ff", s: "#6a82b4", b: "#b2c6ea" };

  // ---------------------------------------------------------------- geometry (the logical 320×180 grid)
  const LID = [[78, 96], [147, 104], [165, 160], [97, 147]];
  const BL = [158, 141], BR = [212, 131], FR = [219, 151], FL = [165, 161];
  const EYE_L = { cx: 134, cy: 67, w: 34, h: 41 };
  const EYE_R = { cx: 200, cy: 67, w: 36, h: 43 };
  const MOUTH = { cx: 167, y: 91 };
  const HAND_L = [156, 125], HAND_R = [192, 129];
  const DU = [BR[0] - BL[0], BR[1] - BL[1]], DV = [FL[0] - BL[0], FL[1] - BL[1]];
  // key rows run parallel to the hinge (slope 0.2), stacked 3px apart, emerging from behind the lid
  const KEY_ZONE = [[160, 140], [211, 130.6], [216.5, 149], [166.5, 158.4]];
  const KEY_SLOPE = 0.2;
  const KEYS = [];
  for (let j = 0; j < 12; j++) {
    const row = [];
    for (let i = -3; i < 14; i++) {
      const x = R(160 + i * 5 + (j % 2) * 2), y = R(156 - j * 4 + (x - 160) * KEY_SLOPE);
      let ok = true;
      for (let dy = 0; dy < 3 && ok; dy++) for (let dx = 0; dx < 4 && ok; dx++) if (!inPoly(x + dx + 0.5, y + dy + 0.5, KEY_ZONE)) ok = false;
      if (ok) row.push({ x, y, w: 4 });
    }
    if (row.length > 1) {
      const k = row[row.length - 1];
      while (k.w < 8 && [0, 1, 2].every((dy) => inPoly(k.x + k.w + 0.5, k.y + dy + 0.5, KEY_ZONE))) k.w++;
    }
    row.forEach((k) => KEYS.push({
      ...k, id: KEYS.length, cx: k.x + k.w / 2, cy: k.y + 1.5,
      corners: [[k.x, k.y], [k.x + k.w, k.y + k.w * KEY_SLOPE], [k.x + k.w, k.y + k.w * KEY_SLOPE + 1.9], [k.x, k.y + 1.9]],
    }));
  }
  const nearKeys = (px, py, n) => KEYS.slice().sort((a, b) => Math.hypot(a.cx - px, a.cy - py) - Math.hypot(b.cx - px, b.cy - py)).slice(0, n).map((k) => k.id);
  const KEYS_L = nearKeys(HAND_L[0] + 8, HAND_L[1] + 17, 4), KEYS_R = nearKeys(HAND_R[0] + 8, HAND_R[1] + 17, 4);
  const KEYS_ENTER = nearKeys(HAND_R[0] + 20, HAND_R[1] + 16, 5);

  const HAND_SPRITE = [
    "........oooooooo..........",
    "......oowwwwwwwwoo........",
    "....oowwwwwwwwwwwwoo......",
    "...owwwwwwwwwwwwwwwwoo....",
    "..owwwwwwwwwwwwwwwwwwwo...",
    ".owwwwwwwwwwwwwwwwwwwwwo..",
    ".owwwwwwwwwwwwwwwwwwwwwwo.",
    "owwwsssswwwwwwwwwwwwwwwwo.",
    "owwswwwwwwwwwwwwwwwwwwwbbo",
    "owswwwwwwwwwwwwwwwwwwwbbbo",
    "owswwwwwwwwwwwwwwwwwwbbbbo",
    "owwswwwwwwwwwwwwwwwbbbbbbo",
    ".owwsssswwwwwwwwwbbbbbbbo.",
    ".owwwwwwwwwwwwbbbbbbbbbo..",
    "..oowwwwwwbbbbbbbbbbooo...",
    "....oooooooooooooooo......",
  ];
  const TICK = ["#.....#", "#....#.", ".#...#.", ".#..#.."];
  const TICK_BIG = ["#....#....#", "#....#....#", ".#...#...#.", ".#.......#.", "..#.....#.."];
  const TICK_LINES = { small: [[0, 0, 1.3, 3.4], [6, 0, 4.6, 3.4]], big: [[0, 0, 2, 4.4], [5, -0.4, 5, 3.6], [10, 0, 8, 4.4]] };
  const SPARK_S = [".#.", "#+#", ".#."];
  const SPARK_B = ["..#..", "..#..", "##+##", "..#..", "..#.."];
  const BUBBLE = [
    ".#############.",
    "#fffffffffffff#",
    "#ff##ff##ff##f#",
    "#ff##ff##ff##f#",
    "#fffffffffffff#",
    ".##f##########.",
    "..#f#..........",
    "...#...........",
  ];
  const MOON_CELLS = [];
  for (let y = -8; y < 8; y++) for (let x = -8; x < 8; x++) {
    const px = x + 0.5, py = y + 0.5;
    if (Math.hypot(px, py) <= 7.2 && Math.hypot(px - 3.6, py + 3) > 6) MOON_CELLS.push([x, y]);
  }
  const MOUTHS = {
    neutral: ["##################", "##################", ".....########.....", ".....########....."],
    flat: ["############", "############"],
    hmm: [".........#####", "....#########.", "#########.....", "#####........."],
    o: [".####.", "######", "##..##", "##..##", "######", ".####."],
    grin: ["######################", "######################", ".####################.", "..##################..", "....##############....", ".......########......."],
    small: ["##########", "..######.."],
  };
  const HAND_D = new Path2D("M1.5 9.5 C1.2 4.2 7 0.8 13 0.8 C19.5 0.8 25 4.4 25 9.6 C25 13.6 21.6 15.6 16.5 15.6 L8.5 15.6 C4.2 15.6 1.7 13.4 1.5 9.5 Z");
  const HAND_THUMB = new Path2D("M8.6 7.4 C5.6 7.2 3.8 9.5 4.4 11.4 C5 13 7.2 13.4 8.8 12.6");
  const HAND_SHINE = new Path2D("M11.5 3.2 C14.2 2.4 17.4 2.6 19.6 3.7");

  // ---------------------------------------------------------------- pixel helpers
  function inPoly(x, y, p) {
    let ins = false;
    for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
      const [xi, yi] = p[i], [xj, yj] = p[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) ins = !ins;
    }
    return ins;
  }
  function polyCells(p) {
    const xs = p.map((q) => q[0]), ys = p.map((q) => q[1]), out = [];
    for (let y = Math.floor(Math.min(...ys)); y <= Math.ceil(Math.max(...ys)); y++)
      for (let x = Math.floor(Math.min(...xs)); x <= Math.ceil(Math.max(...xs)); x++)
        if (inPoly(x + 0.5, y + 0.5, p)) out.push([x, y]);
    return out;
  }
  function lineCells(a, b) {
    let [x0, y0] = a.map(R);
    const [x1, y1] = b.map(R);
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, out = [];
    let err = dx + dy;
    for (;;) {
      out.push([x0, y0]);
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x0 += sx; }
      if (e2 <= dx) { err += dx; y0 += sy; }
    }
    return out;
  }
  function layer(w = GW, h = GH) { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; }
  function paint(ctx, cells, col) {
    for (const [x, y] of cells) { ctx.fillStyle = typeof col === "function" ? col(x, y) : col; ctx.fillRect(x, y, 1, 1); }
  }
  function spriteRuns(rows, x0, y0, colors) {
    const runs = [];
    rows.forEach((row, y) => {
      let run = null;
      for (let x = 0; x <= row.length; x++) {
        const c = colors[row[x]];
        if (run && (!c || c !== run.c)) { runs.push(run); run = null; }
        if (c && !run) run = { x: x0 + x, y: y0 + y, w: 0, c };
        if (run) run.w++;
      }
    });
    return runs;
  }
  function drawRuns(ctx, runs) { for (const r of runs) { ctx.fillStyle = r.c; ctx.fillRect(r.x, r.y, r.w, 1); } }

  // the laptop, built once per palette for the pixel look
  function buildPixelStatic(pal) {
    const det = DU[0] * DV[1] - DU[1] * DV[0];
    const deck = layer(), d = deck.getContext("2d");
    paint(d, polyCells([[97, 147], [165, 160], [165, 163], [97, 150]]), pal.baseFrontDark);
    paint(d, polyCells([[165, 161], [219, 151], [219, 154], [165, 164]]), pal.baseFront);
    paint(d, polyCells([BL, BR, FR, FL]), (x, y) => {
      const dx = x + 0.5 - BL[0], dy = y + 0.5 - BL[1];
      const u = (dx * DV[1] - dy * DV[0]) / det, v = (DU[0] * dy - DU[1] * dx) / det;
      return u < 0.025 || u > 0.975 || v > 0.96 ? pal.deckRim : pal.keyGap;
    });
    paint(d, lineCells(FL, FR), pal.deckRim);
    const keys = layer(), k = keys.getContext("2d"), keyCells = {};
    KEYS.forEach((key) => {
      const face = [], lip = [];
      for (let dx = 0; dx < key.w; dx++) { face.push([key.x + dx, key.y], [key.x + dx, key.y + 1]); lip.push([key.x + dx, key.y + 2]); }
      paint(k, face, pal.keyFace); paint(k, lip, pal.keyLip);
      keyCells[key.id] = face.concat(lip);
    });
    const lid = layer(), l = lid.getContext("2d");
    paint(l, polyCells(LID), (x, y) => (y % 3 === 0 ? pal.lidLine : pal.lid));
    paint(l, lineCells(LID[3], LID[2]), pal.lidBottom);
    paint(l, lineCells(LID[1], LID[2]), pal.lidEdge);
    paint(l, lineCells([LID[1][0] - 1, LID[1][1] + 1], [LID[2][0] - 1, LID[2][1]]), pal.lidEdgeDark);
    const rim = [...lineCells(LID[0], LID[1]), ...lineCells(LID[0], LID[3])];
    const logo = [];
    for (let y = 119; y <= 135; y++) for (let x = 113; x <= 129; x++) {
      const dd = ((x + 0.5 - 121) / 6) ** 2 + ((y + 0.5 - 127) / 7) ** 2;
      if (dd <= 1) logo.push({ x, y, inner: dd < 0.45 });
    }
    const hand = layer(26, 16);
    drawRuns(hand.getContext("2d"), spriteRuns(HAND_SPRITE, 0, 0, HAND));
    return { deck, keys, lid, rim, logo, keyCells, hand };
  }

  // ---------------------------------------------------------------- face (pixel)
  function pixelEyeRuns(o, pal) {
    const runs = [], w = o.w, h = o.h;
    if (w < 1 || h < 1) return runs;
    const x0 = R(o.cx - w / 2), y0 = R(o.cy - h / 2);
    const jit = (r) => (o.jit && hash(r * 3.7 + o.seed) < o.jit * 0.35 ? R((hash(r * 9.1 + o.seed * 1.3) - 0.5) * 8) : 0);
    if (o.happy) {
      const rx = w / 2, ry = Math.max(3, R(h * 0.4)), t = Math.max(2, R(w * 0.17)), base = R(o.cy + ry * 0.35);
      for (let r = 0; r < ry; r++) {
        const py = r - ry + 0.5;
        let run = null;
        for (let c = 0; c <= w; c++) {
          const px = c - rx + 0.5;
          const on = c < w && (px * px) / (rx * rx) + (py * py) / (ry * ry) <= 1 && !((px * px) / ((rx - t) ** 2) + (py * py) / ((ry - t) ** 2) < 1);
          if (on && !run) run = { x: x0 + c, y: base - ry + r, w: 0, c: r % 3 === 1 ? pal.light : pal.main };
          if (on) run.w++;
          if (!on && run) { runs.push(run); run = null; }
        }
      }
      return runs;
    }
    const prof = [6, 4, 2, 1, 1], lidProf = [2, 1];
    const cut = h > 3 ? Math.min(h - 2, R(h * (o.lid || 0))) : 0, maxIn = Math.floor((w - 1) / 2), band = h >= 10 ? R(h * 0.2) : 0;
    for (let r = cut; r < h; r++) {
      const it = cut > 0 ? lidProf[r - cut] || 0 : prof[r] || 0;
      const inset = Math.min(maxIn, Math.max(it, prof[h - 1 - r] || 0));
      const rw = w - inset * 2;
      if (rw <= 0) continue;
      const c = o.flash ? pal.hi : r >= h - band ? (r % 3 === 1 ? pal.main : pal.dark) : r % 3 === 1 ? pal.light : pal.main;
      runs.push({ x: x0 + inset + jit(r), y: y0 + r, w: rw, c });
    }
    if (o.hl) for (const [hx, hy, s] of [[w - 11, 5, 6], [w - 15, 13, 3]])
      for (let r = hy; r < hy + s; r++) if (r >= cut && r < h) runs.push({ x: x0 + hx, y: y0 + r, w: s, c: pal.hi });
    return runs;
  }
  function pixelFace(ctx, T, st, pal) {
    const f = st.face, colors = { "#": pal.main, "+": pal.hi };
    const dx = R(f.dx), dy = R(f.dy), bob = R(f.bob);
    let runs = [];
    if (f.sx > 0.001) {
      for (const [base, lid, raise] of [[EYE_L, f.lidL, 0], [EYE_R, f.lidR, f.raiseR]]) {
        const syEff = f.sy * f.wide * (1 - 0.95 * f.blink);
        const isHappy = f.happy && f.blink < 0.5;
        runs = runs.concat(pixelEyeRuns({
          cx: base.cx + dx, cy: base.cy + dy + bob - raise, w: Math.max(2, R(base.w * f.sx * f.wide)), h: Math.max(1, R(base.h * syEff)),
          lid, happy: isHappy, flash: f.flash, hl: !f.flash && !isHappy && syEff > 0.75, jit: f.jit, seed: Math.floor(T * 20),
        }, pal));
      }
    }
    if (f.mouth) {
      const m = MOUTHS[f.mouth];
      runs = runs.concat(spriteRuns(m, R(MOUTH.cx - m[0].length / 2 + dx * 0.6 + f.mouthDx), MOUTH.y + R(dy * 0.6) + bob, colors));
    }
    st.dots.forEach((d) => { for (let r = 0; r < d.s; r++) runs.push({ x: d.x, y: d.y + r, w: d.s, c: pal.main }); });
    st.sparks.forEach((sp) => {
      const spr = sp.big ? SPARK_B : SPARK_S;
      runs = runs.concat(spriteRuns(spr, sp.x - (spr.length >> 1), sp.y - (spr.length >> 1), colors));
    });
    drawRuns(ctx, runs);
  }

  // ---------------------------------------------------------------- face (smooth)
  function rrPath(ctx, x, y, w, h, rt, rb) {
    rt = Math.max(0, Math.min(rt, w / 2, h / 2)); rb = Math.max(0, Math.min(rb, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + rt, y); ctx.lineTo(x + w - rt, y); ctx.arc(x + w - rt, y + rt, rt, -Math.PI / 2, 0);
    ctx.lineTo(x + w, y + h - rb); ctx.arc(x + w - rb, y + h - rb, rb, 0, Math.PI / 2);
    ctx.lineTo(x + rb, y + h); ctx.arc(x + rb, y + h - rb, rb, Math.PI / 2, Math.PI);
    ctx.lineTo(x, y + rt); ctx.arc(x + rt, y + rt, rt, Math.PI, Math.PI * 1.5);
    ctx.closePath();
  }
  function eyeGrad(ctx, pal, y0, y1) {
    const gr = ctx.createLinearGradient(0, y0, 0, y1);
    gr.addColorStop(0, pal.eyeTop); gr.addColorStop(1, pal.eyeBot);
    return gr;
  }
  function smoothMouth(ctx, kind, mx, my, pal) {
    const c = pal.main;
    ctx.fillStyle = c; ctx.strokeStyle = c; ctx.lineJoin = "round"; ctx.lineCap = "round";
    const lens = (half, up, down) => {  // the mouths that are a lens between two curves
      ctx.beginPath(); ctx.moveTo(mx - half, my); ctx.quadraticCurveTo(mx, my + up, mx + half, my);
      ctx.quadraticCurveTo(mx, my + down, mx - half, my); ctx.closePath(); ctx.lineWidth = 0.9; ctx.fill(); ctx.stroke();
    };
    switch (kind) {
      case "neutral": return lens(7, 1.6, 6.4);
      case "grin": return lens(11, 2, 11);
      case "small": return lens(5, 1, 4);
      case "flat": ctx.beginPath(); ctx.roundRect(mx - 6, my + 0.6, 12, 2.3, 1.15); return ctx.fill();
      case "hmm": ctx.beginPath(); ctx.moveTo(mx - 6, my + 2.8); ctx.lineTo(mx + 6, my + 0.4); ctx.lineWidth = 2.3; return ctx.stroke();
      case "o": ctx.beginPath(); ctx.ellipse(mx, my + 3, 2.6, 3, 0, 0, Math.PI * 2); ctx.lineWidth = 1.9; return ctx.stroke();
      default: return null;
    }
  }
  function starPath(ctx, x, y, r) {
    ctx.beginPath(); ctx.moveTo(x, y - r);
    ctx.quadraticCurveTo(x, y, x + r, y); ctx.quadraticCurveTo(x, y, x, y + r);
    ctx.quadraticCurveTo(x, y, x - r, y); ctx.quadraticCurveTo(x, y, x, y - r); ctx.closePath();
  }
  function smoothFace(ctx, st, pal) {
    const f = st.face;
    if (f.sx > 0.001) {
      [[EYE_L, f.lidL, 0], [EYE_R, f.lidR, f.raiseR]].forEach(([b, lid, raise]) => {
        const open = 1 - 0.95 * f.blink;
        const w = Math.max(1.2, b.w * f.sx * f.wide), hF = b.h * f.sy * f.wide, h = Math.max(0.9, hF * open);
        const cx = b.cx + f.dx, cy = b.cy + f.dy + f.bob - raise;
        if (f.happy && f.blink < 0.5) {
          const t = w * 0.21, ry = hF * 0.33, base = cy + ry * 0.35, rx = w / 2 - t / 2;
          ctx.beginPath(); ctx.ellipse(cx, base, rx, ry, 0, Math.PI, Math.PI * 2);
          ctx.strokeStyle = eyeGrad(ctx, pal, base - ry - t / 2, base + t / 2); ctx.lineWidth = t; ctx.lineCap = "round"; ctx.stroke();
          return;
        }
        const x = cx - w / 2, y = cy - h / 2, cut = h > 3 ? Math.min(h - 2, h * lid) : 0;
        const r = Math.min(w * 0.3, h / 2);
        rrPath(ctx, x, y + cut, w, h - cut, cut > 0 ? Math.min(3, r) : r, r);
        ctx.fillStyle = f.flash ? pal.hi : eyeGrad(ctx, pal, y + cut, y + h);
        ctx.fill();
        if (!f.flash && open > 0.75) {
          const top = cy - hF / 2;
          ctx.save(); ctx.clip();
          ctx.fillStyle = pal.hi;
          ctx.beginPath(); ctx.arc(x + w * 0.71, top + hF * 0.23, w * 0.105, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.arc(x + w * 0.6, top + hF * 0.39, w * 0.048, 0, Math.PI * 2); ctx.fill();
          ctx.restore();
        }
      });
    }
    if (f.mouth) smoothMouth(ctx, f.mouth, MOUTH.cx + f.dx * 0.6 + f.mouthDx, MOUTH.y + 1 + f.dy * 0.6 + f.bob, pal);
    ctx.fillStyle = pal.main;
    st.dots.forEach((d) => { ctx.beginPath(); ctx.arc(d.x + d.s / 2, d.y + d.s / 2, d.s * 0.6, 0, Math.PI * 2); ctx.fill(); });
    st.sparks.forEach((sp) => {
      const r = sp.big ? 2.8 : 1.5;
      ctx.fillStyle = pal.main; starPath(ctx, sp.x + 0.5, sp.y + 0.5, r); ctx.fill();
      ctx.fillStyle = pal.hi; ctx.beginPath(); ctx.arc(sp.x + 0.5, sp.y + 0.5, r * 0.28, 0, Math.PI * 2); ctx.fill();
    });
  }

  // ---------------------------------------------------------------- notification bubbles and the focus moon
  function overlays(ctx, st, pal, smooth) {
    st.bubbles.forEach((b) => {
      const c = b.muted ? pal.dark : pal.main, fillC = smooth ? pal.smoothBg : pal.keyGap;
      ctx.save(); ctx.globalAlpha *= b.opacity;
      if (smooth) {
        ctx.translate(b.x, b.y); ctx.scale(b.scale, b.scale);
        ctx.strokeStyle = c; ctx.fillStyle = fillC; ctx.lineWidth = 1.1; ctx.lineJoin = "round";
        ctx.beginPath(); ctx.moveTo(-4, 4); ctx.lineTo(-5.8, 7.6); ctx.lineTo(-0.8, 4.3); ctx.fill(); ctx.stroke();
        ctx.beginPath(); ctx.roundRect(-7.5, -4.5, 15, 9, 4.5); ctx.fill(); ctx.stroke();
        ctx.fillStyle = c;
        for (const dx of [-3.6, 0, 3.6]) { ctx.beginPath(); ctx.arc(dx, 0, 1.1, 0, Math.PI * 2); ctx.fill(); }
      } else {
        ctx.translate(R(b.x), R(b.y)); ctx.scale(b.scale, b.scale); ctx.translate(-7.5, -4);
        drawRuns(ctx, spriteRuns(BUBBLE, 0, 0, { "#": c, f: fillC }));
      }
      ctx.restore();
    });
    if (st.moon) {
      const m = st.moon;
      ctx.save(); ctx.fillStyle = pal.main;
      if (smooth) {
        ctx.translate(m.x, m.y); ctx.scale(m.scale, m.scale);
        ctx.beginPath(); ctx.arc(0, 0, 7, 0, Math.PI * 2); ctx.clip();  // the circle, less the one that bites it
        ctx.beginPath(); ctx.arc(0, 0, 7, 0, Math.PI * 2); ctx.arc(3.6, -3, 5.9, 0, Math.PI * 2, true); ctx.fill();
      } else {
        ctx.translate(R(m.x), R(m.y)); ctx.scale(m.scale, m.scale);
        for (const [x, y] of MOON_CELLS) ctx.fillRect(x, y, 1, 1);
      }
      ctx.restore();
    }
  }

  // ---------------------------------------------------------------- the laptop, keys and hands, both looks
  const pts = (ctx, p) => { ctx.beginPath(); p.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); };
  const smoothLaptop = {
    deck(ctx, pal) {
      ctx.lineJoin = "round";
      pts(ctx, [[97, 147], [165, 160], [165, 163], [97, 150]]); ctx.fillStyle = ctx.strokeStyle = pal.baseFrontDark; ctx.lineWidth = 0.8; ctx.fill(); ctx.stroke();
      pts(ctx, [[165, 161], [219, 151], [219, 154], [165, 164]]); ctx.fillStyle = ctx.strokeStyle = pal.baseFront; ctx.fill(); ctx.stroke();
      pts(ctx, [BL, BR, FR, FL]); ctx.fillStyle = pal.keyGap; ctx.strokeStyle = pal.deckRim; ctx.lineWidth = 1; ctx.fill(); ctx.stroke();
    },
    keys(ctx, pal) {
      ctx.lineJoin = "round"; ctx.lineWidth = 0.4;
      ctx.fillStyle = ctx.strokeStyle = pal.keyLip;
      KEYS.forEach((k) => { pts(ctx, k.corners.map(([x, y]) => [x, y + 0.9])); ctx.fill(); ctx.stroke(); });
      ctx.fillStyle = ctx.strokeStyle = pal.keyFace;
      KEYS.forEach((k) => { pts(ctx, k.corners); ctx.fill(); ctx.stroke(); });
    },
    lid(ctx, pal) {
      const [, B, C, D] = LID;
      const gr = ctx.createLinearGradient(78, 96, 78 + 0.3 * 87, 160);
      gr.addColorStop(0, pal.lidLine); gr.addColorStop(1, pal.lid);
      pts(ctx, LID); ctx.fillStyle = gr; ctx.strokeStyle = pal.lid; ctx.lineWidth = 1.2; ctx.lineJoin = "round"; ctx.fill(); ctx.stroke();
      ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(D[0], D[1]); ctx.lineTo(C[0], C[1]); ctx.strokeStyle = pal.lidBottom; ctx.lineWidth = 1.3; ctx.stroke();
      ctx.beginPath(); ctx.moveTo(B[0] - 0.4, B[1] + 0.6); ctx.lineTo(C[0] - 0.4, C[1]); ctx.strokeStyle = pal.lidEdge; ctx.lineWidth = 1.9; ctx.stroke();
    },
    rim(ctx, pal) {
      const [A, B, , D] = LID;
      ctx.strokeStyle = pal.rim; ctx.lineWidth = 1; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(A[0], A[1]); ctx.lineTo(B[0], B[1]); ctx.moveTo(A[0], A[1]); ctx.lineTo(D[0], D[1]); ctx.stroke();
    },
    logo(ctx, pal) {
      const gr = ctx.createRadialGradient(115 + 0.45 * 12, 120 + 0.42 * 14, 0, 115 + 0.45 * 12, 120 + 0.42 * 14, 0.6 * 14);
      gr.addColorStop(0, pal.hi); gr.addColorStop(0.6, pal.hi); gr.addColorStop(1, pal.light);
      ctx.fillStyle = gr; ctx.beginPath(); ctx.ellipse(121, 127, 6, 7, 0, 0, Math.PI * 2); ctx.fill();
    },
    hand(ctx, x, y) {
      ctx.save(); ctx.translate(x, y);
      const gr = ctx.createLinearGradient(0.2 * 26, 0, 0.8 * 26, 16);
      gr.addColorStop(0, HAND.w); gr.addColorStop(0.55, HAND.w); gr.addColorStop(1, HAND.b);
      ctx.fillStyle = gr; ctx.fill(HAND_D); ctx.strokeStyle = HAND.o; ctx.lineWidth = 1; ctx.stroke(HAND_D);
      ctx.lineCap = "round"; ctx.lineWidth = 0.9;
      ctx.strokeStyle = HAND.s; ctx.stroke(HAND_THUMB);
      ctx.globalAlpha *= 0.85; ctx.strokeStyle = "#ffffff"; ctx.stroke(HAND_SHINE);
      ctx.restore();
    },
  };

  // ---------------------------------------------------------------- choreography (as in the design)
  function tapAt(T, streams, seed) {
    for (const [s, e, p] of streams) {
      if (T < s || T > e + 0.4) continue;
      const k = Math.floor((T - s) / p);
      for (let kk = k; kk >= Math.max(0, k - 1); kk--) {
        const t = s + kk * p + (hash(kk * 7.3 + seed) - 0.5) * p * 0.35;
        if (t <= T && t <= e) return { since: T - t, k: kk + seed * 100, big: p < 0.2 };
      }
    }
    return null;
  }
  function typingHands(T, sL, sR, lift, enterY) {
    const tapL = tapAt(T, sL, 1), tapR = tapAt(T, sR, 2);
    const pos = (base, tap, extra) => [base[0] + (tap ? [0, 1, 0, -1][Math.floor(hash(tap.k * 3.3) * 4)] : 0), base[1] + (tap && tap.since < 0.07 ? 1 : 0) + lift + extra];
    const l = pos(HAND_L, tapL, 0), r = pos(HAND_R, tapR, enterY);
    const lit = [], ticks = [];
    [[tapL, KEYS_L, l, 4], [tapR, KEYS_R, r, 6]].forEach(([tap, keys, hp, tx]) => {
      if (!tap) return;
      if (tap.since < 0.28) lit.push({ id: keys[Math.floor(hash(tap.k * 5.1) * keys.length)], c: tap.since < 0.14 ? "hi" : "light" });
      if (tap.since < 0.16) ticks.push({ x: hp[0] + (tap.big ? tx - 2 : tx), y: hp[1] - 7, big: tap.big });
    });
    return { hands: { l, r }, lit, ticks };
  }
  function sparksAt(T, list) {
    const out = [];
    for (const [x, y, big, t0] of list) {
      const a = T - t0;
      if (a >= 0 && a <= 0.75) out.push({ x, y, big: !!big && a > 0.06 && a < 0.6 });
    }
    return out;
  }

  // Robot Typing: Boot 1.8 s, Typing 3.6, Stuck 2.4, Idea 1.2, Burst 2.4, Done 2.2, Sleep 1.6
  const TC = { Boot: 0, Typing: 1.8, Stuck: 5.4, Idea: 7.8, Burst: 9.0, Done: 11.4, Sleep: 13.6 }, T_END = 15.2;
  function typingState(T, C, END) {
    const B = C.Boot, Ty = C.Typing, St = C.Stuck, Id = C.Idea, Bu = C.Burst, Dn = C.Done, Sl = C.Sleep;
    const sx = seq(T, [[B + 0.15, 0], [B + 0.3, 1.25, "snap"], [B + 0.75, 1, "move"], [Sl + 0.98, 1], [Sl + 1.2, 0.06, "snap"], [Sl + 1.42, 0, "move"]]);
    const sy = seq(T, [[B + 0.3, 0.02], [B + 0.75, 1, "pop"], [Sl + 0.72, 1], [Sl + 0.98, 0.02, "snap"]]);
    let dx = seq(T, [[Ty, 0], [Ty + 0.35, -3], [Ty + 2.0, -3], [Ty + 2.2, 3, "snap"], [Ty + 2.8, 3], [Ty + 3.0, -3, "snap"],
      [St + 0.45, -3], [St + 0.75, 5], [St + 1.35, 5], [St + 1.55, -4], [St + 2.0, -4], [St + 2.25, 4],
      [Id, 4], [Id + 0.08, 0, "snap"], [Id + 0.95, 0], [Id + 1.2, -3], [Dn, -3], [Dn + 0.15, 3], [Dn + 0.5, 3], [Dn + 0.6, 0, "snap"]]);
    const dy = seq(T, [[Ty, 0], [Ty + 0.35, 3], [Ty + 2.0, 3], [Ty + 2.2, 5, "snap"], [Ty + 2.8, 5], [Ty + 3.0, 3, "snap"],
      [St + 0.45, 3], [St + 0.75, -4], [St + 2.0, -4], [St + 2.25, -5],
      [Id, -5], [Id + 0.08, -1, "snap"], [Id + 0.95, -1], [Id + 1.2, 3], [Dn, 3], [Dn + 0.15, 4], [Dn + 0.5, 4], [Dn + 0.6, 0, "snap"]]);
    if (T > Bu + 0.2 && T < Dn) dx += Math.floor((T - Bu) / 0.42) % 2 ? 1 : -1;
    const blink = Math.max(...[B + 1.25, Ty + 1.4, Ty + 3.25, St + 1.45, Bu + 1.5, Dn + 0.48, Sl + 0.05].map((b) => blinkAt(T, b)));
    const happy = T >= Dn + 0.54 && T < Sl + 0.11;
    const focus = seq(T, [[Bu - 0.2, 0], [Bu + 0.1, 0.28], [Dn + 0.05, 0.28], [Dn + 0.2, 0]]);
    const droop = seq(T, [[Sl + 0.2, 0], [Sl + 0.55, 0.5]]);
    const hmmL = seq(T, [[St + 0.6, 0], [St + 0.8, 0.3], [Id - 0.05, 0.3], [Id, 0, "snap"]]);
    const bob = (sx > 0.3 ? Math.sin((T * Math.PI * 2) / 2.4) * 0.7 : 0)
      + seq(T, [[Dn + 0.54, 0], [Dn + 0.66, -3, "snap"], [Dn + 0.85, 0], [Dn + 0.95, -2, "snap"], [Dn + 1.1, 0]]);
    let mouth = null;
    if (T >= B + 0.85 && T < Sl + 0.72) mouth = T < Ty + 0.4 ? "neutral" : T < St + 0.6 ? "flat" : T < Id ? "hmm" : T < Id + 1.0 ? "o" : T < Dn + 0.54 ? "flat" : happy ? "grin" : "small";
    const face = {
      sx, sy, dx, dy, blink, happy, bob, mouth, mouthDx: mouth === "hmm" ? 4 : 0,
      flash: (T >= B + 0.15 && T < B + 0.42) || T >= Sl + 0.9,
      flicker: T > B + 0.3 && T < B + 0.95 ? (hash(Math.floor(T * 24)) > 0.35 ? 1 : 0.35) : 1,
      jit: T > B + 0.3 && T < B + 0.8 ? 1 : T > Id && T < Id + 0.12 ? 0.6 : 0,
      wide: seq(T, [[Id - 0.15, 1], [Id - 0.02, 0.88], [Id + 0.16, 1.14, "pop"], [Id + 0.85, 1.14], [Id + 1.15, 1]]),
      lidL: Math.max(focus, droop, hmmL), lidR: Math.max(focus, droop), raiseR: hmmL > 0.1 ? 1 : 0,
    };
    const dots = [];
    [[224, 46, 2], [230, 39, 3], [238, 31, 4]].forEach(([x, y, s], i) => { if (T >= St + 0.8 + i * 0.25 && T < Id) dots.push({ x, y, s }); });
    const sparks = sparksAt(T, [[114, 36, 1, Id + 0.05], [220, 32, 1, Id + 0.12], [242, 58, 0, Id + 0.2], [94, 60, 0, Id + 0.16],
      [216, 112, 1, Dn + 0.4], [228, 126, 0, Dn + 0.44], [200, 106, 0, Dn + 0.47]]);
    const lift = seq(T, [[St + 0.55, 0], [St + 0.8, -2], [Id - 0.02, -2], [Id + 0.12, -4, "pop"], [Bu - 0.05, -4], [Bu + 0.05, 0, "snap"]]);
    const enter = seq(T, [[Dn + 0.02, 0], [Dn + 0.34, -6], [Dn + 0.4, 1, "snap"], [Dn + 0.6, 1], [Dn + 0.8, 0]]);
    const th = typingHands(T, [[Ty + 0.3, St + 0.5, 0.24], [Bu + 0.04, Dn - 0.04, 0.13]], [[Ty + 0.42, St + 0.3, 0.24], [Bu + 0.1, Dn - 0.12, 0.13]], lift, enter);
    if (T >= Dn + 0.4 && T < Dn + 0.75) {
      KEYS_ENTER.forEach((id) => th.lit.push({ id, c: T < Dn + 0.55 ? "hi" : "light" }));
      if (T < Dn + 0.62) th.ticks.push({ x: th.hands.r[0] + 4, y: th.hands.r[1] - 8, big: true });
    }
    const cam = {
      fx: seq(T, [[0, 162], [Ty + 0.2, 162], [St, 178], [St + 0.2, 178], [St + 1.2, 166], [Bu, 166], [Bu + 0.5, 186], [Dn, 190], [Dn + 0.55, 190], [Dn + 1.3, 166], [Sl + 0.3, 166], [END, 162]]),
      fy: seq(T, [[0, 96], [Ty + 0.2, 96], [St, 116], [St + 0.2, 116], [St + 1.2, 72], [Bu, 70], [Bu + 0.5, 124], [Dn, 126], [Dn + 0.55, 126], [Dn + 1.3, 92], [Sl + 0.3, 92], [END, 96]]),
      s: seq(T, [[0, 1], [Ty, 1.04], [St, 1.22], [St + 0.2, 1.22], [St + 1.2, 1.3], [Id - 0.02, 1.36], [Id + 0.14, 1.5, "snap"], [Bu, 1.46],
        [Bu + 0.5, 1.6], [Dn, 1.66], [Dn + 0.4, 1.62], [Dn + 0.42, 1.7, "snap"], [Dn + 0.6, 1.66], [Dn + 1.3, 1.12], [Sl + 0.3, 1.1], [END, 1]]),
      shake: T > Dn + 0.4 && T < Dn + 0.56 ? (Math.floor(T * 40) % 2 ? 1 : -1) * (1 - (T - Dn - 0.4) / 0.16) * PX : 0,
    };
    return {
      face, dots, sparks, bubbles: [], moon: null, ...th, cam, dim: 0, glowBoost: 1,
      lights: seq(T, [[B + 0.45, 0], [B + 0.95, 1], [Sl + 0.85, 1], [Sl + 1.3, 0]]),
      logoOn: T < B + 0.62 ? 0 : T < B + 0.8 ? (hash(Math.floor(T * 30)) > 0.4 ? 1 : 0.2) : 1,
      rimB: seq(T, [[B + 0.5, 0], [B + 1.0, 0.55], [Bu - 0.1, 0.55], [Bu + 0.1, 1, "snap"], [Dn + 0.42, 1], [Dn + 0.5, 1, "snap"], [Dn + 0.9, 0.6], [Sl + 0.85, 0.6], [Sl + 1.3, 0]]),
      slam: seq(T, [[Dn + 0.4, 0], [Dn + 0.43, 1, "snap"], [Dn + 0.9, 0]]),
    };
  }

  // Robot Focus: Distracted 2.6 s, Switch 1.6, Deep 4.6, Flow 2.4, Release 2.4. The design's scripted muted
  // notifications are replaced by real ones (`muted`: seconds since each arrived).
  const FC = { Distracted: 0, Switch: 2.6, Deep: 4.2, Flow: 8.8, Release: 11.2 }, F_END = 13.6;
  const MUTED_SPOTS = [[236, 54], [94, 44], [218, 30]];
  function focusState(T, C, END, muted) {
    const Sw = C.Switch, De = C.Deep, Fl = C.Flow, Re = C.Release;
    let dx = seq(T, [[0, -3], [0.4, -3], [0.5, 5, "snap"], [0.85, 5], [0.97, -3, "snap"], [1.28, -3], [1.38, -6, "snap"], [1.7, -6], [1.82, -3, "snap"],
      [2.05, -3], [2.15, 4, "snap"], [2.45, 4], [Sw, 0], [Sw + 0.6, 0], [Sw + 0.8, -3], [Re + 0.2, -3], [Re + 0.32, 0, "snap"], [Re + 1.55, 0], [Re + 2.0, -3]]);
    const dy = seq(T, [[0, 3], [0.4, 3], [0.5, -3, "snap"], [0.85, -3], [0.97, 3, "snap"], [1.28, 3], [1.38, -2, "snap"], [1.7, -2], [1.82, 3, "snap"],
      [2.05, 3], [2.15, -5, "snap"], [2.45, -5], [Sw, 0], [Sw + 0.6, 0], [Sw + 0.8, 3], [Re + 0.2, 3], [Re + 0.32, -1, "snap"], [Re + 1.55, -1], [Re + 2.0, 3]]);
    if (T > De + 0.3 && T < Fl) dx += Math.floor((T - De) / 0.6) % 2 ? 1 : -1;
    if (T > Fl + 0.1 && T < Re) dx += Math.floor((T - Fl) / 0.35) % 2 ? 1 : -1;
    const longBlink = seq(T, [[Sw + 0.1, 0], [Sw + 0.2, 1, "snap"], [Sw + 0.6, 1], [Sw + 0.78, 0]]);
    const blink = Math.max(longBlink, ...[De + 2.0, De + 4.0, Fl + 1.2, Re + 0.55, Re + 1.5].map((b) => blinkAt(T, b)));
    const happy = T >= Re + 0.61 && T < Re + 1.56;
    const lid = seq(T, [[Sw + 0.55, 0], [Sw + 0.6, 0.32, "snap"], [Fl, 0.32], [Fl + 0.3, 0.38], [Re + 0.15, 0.38], [Re + 0.3, 0, "snap"]]);
    const bob = Math.sin((T * Math.PI * 2 * 6) / END) * 0.7 + seq(T, [[Re + 0.62, 0], [Re + 0.74, -3, "snap"], [Re + 0.93, 0], [Re + 1.03, -2, "snap"], [Re + 1.18, 0]]);
    const mouth = T < 0.5 ? "neutral" : T < 2.15 ? "flat" : T < Sw + 0.1 ? "hmm" : T < Sw + 0.75 ? "small" : T < Re + 0.32 ? "flat" : T < Re + 0.61 ? "o" : happy ? "grin" : "neutral";
    const face = {
      sx: 1, sy: 1, flash: false, flicker: 1, jit: 0, dx, dy, blink, happy, bob, mouth, mouthDx: mouth === "hmm" ? 4 : 0,
      wide: seq(T, [[Sw + 0.55, 1], [Sw + 0.6, 0.94, "snap"], [Re + 0.12, 0.94], [Re + 0.22, 0.86], [Re + 0.4, 1.12, "pop"], [Re + 0.55, 1.12], [Re + 0.8, 1]]),
      lidL: lid, lidR: lid, raiseR: 0,
    };
    const bubbles = [];
    const gone = seq(T, [[Sw + 0.15, 1], [Sw + 0.45, 0]]);
    [[236, 50, 0.38], [92, 46, 1.3], [230, 24, 2.08]].forEach(([x, y, t0]) => {
      const sc = seq(T, [[t0, 0], [t0 + 0.22, 1, "pop"]]) * gone;
      if (sc > 0.01) bubbles.push({ x, y: y + Math.sin((T - t0) * 3) * 0.6, scale: sc, opacity: 1, muted: false });
    });
    let pulse = 0;
    muted.forEach(({ age, spot }) => {
      const [x, y] = MUTED_SPOTS[spot];
      const sc = seq(age, [[0, 0], [0.15, 0.75, "pop"], [0.35, 0.75], [0.7, 0]]);
      if (sc > 0.01) bubbles.push({ x, y, scale: sc, opacity: 0.6, muted: true });
      pulse += seq(age, [[0.3, 0], [0.38, 0.25, "snap"], [0.7, 0]]);
    });
    const moonS = seq(T, [[Sw + 0.7, 0], [Sw + 0.95, 1, "pop"], [Re + 0.2, 1], [Re + 0.5, 0]]);
    const th = typingHands(T,
      [[0.05, 0.38, 0.22], [1.0, 1.28, 0.22], [1.84, 2.06, 0.22], [De + 0.3, Fl, 0.2], [Fl + 0.02, Re - 0.05, 0.13]],
      [[0.16, 0.36, 0.22], [1.1, 1.26, 0.22], [1.95, 2.06, 0.22], [De + 0.4, Fl, 0.2], [Fl + 0.08, Re - 0.1, 0.13]],
      seq(T, [[Re + 0.35, 0], [Re + 0.5, -3, "pop"], [Re + 1.4, -3], [Re + 1.7, 0]]), 0);
    const cam = {
      fx: seq(T, [[0, 162], [Sw, 164], [Sw + 1.0, 166], [De + 0.6, 172], [Fl, 178], [Fl + 0.5, 186], [Re, 188], [Re + 0.9, 166], [END, 162]]),
      fy: seq(T, [[0, 96], [Sw, 90], [Sw + 1.0, 80], [De + 0.6, 96], [Fl, 106], [Fl + 0.5, 122], [Re, 124], [Re + 0.9, 92], [END, 96]]),
      s: seq(T, [[0, 1], [Sw, 1.06], [Sw + 1.0, 1.18], [De + 0.6, 1.22], [Fl, 1.3], [Fl + 0.5, 1.55], [Re, 1.6], [Re + 0.9, 1.1], [END, 1]]),
      shake: 0,
    };
    return {
      face, dots: [], sparks: [], bubbles, ...th, cam,
      moon: moonS > 0.01 ? { x: 238, y: 42 + Math.sin(T * 2) * 0.6, scale: moonS * (1 + pulse) } : null,
      dim: seq(T, [[Sw + 0.2, 0], [Sw + 0.95, 1], [Re + 0.2, 1], [Re + 1.0, 0]]),
      glowBoost: 1 + seq(T, [[Sw + 0.72, 0], [Sw + 0.82, 0.7, "snap"], [Sw + 1.3, 0]]),
      lights: 1, logoOn: 1, slam: 0,
      rimB: seq(T, [[0, 0.55], [Sw + 0.7, 0.55], [Sw + 1.0, 0.75], [Fl, 0.75], [Fl + 0.2, 1], [Re + 0.2, 1], [Re + 1.0, 0.55]]),
    };
  }

  // ---------------------------------------------------------------- what plays, from what's happening
  // Each section that can last as long as you keep going loops over a stretch whose two ends match, so the
  // face never jumps; between sections it moves on at points where the design's motion lines up.
  let run = null;  // { piece: "typing" | "focus", T, phase }
  // previews start a scene at a given moment of the design, without the fade: ?typing&sceneT=10 or ?mood=focus&sceneT=9
  const startT = new URLSearchParams(location.search).has("sceneT") ? Number(new URLSearchParams(location.search).get("sceneT")) : null;
  if (startT != null) wrap.style.transition = "none";
  const typingAt = (T) => ({ piece: "typing", T, phase: T >= TC.Done ? "done" : T >= TC.Burst ? "burst" : T >= TC.Idea ? "idea" : T >= TC.Stuck ? "stuck" : T >= TC.Typing + 0.4 ? "type" : "boot" });
  const focusAt = (T) => ({ piece: "focus", T, phase: T >= FC.Release ? "release" : T >= FC.Flow + 0.3 ? "flow" : T >= FC.Deep + 0.3 ? "deep" : "switch" });
  const muted = [];  // notifications during a focus session
  let nextSpot = 0;
  document.addEventListener("chip:notify", () => {
    if (run && run.piece === "focus" && run.phase !== "release") { muted.push({ at: performance.now(), spot: nextSpot }); nextSpot = (nextSpot + 1) % 3; }
  });
  function live() {
    const d = app.dataset;
    return { focus: d.focus === "1", typing: d.typing === "1", fast: Number(d.wpm) >= 60, paused: Number(d.idle) >= 2 };
  }
  function advance(dt) {
    const L = live();
    if (!run) {
      if (L.focus) run = focusAt(startT ?? FC.Switch);
      else if (L.typing) run = typingAt(startT ?? TC.Boot);
      return;
    }
    run.T += dt;
    const T = run.T;
    if (run.piece === "focus") {
      const C = FC, deep0 = C.Deep + 0.3, flow0 = C.Flow + 0.3;
      if (!L.focus && run.phase !== "release") { run.phase = "release"; run.T = Math.max(T, C.Release); return; }
      if (run.phase === "switch" && T >= deep0) run.phase = "deep";
      else if (run.phase === "deep" && T >= C.Flow) {
        if (L.fast) run.phase = "flow"; else run.T -= C.Flow - deep0;
      } else if (run.phase === "flow" && T >= C.Release) {
        if (L.fast) run.T -= C.Release - flow0; else { run.T = deep0; run.phase = "deep"; }
      } else if (run.phase === "release" && T >= F_END) run = null;
      return;
    }
    const C = TC, type0 = C.Typing + 0.4, burst0 = C.Burst + 0.2;
    if (L.focus) { run = { piece: "focus", T: FC.Switch, phase: "switch" }; return; }  // focus takes over
    switch (run.phase) {
      case "boot":
        if (T >= type0) run.phase = "type";
        break;
      case "type":
        if (T < C.Stuck) break;
        if (!L.typing) { run.T = C.Done; run.phase = "done"; }
        else if (L.paused) run.phase = "stuck";
        else if (L.fast) { run.T = C.Burst + 0.05; run.phase = "burst"; }
        else run.T -= C.Stuck - type0;
        break;
      case "stuck":
        if (!L.typing) { run.T = C.Done; run.phase = "done"; }
        else if (!L.paused && T >= C.Stuck + 0.8) { run.T = C.Idea; run.phase = "idea"; }  // back at it: an idea
        else if (L.paused && T >= C.Stuck + 2.0) run.T = C.Stuck + 0.75;  // still thinking
        break;
      case "idea":
        if (T >= C.Burst) {
          if (L.fast) run.phase = "burst"; else { run.T = type0; run.phase = "type"; }
        }
        break;
      case "burst":
        if (T < C.Done) break;
        if (!L.typing) run.phase = "done";
        else if (L.fast) run.T -= C.Done - burst0;
        else { run.T = type0; run.phase = "type"; }
        break;
      case "done":
        if (T >= T_END) run = null;  // through Sleep: the face powers off, and the normal one comes back
        break;
    }
  }
  // While a section loops the camera holds the framing it starts with: the design's slow push-in would otherwise
  // pull back out at every wrap (and keep the frame rate up)
  const HOLD = { type: TC.Typing + 0.4, deep: FC.Deep + 0.3, flow: FC.Flow + 0.3 };
  function sceneState() {
    const now = performance.now();
    while (muted.length && now - muted[0].at > 1200) muted.shift();
    const at = (T) => (run.piece === "typing" ? typingState(T, TC, T_END) : focusState(T, FC, F_END, muted.map((m) => ({ age: (now - m.at) / 1000, spot: m.spot }))));
    const st = at(run.T);
    if (run.phase in HOLD) st.cam = at(HOLD[run.phase]).cam;
    return st;
  }

  // ---------------------------------------------------------------- drawing
  // The scene is drawn on the design's grid (1 px a unit for the pixel look, 2 for smooth), and the grid is then
  // drawn on screen through the camera: crisp big pixels for the pixel look. Glow comes from blurred copies (a
  // wide and a narrow blur, at half size): for the face and bubbles every frame, for the keys, the lid's rim and
  // its logo once per palette (they don't change); lit keys and tap marks go without, to spare the phone.
  const gridCv = layer(), gg = gridCv.getContext("2d");
  const glowCv = layer(GW / 2, GH / 2), glowG = glowCv.getContext("2d");
  let built = null;  // { key, pixel: buildPixelStatic(pal), glow: { keys, rim, logo } }
  function blurredCopy(draw, scale) {  // the glow of a part that doesn't change, made once
    const src = layer(GW * scale / 2, GH * scale / 2), sg = src.getContext("2d");
    sg.setTransform(scale / 2, 0, 0, scale / 2, 0, 0); draw(sg);
    const out = layer(GW * scale, GH * scale), o = out.getContext("2d");
    o.globalAlpha = 0.5; o.filter = `blur(${(scale > 1 ? 6 : 5) * scale}px)`; o.drawImage(src, 0, 0, out.width, out.height);
    o.globalAlpha = 0.85; o.filter = `blur(${(scale > 1 ? 2 : 1.6) * scale}px)`; o.drawImage(src, 0, 0, out.width, out.height);
    return out;
  }
  const cam = { fx: 162, fy: 96, s: 1 };
  function glowing(ctx, scale, weight, items) {  // items: [[draw(ctx), opacity, glowWeight]]
    const gw = glowCv.width, gh = glowCv.height;
    glowG.setTransform(1, 0, 0, 1, 0, 0); glowG.clearRect(0, 0, gw, gh);
    glowG.setTransform(scale / 2, 0, 0, scale / 2, 0, 0);
    let any = false;
    for (const [draw, opacity, w] of items) {
      const a = Math.min(1, w * weight) * opacity;
      if (a <= 0.01) continue;
      glowG.globalAlpha = a; draw(glowG); any = true;
    }
    glowG.globalAlpha = 1;
    if (!any) return;
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.imageSmoothingEnabled = true;
    const smooth = scale > 1;
    ctx.globalAlpha = 0.5; ctx.filter = `blur(${(smooth ? 6 : 5) * scale}px)`; ctx.drawImage(glowCv, 0, 0, gridCv.width, gridCv.height);
    ctx.globalAlpha = 0.85; ctx.filter = `blur(${(smooth ? 2 : 1.6) * scale}px)`; ctx.drawImage(glowCv, 0, 0, gridCv.width, gridCv.height);
    ctx.restore();
  }
  function render(T, st) {
    const pal = PALETTES[app.dataset.accent] || PALETTES.cyan;
    const smooth = !app.classList.contains("pixel"), scale = smooth ? 2 : 1, glow = smooth ? 0.9 : 0.65;
    if (gridCv.width !== GW * scale) { gridCv.width = GW * scale; gridCv.height = GH * scale; glowCv.width = GW * scale / 2; glowCv.height = GH * scale / 2; }
    const key = app.dataset.accent + (smooth ? "s" : "p");
    if (!built || built.key !== key) built = { key, pixel: smooth ? null : buildPixelStatic(pal) };
    const P = built.pixel, g = gg, bg = smooth ? pal.smoothBg : pal.bg;
    const drawKeys = (c) => (smooth ? smoothLaptop.keys(c, pal) : c.drawImage(P.keys, 0, 0));
    const drawRim = (c) => { if (smooth) smoothLaptop.rim(c, pal); else { c.fillStyle = pal.rim; for (const [x, y] of P.rim) c.fillRect(x, y, 1, 1); } };
    const drawLogo = (c) => {
      if (smooth) smoothLaptop.logo(c, pal);
      else for (const p of P.logo) { c.fillStyle = p.inner ? pal.hi : pal.light; c.fillRect(p.x, p.y, 1, 1); }
    };
    if (!built.glow) built.glow = { keys: blurredCopy(drawKeys, scale), rim: blurredCopy(drawRim, scale), logo: blurredCopy(drawLogo, scale) };
    const cached = (img, a) => { if (a > 0.01) { g.globalAlpha = a; g.drawImage(img, 0, 0, GW, GH); } };
    g.setTransform(scale, 0, 0, scale, 0, 0);
    g.globalAlpha = 1; g.filter = "none"; g.imageSmoothingEnabled = false;
    g.fillStyle = bg; g.fillRect(0, 0, GW, GH);
    const dim = st.dim || 0;
    const ellipse = (cx, cy, rx, ry, color, stop0, alpha) => {
      if (alpha <= 0) return;
      g.save(); g.globalAlpha = alpha; g.translate(cx, cy); g.scale(rx, ry);
      const gr = g.createRadialGradient(0, 0, 0, 0, 0, 1);
      gr.addColorStop(0, color + stop0); gr.addColorStop(1, color + "00");
      g.fillStyle = gr; g.beginPath(); g.arc(0, 0, 1, 0, Math.PI * 2); g.fill(); g.restore();
    };
    if (smooth) ellipse(166, 72, 150, 95, pal.smoothCenter, "ff", st.lights * (1 - 0.5 * dim));
    ellipse(156, 161, 88 - 30 * dim, 11, pal.floor, "8c", st.lights * (0.7 + 0.3 * st.slam));

    const drawFace = (c) => (smooth ? smoothFace(c, st, pal) : pixelFace(c, T, st, pal));
    const drawOver = (c) => overlays(c, st, pal, smooth);
    const fg = glow * (st.glowBoost || 1);
    // face and notification bubbles / moon, glowing
    glowing(g, scale, 1, [[drawFace, st.face.flicker, fg], [drawOver, 1, glow]]);
    g.globalAlpha = st.face.flicker; drawFace(g); g.globalAlpha = 1;
    drawOver(g);

    // the laptop (fades in and out with the lights)
    const L = st.lights;
    if (L > 0.01) {
      const hand = (c, [x, y]) => (smooth ? smoothLaptop.hand(c, x, y) : c.drawImage(P.hand, R(x), R(y)));
      const drawLit = (c) => st.lit.forEach((l) => {
        c.fillStyle = pal[l.c];
        if (smooth) { const k = KEYS[l.id]; if (k) { pts(c, k.corners); c.strokeStyle = pal[l.c]; c.lineWidth = 0.5; c.fill(); c.stroke(); } }
        else for (const [x, y] of P.keyCells[l.id] || []) c.fillRect(x, y, 1, 1);
      });
      const drawTicks = (c) => {
        if (smooth) {
          c.strokeStyle = pal.main; c.lineWidth = 1; c.lineCap = "round"; c.beginPath();
          st.ticks.forEach((tk) => TICK_LINES[tk.big ? "big" : "small"].forEach(([x1, y1, x2, y2]) => { c.moveTo(tk.x + x1 + 0.5, tk.y + y1 + 0.5); c.lineTo(tk.x + x2 + 0.5, tk.y + y2 + 0.5); }));
          c.stroke();
        } else drawRuns(c, st.ticks.flatMap((tk) => spriteRuns(tk.big ? TICK_BIG : TICK, R(tk.x), R(tk.y), { "#": pal.main })));
      };
      const rimA = Math.min(1, st.rimB + st.slam * 0.4) * L, logoA = st.logoOn * L;

      g.globalAlpha = L;
      if (smooth) smoothLaptop.deck(g, pal); else g.drawImage(P.deck, 0, 0);
      cached(built.glow.keys, L * Math.min(1, glow * 0.3));
      g.globalAlpha = L; drawKeys(g); drawLit(g);
      hand(g, st.hands.l); hand(g, st.hands.r);
      drawTicks(g);
      if (smooth) smoothLaptop.lid(g, pal); else g.drawImage(P.lid, 0, 0);
      cached(built.glow.rim, rimA * Math.min(1, glow * (0.8 + st.slam)));
      cached(built.glow.logo, logoA * Math.min(1, glow * (1 + st.slam * 0.8)));
      g.globalAlpha = rimA; drawRim(g);
      g.globalAlpha = logoA; drawLogo(g);
      g.globalAlpha = 1;
    }

    // on screen through the camera, eased so the loops' camera moves never jump
    const W = cv.width, H = cv.height, k = (H / GH) * ZOOM;
    vg.setTransform(1, 0, 0, 1, 0, 0);
    vg.fillStyle = bg; vg.fillRect(0, 0, W, H);
    vg.imageSmoothingEnabled = smooth;
    vg.translate(Math.round(W / 2 + (st.cam.shake / PX) * k * cam.s), Math.round(H * 0.45));
    vg.scale(cam.s * k, cam.s * k);
    vg.translate(-cam.fx, -cam.fy);
    vg.drawImage(gridCv, 0, 0, GW, GH);
    // the vignette, and the room dimming in focus mode, drawn here rather than as page overlays (cheaper)
    vg.setTransform(1, 0, 0, 1, 0, 0);
    const shade = (rx, ry, inner, alpha) => {
      vg.save(); vg.translate(W / 2, H * 0.52); vg.scale(rx, ry);
      const gr = vg.createRadialGradient(0, 0, 0, 0, 0, 1);
      gr.addColorStop(inner, "rgba(0,0,0,0)"); gr.addColorStop(1, `rgba(0,0,0,${alpha})`);
      vg.fillStyle = gr; vg.fillRect(-2, -2, 4, 4); vg.restore();
    };
    shade(W * 0.71, H * 0.71, 0.55, 0.55);
    if (dim > 0.001) shade(W * 0.46, H * 0.54, 0.35, 0.82 * dim);
  }

  // ---------------------------------------------------------------- loop: every frame costs this phone a
  // whole-screen redraw (about 7% CPU per frame a second), so ~12 fps for the moves and 8 once Chip has settled
  // into a loop (typing away, deep focus, flow, stuck) with the camera still
  const STEADY = ["type", "stuck", "deep", "flow"];
  let raf = 0, last = 0, steady = false;
  function frame(t) {
    raf = requestAnimationFrame(frame);
    if (last && t - last < (steady ? 125 : 83)) return;
    const dt = last ? Math.min(0.1, (t - last) / 1000) : 0.04;
    last = t;
    advance(dt);
    app.classList.toggle("scene", !!run);
    if (!run) { cancelAnimationFrame(raf); raf = 0; last = 0; return; }
    if (!faceScreen.classList.contains("active") || document.hidden) return;  // keeps time, draws nothing
    // the screen canvas is only as fine as the grid (CSS scales it up, crisp for the pixel look): drawing it
    // at the phone's full resolution kept a whole CPU core busy
    const r = cv.getBoundingClientRect(), scale = app.classList.contains("pixel") ? 1 : 2;
    const h = Math.round((GH / ZOOM) * scale), w = Math.round((h * r.width) / Math.max(1, r.height));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    const st = sceneState();
    const a = 1 - Math.exp(-dt * 5);
    cam.fx += (st.cam.fx - cam.fx) * a; cam.fy += (st.cam.fy - cam.fy) * a; cam.s += (st.cam.s - cam.s) * a;
    steady = STEADY.includes(run.phase) && Math.abs(st.cam.fx - cam.fx) + Math.abs(st.cam.fy - cam.fy) < 1 && Math.abs(st.cam.s - cam.s) < 0.01;
    render(run.T, st);
  }
  function wake() {
    if (raf) return;
    const L = live();
    if (L.focus || L.typing) { last = 0; raf = requestAnimationFrame(frame); }
  }
  new MutationObserver(wake).observe(app, { attributes: true, attributeFilter: ["data-focus", "data-typing"] });
  wake();
})();
