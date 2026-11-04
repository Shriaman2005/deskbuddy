// Chip pack player: rig tree + camera + moods + blink, drawn from the baked sprites of pack.js.
// Time is stepped at pack.fps; each frame only translates, rotates and fades baked bitmaps.
// Track values are offsets from a layer's `at` (x, y, rot) or absolute (opacity, frame); the last clip to touch
// a property wins, over the scene's pose, over the mood.
// Eyes (chip-pack/2): setEyes picks a style, which swaps the sprites of eyeL/eyeR/pupilL/pupilR/frontL/frontR. Each eye
// frame resolves through the style (and pack.fallbacks) to a back frame, a front frame and a pupil; the pupil and the
// front follow their eye's frame. setGaze moves the eyes by the style's shift and each pupil across its frame's box,
// in at most two steps per jump (pack.saccade).
(function (root) {
  "use strict";

  const [GW, GH] = [320, 180];

  function ChipPlayer(pack, canvas) {
    const FPS = pack.fps || 12, STEP = 1 / FPS;
    const ctx = canvas.getContext("2d");
    canvas.width = GW; canvas.height = GH;
    ctx.imageSmoothingEnabled = false;

    // ---------------------------------------------------------------- rig
    const layers = pack.rig.map((r) => Object.assign({ children: [] }, r));
    const byId = {};
    layers.forEach((l) => { byId[l.id] = l; });
    const roots = [];
    layers.forEach((l) => (l.parent ? byId[l.parent].children : roots).push(l));
    // a layer's first frame, of the sprite it shows now (a skin may fill faceBase and faceTop, which the rig leaves empty)
    const frameOf = (l) => {
      const n = S.spr[l.id] !== undefined ? S.spr[l.id] : l.sprite;
      return n ? Object.keys(ChipPack.source(n).frames)[0] : null;
    };
    const EYE_OF = { pupilL: "eyeL", frontL: "eyeL", pupilR: "eyeR", frontR: "eyeR" };
    const SAC = Object.assign({ frames: 2, oneFrameUpTo: 8, secondFrameAt: 0.67, hold: 4, deadband: 3, idleToCentre: 2.5 }, pack.saccade);

    // ---------------------------------------------------------------- state
    const S = {
      mood: null, moodDef: null, camera: "face", signals: {},
      oneShots: [], moodLoop: null, loops: [], loopT0: 0, scene: { show: {}, pose: {} },
      shown: {}, moodFrame: {}, text: {}, textStr: {},
      nextBlink: 0, doubleAt: 0, t0: 0, step: -1, dirty: true, raf: 0, frozen: null,
      onStep: null, onEvent: null, shouldDraw: null,
      stats: { moving: 0, tilted: 0, peakMoving: 0, peakTilted: 0 }, pos: {}, camPos: "",
      // eyes: style, pupil size, sprite per layer id, resolved frames; gaze target, gaze shown, the saccade's landing
      style: null, pupil: "M", noPupil: false, skinRev: -1, phonesRev: -1, skinPhones: true, spr: {}, env: null, looks: {}, eyeNow: {},
      gap: 0, gapWant: 0, gapFloor: -Infinity, hpGap: 0, gazeT: [0, 0, false], gazeAt: 0, gz: [0, 0], conv: false, land: null, hold: 0,
    };

    // ---------------------------------------------------------------- eyes
    // until setEyes: the rig's own eye sprites, no pupils
    S.env = { style: null, names: { eyeL: byId.eyeL.sprite, eyeR: byId.eyeR.sprite }, fb: pack.fallbacks && pack.fallbacks.eye, spr: ChipPack.source };
    // skinPhones: false = Chip's own headphones even when the skin has a pair; a borrowed pair (ChipPack.setPhones) wins over both
    function setEyes(styleId, pupilSize, showPupils = true, skinPhones = true) {
      const eyes = ChipPack.pack.eyes;   // the base pack's, or the base pack's with a skin's style added
      if (!eyes) return;
      const id = typeof styleId === "string" && Object.prototype.hasOwnProperty.call(eyes.styles, styleId) ? styleId : eyes.default, st = eyes.styles[id];
      const size = st.pupils.includes(pupilSize) ? pupilSize : st.pupilDefault, noPupil = !showPupils;
      skinPhones = !!skinPhones;
      if (S.style === st && S.pupil === size && S.noPupil === noPupil && S.skinRev === ChipPack.skinRev &&
        S.phonesRev === ChipPack.phonesRev && S.skinPhones === skinPhones) return;
      S.skinRev = ChipPack.skinRev; S.phonesRev = ChipPack.phonesRev; S.skinPhones = skinPhones;
      ChipPack.setStyle(id);
      // a layer the style leaves out is null (drawn as nothing), not the rig's default sprite
      S.style = st; S.pupil = size; S.noPupil = noPupil; S.looks = {};
      S.gapFloor = touchFloor(st); applyGap();   // a new style may have wider eyes: the gap stops where they touch
      S.spr = Object.fromEntries(["eyeL", "eyeR", "pupilL", "pupilR", "frontL", "frontR"].map((l) => [l, st.sprites[l] || null]));
      const skinLayers = ChipPack.skinLayers;   // the skin's own mouth, faceBase, faceTop, headphones
      for (const l of ["mouth", "faceBase", "faceTop"]) if (skinLayers[l]) S.spr[l] = skinLayers[l];
      // headphones: the borrowed pair, else the skin's own (unless Chip's own are asked for), else the rig's
      const hp = ChipPack.phonesLayer || (skinPhones && skinLayers.headphones);
      if (hp) S.spr.headphones = hp;
      S.env = { style: st, names: S.spr, fb: pack.fallbacks && pack.fallbacks.eye, spr: ChipPack.source };
      S.dirty = true;
    }

    // eye gap: px each eye sits further from (or, negative, closer to) the centre; its pupil and front follow
    // the gap can close until the eyes touch: the closest ink of the two eyes at gap 0 (over every row and frame)
    // is the room they have; each px of gap moves each eye 1 px, so the floor is -floor(room / 2)
    function touchFloor(st) {
      const L = ChipPack.source(st.sprites.eyeL), R = ChipPack.source(st.sprites.eyeR);
      const rows = (sp) => {
        const m = {};
        for (const rs of Object.values(sp.frames)) rs.forEach((r, y) => {
          for (let x = 0; x < r.length; x++) if (r[x] !== "." && r[x] !== " ") {
            const k = y - sp.anchor[1], dx = x - sp.anchor[0], v = m[k] || (m[k] = [Infinity, -Infinity]);
            v[0] = Math.min(v[0], dx); v[1] = Math.max(v[1], dx);
          }
        });
        return m;
      };
      const lr = rows(L), rr = rows(R);
      let room = Infinity;
      for (const k in lr) if (rr[k]) room = Math.min(room, (byId.eyeR.at[0] + rr[k][0]) - (byId.eyeL.at[0] + lr[k][1]));
      return Number.isFinite(room) ? -Math.floor(room / 2) : -Infinity;
    }
    function applyGap() {
      const v = Math.min(24, Math.max(S.gapWant, S.gapFloor));
      if (v !== S.gap) { S.gap = v; S.dirty = true; }
    }
    function setEyeGap(px) {
      S.gapWant = Math.round(+px || 0);
      applyGap();
    }

    // ear-cup gap: px each headphone cup sits further from (or, negative, closer to) the centre. The sprite is split
    // at its anchor column, which must hold only the headband: that column is repeated (wider) or the columns next
    // to it are cut (narrower), so any skin's headphones follow without a re-bake.
    function setPhonesGap(px) {
      px = Math.max(-16, Math.min(24, Math.round(+px || 0)));
      if (px !== S.hpGap) { S.hpGap = px; S.dirty = true; }
    }
    function drawSplit(cv, b, g) {
      const ax = b.ax, w = cv.width, h = cv.height, y = -b.ay;
      if (g > 0) {
        ctx.drawImage(cv, 0, 0, ax, h, -ax - g, y, ax, h);
        ctx.drawImage(cv, ax, 0, 1, h, -g, y, 2 * g + 1, h);
        ctx.drawImage(cv, ax + 1, 0, w - ax - 1, h, 1 + g, y, w - ax - 1, h);
      } else {
        const k = Math.min(-g, ax - 1, w - ax - 2);
        ctx.drawImage(cv, 0, 0, ax - k, h, k - ax, y, ax - k, h);
        ctx.drawImage(cv, ax, 0, 1, h, 0, y, 1, h);
        ctx.drawImage(cv, ax + 1 + k, 0, w - ax - 1 - k, h, 1, y, w - ax - 1 - k, h);
      }
    }

    // what eye frame f of eyeL/eyeR draws (ChipPack.eyeLook, cached): {back, front, pupil (frame or null), box, shift, anchor}
    function eyeLook(id, f) {
      const k = id + ":" + f;
      // showPupils off: the look has no pupil (as a shut eye has none), so the eye is drawn plain
      return S.looks[k] || (S.looks[k] = S.noPupil ? { ...ChipPack.eyeLook(S.env, id, f, S.pupil), pupil: null } : ChipPack.eyeLook(S.env, id, f, S.pupil));
    }
    // the pupil layer's offset from its eye: the box point for the gaze shown, minus the eye's anchor, converged inward
    function pupilAt(look, side) {
      const [x, y] = ChipPack.pupilPoint(look.box, side, S.gz[0], S.gz[1], S.conv ? S.style.converge || 0 : 0);
      return [x - look.anchor[0], y - look.anchor[1]];
    }
    // the whole-eye shift: a blink keeps the shift of the mood it interrupts
    function eyeShift(ov) {
      const o = ov.eyeL || {}, f = S.oneShots.some((c) => c.name === "blink") ? o.base : o.frame;
      const sh = eyeLook("eyeL", f !== undefined && f !== null ? f : S.moodFrame.eyeL || frameOf(byId.eyeL)).shift;
      return [Math.round(sh[0] * S.gz[0]), Math.round(sh[1] * S.gz[1])];
    }

    // gaze: x, y in -1..1, near = the target is close (the pupils converge, as they do when the gaze rests)
    function setGaze(x, y, near) {
      const t = [Math.max(-1, Math.min(1, +x || 0)), Math.max(-1, Math.min(1, +y || 0)), !!near];
      if (t.join() === S.gazeT.join()) return;
      S.gazeT = t; S.gazeAt = S.step * STEP;
      if (S.frozen !== null) { S.gz = t.slice(0, 2); S.conv = t[2]; S.land = null; S.dirty = true; }   // previews: no saccade
    }
    // one step of the saccade: a jump up to oneFrameUpTo px lands at once, a longer one goes secondFrameAt of the
    // way and lands on the next step; then the gaze holds for `hold` steps. Moves under `deadband` px are skipped.
    function tickGaze(T) {
      if (S.land) { S.gz = S.land; S.land = null; S.hold = SAC.hold; S.dirty = true; return; }
      if (S.hold > 0) { S.hold--; return; }
      const [tx, ty, near] = S.gazeT, conv = near || T - S.gazeAt >= SAC.idleToCentre;
      const dx = tx - S.gz[0], dy = ty - S.gz[1];
      if (!dx && !dy && conv === S.conv) return;
      const look = S.eyeNow.eyeL ? eyeLook("eyeL", S.eyeNow.eyeL.f) : null, sh = look ? look.shift : [0, 0];
      const half = look && look.box ? [(look.box[2] - look.box[0]) / 2, (look.box[3] - look.box[1]) / 2] : [0, 0];
      const px = Math.max(Math.abs(dx) * (sh[0] + half[0]), Math.abs(dy) * (sh[1] + half[1]));
      if (px < SAC.deadband && conv === S.conv) return;
      S.conv = conv;
      if (px <= SAC.oneFrameUpTo || SAC.frames < 2) { S.gz = [tx, ty]; S.hold = SAC.hold; }
      else { S.gz = [S.gz[0] + dx * SAC.secondFrameAt, S.gz[1] + dy * SAC.secondFrameAt]; S.land = [tx, ty]; }
      S.dirty = true;
    }

    function setMood(name) {
      const m = pack.moods[name] || pack.moods.neutral;
      if (S.mood === name) return;
      S.mood = name; S.moodDef = m; S.shown = {}; S.moodFrame = {};
      for (const [k, v] of Object.entries(m)) {
        if (k === "show") v.forEach((id) => { S.shown[id] = true; });
        else if (k !== "loop" && byId[k]) S.moodFrame[k] = v;
      }
      S.moodLoop = m.loop ? { name: m.loop, clip: pack.clips[m.loop], t0: S.step * STEP } : null;
      S.dirty = true;
    }

    // a scene: the layers to unhide, a rest pose per layer, a camera, and clips that loop while it lasts
    function setScene({ show = [], pose = {}, camera = "face", loops = [] }) {
      S.scene = { show: Object.fromEntries(show.map((id) => [id, true])), pose };
      S.camera = pack.cameras[camera] ? camera : "face";
      S.loops = loops.filter((n) => pack.clips[n]);
      S.loopT0 = S.step * STEP;
      S.dirty = true;
    }

    function play(name, opts) {
      const clip = pack.clips[name];
      if (!clip) return;
      S.oneShots = S.oneShots.filter((c) => c.name !== name);
      S.oneShots.push({ name, clip, t0: S.step * STEP, silent: !!(opts && opts.silent), fired: 0 });
      S.dirty = true;
    }
    const playing = (name) => S.oneShots.some((c) => c.name === name);
    const busy = () => S.oneShots.some((c) => c.name !== "blink");

    // the keyframe in force at local time t: stepped, so the last key at or before t holds
    function sample(keys, t) {
      let v;
      for (let i = 0; i < keys.length && keys[i][0] <= t + 1e-6; i++) v = keys[i][1];
      return v;
    }

    // overrides per layer id at time T: {x, y, rot, opacity, frame, rev (a clip touched frame/opacity)}
    function evalClips(T) {
      const out = {};
      const ensure = (id) => out[id] || (out[id] = {});
      for (const [id, p] of Object.entries(S.scene.pose)) {
        const o = ensure(id);
        Object.assign(o, p);
        o.base = p.frame;
      }
      const apply = (clip, t) => {
        for (const [id, tracks] of Object.entries(clip.tracks)) {
          const o = ensure(id);
          for (const [prop, keys] of Object.entries(tracks)) {
            const v = sample(keys, t);
            if (v === undefined) continue;
            if (prop === "frame") { o.frame = v === null ? o.base : v; o.rev = true; }
            else { o[prop] = v; if (prop === "opacity") o.rev = true; }
          }
        }
      };
      if (S.moodLoop) apply(S.moodLoop.clip, (T - S.moodLoop.t0) % S.moodLoop.clip.dur);
      for (const n of S.loops) apply(pack.clips[n], (T - S.loopT0) % pack.clips[n].dur);
      for (const c of S.oneShots) {
        const t = T - c.t0;
        apply(c.clip, t);
        const ev = c.clip.events || [];
        while (c.fired < ev.length && ev[c.fired][0] <= t + 1e-6) {
          if (!c.silent && S.onEvent) S.onEvent(ev[c.fired][1], c.name);
          c.fired++;
        }
      }
      S.oneShots = S.oneShots.filter((c) => T - c.t0 < c.clip.dur - 1e-6);
      return out;
    }

    const when = (expr) => !expr || (expr[0] === "!" ? !S.signals[expr.slice(1)] : !!S.signals[expr]);

    // ---------------------------------------------------------------- text (the notify bubble): a 3x5 pixel font,
    // baked once; the bubble leaves 7 rows and about 7 characters, too small for any outline font
    const FONT = {
      A: "010101111101101", B: "110101110101110", C: "011100100100011", D: "110101101101110", E: "111100110100111",
      F: "111100110100100", G: "011100101101011", H: "101101111101101", I: "111010010010111", J: "001001001101010",
      K: "101101110101101", L: "100100100100111", M: "101111111101101", N: "111101101101101", O: "010101101101010",
      P: "110101110100100", Q: "010101101111011", R: "110101110101101", S: "011100010001110", T: "111010010010010",
      U: "101101101101111", V: "101101101101010", W: "101101111111101", X: "101101010101101", Y: "101101010010010",
      Z: "111001010100111", 0: "111101101101111", 1: "010110010010111", 2: "110001010100111", 3: "110001010001110",
      4: "101101111001001", 5: "111100110001110", 6: "011100111101111", 7: "111001010010010", 8: "111101111101111",
      9: "111101111001110", ".": "000000000000010", "-": "000000111000000", " ": "000000000000000", "?": "110001010000010",
    };
    function setText(id, str) {
      const l = byId[id];
      if (!l || S.textStr[id] === str) return;
      S.textStr[id] = str;
      const s = String(str || "").toUpperCase().slice(0, l.maxChars || 8);
      const cv = document.createElement("canvas"), g = cv.getContext("2d");
      cv.width = Math.max(1, s.length * 4 - 1); cv.height = 5;
      g.fillStyle = ChipPack.palette[l.color || "light"];
      [...s].forEach((ch, n) => {
        const bits = FONT[ch] || FONT["?"];
        for (let i = 0; i < 15; i++) if (bits[i] === "1") g.fillRect(n * 4 + (i % 3), Math.floor(i / 3), 1, 1);
      });
      S.text[id] = cv;
      S.dirty = true;
    }

    // ---------------------------------------------------------------- draw
    // budget: a drawn layer counts as moving when its place on screen changed since it was last drawn (own
    // offset or an ancestor's), as rotated when it or an ancestor has a rotation. The camera counts once.
    function drawLayer(l, ov, parentAlpha, moved, tilted) {
      if (!when(l.when)) return;
      const o = ov[l.id];
      const spr = S.spr[l.id] !== undefined ? S.spr[l.id] : l.sprite;
      // a sprite-less slot (faceBase, faceTop) shows once it is given a sprite
      if (l.hidden && !S.shown[l.id] && !S.scene.show[l.id] && !(o && o.rev) && !(l.sprite === null && spr)) return;
      const alpha = parentAlpha * (o && o.opacity !== undefined ? o.opacity : 1);
      if (alpha <= 0.001) return;
      const eye = EYE_OF[l.id] && S.eyeNow[EYE_OF[l.id]];
      let frame = null;
      if (eye) {   // a pupil or front layer: follows its eye's frame
        frame = l.id[0] === "p" ? eye.look.pupil : eye.look.front;
        if (!frame) return;
      }
      const gz = l.id === "gaze" ? eyeShift(ov) : eye && l.id[0] === "p" ? pupilAt(eye.look, l.id.slice(-1)) : null;
      const x = l.at[0] + (l.id === "eyeL" ? -S.gap : l.id === "eyeR" ? S.gap : 0) + (o && o.x || 0) + (gz ? gz[0] : 0), y = l.at[1] + (o && o.y || 0) + (gz ? gz[1] : 0);
      ctx.save();
      ctx.translate(x, y);
      if (o && o.rot) { ctx.rotate(o.rot * Math.PI / 180); tilted = true; }
      const key = x + "," + y;
      if (S.pos[l.id] !== undefined && S.pos[l.id] !== key) moved = true;
      S.pos[l.id] = key;
      if (spr && (!S.only || l.id === S.only)) {   // only: the dashboard's headphones card draws just that layer
        const b = ChipPack.sprite(spr);
        let f = frame || (o && o.frame !== undefined && o.frame !== null ? o.frame : (S.moodFrame[l.id] || frameOf(l)));
        if (l.id === "eyeL" || l.id === "eyeR") {
          const look = eyeLook(l.id, f);
          S.eyeNow[l.id] = { f, look };
          f = look.back;
        } else if (l.id === "mouth" && b && !b.frames[f]) f = ChipPack.chain(pack.fallbacks && pack.fallbacks.mouth, f).find((n) => b.frames[n]);
        const cv = b && (b.frames[f] || b.frames[frameOf(l)]);
        if (cv) {
          ctx.globalAlpha = alpha;
          if (l.id === "headphones" && S.hpGap) drawSplit(cv, b, S.hpGap); else ctx.drawImage(cv, -b.ax, -b.ay);
          ctx.globalAlpha = 1; if (moved) S.stats.moving++; if (tilted) S.stats.tilted++; }
      } else if (l.text && S.text[l.id] && !S.only) {
        ctx.globalAlpha = alpha; ctx.drawImage(S.text[l.id], 0, 0); ctx.globalAlpha = 1;
        if (moved) S.stats.moving++; if (tilted) S.stats.tilted++;
      }
      for (const c of l.children) drawLayer(c, ov, alpha, moved, tilted);
      ctx.restore();
    }

    function cameraNow(ov) {
      const o = ov.camera;
      const cam = pack.cameras[o && o.frame ? o.frame : S.camera] || pack.cameras.face;
      return { x: cam.x + (o && o.x || 0), y: cam.y + (o && o.y || 0), scale: cam.scale };
    }

    function render(T) {
      const ov = evalClips(T), cam = cameraNow(ov);
      const st = S.stats, camKey = cam.x + "," + cam.y + "," + cam.scale;
      st.moving = S.camPos && S.camPos.slice(0, S.camPos.lastIndexOf(",")) !== camKey.slice(0, camKey.lastIndexOf(",")) ? 1 : 0;
      st.tilted = S.camPos && S.camPos.split(",")[2] !== String(cam.scale) ? 1 : 0;   // a camera cut to another zoom
      S.camPos = camKey;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      if (!S.only) { ctx.fillStyle = ChipPack.palette.bg; ctx.fillRect(0, 0, GW, GH); }   // only: transparent, the headphones alone
      // whole-number scale at rest; the offset is rounded so sprite pixels stay on the grid
      ctx.setTransform(cam.scale, 0, 0, cam.scale, Math.round(GW / 2 - cam.x * cam.scale), Math.round(GH / 2 - cam.y * cam.scale));
      roots.forEach((l) => drawLayer(l, ov, 1, false, false));
      if (st.moving > st.peakMoving || st.tilted > st.peakTilted) {
        st.peakMoving = Math.max(st.peakMoving, st.moving); st.peakTilted = Math.max(st.peakTilted, st.tilted);
        console.info(`[chip] peak moving layers ${st.peakMoving}/12, rotated or scaled ${st.peakTilted}/2`);
      }
    }

    // ---------------------------------------------------------------- idle blink (every mood, personality timing)
    const rand = (a, b) => a + Math.random() * (b - a);
    function tickBlink(T) {
      const eyes = S.moodDef && S.moodDef.eyeL;
      if (T >= S.nextBlink) {
        if (eyes !== "shut") play("blink", { silent: true });   // shut eyes have nothing to blink
        const p = pack.personality;
        S.nextBlink = T + rand(p.blinkEvery[0], p.blinkEvery[1]);
        S.doubleAt = Math.random() < p.doubleBlink ? T + 0.35 : 0;
      } else if (S.doubleAt && T >= S.doubleAt) {
        if (eyes !== "shut") play("blink", { silent: true });
        S.doubleAt = 0;
      }
    }

    // ---------------------------------------------------------------- loop (stepped; draws only when the step changes)
    function frame(now) {
      S.raf = requestAnimationFrame(frame);
      const T = S.frozen !== null ? S.frozen : (now - S.t0) / 1000;
      const step = Math.floor(T * FPS + 1e-6);
      const fresh = step !== S.step;
      if (!fresh && !S.dirty) return;
      if (fresh) {
        S.step = step;
        if (S.frozen === null) { tickBlink(step * STEP); if (S.onStep) S.onStep(step * STEP); tickGaze(step * STEP); }
      }
      if (S.shouldDraw && !S.shouldDraw()) return;   // time and state keep running; drawing waits (dirty stays set)
      S.dirty = false;
      render(step * STEP);
    }

    // ---------------------------------------------------------------- integer fit: each grid pixel is k screen pixels
    let nudge = [0, 0];   // burn-in guard offset in CSS px, applied in whole device pixels
    function fit() {
      const d = devicePixelRatio || 1;   // k counts device pixels, so every grid pixel is a whole number of them
      // faceSize (% , the dashboard's "Face size"): 100 = the biggest whole k that fits; more zooms in past the screen's
      // edges (centred, the edges cut), less shrinks. k stays whole so pixels stay square: it moves in steps.
      const base = Math.min(innerWidth * d / GW, innerHeight * d / GH);
      const pct = Math.max(50, Math.min(250, +(canvas.closest("#app") || document.body).dataset.faceSize || 100));
      const k = Math.max(1, pct === 100 ? Math.floor(base) : Math.round(base * pct / 100));
      const w = GW * k, h = GH * k;
      canvas.style.cssText += `;position:absolute;inset:auto;width:${w / d}px;height:${h / d}px;` +
        `left:${(Math.round((innerWidth * d - w) / 2) + Math.round(nudge[0] * d)) / d}px;top:${(Math.round((innerHeight * d - h) / 2) + Math.round(nudge[1] * d)) / d}px;image-rendering:pixelated`;
    }

    const onNudge = (e) => { nudge = [e.detail.x, e.detail.y]; fit(); };
    return {
      start() { S.t0 = performance.now(); fit(); addEventListener("resize", fit); addEventListener("chip:nudge", onNudge); S.raf = requestAnimationFrame(frame); },
      stop() { cancelAnimationFrame(S.raf); removeEventListener("resize", fit); removeEventListener("chip:nudge", onNudge); },
      setMood, setScene, setLoops(names) {
        const l = names.filter((n) => pack.clips[n]);
        if (l.join() !== S.loops.join()) { S.loops = l; S.loopT0 = S.step * STEP; S.dirty = true; }
      },
      play, playing, busy, setText,
      setSignals(s) { Object.assign(S.signals, s); S.dirty = true; },
      setGaze, setEyes, setEyeGap, setPhonesGap,
      set onStep(fn) { S.onStep = fn; },
      set onEvent(fn) { S.onEvent = fn; },
      set shouldDraw(fn) { S.shouldDraw = fn; },
      freeze(T) { S.frozen = T; S.dirty = true; },   // for previews: render this time only, no random blinks
      setOnly(id) { S.only = id || null; S.dirty = true; },   // draw just this sprite layer (the dashboard's headphones card)
      refresh() { S.textStr = {}; S.text = {}; S.dirty = true; },   // after an accent change
      get mood() { return S.mood; },
      get stats() { return S.stats; },
      renderAt(T) { S.step = Math.floor(T * FPS + 1e-6); render(S.step * STEP); },   // synchronous, for the budget check
      resetMotion() { S.pos = {}; S.camPos = ""; },   // forget last positions (a new scenario in the budget check)
    };
  }

  root.ChipPlayer = ChipPlayer;
})(typeof window !== "undefined" ? window : globalThis);
