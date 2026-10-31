#!/usr/bin/env node
// Phase-4 budget check: steps Chip's player through every state x every clip (and every mood) in headless
// Chrome and reports the peak number of moving layers (limit 12) and rotated/scaled layers (limit 2).
// Needs the bridge running (it serves the preview). Usage: node laptop/check_budget.js
// SKIN=<id|draft> node laptop/check_budget.js measures with that skin merged over the pack (faceBase/faceTop add layers).
const { spawn } = require("child_process");
const SWEEP = `(() => {
  const pack = ChipPack.pack, p = chip, FPS = pack.fps || 12, peaks = [];
  const clips = Object.keys(pack.clips), loopsOf = (st) => (st.loop || []).map((l) => l.clip || l);
  const run = (label, setup, secs) => {
    p.resetMotion(); p.freeze(0);
    setup();
    let pm = 0, pt = 0;
    for (let k = 0; k <= secs * FPS; k++) {
      p.renderAt(k / FPS);
      pm = Math.max(pm, p.stats.moving); pt = Math.max(pt, p.stats.tilted);
    }
    peaks.push({ label, moving: pm, tilted: pt });
  };
  const sig = { music: true, badAir: false, night: false };
  for (const [name, st] of Object.entries(pack.states)) {
    const scene = () => { p.setMood(name === "face" || name === "wake" ? "neutral" : "neutral"); p.setSignals(sig); p.setScene({ show: st.show || [], pose: st.pose || {}, camera: st.camera, loops: loopsOf(st) }); };
    const extras = [[], ...clips.map((c) => [c]), ["blink", "notice", "hop"], ["blink", "notifyA", "shake"]];
    for (const ex of extras) run(name + " + " + (ex.join("+") || "-"), () => { scene(); if (st.enter) p.play(st.enter); ex.forEach((c) => p.play(c)); }, 5);
  }
  for (const m of Object.keys(pack.moods)) for (const sg of [{ music: false }, { music: true, badAir: true }])
    run("mood " + m + (sg.music ? " +music+mask" : ""), () => { p.setSignals(sg); p.setMood(m); p.setScene({ camera: "face" }); if (sg.music) p.setLoops(["bob", "notes"]); p.play("blink"); }, 5);
  peaks.sort((a, b) => b.moving - a.moving || b.tilted - a.tilted);
  const tilt = [...peaks].sort((a, b) => b.tilted - a.tilted);
  return JSON.stringify({ n: peaks.length, maxMoving: peaks[0].moving, maxTilted: tilt[0].tilted, topMoving: peaks.slice(0, 4), topTilted: tilt.slice(0, 4) });
})()`;

(async () => {
  const port = 9300 + Math.floor(Math.random() * 500);
  const ch = spawn("google-chrome", ["--headless=new", "--no-sandbox", "--disable-gpu", "--window-size=1480,720", `--remote-debugging-port=${port}`, "about:blank"], { stdio: "ignore" });
  let list;
  for (let i = 0; i < 50 && !(list && list[0]); i++) { try { list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch (e) { await new Promise((r) => setTimeout(r, 200)); } }
  const ws = new WebSocket(list.find((p) => p.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const pend = {};
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) pend[d.id](d.result || d.error); };
  const send = (method, params = {}) => new Promise((r) => { pend[++id] = r; ws.send(JSON.stringify({ id, method, params })); });
  await send("Runtime.enable"); await send("Page.enable");
  await send("Page.navigate", { url: "http://127.0.0.1:8765/preview/pack-test.html?budget" + (process.env.SKIN ? "&skin=" + encodeURIComponent(process.env.SKIN) : "") });
  for (let i = 0; i < 50; i++) { const r = await send("Runtime.evaluate", { expression: "!!window.chip", returnByValue: true }); if (r.result && r.result.value) break; await new Promise((r) => setTimeout(r, 200)); }
  const r = await send("Runtime.evaluate", { expression: SWEEP, returnByValue: true, timeout: 300000 });
  ch.kill();
  if (!r.result || r.result.type !== "string") { console.error("sweep failed:", JSON.stringify(r).slice(0, 400)); process.exit(2); }
  const o = JSON.parse(r.result.value);
  const show = (a) => a.map((x) => `  ${x.moving} moving, ${x.tilted} rotated: ${x.label}`).join("\n");
  console.log(`${o.n} scenarios\npeak moving layers ${o.maxMoving}/12, rotated or scaled ${o.maxTilted}/2\ntop moving:\n${show(o.topMoving)}\ntop rotated:\n${show(o.topTilted)}`);
  process.exit(o.maxMoving > 12 || o.maxTilted > 2 ? 1 : 0);
})();
