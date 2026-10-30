// Chip: the state machine that drives the pack player from the page's signals (#app data-* and classes, #face
// mood classes, chip:react / chip:notify events). All art and motion come from pack.json.
(() => {
  "use strict";
  const app = document.getElementById("app"), faceScreen = document.getElementById("s-face");
  const face = document.getElementById("face"), canvas = document.querySelector("#scene canvas");
  // buddy.js tints its own UI (eyes, glow) from main/dark per accent and passes main on as data-accent-hex (the pack
  // derives every other colour from it); it loads after this file
  window.CHIP_PALETTES = {
    cyan: { main: "#2ee6f2", dark: "#17a3ba" }, terracotta: { main: "#ee9358", dark: "#b8622f" }, sage: { main: "#b4d38c", dark: "#7a9a5c" },
    violet: { main: "#a78bfa", dark: "#6d54c4" }, rose: { main: "#f472b6", dark: "#b8407f" },
    amber: { main: "#f5c04a", dark: "#b88a1c" }, sky: { main: "#6cb8ff", dark: "#3a7fc4" },
  };
  window.chipCustomPalette = (hex) => {  // a colour from the dashboard's picker: the night tint is the same hue, 35% darker
    const c = [1, 3, 5].map((i) => Math.round(parseInt(hex.slice(i, i + 2), 16) * 0.65));
    return { main: hex, dark: "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("") };
  };
  const hooks = () => window.ChipHooks || {};

  ChipPack.load("pack.json").then(async (pack) => {
    const player = ChipPlayer(pack, canvas), P = pack.personality;
    const rand = (a, b) => a + Math.random() * (b - a);
    const SCENES = new Set(["boot", "type", "stuck", "idea", "done", "switch", "deep", "flow", "release"]);

    // ---------------------------------------------------------------- accent
    let accent = "";
    function applyAccent() {
      const hex = app.dataset.accentHex || window.CHIP_PALETTES.cyan.main;
      if (hex === accent) return;
      accent = hex;
      ChipPack.setAccent(hex);
      player.refresh();
    }
    applyAccent();
    new MutationObserver(applyAccent).observe(app, { attributes: true, attributeFilter: ["data-accent-hex"] });

    // ---------------------------------------------------------------- signals
    const sig = () => ({
      focus: app.dataset.focus === "1", typing: app.dataset.typing === "1", pause: Number(app.dataset.idle) >= 2,
      music: app.classList.contains("music"), badAir: app.classList.contains("masked"),
      night: app.classList.contains("night"), away: !!(hooks().away && hooks().away()),
    });
    const moodNow = () => (face.className.match(/\bm-(\w+)/) || [])[1] || "neutral";

    // ---------------------------------------------------------------- states
    // the dashboard's idle settings: on/off, how often (a multiplier on the pack's timing) and the clips switched off
    const idlePrefs = () => (hooks().idle && hooks().idle()) || { on: true, rate: 1, off: [] };
    let name = pack.start, st = pack.states[name], enteredAt = 0, enter = null, nextIdle = 0, nextFlourish = 0, notifyAt = 0, q = 0;
    const val = (k, s) => (k === "stateFor" ? q - enteredAt : k === "end" ? !enter || !player.playing(enter) : s[k]);
    function test(expr, s) {
      return expr.split("&").every((t) => {
        t = t.trim();
        const m = t.match(/^(\w+)\s*>=\s*([\d.]+)$/);
        if (m) return val(m[1], s) >= Number(m[2]);
        return t[0] === "!" ? !val(t.slice(1), s) : !!val(t, s);
      });
    }
    function go(to) {
      name = to; st = pack.states[to]; enteredAt = q; enter = st.enter || null;
      player.setScene({ show: st.show || [], pose: st.pose || {}, camera: st.camera });
      if (enter) player.play(enter);
      nextFlourish = st.flourish ? q + rand(...st.flourish[0].every) : 0;
      nextIdle = q + rand(...P.idleEvery) * idlePrefs().rate;
      app.classList.toggle("scene", SCENES.has(to));
    }
    const pickWeighted = (list) => {
      let r = Math.random() * list.reduce((a, i) => a + i.weight, 0);
      return (list.find((i) => (r -= i.weight) < 0) || list[0]).clip;
    };

    player.onStep = (t) => {
      q = t;
      const s = sig();
      player.setSignals(s);
      for (const n of st.next || []) if (test(n.when, s)) { go(n.to); st = pack.states[name]; break; }
      // loops that depend on a signal (the music bob)
      player.setLoops((st.loop || []).filter((l) => typeof l === "string" || !l.when || test(l.when, s)).map((l) => l.clip || l));
      const inFace = name === "face";
      player.setMood(inFace ? moodNow() : "neutral");
      if (inFace) {
        const x = parseFloat(face.style.getPropertyValue("--lx")) / 7 || 0, y = parseFloat(face.style.getPropertyValue("--ly")) / 5 || 0;
        player.setGaze(x * 4, y * 3);
        if (!s.night && q >= nextIdle) {
          const ip = idlePrefs(), list = (s.away ? P.idleAway : P.idle).filter((i) => !ip.off.includes(i.clip));
          if (ip.on && list.length && player.mood === "neutral" && !player.busy()) player.play(pickWeighted(list));
          nextIdle = q + rand(...P.idleEvery) * ip.rate;
        }
      } else player.setGaze(0, 0);
      if (st.flourish && q >= nextFlourish) {
        player.play(st.flourish[0].clip);
        nextFlourish = q + rand(...st.flourish[0].every);
      }
    };

    // clip events: sounds and the torch go through buddy.js
    player.onEvent = (ev) => {
      const [kind, what] = ev.split(":");
      if (kind === "sfx" && hooks().sfx) hooks().sfx(what);
      else if (kind === "torch" && hooks().torch) hooks().torch();
    };
    player.shouldDraw = () => !document.hidden && faceScreen.classList.contains("active");

    // ---------------------------------------------------------------- reactions and notifications
    // (buddy.js already plays the sound and sets the mood for these, so the clip runs silent)
    document.addEventListener("chip:react", (e) => {
      const clip = pack.reactions[e.detail];
      if (name === "face" && clip && !sig().night) player.play(clip, { silent: true });
    });
    document.addEventListener("chip:notify", (e) => {
      let on = st.on && st.on.notify;
      if (!on) return;
      if (Array.isArray(on)) on = on[notifyAt++ % on.length];
      player.setText("notifyText", (e.detail && e.detail.app) || "");
      player.play(on, { silent: true });
    });

    app.classList.add("chip");
    go(pack.start);
    player.start();
    window.Chip = { player, pack };   // for the preview and the budget check
  });
})();
