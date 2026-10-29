// Pixel-art face: draws the buddy on a tiny canvas that CSS scales up with crisp pixels.
// It reads the state buddy.js puts on the (invisible) #face: mood classes, blink, gaze, accessories.
(() => {
  "use strict";
  const app = document.getElementById("app"), face = document.getElementById("face");
  const cv = document.getElementById("pix"), g = cv.getContext("2d");
  const CW = cv.width, CH = cv.height;                 // 62 × 42 pixels
  const EW = 18, EH = 24, EY = 8, LX = 6, RX = 38;    // eye size and left edges
  const MOUTH = { x: 22, y: 33, w: 17, h: 7 };         // the mouth box, in pixels

  // lid closure (fraction of eye height), lid tilt (degrees) and eye scale for each mood
  const MOODS = {
    happy: { bot: .4 }, joy: { bot: .5, sc: 1.05 }, drowsy: { top: .36 }, sleepy: { top: .54 },
    asleep: { closed: 1 }, angry: { top: .36, rot: 22 }, focus: { top: .22, rot: 9 }, strain: { top: .3, rot: 14 },
    sad: { top: .28, rot: -18 }, worried: { top: .22, rot: -14, bot: .08 }, surprised: { sc: 1.13 },
    suspicious: { top: .46, topR: .06, botR: .22 }, curious: { scL: .86, scR: 1.1 }, wink: { winkR: 1 },
    love: { sprite: "heart" }, dizzy: { sprite: "spiral" }, star: { sprite: "star" }, yawn: { top: .46 },
    whistle: { top: .08 }, bored: { top: .4, bot: .06 }, smirk: { bot: .26, topR: .2 },
    listen: { sc: 1.06 }, think: { top: .18, topR: .3, rot: -6 },
  };
  // mouth outlines: x0 y0, upper-lip control, x1 y1, lower-lip control
  const MOUTHS = {
    neutral: [32, 18, 50, 22, 68, 18, 50, 30], happy: [24, 14, 50, 18, 76, 14, 50, 38],
    joy: [18, 10, 50, 12, 82, 10, 50, 46], flat: [36, 21, 50, 20, 64, 21, 50, 23],
    sad: [32, 27, 50, 14, 68, 27, 50, 19], worried: [34, 25, 50, 17, 66, 25, 50, 21],
    o: [41, 20, 50, -4, 59, 20, 50, 44], yawn: [34, 20, 50, -22, 66, 20, 50, 62],
    whistle: [46, 20, 50, 13, 54, 20, 50, 27], sleepy: [42, 22, 50, 21, 58, 22, 50, 25],
    asleep: [45, 22, 50, 17, 55, 22, 50, 27], dizzy: [30, 24, 50, 30, 70, 16, 50, 26],
    smirk: [38, 23, 54, 23, 68, 15, 54, 28], bored: [38, 23, 50, 23, 62, 23, 50, 24],
    talkA: [34, 18, 50, 20, 66, 18, 50, 26], talkB: [38, 16, 50, 8, 62, 16, 50, 34],
  };
  const MOOD_MOUTH = {
    happy: "happy", love: "happy", wink: "happy", joy: "joy", star: "joy", focus: "flat", strain: "flat",
    sad: "sad", worried: "worried", angry: "worried", surprised: "o", yawn: "yawn", whistle: "whistle",
    sleepy: "sleepy", drowsy: "sleepy", asleep: "asleep", dizzy: "dizzy", suspicious: "smirk",
    curious: "smirk", smirk: "smirk", bored: "bored", listen: "whistle", think: "bored",
  };
  const SPRITES = {
    heart: [".##...##.", "####.####", "#########", "#########", ".#######.", "..#####..", "...###...", "....#...."],
    star: ["....#....", "....#....", "...###...", "#########", ".#######.", "..#####..", "..##.##..", ".##...##.", ".#.....#."],
    drop: [".#.", "###", "###", ".#."],
  };

  // ---------------------------------------------------------------- state (eased towards targets)
  const cur = { topL: 0, topR: 0, botL: 0, botR: 0, rot: 0, sc: 1, scL: 1, scR: 1, closed: 0, blink: 0, winkR: 0,
    lx: 0, ly: 0, lookL: 1, lookR: 1 };
  const tgt = Object.assign({}, cur);
  const SPEED = { lx: 90, ly: 90, blink: 1 };          // ms time constants; lids default to 60
  const st = { mood: "neutral", sprite: null, talk: false, color: [77, 232, 255], music: false, masked: false };
  let lastKey = "";

  function rgb(css) {
    css = css.trim();
    if (css[0] === "#") { const n = parseInt(css.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
    const m = css.match(/[\d.]+/g);
    return m ? m.slice(0, 3).map(Number) : [77, 232, 255];
  }
  const css = (c) => `rgb(${c.join(",")})`;
  const mix = (c, to, a) => `rgb(${c.map((v, i) => Math.round(v + (to[i] - v) * a)).join(",")})`;
  const WHITE = [255, 255, 255], BLACK = [0, 0, 0];

  function readState() {
    let mood = "neutral";
    for (const c of face.classList) if (c.startsWith("m-")) mood = c.slice(2);
    const m = MOODS[mood] || {};
    const v = (name, d) => { const x = parseFloat(face.style.getPropertyValue(name)); return isNaN(x) ? d : x; };
    Object.assign(tgt, {
      topL: m.top || 0, topR: m.topR ?? m.top ?? 0, botL: m.bot || 0, botR: m.botR ?? m.bot ?? 0, rot: m.rot || 0,
      sc: m.sc || 1, scL: m.scL || 1, scR: m.scR || 1, closed: m.closed || 0, winkR: m.winkR || 0,
      blink: face.classList.contains("blink") ? 1 : 0,
      lx: v("--lx", 0) / 7, ly: v("--ly", 0) / 5, lookL: v("--sl", 1), lookR: v("--sr", 1),
    });
    Object.assign(st, {
      mood, sprite: m.sprite || null, talk: face.classList.contains("talk"),
      color: rgb(getComputedStyle(face).getPropertyValue("--eye") || "#4de8ff"),
      music: app.classList.contains("music"), masked: app.classList.contains("masked"),
    });
    cv.style.setProperty("--tilt", face.style.getPropertyValue("--tilt") || "0deg");
    const key = JSON.stringify([tgt, st]);
    if (key !== lastKey) { lastKey = key; kick(); }
  }

  // ---------------------------------------------------------------- drawing helpers
  function px(x, y, color) { g.fillStyle = color; g.fillRect(Math.round(x), Math.round(y), 1, 1); }
  function sprite(rows, cx, cy, scale, color) {
    const w = rows[0].length * scale, h = rows.length * scale, x0 = Math.round(cx - w / 2), y0 = Math.round(cy - h / 2);
    g.fillStyle = color;
    rows.forEach((row, j) => [...row].forEach((ch, i) => { if (ch === "#") g.fillRect(x0 + i * scale, y0 + j * scale, scale, scale); }));
  }
  function line(x0, y0, x1, y1, color) {  // Bresenham
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy;
    for (;;) {
      px(x0, y0, color);
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x0 += sx; }
      if (e2 <= dx) { err += dx; y0 += sy; }
    }
  }

  function drawEye(cx, cy, side) {
    const s = cur, scale = (side < 0 ? s.scL * s.lookL : s.scR * s.lookR) * s.sc;
    const w = Math.max(3, Math.round(EW * scale)), fullH = Math.round(EH * scale);
    const shut = Math.max(s.blink, s.closed, side > 0 ? s.winkR : 0);
    const h = Math.max(1, Math.round(fullH * (1 - shut * 0.94)));
    const x0 = Math.round(cx - w / 2), y0 = Math.round(cy - h / 2);
    const top = side < 0 ? s.topL : s.topR, bot = side < 0 ? s.botL : s.botR;
    const slope = Math.tan((s.rot * Math.PI) / 180) * (side < 0 ? 1 : -1);
    const rx = Math.max(1, w * 0.3), ry = Math.max(1, h * 0.26), mid = (w - 1) / 2;
    const c = st.color, light = mix(c, WHITE, 0.3), base = css(c), dark = mix(c, BLACK, 0.28);
    // highlight blocks drift with the gaze
    const gx = Math.round(s.lx), gy = Math.round(s.ly);
    const shine = (i, j) =>
      (i >= w * 0.6 + gx && i < w * 0.83 + gx && j >= h * 0.12 + gy && j < h * 0.3 + gy) ||
      (i >= w * 0.5 + gx && i < w * 0.6 + gx && j >= h * 0.34 + gy && j < h * 0.42 + gy);
    g.globalAlpha = s.closed > 0.5 ? 0.6 : 1;
    for (let j = 0; j < h; j++) {
      for (let i = 0; i < w; i++) {
        const dx = Math.max(0, rx - (i + 0.5), i + 0.5 - (w - rx)), dy = Math.max(0, ry - (j + 0.5), j + 0.5 - (h - ry));
        if ((dx / rx) ** 2 + (dy / ry) ** 2 > 1) continue;                                   // rounded-off corner
        if (j + 0.5 < top * h + slope * (i - mid)) continue;                                  // top lid
        const bc = bot * h * Math.sqrt(Math.max(0, 1 - ((i - mid) / (0.75 * w)) ** 2));
        if (j + 0.5 > h - bc) continue;                                                       // bottom lid
        const color = h > 3 && shine(i, j) ? "#f4fbff" : j < h * 0.18 ? light : j > h * 0.78 ? dark : base;
        px(x0 + i, y0 + j, color);
      }
    }
    g.globalAlpha = 1;
  }

  function drawSpiral(cx, cy, t) {
    const phase = t / 160, color = css(st.color);
    for (let a = 0; a < 4.2 * Math.PI; a += 0.16) {
      const r = a * 0.7;
      px(cx + r * Math.cos(a + phase) - 0.5, cy + r * Math.sin(a + phase) - 0.5, color);
    }
  }

  // mouth: fill pixels inside the outline, plus anything within half a pixel of it (so thin mouths still show)
  const mouthCache = {};
  function mouthPixels(key) {
    if (mouthCache[key]) return mouthCache[key];
    const [x0, y0, ax, ay, x1, y1, bx, by] = MOUTHS[key];
    const q = (sx, sy, cx, cy, ex, ey, u) => [(1 - u) ** 2 * sx + 2 * (1 - u) * u * cx + u * u * ex, (1 - u) ** 2 * sy + 2 * (1 - u) * u * cy + u * u * ey];
    const pts = [];
    for (let i = 0; i <= 16; i++) pts.push(q(x0, y0, ax, ay, x1, y1, i / 16));
    for (let i = 1; i < 16; i++) pts.push(q(x1, y1, bx, by, x0, y0, i / 16));
    const P = pts.map(([x, y]) => [MOUTH.x + (x / 100) * MOUTH.w, MOUTH.y + (y / 40) * MOUTH.h]);
    const inside = (x, y) => {
      let hit = false;
      for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
        if ((P[i][1] > y) !== (P[j][1] > y) && x < ((P[j][0] - P[i][0]) * (y - P[i][1])) / (P[j][1] - P[i][1]) + P[i][0]) hit = !hit;
      }
      return hit;
    };
    const near = (x, y) => P.some(([ax2, ay2], i) => {
      const [bx2, by2] = P[(i + 1) % P.length], vx = bx2 - ax2, vy = by2 - ay2;
      const u = Math.max(0, Math.min(1, ((x - ax2) * vx + (y - ay2) * vy) / (vx * vx + vy * vy || 1)));
      return Math.hypot(x - (ax2 + u * vx), y - (ay2 + u * vy)) < 0.55;
    });
    const out = [];
    for (let j = MOUTH.y - 5; j < CH; j++) {
      for (let i = MOUTH.x - 1; i <= MOUTH.x + MOUTH.w + 1; i++) if (inside(i + 0.5, j + 0.5) || near(i + 0.5, j + 0.5)) out.push([i, j]);
    }
    return (mouthCache[key] = out);
  }

  function draw(t) {
    g.clearRect(0, 0, CW, CH);
    const lx = Math.round(cur.lx * 4), ly = Math.round(cur.ly * 3);
    for (const side of [-1, 1]) {
      const cx = (side < 0 ? LX : RX) + EW / 2 + lx, cy = EY + EH / 2 + ly;
      if (st.sprite === "heart") sprite(SPRITES.heart, cx, cy, 2, Math.floor(t / 350) % 2 ? "#ff6fb1" : "#ff9fcb");
      else if (st.sprite === "star") sprite(SPRITES.star, cx, cy, 2, Math.floor(t / 300) % 2 ? "#ffd84d" : "#fff2a8");
      else if (st.sprite === "spiral") drawSpiral(cx, cy, t);
      else drawEye(cx, cy, side);
    }
    if (["happy", "joy", "love"].includes(st.mood)) {  // dithered blush
      for (const x0 of [LX + 1 + lx, RX + EW - 8 + lx]) {
        for (let j = 0; j < 3; j++) for (let i = 0; i < 7; i++) if ((i + j) % 2 === 0) px(x0 + i, EY + EH - 2 + j + ly, "#ff6fb1");
      }
    }
    if (st.mood === "strain" || st.mood === "worried") {  // sweat drop sliding down
      const p = (t % 2200) / 2200;
      if (p < 0.85) sprite(SPRITES.drop, RX + EW + 1 + lx, EY + 3 + p * 7 + ly, 1, "#8fd3ff");
    }
    if (st.masked) {
      const c = "#d7eef7", d = "#a9cddc";
      line(20, 33, 11, 30, c); line(41, 33, 50, 30, c); line(20, 37, 12, 39, c); line(41, 37, 49, 39, c);
      g.fillStyle = c; g.fillRect(20, 31, 22, 9);
      g.fillStyle = d; g.fillRect(21, 34, 20, 1); g.fillRect(21, 37, 20, 1);
    } else {
      const key = st.talk ? (Math.floor(t / 220) % 2 ? "talkA" : "talkB") : MOOD_MOUTH[st.mood] || "neutral";
      g.fillStyle = css(st.color);
      for (const [i, j] of mouthPixels(key)) g.fillRect(i, j, 1, 1);
    }
    if (st.music) {  // headphones: band over the top, cups at the sides
      const pink = "#ff6fb1", dark = "#c94d8a";
      for (let a = 180; a <= 360; a += 1.5) {
        const r = (a * Math.PI) / 180;
        px(31 + 29.5 * Math.cos(r) - 0.5, 21 + 19 * Math.sin(r), pink);
        px(31 + 29.5 * Math.cos(r) - 0.5, 22 + 19 * Math.sin(r), dark);
      }
      g.fillStyle = pink; g.fillRect(0, 15, 4, 12); g.fillRect(58, 15, 4, 12);
      g.fillStyle = dark; g.fillRect(3, 16, 1, 10); g.fillRect(58, 16, 1, 10);
    }
  }

  // ---------------------------------------------------------------- loop: ~20 fps, only while something moves
  let raf = 0, last = 0;
  function kick() { if (!raf) raf = requestAnimationFrame(frame); }
  function step(dt) {
    let moving = false;
    for (const k in tgt) {
      const d = tgt[k] - cur[k];
      if (Math.abs(d) < 0.004) { cur[k] = tgt[k]; continue; }
      cur[k] += d * Math.min(1, dt / (SPEED[k] || 60));
      moving = true;
    }
    return moving;
  }
  function frame(t) {
    raf = 0;
    if (app.classList.contains("scene")) return;  // robot.js's scene instead
    if (t - last < 45) { raf = requestAnimationFrame(frame); return; }
    const dt = last ? Math.min(120, t - last) : 50;
    last = t;
    const moving = step(dt);
    draw(t);
    const animated = st.sprite || st.talk || st.mood === "strain" || st.mood === "worried";
    if (moving || animated) raf = requestAnimationFrame(frame);
  }

  new MutationObserver(readState).observe(face, { attributes: true, attributeFilter: ["class", "style"] });
  new MutationObserver(readState).observe(app, { attributes: true, attributeFilter: ["class"] });
  readState();
})();
