// Desk buddy: an animated face plus clock, laptop and focus screens.
// Runs full screen in kiFOSSk on the phone and is served by ~/deskbuddy/server.py (Termux).
(() => {
  "use strict";

  const C = Object.assign({
    name: "Chip",
    location: { name: "New Delhi", lat: 28.6, lon: 77.2 },
    night: { start: "23:00", end: "06:30" },
    brightness: { day: 90, night: 3 },
    sounds: true,
    talk: true,
    stretchEveryMin: 50,
    laptop: "http://127.0.0.1:8765",
  }, window.BUDDY_CONFIG || {});

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const app = $("#app"), head = $("#head"), face = $("#face");
  const rand = (a, b) => a + Math.random() * (b - a);
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const now = () => Date.now();
  const pad = (n) => String(n).padStart(2, "0");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const bootAt = now();

  // localStorage can be unavailable in some WebViews; everything still works without it.
  const store = {
    get(k, d) { try { const v = localStorage.getItem("buddy." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("buddy." + k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
  };
  // What to show and how to behave. Set from the dashboard on the laptop (http://127.0.0.1:8765, see "preferences"
  // below) or the drawer toggles, and kept here so the buddy stays the same while the laptop is away.
  const DEFAULT_PREFS = {
    tabClock: true, tabLaptop: true, tabTimer: true, tabViz: true,
    dock: true, dockTime: true, dockWeather: true, dockAqi: true, dockCpu: true, dockLaptopTemp: true, dockLaptopBattery: true,
    dockPhoneBattery: true, dockPhoneTemp: true, timerPill: true, focusBar: true, dots: true, musicMode: true, mask: true,
    clockNow: true, clockHours: true, clockAir: true, ringCpu: true, ringRam: true, ringGpu: true, ringBattery: true, mediaCard: true,
    sounds: C.sounds, talk: C.talk, idle: true, greetings: true, updateBubble: true, hourly: true, trackToasts: true, laptopAlerts: true, phoneAlerts: true,
    shake: true, stretch: true, stretchMin: C.stretchEveryMin, dictation: true, fastDictation: C.fastDictation ?? false,
    dictEngine: "phone", dictLang: "hinglish", burnGuard: false, gazeFollow: false,
    torch: true, torchAsk: true, torchDone: true, torchApps: true, notifyAllApps: false, alertTorch: true, alertSound: true,
    torchAway: false, torchRepeat: true, torchNight: false, behaviourTorch: true, torchSeconds: 3, soundSeconds: 2,
    soundVolume: 80, soundStyle: "chime", remindEvery: 20, remindMinutes: 3,
    pomoFocus: 25, pomoShort: 5, pomoLong: 15, pomoLongEvery: 4, pomoAutoBreak: true, pomoAutoFocus: false, pomoGoal: 8,
    workScene: true, typingScene: true, typingAfter: 10, accent: "cyan", accentColor: "#2ee6f2", chipGlow: 100, eyeGap: 0, phonesGap: 0, faceSize: 100, idleRate: "normal", idleOff: [],
    phonesFollowSkin: true, phonesDefault: "",  // a skin's own headphones when it has a pair; else "" = Chip's own, or an installed skin id to borrow from
    eyeStyle: "", pupilSize: "M", showPupils: false, skin: "", locName: "", locLat: 0, locLon: 0,  // weather place from the dashboard ("" = config.js); eye style (a pack style id, "" = the pack's default), pupil size S/M/L, pupils on/off, installed skin id ("" = none)
    brightnessDay: C.brightness.day,
    personalPhone: false,  // the phone is also in use (Chrome web app): never touch its screen brightness
    sleep: true, sleepAt: C.night.start, wakeAt: C.night.end, brightnessNight: C.brightness.night, drowsy: true, drowsyMin: 45,
  };
  const prefs = Object.assign({}, DEFAULT_PREFS,
    { sounds: store.get("sounds", C.sounds), talk: store.get("talk", C.talk),
      fastDictation: store.get("fastDictation", C.fastDictation ?? false) },  // drawer toggles from before the dashboard
    store.get("prefs", {}));
  { const old = store.get("prefs", {}).dictateOnLaptop;  // before dictEngine: a yes/no for "dictate on the laptop"
    if (typeof old === "boolean" && !("dictEngine" in store.get("prefs", {}))) prefs.dictEngine = old ? "laptop" : "phone"; }

  const state = {
    night: false, wakeUntil: 0, lastTouch: now(), lastHour: -1,
    laptop: null, laptopOnline: false, laptopFails: 0,
    busySince: 0, lowBatWarned: false, activeSince: 0, lastIdleMs: 0,
    music: false, lastTrack: "",
    weather: store.get("weather", null), aqi: store.get("aqi", null),
    phone: null, phoneLowWarned: false,
  };

  // ---------------------------------------------------------------- network
  function getJSON(url, ms = 2500) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), ms);
    return fetch(url, { signal: ctl.signal, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null).finally(() => clearTimeout(t));
  }
  const post = (url) => fetch(url, { method: "POST" }).then((r) => r.ok).catch(() => false);
  const phone = {
    brightness: (level) => (prefs.personalPhone ? Promise.resolve(false) : post(`/api/brightness?level=${level}`)),
    say: (text) => { if (prefs.talk && !state.night) post(`/api/say?text=${encodeURIComponent(text)}`); },
    launch: (id) => post(`/api/launch?app=${id}`),
    // Android blocks `am start` from Termux unless Termux is in front, which it isn't in Chrome (the installed web app too):
    // apps are only offered in kiFOSSk, a WebView ("; wv)"), and never on a personal phone
    get canLaunch() { return !prefs.personalPhone && !(/Chrome\//.test(navigator.userAgent) && !/; wv\)/.test(navigator.userAgent)); },
  };
  const laptop = (path) => post(C.laptop + path);

  // ---------------------------------------------------------------- time
  function fmt12(d) { return { h: d.getHours() % 12 || 12, m: pad(d.getMinutes()), ap: d.getHours() < 12 ? "AM" : "PM" }; }
  const mins = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
  function isNight(d) {
    if (!prefs.sleep) return false;
    const t = d.getHours() * 60 + d.getMinutes(), s = mins(prefs.sleepAt), e = mins(prefs.wakeAt);
    return s > e ? t >= s || t < e : t >= s && t < e;
  }
  const hourLabel = (h) => `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`;

  // ---------------------------------------------------------------- sound
  let actx = null;
  function audio() {
    if (!actx) { try { actx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return null; } }
    if (actx.state === "suspended") actx.resume();
    return actx;
  }
  function chirp(f1, f2, dur = 0.12, type = "sine", vol = 0.12, delay = 0) {
    if (!prefs.sounds || state.night || !actx) return;
    const t = actx.currentTime + delay, o = actx.createOscillator(), g = actx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f1, t);
    o.frequency.exponentialRampToValueAtTime(f2, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(actx.destination);
    o.start(t); o.stop(t + dur + 0.03);
  }
  const sfx = {
    boop: () => chirp(520, 880, 0.1),
    giggle: () => { chirp(700, 1100, 0.07); chirp(820, 1300, 0.07, "sine", 0.1, 0.09); chirp(940, 1500, 0.08, "sine", 0.1, 0.18); },
    purr: () => { for (let i = 0; i < 4; i++) chirp(190, 140, 0.12, "triangle", 0.09, i * 0.13); },
    alert: () => { chirp(660, 660, 0.12, "square", 0.04); chirp(880, 880, 0.14, "square", 0.04, 0.16); },
    done: () => [523, 659, 784, 1046].forEach((f, i) => chirp(f, f * 1.01, 0.16, "triangle", 0.12, i * 0.13)),
    dizzy: () => chirp(900, 200, 0.6, "sawtooth", 0.04),
    yawn: () => chirp(420, 180, 0.7, "sine", 0.06),
    listen: () => { chirp(500, 900, 0.09, "sine", 0.1); chirp(900, 1200, 0.07, "sine", 0.08, 0.1); },
    heard: () => chirp(1000, 600, 0.12, "sine", 0.1),
    sneeze: () => chirp(900, 300, 0.25, "sawtooth", 0.04),
    whistle: () => chirp(880, 1175, 0.3, "sine", 0.05),
  };
  const react = (n) => document.dispatchEvent(new CustomEvent("chip:react", { detail: n }));  // chip.js plays the pack's clip

  // ---------------------------------------------------------------- face
  const MOODS = ["happy", "joy", "drowsy", "sleepy", "asleep", "angry", "focus", "strain", "sad", "worried",
    "surprised", "suspicious", "curious", "wink", "love", "dizzy", "yawn", "whistle", "bored", "smirk", "star", "listen", "think"];
  // background glow: by mood first, otherwise by time of day
  const MOOD_SKY = { love: "rgba(255,111,177,.55)", angry: "rgba(255,140,60,.5)", star: "rgba(255,216,77,.45)",
    sad: "rgba(90,120,255,.45)", dizzy: "rgba(160,90,255,.45)", joy: "rgba(255,111,177,.4)" };
  function timeSky(h) {
    if (h < 5 || h >= 21) return "rgba(20,50,110,.55)";   // night
    if (h < 8) return "rgba(255,140,80,.45)";             // sunrise
    if (h < 17) return "rgba(27,106,138,.5)";             // day
    return "rgba(130,70,220,.45)";                        // evening
  }
  let tempMood = null, tempUntil = 0, tempTimer = 0, mood = "neutral";

  // What the laptop can do (bridge /stats caps, laptop/platforms): a feature whose cap is missing stays hidden, whatever
  // the pref says. No caps yet (laptop away, an older bridge) = everything as before.
  const NEEDS = { ringGpu: "gpu", mediaCard: "media", tabViz: "visualizer", typingScene: "typingRate", gazeFollow: "gaze" };
  const capOk = (k) => !NEEDS[k] || !state.laptop || !state.laptop.caps || state.laptop.caps[NEEDS[k]] !== false;
  const want = (k) => !!prefs[k] && capOk(k);
  // You've been typing on the laptop for a while (bridge.py counts key presses, not which keys): Chip types along.
  const typingNow = () => want("typingScene") && state.laptopOnline && !!state.laptop && state.laptop.typing_for >= prefs.typingAfter;
  function baseMood() {
    if (dict.phase === "listening") return "listen";
    if (dict.phase === "thinking") return "think";
    if (state.night) return now() < state.wakeUntil ? "sleepy" : "asleep";
    if (focus.running && focus.mode === "focus") return "focus";
    if (typingNow()) return "focus";
    if (state.laptopOnline && state.busySince && now() - state.busySince > 9000) return "strain";
    if (laptopBatteryLow()) return "worried";
    if (drowsy()) return "drowsy";
    return "neutral";
  }
  // Preview without waiting: ?mood=love&music=1&aqi=250&timer=10&screen=3
  const preview = new URLSearchParams(location.search);
  if (preview.has("eyes")) app.dataset.eyes = preview.get("eyes");  // ?eyes=toon&pupil=L: chip.js's eye style and pupil size
  if (preview.has("pupil")) app.dataset.pupil = preview.get("pupil").toUpperCase();
  if (preview.has("only")) app.dataset.only = preview.get("only");  // ?only=phones: the dashboard's headphones card (chip.js)
  // ?skin=<id> shows an installed skin, ?skin=draft the last skin that passed the check (before it is installed)
  // busy at its computer (a scene is playing or a focus session runs): no tricks, no bobbing to the music
  const isWorking = () => app.classList.contains("scene") || (focus.running && focus.mode === "focus");
  function refreshMood() {
    if (tempMood && now() >= tempUntil) tempMood = null;
    mood = preview.get("mood") || tempMood || baseMood();
    // chip.js plays Chip's scenes: focus mode during a focus session (or ?mood=focus), typing along while you
    // type (or ?typing)
    app.dataset.focus = (prefs.workScene && focus.running && focus.mode === "focus" && !state.night) || preview.get("mood") === "focus" ? "1" : "0";
    app.dataset.typing = (typingNow() && !state.night) || preview.has("typing") ? "1" : "0";
    if (preview.has("music")) state.music = true;
    if (preview.has("aqi")) state.aqi = { v: Number(preview.get("aqi")) };
    for (const m of MOODS) face.classList.toggle("m-" + m, m === mood);
    head.classList.toggle("bob", state.music && prefs.musicMode && !state.night && !tempMood && !isWorking());
    app.classList.toggle("music", state.music && prefs.musicMode && !state.night);
    app.classList.toggle("masked", prefs.mask && !!(state.aqi && state.aqi.v >= (C.maskAqi || 200)) && !state.night && !maskOffUntil());
    app.style.setProperty("--sky", MOOD_SKY[mood] || timeSky(new Date().getHours()));
  }
  let maskOff = 0;
  const maskOffUntil = () => now() < maskOff;
  function express(m, ms = 2500) {
    tempMood = m; tempUntil = now() + ms; refreshMood();
    clearTimeout(tempTimer); tempTimer = setTimeout(refreshMood, ms + 20);
  }
  function anim(cls, ms) {
    head.classList.remove(cls); void head.offsetWidth; head.classList.add(cls);
    setTimeout(() => head.classList.remove(cls), ms);
  }
  function look(x, y, near = false) {  // x, y in -1..1; near: the target is close to the phone (Chip's pupils converge)
    face.style.setProperty("--lx", (x * 7).toFixed(2) + "vmin");
    face.style.setProperty("--near", near ? "1" : "0");
    face.style.setProperty("--ly", (y * 5).toFixed(2) + "vmin");
    face.style.setProperty("--sl", (1 - x * 0.06).toFixed(3));
    face.style.setProperty("--sr", (1 + x * 0.06).toFixed(3));
    face.style.setProperty("--gx", (x * 1.6).toFixed(2) + "vmin");  // highlights drift with the gaze
    face.style.setProperty("--gy", (y * 1.2).toFixed(2) + "vmin");
  }
  function tilt(deg, ms = 1800) {
    face.style.setProperty("--tilt", deg + "deg");
    setTimeout(() => face.style.setProperty("--tilt", "0deg"), ms);
  }
  function blink(twice) {
    if (["asleep", "love", "dizzy", "wink"].includes(mood)) return;
    face.classList.add("blink");
    setTimeout(() => face.classList.remove("blink"), 110);
    if (twice) setTimeout(() => blink(false), 260);
  }
  function lookAround() {
    look(-1, 0); setTimeout(() => look(1, 0), 450); setTimeout(() => look(0, 0), 900);
  }
  function yawn() { express("yawn", 2200); anim("stretch", 1400); sfx.yawn(); }
  function sneeze() {
    express("surprised", 700);
    setTimeout(() => { express("sleepy", 600); anim("sneeze", 900); particles(["💨"], 2); say("Achoo! 🤧", 1500); chirp(900, 300, 0.25, "sawtooth", 0.04); }, 700);
  }
  function whistle() { express("whistle", 2600); look(0.5, -0.6); particles(["♪", "♫"], 3, "", 500); [880, 990, 1175].forEach((f, i) => chirp(f, f, 0.18, "sine", 0.05, i * 0.25)); }
  function peek() { anim("peek", 2400); setTimeout(() => express("smirk", 900), 1700); }
  function spin() { express("dizzy", 1400); anim("spin", 900); }
  function bored() { express("bored", 3000); look(-0.8, 0.4); setTimeout(() => say("…", 1200), 600); }
  const IDLE = [
    [3, () => { express("curious", 1800); tilt(rand(-9, 9)); }],
    [3, () => express("happy", 1500)],
    [2, () => express("suspicious", 1600)],
    [3, lookAround],
    [2, () => express("wink", 420)],
    [2, whistle],
    [1, sneeze],
    [1, peek],
    [1, spin],
    [1, () => { anim("wiggle", 900); express("joy", 900); }],
    [1, () => { express("smirk", 1500); look(0.7, 0); }],
  ];
  function idleAction() {
    if (drowsy()) return pick([yawn, bored, () => anim("nod", 1600)])();
    let r = Math.random() * IDLE.reduce((s, [w]) => s + w, 0);
    for (const [w, fn] of IDLE) { if ((r -= w) < 0) return fn(); }
  }

  function blinkLoop() {
    blink(Math.random() < 0.15);
    setTimeout(blinkLoop, rand(2200, mood === "drowsy" || mood === "sleepy" ? 9000 : 6000));
  }
  function lookLoop() {
    if (gesture) { /* eyes are following a finger */ }
    else if (mood === "asleep") look(0, 0);
    else if (following) { /* eyes are following the mouse */ }
    else if (Math.random() < 0.4) look(0, 0);
    else look(rand(-1, 1), rand(-0.6, 0.6));
    setTimeout(lookLoop, rand(1800, 6000));
  }
  function idleLoop() {
    if (prefs.idle && !isWorking() && !state.night && !tempMood && screenIdx === 0 && !gesture && now() - bootAt > 20000) idleAction();
    setTimeout(idleLoop, rand(15000, 45000));
  }

  // ---------------------------------------------------------------- bubble + particles
  let bubbleTimer = 0, typeTimer = 0;
  function say(text, ms = 4000, speak = false) {
    const b = $("#bubble");
    clearTimeout(bubbleTimer); clearInterval(typeTimer); face.classList.remove("talk");
    b.textContent = ""; b.classList.add("show"); b.classList.remove("long");
    let i = 0;
    const chars = Array.from(text);
    face.classList.add("talk");
    typeTimer = setInterval(() => {
      b.textContent = chars.slice(0, ++i).join("");
      if (i >= chars.length) { clearInterval(typeTimer); setTimeout(() => face.classList.remove("talk"), 250); }
    }, 28);
    bubbleTimer = setTimeout(() => b.classList.remove("show"), ms + chars.length * 28);
    if (speak) phone.say(text.replace(/[^\p{L}\p{N}\s.,!?'%:-]/gu, "").trim());
  }
  function bubbleNow(text, ms = 0, wrap = false) {
    const b = $("#bubble");
    clearTimeout(bubbleTimer); clearInterval(typeTimer); face.classList.remove("talk");
    b.textContent = text; b.classList.add("show"); b.classList.toggle("long", wrap);
    if (ms) bubbleTimer = setTimeout(() => b.classList.remove("show", "long"), ms);
  }
  function particles(chars, n = 5, color = "", gap = 160) {
    const r = face.getBoundingClientRect(), fx = $("#fx");
    for (let i = 0; i < n; i++) {
      setTimeout(() => {
        const p = document.createElement("span");
        p.className = "p"; p.textContent = pick(chars);
        p.style.left = r.left + rand(0, r.width) + "px";
        p.style.top = r.top + rand(r.height * 0.05, r.height * 0.6) + "px";
        p.style.setProperty("--dx", rand(-8, 8).toFixed(1) + "vmin");
        p.style.setProperty("--rz", rand(-30, 30).toFixed(0) + "deg");
        if (color) p.style.color = color;
        fx.appendChild(p);
        setTimeout(() => p.remove(), 2700);
      }, i * gap);
    }
  }

  // ---------------------------------------------------------------- reactions
  let taps = [];
  function onFaceTap() {
    audio();
    if (alarmUntil) return stopAlarm();
    const t = now();
    if (state.night && t > state.wakeUntil) return wakeAtNight();
    taps = taps.filter((x) => t - x < 2500); taps.push(t);
    if (taps.length >= 6) {
      taps = []; express("angry", 2200); anim("shake", 450); sfx.alert(); react("poke");
      return say(pick(["Hey! That tickles 😤", "Okay okay, I'm awake!", "Poke me one more time…"]), 3000);
    }
    if (app.classList.contains("masked")) {
      maskOff = t + 15000; refreshMood(); express("joy", 1500); anim("hop", 550);
      setTimeout(() => refreshMood(), 15100);
      return say(`Quick breath! AQI is ${state.aqi.v} out there 😷`, 3500);
    }
    if (taps.length >= 2 && t - taps[taps.length - 2] < 320) {
      express("love", 2600); particles(["❤", "💖", "💕"], 6, "var(--pink)"); react("doubleTap"); return sfx.giggle();
    }
    express("happy", 1400); anim("hop", 500); sfx.boop(); react("tap");
    if (prefs.greetings && store.get("greeted", "") !== new Date().toDateString()) {
      store.set("greeted", new Date().toDateString());
      setTimeout(() => say(greeting(), 6000, true), 600);
    }
  }
  function onPet() {
    audio(); react("pet"); express("joy", 2600); anim("wiggle", 900); particles(["❤", "✨"], 4, "var(--pink)"); sfx.purr();
    if (Math.random() < 0.35) say(pick(["Hehe, that's nice 😊", "Purrrr…", "More pets please!"]), 2500);
  }
  function wakeAtNight() {
    state.wakeUntil = now() + 20000; phone.brightness(30);
    express("surprised", 900);
    const t = fmt12(new Date());
    say(`${t.h}:${t.m} ${t.ap}… it's late. Go to sleep! 😴`, 5000);
    setTimeout(() => { if (state.night) phone.brightness(prefs.brightnessNight); refreshMood(); }, 20500);
  }
  let shakes = [];
  let lastMotion = 0;
  window.addEventListener("devicemotion", (e) => {
    if (!prefs.shake || e.timeStamp - lastMotion < 100) return;
    lastMotion = e.timeStamp;
    const a = e.accelerationIncludingGravity;
    if (!a || a.x == null) return;
    if (Math.abs(Math.hypot(a.x, a.y, a.z) - 9.81) < 9) return;
    const t = now();
    shakes = shakes.filter((x) => t - x < 700); shakes.push(t);
    if (shakes.length >= 3 && mood !== "dizzy") {
      shakes = []; express("dizzy", 3200); sfx.dizzy(); react("shake");
      say(pick(["Whoa, earthquake?! 😵", "Stop shaking me! 🌀", "Wheee— I'm dizzy"]), 3000);
    }
  });

  function greeting() {
    const h = new Date().getHours();
    const hi = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
    const w = weatherNow();
    let s = w ? `${hi}! ${w.icon} ${w.temp}°, high ${w.max}°` : `${hi}!`;
    const rain = rainSoon();
    if (rain) s += ` · rain around ${rain} ☔`;
    if (state.aqi && state.aqi.v > 200) s += ` · AQI ${state.aqi.v} 😷`;
    return s;
  }
  function summary() {
    const t = fmt12(new Date()), w = weatherNow(), L = state.laptop;
    const parts = [`${t.h}:${t.m} ${t.ap}`];
    if (w) parts.push(`${w.icon} ${w.temp}°`);
    if (state.laptopOnline && L) parts.push(`💻 ${L.cpu}% CPU${L.battery != null ? ` · 🔋${L.battery}%` : ""}`);
    say(parts.join("  ·  "), 5000);
  }

  // ---------------------------------------------------------------- gestures
  // One finger: tap, swipe, pet. Two fingers held on the face: dictation. kiFOSSk opens its settings on a
  // one-finger long-press (~0.4 s), but Android cancels the long-press as soon as a second finger lands.
  let gesture = null;
  const fingers = new Map();  // pointerId -> where it went down and where it is now
  app.addEventListener("pointerdown", (e) => {
    fingers.set(e.pointerId, { x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY });
    state.lastTouch = now();
    if (fingers.size === 1) {
      gesture = { x: e.clientX, y: e.clientY, t: now(), lastX: e.clientX, dir: 0, rev: 0, onButton: !!e.target.closest("button") };
      return;
    }
    if (!gesture) return;
    gesture.multi = true;
    if (fingers.size === 2 && prefs.dictation && screenIdx === 0 && !gesture.onButton && !$("#drawer").classList.contains("open") && dict.phase === "idle") {
      gesture.dictating = true;
      dictateStart();
    }
  });
  app.addEventListener("pointermove", (e) => {
    const f = fingers.get(e.pointerId);
    if (!gesture || !f) return;
    f.x = e.clientX; f.y = e.clientY;
    if (gesture.dictating) {  // slide away to cancel
      const armed = [...fingers.values()].some((p) => Math.hypot(p.x - p.x0, p.y - p.y0) > 90);
      if (armed !== dict.cancelArmed) { dict.cancelArmed = armed; dictateBubble(); }
      return;
    }
    if (gesture.multi) return;
    if (screenIdx === 0 && mood !== "asleep") {  // eyes follow your finger
      look(Math.max(-1, Math.min(1, (e.clientX / innerWidth - 0.5) * 2.4)),
        Math.max(-1, Math.min(1, (e.clientY / innerHeight - 0.45) * 2.4)), true);
    }
    const dx = e.clientX - gesture.lastX;
    if (Math.abs(dx) > 14) {
      const d = Math.sign(dx);
      if (gesture.dir && d !== gesture.dir) gesture.rev++;
      gesture.dir = d; gesture.lastX = e.clientX;
    }
  });
  app.addEventListener("pointercancel", (e) => {
    fingers.delete(e.pointerId);
    if (fingers.size) return;
    if (gesture && gesture.dictating) dictateEnd(true);
    gesture = null;
  });
  app.addEventListener("pointerup", (e) => {
    const f = fingers.get(e.pointerId);
    fingers.delete(e.pointerId);
    if (!gesture || !f) return;
    const g = gesture;
    if (g.multi) {  // dictation ends when the last finger lifts; other multi-finger touches do nothing
      if (fingers.size) return;
      gesture = null;
      return g.dictating ? dictateEnd(dict.cancelArmed) : undefined;
    }
    const dx = e.clientX - g.x, dy = e.clientY - g.y, dt = now() - g.t;
    gesture = null; state.lastTouch = now();
    setTimeout(() => { if (!gesture) { if (following) gazeLook(...cursorGaze); else look(0, 0); } }, 700);
    const horiz = Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.3;
    const vert = Math.abs(dy) > 70 && Math.abs(dy) > Math.abs(dx);
    if (g.onButton && !horiz && !vert) return; // a plain tap on a button: its click handler runs
    if ($("#drawer").classList.contains("open")) { if (vert && dy > 0) $("#drawer").classList.remove("open"); return; }
    if (screenIdx === 0 && g.rev >= 2) return onPet();
    if (screenIdx === VIZ && (horiz || vert)) return go(2);  // any swipe leaves the visualizer
    if (horiz) return go(nextTab(dx < 0 ? 1 : -1));
    if (vert && dy < 0) return openDrawer();
    if (vert && dy > 0) return screenIdx === 0 ? summary() : go(0);
    if (Math.abs(dx) < 16 && Math.abs(dy) < 16 && dt < 600) {
      if (screenIdx === 0) onFaceTap();
      else if (screenIdx === VIZ) cycleViz();
    }
  });

  // ---------------------------------------------------------------- dictation: hold the face with two fingers, speak, let go
  // The phone records (dictation.py in Termux) and transcribes with the engine from the dashboard: whisper on the phone,
  // whisper on the laptop or a cloud API (both through the bridge). The laptop types the text. No fallback between engines.
  const ENGINES = ["phone", "laptop", "cloud"];
  const ENGINE_ICON = { phone: "📱", laptop: "💻", cloud: "☁️" };
  const ENGINE_NAME = { phone: "Phone", laptop: "Laptop", cloud: "Cloud" };
  // error code (laptop/stt.py ERRORS) -> [mood, what Chip says]; the codes are the same on the phone and the bridge
  const DICT_ERRORS = {
    silence: ["sad", "🤔 Didn't hear anything. Hold me with two fingers, speak, then let go"],
    too_short: ["sad", "🤔 That was too short. Hold a little longer"],
    no_words: ["sad", "🤔 Couldn't make out any words"],
    key_missing: ["worried", "☁️ No cloud key yet — add it on the dashboard"],
    key_rejected: ["worried", "☁️ Cloud key was rejected — check the dashboard"],
    quota: ["worried", "☁️ Cloud limit reached — try again later"],
    offline: ["worried", "📡 Can't reach the speech engine — is the laptop connected?"],
    timeout: ["worried", "⏳ The speech engine took too long"],
    lang_unsupported: ["worried", "🌐 This engine doesn't do that language — change it on the dashboard"],
    provider_error: ["worried", "😵 The speech engine failed"],
    locked: ["worried", "🔒 Unlock the laptop first"],
  };
  const dict = { phase: "idle", cancelArmed: false, level: 0, elapsed: 0, poll: 0, dots: 0 };
  const BARS = "▁▂▃▄▅▆▇█";
  function dictateBubble() {
    if (dict.phase !== "listening") return;
    if (dict.cancelArmed) return bubbleNow("↩ let go to cancel");
    const n = Math.round(dict.level * 7), bars = Array.from({ length: 6 }, (_, i) => BARS[Math.max(0, Math.min(7, n - Math.abs(i - 2.5) * 1.2 | 0))]).join("");
    bubbleNow(`🎙 Listening ${bars} ${dict.elapsed.toFixed(0)}s`);
  }
  async function dictateStart() {
    if (dict.phase !== "idle") return;
    dict.phase = "starting"; dict.cancelArmed = false; dict.level = 0; dict.elapsed = 0;
    audio(); look(0, -0.7); bubbleNow("🎙 …");
    const r = await fetch("/api/dictate/start", { method: "POST" }).then((x) => x.json()).catch(() => null);
    if (!r || !r.ok) { dict.phase = "idle"; refreshMood(); return bubbleNow("🎙 Mic isn't available right now", 3000); }
    if (dict.phase !== "starting") return fetch("/api/dictate/cancel", { method: "POST" });  // let go while the mic was opening
    dict.phase = "listening"; sfx.listen(); refreshMood(); dictateBubble();
    dict.poll = setInterval(async () => {
      const st = await getJSON("/api/dictate/status", 1000);
      if (!st || dict.phase !== "listening") return;
      dict.level = st.level; dict.elapsed = st.elapsed;
      face.style.setProperty("--sl", (1 + st.level * 0.12).toFixed(3)); face.style.setProperty("--sr", (1 + st.level * 0.12).toFixed(3));
      dictateBubble();
      if (st.elapsed >= 60) dictateEnd(false);  // the phone stops recording at 60 s anyway
    }, 160);
  }
  async function dictateEnd(cancel) {
    clearInterval(dict.poll);
    if (dict.phase === "starting") { dict.phase = "idle"; refreshMood(); return bubbleNow("Cancelled", 1500); }
    if (dict.phase !== "listening") return;
    look(0, 0);
    if (cancel) {
      dict.phase = "idle"; refreshMood();
      fetch("/api/dictate/cancel", { method: "POST" });
      return bubbleNow("Cancelled", 1500);
    }
    dict.phase = "thinking"; sfx.heard(); refreshMood(); look(-0.6, -0.8);
    const where = ENGINES.includes(prefs.dictEngine) ? prefs.dictEngine : "phone";
    const think = setInterval(() => bubbleNow(`💭 ${".".repeat(1 + (dict.dots++ % 3))} ${where === "phone" ? "" : ENGINE_ICON[where]}`), 400);
    const r = await fetch(`/api/dictate/stop?on=${where}&lang=${encodeURIComponent(prefs.dictLang)}${prefs.fastDictation ? "&fast=1" : ""}`, { method: "POST" }).then((x) => x.json()).catch(() => null);
    clearInterval(think); dict.phase = "idle"; look(0, 0); refreshMood();
    if (!r) { express("worried", 2500); return bubbleNow(DICT_ERRORS.provider_error[1], 4000); }  // the phone server itself didn't answer
    if (r.error) {
      const [mood, line] = DICT_ERRORS[r.error] || ["worried", "😵 Something went wrong: " + r.error];
      express(mood, 2500); return bubbleNow(line, 4500);
    }
    const text = r.text;
    if (!state.laptopOnline) { express("worried", 2500); return bubbleNow(`💻 Laptop not connected. Heard: “${text}”`, 9000, true); }
    // any language: the bridge types or pastes non-ASCII text. A 409 says why it couldn't (macOS: allow Python in Accessibility)
    const res = await fetch(C.laptop + "/type", { method: "POST", body: text })
      .then(async (x) => ({ status: x.status, message: x.status === 409 ? ((await x.json().catch(() => ({}))).message || "") : "" }))
      .catch(() => ({ status: 0, message: "" }));
    if (res.status === 200) { express("happy", 1800); anim("hop", 550); bubbleNow(`✓ Typed: “${text}”`, 6000, true); }
    else if (res.status === 423) { express("worried", 2500); bubbleNow(`🔒 Unlock the laptop first. Heard: “${text}”`, 9000, true); }
    else { express("worried", 2500); bubbleNow(`💻 ${res.message || "Couldn't type it"}. Heard: “${text}”`, 12000, true); }
  }

  // ---------------------------------------------------------------- screens
  const screens = $$(".screen");
  const TABS = 4, VIZ = 4;  // face, clock, laptop, timer; the visualizer opens from the laptop page
  const TAB_PREFS = [null, "tabClock", "tabLaptop", "tabTimer", "tabViz"];  // the face can't be hidden
  const tabOn = (i) => !TAB_PREFS[i] || want(TAB_PREFS[i]);
  let screenIdx = 0;
  function nextTab(dir) {
    let i = screenIdx;
    do i = (i + dir + TABS) % TABS; while (!tabOn(i));
    return i;
  }
  function go(i) {
    i = (i + screens.length) % screens.length;
    if (!tabOn(i)) i = i === VIZ && tabOn(2) ? 2 : 0;
    if (i === screenIdx) return;
    screenIdx = i;
    store.set("screen", i === VIZ ? 2 : i);  // stay on this tab, even after a reload
    screens.forEach((s, k) => { s.classList.toggle("active", k === i); s.classList.toggle("left", k < i); });
    $$("#dots i").forEach((d, k) => d.classList.toggle("on", k === (i === VIZ ? 2 : i)));
    if (i === VIZ) vizStart(); else vizStop();
    if (window.parent !== window) window.parent.postMessage({ screen: i }, location.origin);  // the dashboard's preview
    render();
  }

  // ---------------------------------------------------------------- weather (Open-Meteo, no key needed)
  const WMO = {
    0: ["☀️", "Clear"], 1: ["🌤️", "Mostly clear"], 2: ["⛅", "Partly cloudy"], 3: ["☁️", "Cloudy"],
    45: ["🌫️", "Fog"], 48: ["🌫️", "Fog"], 51: ["🌦️", "Drizzle"], 53: ["🌦️", "Drizzle"], 55: ["🌦️", "Drizzle"],
    56: ["🌧️", "Freezing drizzle"], 57: ["🌧️", "Freezing drizzle"], 61: ["🌧️", "Light rain"], 63: ["🌧️", "Rain"],
    65: ["🌧️", "Heavy rain"], 66: ["🌧️", "Freezing rain"], 67: ["🌧️", "Freezing rain"], 71: ["🌨️", "Light snow"],
    73: ["🌨️", "Snow"], 75: ["❄️", "Heavy snow"], 77: ["🌨️", "Snow"], 80: ["🌦️", "Showers"], 81: ["🌧️", "Showers"],
    82: ["⛈️", "Heavy showers"], 85: ["🌨️", "Snow showers"], 86: ["🌨️", "Snow showers"], 95: ["⛈️", "Thunderstorm"],
    96: ["⛈️", "Thunderstorm"], 99: ["⛈️", "Thunderstorm"],
  };
  function wx(code, isDay) {
    const w = WMO[code] || ["🌡️", ""];
    return !isDay && code <= 1 ? ["🌙", w[1]] : w;
  }
  function hourIndex(hourly) {
    const d = new Date();
    const key = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
    return hourly.time.indexOf(key);
  }
  function weatherNow() {
    const W = state.weather && state.weather.d;
    if (!W || !W.current) return null;
    const c = W.current, [icon, text] = wx(c.weather_code, c.is_day);
    return {
      icon, text, temp: Math.round(c.temperature_2m), feels: Math.round(c.apparent_temperature),
      max: Math.round(W.daily.temperature_2m_max[0]), min: Math.round(W.daily.temperature_2m_min[0]),
      sunrise: W.daily.sunrise[0].slice(11), sunset: W.daily.sunset[0].slice(11),
    };
  }
  function rainSoon() {
    const W = state.weather && state.weather.d;
    if (!W) return null;
    const i = hourIndex(W.hourly);
    if (i < 0) return null;
    for (let k = i; k < i + 6 && k < W.hourly.time.length; k++) {
      if (W.hourly.precipitation_probability[k] >= 60) return hourLabel(Number(W.hourly.time[k].slice(11, 13)));
    }
    return null;
  }
  const placeNow = () => (prefs.locName ? { name: prefs.locName, lat: prefs.locLat, lon: prefs.locLon } : C.location);
  const placeKey = () => { const L = placeNow(); return L.lat + "," + L.lon; };
  async function fetchWeather() {
    const L = placeNow(), key = placeKey();
    const d = await getJSON(`https://api.open-meteo.com/v1/forecast?latitude=${L.lat}&longitude=${L.lon}` +
      "&current=temperature_2m,apparent_temperature,weather_code,is_day" +
      "&hourly=temperature_2m,weather_code,precipitation_probability,is_day" +
      "&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset&timezone=auto&forecast_days=2", 15000);
    if (key !== placeKey()) return;  // the place changed while this was loading; applyPrefs fetched the new one
    if (d && d.current) { state.weather = { at: now(), d }; store.set("weather", state.weather); render(); }
    const a = await getJSON(`https://air-quality-api.open-meteo.com/v1/air-quality?latitude=${L.lat}&longitude=${L.lon}&current=us_aqi`, 15000);
    if (key !== placeKey()) return;
    if (a && a.current && a.current.us_aqi != null) { state.aqi = { at: now(), v: Math.round(a.current.us_aqi) }; store.set("aqi", state.aqi); render(); }
  }
  function aqiColor(v) { return v <= 50 ? "#5dffa8" : v <= 100 ? "#ffe066" : v <= 150 ? "#ffb347" : v <= 200 ? "#ff6b6b" : v <= 300 ? "#c77dff" : "#ff4d8d"; }

  // ---------------------------------------------------------------- laptop (via the bridge)
  const laptopBatteryLow = () => state.laptopOnline && state.laptop && state.laptop.battery != null && !state.laptop.charging && state.laptop.battery <= 20;
  function drowsy() {
    if (!prefs.drowsy || now() - state.lastTouch < prefs.drowsyMin * 60000) return false;
    const L = state.laptop;
    return !state.laptopOnline || !L || L.locked || (L.idle_ms != null && L.idle_ms > 15 * 60000);
  }
  async function pollLaptop() {
    // the phone tells the laptop how it's doing, for the dashboard's status line
    const P = state.phone || {};
    const report = onPhone ? "?" + new URLSearchParams({ who: "phone", rev: prefsRev, mood, screen: screenIdx,
      bat: P.battery ?? "", chg: P.charging ? 1 : 0, temp: P.temp ?? "", skinErr: app.dataset.skinErr || "",
      ...(P.wifi ? { ssid: P.wifi.ssid, rssi: P.wifi.rssi ?? "", speed: P.wifi.speed ?? "", freq: P.wifi.freq ?? "", pip: P.wifi.ip ?? "" } : {}) }) : "";
    const d = await getJSON(C.laptop + "/stats" + report, 2500);
    if (d) {
      const was = state.laptopOnline;
      state.laptopOnline = true; state.laptopFails = 0;
      onLaptop(d, was);
    } else if (++state.laptopFails >= 3 && state.laptopOnline) {
      state.laptopOnline = false; state.laptop = null; state.music = false;
      refreshMood(); render();
    }
    setTimeout(pollLaptop, !state.laptopOnline ? 6000 : app.dataset.typing === "1" ? 1000 : 3000);  // quicker while it types along
  }
  function onLaptop(d, wasOnline) {
    const prev = state.laptop, t = now(), alerts = prefs.laptopAlerts;
    state.laptop = d;
    if (JSON.stringify(d.caps || null) !== JSON.stringify((prev && prev.caps) || null)) applyPrefs({});  // show/hide what the laptop can do
    if (Object.keys(pendingPrefs).length) pushPrefs();
    else if (d.settingsRev != null && d.settingsRev !== prefsRev) syncPrefs();
    if (d.skinsRev != null) {   // an installed skin's file changed on the laptop (renamed, new headphones): read the one in use again
      if (skinsRev !== null && d.skinsRev !== skinsRev) skinsReload();
      skinsRev = d.skinsRev;
    }
    if (alerts && !wasOnline && t - bootAt > 8000 && !state.night) say("Laptop connected 💻", 2500);
    // a newer Chip on GitHub (laptop/updates.py): said once a day until it is installed; "Chip mentions updates" hides it
    const upd = d.update ? d.update + " " + new Date().toDateString() : "";
    if (upd && prefs.updateBubble && store.get("updateSaid", "") !== upd && t - bootAt > 15000 && !state.night && screenIdx === 0) {
      store.set("updateSaid", upd);
      setTimeout(() => { express("joy", 1500); say(`I've got an update! ${d.update} is out, see the dashboard ✨`, 5000); }, 3000);
    }

    if (d.cpu != null && d.cpu >= 85) { if (!state.busySince) state.busySince = t; } else state.busySince = 0;
    if (alerts && prev && d.temp >= 90 && prev.temp < 90) { express("worried", 3000); flash(2); say(`Laptop is ${d.temp}°C — toasty in here 🥵`, 4000); }

    if (d.battery != null) {
      if (!d.charging && d.battery <= 20 && !state.lowBatWarned) {
        state.lowBatWarned = true;
        if (alerts) { express("worried", 3500); sfx.alert(); flash(3); say(`Laptop battery ${d.battery}% — plug it in! 🔌`, 5000, true); }
      }
      if (d.charging && prev && !prev.charging) {
        state.lowBatWarned = false;
        if (alerts && t - bootAt > 8000) { express("joy", 2000); anim("hop", 500); say("Yum, power! ⚡", 2500); }
      }
    }

    if (d.idle_ms != null && !state.night) {
      if (alerts && state.lastIdleMs > 10 * 60000 && d.idle_ms < 15000 && !d.locked) {
        express("surprised", 700);
        setTimeout(() => { express("joy", 2000); anim("hop", 500); sfx.giggle(); }, 700);
        say(pick(["Welcome back! 👋", "Oh hi! Missed you", "You're back! 🎉"]), 3500);
      }
      if (d.idle_ms < 5 * 60000 && !d.locked) { if (!state.activeSince) state.activeSince = t; } else state.activeSince = 0;
      if (prefs.stretch && state.activeSince && t - state.activeSince > prefs.stretchMin * 60000) {
        state.activeSince = t; express("worried", 2500); sfx.alert(); flash(2);
        say(pick(["Time to stretch! 🧘", "Stand up and drink some water 💧", "Rest your eyes for a minute 👀"]), 6000, true);
      }
      state.lastIdleMs = d.idle_ms;
    }

    const playing = !!(d.media && d.media.status === "Playing");
    if (prefs.trackToasts && playing && d.media.title && d.media.title !== state.lastTrack && screenIdx === 0 && !state.night) {
      say(`♪ ${d.media.title}${d.media.artist ? " — " + d.media.artist : ""}`, 3500);
    }
    if (playing) state.lastTrack = d.media.title || "";
    state.music = playing;

    onAttention(d.attention);
    refreshMood(); render();
  }

  // ---------------------------------------------------------------- attention: torch and sound when something needs you
  // The laptop collects these (agent hooks and desktop notifications, see bridge.py), keeps the ones the
  // dashboard lets through, marks each torch and/or sound, and sends the last minute's with /stats. Here they
  // wait for morning (unless allowed), maybe only count when you're away, and then remind you every so often
  // until you use the laptop or tap Chip. The phone server (alert.py) blinks and plays.
  const attn = { lastId: store.get("attnId", 0), active: null, burstAt: 0, burstUntil: 0 };
  const awayFromLaptop = () => { const L = state.laptop; return !L || L.locked || (L.idle_ms ?? 0) > 60000; };
  function alertNow(torchSecs, soundSecs) {
    attn.burstAt = now(); attn.burstUntil = now() + Math.max(torchSecs, soundSecs) * 1000 + 1500;
    post(`/api/alert?torch=${torchSecs}&sound=${soundSecs}&style=${prefs.soundStyle}&volume=${prefs.soundVolume}`);
  }
  // what chip.js needs from here: the sounds and torch blink the pack's clips ask for, and whether you are away
  window.ChipHooks = { sfx: (n) => sfx[n] && sfx[n](), torch: () => prefs.behaviourTorch && alertNow(1, 0), away: () => awayFromLaptop(),
    idle: () => ({ on: prefs.idle, rate: { rare: 2, normal: 1, often: 0.5 }[prefs.idleRate] || 1, off: prefs.idleOff }) };
  const alertFor = (torch, sound) => alertNow(torch ? prefs.torchSeconds : 0, sound ? prefs.soundSeconds : 0);
  const flash = (secs) => { if (prefs.behaviourTorch && !state.night) alertNow(secs, 0); };  // Chip's own moments
  const stopAlerts = () => { attn.burstUntil = 0; post("/api/alert/stop"); };
  function onAttention(list) {
    if (!Array.isArray(list) || !list.length) return;
    const fresh = list.filter((a) => a.id > attn.lastId && a.age < 30);  // older ones are from before this page loaded
    attn.lastId = Math.max(attn.lastId, ...list.map((a) => a.id)); store.set("attnId", attn.lastId);
    if (!fresh.length) return;
    document.dispatchEvent(new CustomEvent("chip:notify", { detail: { app: fresh[0].source } }));  // chip.js: the bubble names the app
    const a = fresh[0], test = fresh.some((e) => e.kind === "test");
    const torch = fresh.some((e) => e.torch), sound = fresh.some((e) => e.sound);
    if (!test && (!prefs.torch || (state.night && !prefs.torchNight) || (prefs.torchAway && !awayFromLaptop()))) return;
    attn.active = prefs.torchRepeat && !test ?
      { at: now(), next: now() + prefs.remindEvery * 1000, until: now() + prefs.remindMinutes * 60000, torch, sound } : null;
    alertFor(torch, sound);
    express("surprised", 900); setTimeout(() => { express("curious", 2500); anim("hop", 500); }, 900);
    if (!sound) sfx.alert();
    const more = fresh.length > 1 ? ` (+${fresh.length - 1} more)` : "";
    say(`${torch ? "🔦" : "🔔"} ${a.source}${a.project ? ` (${a.project})` : ""}: ${a.text}${more}`, 7000);
  }
  function attentionCheck() {  // every second, from tick()
    if (attn.burstUntil > now() && state.lastTouch > attn.burstAt) stopAlerts();  // a tap silences it
    const A = attn.active, L = state.laptop;
    if (!A) return;
    const back = L && !L.locked && L.idle_ms != null && L.idle_ms + 4000 < now() - A.at;  // used the laptop since
    if (back || state.lastTouch > A.at || now() > A.until || !prefs.torch) {
      attn.active = null;
      if (back && attn.burstUntil > now()) stopAlerts();
      return;
    }
    if (now() >= A.next) {
      A.next = now() + prefs.remindEvery * 1000;
      if (!state.night || prefs.torchNight) alertFor(A.torch, A.sound);
    }
  }

  async function pollPhone() {
    const d = await getJSON("/api/status", 5000);
    if (d) {
      state.phone = d;
      if (typeof d.flashlight === "boolean") state.flashlight = d.flashlight;
      if (d.battery != null && d.battery <= 15 && !d.charging && !state.phoneLowWarned) {
        state.phoneLowWarned = true;
        if (prefs.phoneAlerts) { express("sad", 3000); say(`I'm hungry… ${d.battery}% battery 🔌`, 5000, true); }
      }
      if (d.charging) state.phoneLowWarned = false;
    }
    setTimeout(pollPhone, 30000);
  }

  // ---------------------------------------------------------------- timer: pomodoro (focus, short and long breaks), countdown, stopwatch
  // The pomodoro lengths, the long-break interval, auto-start and the daily goal are settings (dashboard, and the
  // chips beside the ring); the countdown length, this round of the cycle and today's count live on the phone.
  const MODES = {  // icon, name, ring colour
    focus: ["🎯", "Focus", "var(--good)"], short: ["☕", "Short break", "#7cc8ff"], long: ["🛋️", "Long break", "#b48cff"],
    countdown: ["⏳", "Countdown", "var(--warn)"], stopwatch: ["⏱️", "Stopwatch", "var(--pink)"],
  };
  const PRESETS = [1, 3, 5, 10, 15, 30, 60];  // countdown
  const POMO = { focus: "pomoFocus", short: "pomoShort", long: "pomoLong" };
  const POMO_MAX = { focus: 180, short: 60, long: 90 };
  const savedTimer = store.get("focus", {});
  const focus = Object.assign({ mode: "focus", total: 25 * 60000, left: 25 * 60000, endAt: 0, running: false,
    countdownMin: 10, cycle: 0, cycleDay: "", swStart: 0, swElapsed: 0 }, savedTimer);
  if (focus.mode === "break") focus.mode = "short";  // saved before there were long breaks
  if (focus.mins) { focus.countdownMin = focus.mins.countdown || 10; delete focus.mins; }
  const saveFocus = () => store.set("focus", focus);
  if (savedTimer.mins) saveFocus();  // stored in the new shape from now on (savedTimer keeps the old lengths for the hand-over below)
  const isPomo = (m = focus.mode) => m in POMO;
  const isSW = () => focus.mode === "stopwatch";
  const modeMins = (m) => (isPomo(m) ? prefs[POMO[m]] : focus.countdownMin);
  const swTime = () => focus.swElapsed + (focus.running ? now() - focus.swStart : 0);
  const focusLeft = () => (focus.running ? Math.max(0, focus.endAt - now()) : focus.left);
  const timerActive = () => focus.running || (isSW() ? focus.swElapsed > 0 : focus.left < focus.total);  // running, or paused part-way
  let alarmUntil = 0;
  function stats() {
    const st = store.get("focusStats", {}), today = new Date().toDateString();
    return st.day === today ? st : { day: today, sessions: 0, minutes: 0 };
  }
  function cycleNow() {  // focus sessions done in this round of the cycle; each day starts a new round
    const today = new Date().toDateString();
    if (focus.cycleDay !== today) { focus.cycle = 0; focus.cycleDay = today; }
    return focus.cycle;
  }
  function timerSet(mode = focus.mode, min) {
    if (min != null) min = Math.max(1, Math.min(600, Math.round(min)));
    const ms = (min ?? modeMins(mode)) * 60000;
    Object.assign(focus, { mode, total: ms, left: ms, running: false, swElapsed: 0, swStart: 0 });
    if (min != null && mode === "countdown") focus.countdownMin = min;
    saveFocus();
    // a length picked beside the ring for a pomodoro mode becomes the setting, so the dashboard has it too
    if (min != null && isPomo(mode) && min !== prefs[POMO[mode]]) setPrefs({ [POMO[mode]]: min });
    refreshMood(); render();
  }
  function timerToggle(quiet) {
    audio();
    if (alarmUntil) return stopAlarm();
    if (focus.running) {
      if (isSW()) focus.swElapsed = swTime(); else focus.left = focusLeft();
      focus.running = false;
    } else {
      if (isSW()) focus.swStart = now();
      else { if (focus.left <= 0) focus.left = focus.total; focus.endAt = now() + focus.left; }
      focus.running = true;
      if (quiet !== true) sfx.boop();
      if (focus.mode === "focus") express("focus", 1500);
    }
    saveFocus(); refreshMood(); render();
  }
  function timerAdjust(delta) {
    if (isSW()) return;
    const ms = delta * 60000;
    if (focus.running) {  // change the time left without stopping
      focus.endAt = Math.max(now() + 1000, focus.endAt + ms);
      focus.total = Math.max(focus.total + ms, focus.endAt - now());
      saveFocus(); return render();
    }
    timerSet(focus.mode, Math.round(focus.left / 60000) + delta);
  }
  function timerReset() { alarmUntil = 0; stopAlerts(); timerSet(focus.mode); }
  // After focus: a short break, or a long one after every pomoLongEvery sessions. After a break: focus again.
  // `done` = the phase finished (it counts); a skipped focus session doesn't.
  function nextPhase(done) {
    let next = "focus";
    if (focus.mode === "focus") {
      focus.cycle = cycleNow() + (done ? 1 : 0);
      next = done && focus.cycle % prefs.pomoLongEvery === 0 ? "long" : "short";
    } else if (focus.mode === "long") focus.cycle = 0;  // the round is complete
    timerSet(next);
    if (next === "focus" ? prefs.pomoAutoFocus : prefs.pomoAutoBreak) timerToggle(true);
    return next;
  }
  function timerSkip() {
    if (!isPomo()) return;
    alarmUntil = 0;
    const next = nextPhase(false);
    say(`⏭ ${MODES[next][0]} ${MODES[next][1]}: ${modeMins(next)} min`, 2500);
  }
  function stopAlarm() { alarmUntil = 0; focus.left = focus.total; saveFocus(); stopAlerts(); refreshMood(); render(); }
  function focusCheck() {
    if (alarmUntil) {  // ring every 1.5 s for up to 30 s, until tapped
      if (now() > alarmUntil) stopAlarm();
      else if (Math.floor(now() / 1500) % 2 === 0) sfx.alert();
      return;
    }
    if (!focus.running || isSW()) return;
    const left = focusLeft();
    if (left > 0) {
      if (screenIdx === 0 && left < 6000 && !state.night && focus.mode !== "focus") look(0.9, -0.8);  // watching the timer pill
      return;
    }
    focus.running = false; focus.left = 0;
    if (focus.mode === "focus") {
      const st = stats(); st.sessions++; st.minutes += Math.round(focus.total / 60000); store.set("focusStats", st);
      sfx.done(); flash(3); express("star", 4000); anim("hop", 550); particles(["🎉", "✨", "⭐"], 8);
      const next = nextPhase(true), brk = `${MODES[next][0]} ${MODES[next][1]}: ${modeMins(next)} min`;
      if (st.sessions === prefs.pomoGoal) {
        particles(["🏆", "🍅"], 6);
        say(`🏆 Daily goal reached: ${st.sessions} focus sessions! ${brk}`, 7000, true);
      } else say(`Focus session done (${st.sessions} today)! ${brk}`, 6000, true);
    } else if (isPomo()) {
      const wasLong = focus.mode === "long";
      sfx.alert(); flash(3); nextPhase(true);
      say(wasLong ? "Long break's over: new round! 💪" : "Break's over, back to it! 💪", 5000, true);
    } else {
      alarmUntil = now() + 30000; saveFocus(); flash(30);  // until tapped (stopAlarm)
      express("surprised", 900); setTimeout(() => { express("joy", 2500); anim("hop", 550); }, 900);
      particles(["⏰", "🔔"], 5);
      say("⏰ Time's up! (tap to stop)", 8000, true);
    }
  }

  // ---------------------------------------------------------------- rendering
  function setRing(el, frac, color) {
    const c = el.querySelector("circle.fg"), len = parseFloat(getComputedStyle(c).strokeDasharray) || 263.9;
    c.style.strokeDashoffset = (len * (1 - Math.max(0, Math.min(1, frac)))).toFixed(1);
    if (color) c.style.stroke = color;
  }
  const levelColor = (v, warn, bad) => (v >= bad ? "var(--bad)" : v >= warn ? "var(--warn)" : "var(--good)");
  function fmtRate(b) { return b > 1e6 ? (b / 1e6).toFixed(1) + " MB/s" : Math.round(b / 1e3) + " KB/s"; }
  function fmtDur(s) { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h}h ${m}m` : `${m}m`; }

  let lastStrip = "";
  function renderStrip() {
    // floating dock: [time · weather · AQI]  [laptop CPU · temp · battery]  [phone battery · temp]
    const t = fmt12(new Date()), w = weatherNow(), L = state.laptop, P = state.phone, groups = [];
    const hot = (v, warn, bad) => (v >= bad ? ' style="color:var(--bad)"' : v >= warn ? ' style="color:var(--warn)"' : "");
    const env = [];
    if (prefs.dockTime) env.push(`<b>${t.h}:${t.m}</b> ${t.ap}`);
    if (w && prefs.dockWeather) env.push(`${w.icon} <b>${w.temp}°</b>`);
    if (state.aqi && prefs.dockAqi) env.push(`AQI <b style="color:${aqiColor(state.aqi.v)}">${state.aqi.v}</b>`);
    groups.push(env);
    if (state.laptopOnline && L) {
      const lap = [];
      if (prefs.dockCpu) lap.push(`💻 <b>${L.cpu ?? "–"}%</b>`);
      if (L.temp != null && prefs.dockLaptopTemp) lap.push(`🌡 <b${hot(L.temp, 75, 90)}>${L.temp}°</b>`);
      if (L.battery != null && prefs.dockLaptopBattery) lap.push(`${L.charging ? "⚡" : "🔋"} <b${L.battery <= 20 && !L.charging ? ' style="color:var(--bad)"' : ""}>${L.battery}%</b>`);
      groups.push(lap);
    }
    if (P) {
      const ph = [];
      if (P.battery != null && prefs.dockPhoneBattery) ph.push(`📱 <b${P.battery <= 20 && !P.charging ? ' style="color:var(--bad)"' : ""}>${P.battery}%</b>${P.charging ? "⚡" : ""}`);
      if (P.temp != null && prefs.dockPhoneTemp) ph.push(`🌡 <b${hot(P.temp, 40, 45)}>${Math.round(P.temp)}°</b>`);
      groups.push(ph);
    }
    const parts = groups.filter((g) => g.length).map((g) => g.map((x) => `<span>${x}</span>`).join('<i class="sep"></i>'));
    const html = parts.map((p) => `<div class="pod">${p}</div>`).join("");
    if (html !== lastStrip) { lastStrip = html; $("#strip").innerHTML = html; }  // repaint only on change
    renderPill();
  }
  function renderClock() {
    const d = new Date(), t = fmt12(d);
    $("#c-time").innerHTML = `${t.h}:${t.m}<small>${t.ap}</small>`;
    $("#c-date").textContent = d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
    const w = weatherNow();
    if (!w) { $("#cp-now").textContent = "Weather loading…"; return; }
    // now: icon + temperature, condition, feels like, today's high/low
    $("#cp-now").innerHTML = `<div class="big"><span class="ic">${w.icon}</span><b>${w.temp}°</b></div>` +
      `<div class="sub">${esc(w.text)}</div><div class="sub">feels ${w.feels}° · <span class="hi">↑${w.max}°</span> <span class="lo">↓${w.min}°</span></div>`;
    // next hours: label, icon, temperature and a bar scaled between the coldest and warmest hour shown
    const W = state.weather.d, i = hourIndex(W.hourly), hrs = [];
    for (let k = i + 1; i >= 0 && k <= i + 6 && k < W.hourly.time.length; k++) {
      hrs.push({ h: Number(W.hourly.time[k].slice(11, 13)), ic: wx(W.hourly.weather_code[k], W.hourly.is_day[k])[0],
        t: Math.round(W.hourly.temperature_2m[k]), rain: W.hourly.precipitation_probability[k] });
    }
    const tmin = Math.min(...hrs.map((x) => x.t)), tmax = Math.max(...hrs.map((x) => x.t));
    $("#cp-hours").innerHTML = hrs.map((x) => `<div class="hr"><span class="hl">${hourLabel(x.h)}</span><span class="ic">${x.ic}</span>` +
      `<b>${x.t}°</b><i class="tb"><i style="height:${tmax > tmin ? 30 + (70 * (x.t - tmin)) / (tmax - tmin) : 60}%"></i></i>` +
      `<span class="rain">${x.rain >= 20 ? "💧" + x.rain + "%" : ""}</span></div>`).join("");
    // air + sun: AQI with category and a 6-step level meter, sunrise and sunset
    const sun = (s) => { const [hh, mm] = s.split(":"); return `${Number(hh) % 12 || 12}:${mm}`; };
    let air = "";
    if (state.aqi) {
      const v = state.aqi.v, level = v <= 50 ? 1 : v <= 100 ? 2 : v <= 150 ? 3 : v <= 200 ? 4 : v <= 300 ? 5 : 6;
      const name = ["Good", "Moderate", "Sensitive", "Unhealthy", "Very unhealthy", "Hazardous"][level - 1];
      const steps = [25, 75, 125, 175, 250, 350].map((s, n) => `<i style="background:${n < level ? aqiColor(s) : "#1a2a34"}"></i>`).join("");
      air = `<div class="aq"><span class="lbl">AQI</span><b style="color:${aqiColor(v)}">${v}</b><span class="cat">${name}</span></div><div class="meter">${steps}</div>`;
    }
    $("#cp-air").innerHTML = air + `<div class="sun"><span>🌅 ${sun(w.sunrise)}</span><span>🌇 ${sun(w.sunset)}</span></div>`;
  }
  function renderLaptop() {
    const L = state.laptop;
    app.classList.toggle("laptop-off", !state.laptopOnline || !L);
    if (!L) return;
    const ring = (k, v, frac, color, label, sub) => {
      const el = $(`.ring[data-k="${k}"]`);
      el.querySelector("b").textContent = v == null ? "–" : label;
      if (sub) el.querySelector("span").textContent = sub;
      setRing(el, v == null ? 0 : frac, color);
    };
    ring("cpu", L.cpu, L.cpu / 100, levelColor(L.cpu, 60, 85), `${L.cpu}%`);
    ring("ram", L.ram, L.ram / 100, levelColor(L.ram, 75, 90), `${L.ram}%`, L.ram_used_gb ? `RAM ${L.ram_used_gb} GB` : "RAM");
    ring("gpu", L.gpu, L.gpu / 100, levelColor(L.gpu, 60, 85), `${L.gpu}%`);
    ring("battery", L.battery, L.battery / 100, L.charging ? "#7cc8ff" : L.battery <= 20 ? "var(--bad)" : "var(--good)",
      `${L.battery}%`, L.charging ? "⚡ CHARGING" : "BATTERY");


    const m = L.media;
    $("#np-title").textContent = m && m.title ? m.title : "Nothing playing";
    $("#np-artist").textContent = m ? [m.artist, m.player].filter(Boolean).join(" · ") : "";
    $("#vol").textContent = L.volume == null ? "–" : L.muted ? "muted" : `${L.volume}%`;
  }
  const fmtLeft = (ms) => {
    const t = Math.ceil(ms / 1000), h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60);
    return h ? `${h}:${pad(m)}:${pad(t % 60)}` : `${m}:${pad(t % 60)}`;
  };
  const fmtUp = (ms) => fmtLeft(Math.floor(ms / 1000) * 1000);  // a stopwatch counts whole seconds up
  const fmtMins = (m) => (m < 60 ? m + "m" : Math.floor(m / 60) + "h" + (m % 60 ? m % 60 : ""));
  function renderPill() {
    const sw = isSW(), on = timerActive() || alarmUntil > 0, left = focusLeft(), [icon, , color] = MODES[focus.mode];
    const text = alarmUntil ? "Time's up" : sw ? fmtUp(swTime()) : fmtLeft(left);
    app.classList.toggle("focusing", on);
    app.classList.toggle("ringing", alarmUntil > 0);
    app.classList.toggle("ending", focus.running && !sw && left < 10000);
    $("#s-focus").classList.toggle("live", focus.running);  // the ring takes the middle while a timer runs
    app.dataset.wpm = preview.get("wpm") || (state.laptop ? state.laptop.wpm || 0 : 0);  // chip.js: Flow / Burst when you type fast
    app.dataset.idle = preview.get("idle") || (state.laptop ? state.laptop.idle || 0 : 0);  // and Stuck when you pause
    if (!on) return;
    $("#tp-icon").textContent = alarmUntil ? "⏰" : focus.running ? icon : "⏸";
    $("#tp-time").textContent = text;
    setRing($("#tpill"), sw ? (swTime() % 60000) / 60000 : left / focus.total, color);
    const bar = $("#focusbar i");
    bar.style.width = sw ? "0%" : ((1 - left / focus.total) * 100).toFixed(2) + "%";
    bar.style.background = color;
  }
  function renderFocus() {
    const sw = isSW(), pomo = isPomo(), left = focusLeft(), [icon, name, color] = MODES[focus.mode];
    const text = alarmUntil ? "0:00" : sw ? fmtUp(swTime()) : fmtLeft(left);
    const paused = !focus.running && (sw ? focus.swElapsed > 0 : left < focus.total);
    $("#f-time").textContent = text;
    $("#f-time").classList.toggle("long", text.length > 5);
    $("#f-label").textContent = `${icon} ${name}`;
    $("#f-mode").textContent = alarmUntil ? "time's up · tap to stop" : focus.running ? "tap to pause" :
      paused ? "paused · tap to resume" : "tap to start";
    setRing($("#f-ring"), sw ? (swTime() % 60000) / 60000 : left / focus.total, color);
    // this round of the pomodoro cycle: one dot per focus session before the long break
    const n = prefs.pomoLongEvery, done = Math.min(cycleNow(), n), lit = focus.mode === "long" ? n : done;
    $("#f-dots").innerHTML = pomo ? Array.from({ length: n }, (_, i) => `<i class="${i < lit ? "on" : ""}"></i>`).join("") : "";
    $$("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === (pomo ? "pomodoro" : focus.mode)));
    // pomodoro: the three phases with their lengths; countdown: presets and −5…+5
    for (const p in POMO) {
      $(`.ph[data-phase="${p}"]`).classList.toggle("on", p === focus.mode);
      $(`#ph-${p}`).textContent = fmtMins(prefs[POMO[p]]);
    }
    const cur = Math.round(focus.total / 60000);
    if ($("#f-presets").dataset.cur !== String(cur)) {
      $("#f-presets").dataset.cur = cur;
      $("#f-presets").innerHTML = PRESETS.map((m) => `<button data-preset="${m}" class="${m === cur ? "on" : ""}">${fmtMins(m)}</button>`).join("");
    }
    $("#f-phases").classList.toggle("off", !pomo);
    $("#f-presets").classList.toggle("off", focus.mode !== "countdown");
    $("#f-adj").classList.toggle("off", focus.mode !== "countdown");
    // only the rows the mode uses (they're centred below the tabs); without Skip, Start and Reset share the row
    $(".f-set").classList.toggle("off", sw);
    $("#f-pomo").classList.toggle("off", !pomo);
    $("#f-opts").classList.toggle("off", !pomo);
    $("#f-skip").classList.toggle("off", !pomo);
    $("#f-start").textContent = alarmUntil ? "⏹ Stop" : focus.running ? "⏸ Pause" : paused ? "▶ Resume" : "▶ Start";
    const st = stats(), goal = prefs.pomoGoal;
    $("#f-cycle").innerHTML = Array.from({ length: n }, (_, i) => `<i class="${i < done ? "" : "todo"}">🍅</i>`).join("") + ` ${done}/${n}`;
    $("#f-today").textContent = `Today ${st.sessions}/${goal} · ${st.minutes} min`;
    $("#f-goal").style.width = Math.min(100, (st.sessions / goal) * 100) + "%";
    const opt = (k, on, label) => { const b = $(`[data-opt="${k}"]`); b.textContent = label; b.classList.toggle("on", on); };
    opt("pomoAutoBreak", prefs.pomoAutoBreak, `${prefs.pomoAutoBreak ? "✓" : "✗"} Auto breaks`);
    opt("pomoAutoFocus", prefs.pomoAutoFocus, `${prefs.pomoAutoFocus ? "✓" : "✗"} Auto focus`);
    opt("pomoLongEvery", false, `🛋️ Long after ${n}`);
    let next = "";
    if (pomo) {
      const m = focus.mode !== "focus" ? "focus" : (done + 1) % n === 0 ? "long" : "short";
      next = `Next: ${MODES[m][0]} ${MODES[m][1]} · ${modeMins(m)} min`;
    }
    $("#f-stats").textContent = now() < hint[1] ? hint[0] : next;
  }
  function render() {
    renderStrip();
    if (screenIdx === 1) renderClock();
    if (screenIdx === 2) renderLaptop();
    if (screenIdx === 3) renderFocus();
  }

  // ---------------------------------------------------------------- audio visualizer (laptop sound, via the bridge)
  const VIZ_STYLES = ["bars", "mirror", "radial", "neon", "waves", "led", "silk"];
  let vizStyle = store.get("vizStyle", "bars"), vizSrc = null, vizRaf = 0, vizLast = 0, vizSound = 0;
  let vizTarget = [], vizBars = [], vizFall = [], vizPeaks = [];
  const canvas = $("#viz"), vctx = canvas.getContext("2d");
  if (preview.has("viz")) vizStyle = preview.get("viz");
  // Chip's eyes follow the laptop's mouse pointer (bridge /gaze, see laptop/bridge.py Gaze)
  let gazeSrc = null, following = false, cursorGaze = [0, 0, false];
  function gazeLook(x, y, near) {  // the cursor's gaze only shows on the face screen, awake, and not under a finger
    if (screenIdx === 0 && mood !== "asleep" && !state.night && !gesture) look(x, y, near);
  }
  function gazeOpen() {
    if (gazeSrc) return;
    gazeSrc = new EventSource(C.laptop + "/gaze");
    gazeSrc.onmessage = (e) => {
      if (e.data === "idle") {
        following = false;
        if (!gesture) look(0, 0);
        return;
      }
      const [gx, gy, near] = e.data.split(",").map(Number);  // "gx,gy,near(0|1)"
      cursorGaze = [gx, gy, near === 1];
      following = true;
      gazeLook(...cursorGaze);
    };
  }
  function gazeClose() {
    if (gazeSrc) gazeSrc.close();
    gazeSrc = null;
    following = false;
    look(0, 0);
  }
  if (preview.has("gaze")) {  // ?gaze=x,y pins the cursor's gaze for screenshots (-1..1, no /gaze stream)
    const [gx, gy] = preview.get("gaze").split(",").map(Number);
    cursorGaze = [gx || 0, gy || 0, false];
    following = true;
    setTimeout(() => gazeLook(...cursorGaze), 1500);
  }

  function vizStart() {
    if (preview.has("vizdemo")) {  // fake music for previews: ?screen=4&vizdemo&viz=neon
      setInterval(() => {
        const t = now() / 300;
        vizTarget = Array.from({ length: 40 }, (_, i) => Math.max(0, Math.round(70 * Math.exp(-i / 14) * (0.6 + 0.4 * Math.sin(t + i / 3)) + 25 * Math.abs(Math.sin(t * 1.7 + i)))));
        vizSound = now();
      }, 40);
    } else if (!vizSrc) {
      vizSrc = new EventSource(C.laptop + "/viz");
      vizSrc.onmessage = (e) => {
        if (!e.data) return;
        vizTarget = e.data.split(",").map(Number);
        if (Math.max(...vizTarget) > 4) vizSound = now();
      };
    }
    if (!vizRaf) vizRaf = requestAnimationFrame(vizDraw);
  }
  function vizStop() {
    if (vizSrc) { vizSrc.close(); vizSrc = null; }
    cancelAnimationFrame(vizRaf); vizRaf = 0;
  }
  function vizDraw(t) {
    vizRaf = 0;
    if (screenIdx !== VIZ) return;
    const idle = now() - vizSound > 2500;
    app.classList.toggle("viz-idle", idle);
    // ~30 fps while there's sound; just check back twice a second while it's quiet
    if (idle && vizBars.every((v) => v < 0.5)) { setTimeout(() => { if (screenIdx === VIZ && !vizRaf) vizRaf = requestAnimationFrame(vizDraw); }, 500); return; }
    vizRaf = requestAnimationFrame(vizDraw);
    if (t - vizLast < 38) return;  // ~25 fps, the rate the laptop sends
    vizLast = t;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }  // 1:1 pixels keep it cheap
    const n = vizTarget.length || 40;
    for (let i = 0; i < n; i++) {  // cava-style: jump up, fall with gravity
      const target = idle ? 0 : vizTarget[i] || 0;
      if (target >= (vizBars[i] || 0)) { vizBars[i] = target; vizFall[i] = 0; }
      else { vizFall[i] = (vizFall[i] || 0) + 0.45; vizBars[i] = Math.max(target, vizBars[i] - vizFall[i]); }
      vizPeaks[i] = Math.max(vizBars[i], (vizPeaks[i] || 0) - 0.6);
    }
    vctx.clearRect(0, 0, W, H);
    const draw = { radial: drawRadial, neon: drawNeon, waves: drawWaves, led: drawLed, silk: drawSilk }[vizStyle];
    if (draw) return draw(W, H, n, t);
    const mirror = vizStyle === "mirror", gap = W / n * 0.28, bw = W / n - gap;
    const base = mirror ? H * 0.55 : H - 6, maxH = mirror ? H * 0.42 : H * 0.8;
    const grad = vctx.createLinearGradient(0, base, 0, base - maxH);
    grad.addColorStop(0, "#4de8ff"); grad.addColorStop(0.6, "#9d7bff"); grad.addColorStop(1, "#ff6fb1");
    vctx.fillStyle = grad;
    for (let i = 0; i < n; i++) {
      const x = i * (bw + gap) + gap / 2, h = Math.max(2, (vizBars[i] / 100) * maxH);
      vctx.fillRect(x, base - h, bw, h);
      if (mirror) { vctx.globalAlpha = 0.35; vctx.fillRect(x, base + 3, bw, h * 0.6); vctx.globalAlpha = 1; }
      else vctx.fillRect(x, base - (vizPeaks[i] / 100) * maxH - 5, bw, 2);  // peak caps
    }
  }
  function drawRadial(W, H, n) {
    const cx = W / 2, cy = H / 2, r0 = Math.min(W, H) * 0.2, len = Math.min(W, H) * 0.28;
    const bass = (vizBars[0] + vizBars[1] + vizBars[2] + vizBars[3]) / 400;
    vctx.lineWidth = Math.max(2, (2 * Math.PI * r0) / (n * 2) * 0.6);
    vctx.lineCap = "round";
    for (let i = 0; i < n * 2; i++) {  // the spectrum twice, mirrored around the circle
      const v = vizBars[i < n ? i : 2 * n - 1 - i] / 100, ang = (i / (n * 2)) * Math.PI * 2 - Math.PI / 2;
      const r1 = r0 * (1 + bass * 0.15), r2 = r1 + 3 + v * len;
      vctx.strokeStyle = `hsl(${190 + (i < n ? i : 2 * n - i) * 3.5}, 90%, 62%)`;
      vctx.beginPath();
      vctx.moveTo(cx + Math.cos(ang) * r1, cy + Math.sin(ang) * r1);
      vctx.lineTo(cx + Math.cos(ang) * r2, cy + Math.sin(ang) * r2);
      vctx.stroke();
    }
    // Chip's eyes in the middle, bouncing with the bass
    const ew = r0 * 0.36, eh = r0 * 0.5 * (1 - bass * 0.25), gy = cy - eh / 2 - bass * r0 * 0.15;
    vctx.fillStyle = "#4de8ff";
    for (const dx of [-r0 * 0.45, r0 * 0.45 - ew]) {
      vctx.beginPath();
      if (vctx.roundRect) vctx.roundRect(cx + dx + (dx < 0 ? 0 : 0), gy, ew, eh, ew * 0.3); else vctx.rect(cx + dx, gy, ew, eh);
      vctx.fill();
    }
  }
  // smooth curve through points using midpoints as quadratic anchors
  function smoothPath(pts) {
    vctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length - 1; i++) {
      const mx = (pts[i][0] + pts[i + 1][0]) / 2, my = (pts[i][1] + pts[i + 1][1]) / 2;
      vctx.quadraticCurveTo(pts[i][0], pts[i][1], mx, my);
    }
    const last = pts[pts.length - 1];
    vctx.lineTo(last[0], last[1]);
  }
  function drawNeon(W, H, n, t) {
    // glowing tubes: a wide faint stroke under a thin bright one (cheaper than canvas blur)
    const step = W / n, base = H * 0.78, maxH = H * 0.66, hue0 = (t / 40) % 360;
    vctx.lineCap = "round";
    for (const [width, alpha, light] of [[step * 0.9, 0.18, 55], [step * 0.45, 0.45, 60], [step * 0.16, 1, 85]]) {
      vctx.lineWidth = width; vctx.globalAlpha = alpha;
      for (let i = 0; i < n; i++) {
        const x = i * step + step / 2, h = 4 + (vizBars[i] / 100) * maxH;
        vctx.strokeStyle = `hsl(${(hue0 + i * 6) % 360}, 100%, ${light}%)`;
        vctx.beginPath(); vctx.moveTo(x, base); vctx.lineTo(x, base - h); vctx.stroke();
      }
    }
    vctx.globalAlpha = 0.18;  // reflection on a glossy floor
    vctx.lineWidth = step * 0.45;
    for (let i = 0; i < n; i++) {
      const x = i * step + step / 2, h = (vizBars[i] / 100) * maxH * 0.25;
      vctx.strokeStyle = `hsl(${(hue0 + i * 6) % 360}, 100%, 60%)`;
      vctx.beginPath(); vctx.moveTo(x, base + 8); vctx.lineTo(x, base + 8 + h); vctx.stroke();
    }
    vctx.globalAlpha = 1;
  }
  function drawWaves(W, H, n, t) {
    // three layered liquid waves (bass at the back, highs in front), fading out towards the bottom
    const layers = [[190, 0, 0, 0.6], [265, 1, 0.33, 0.75], [330, 2, 0.66, 0.9]];
    for (const [hue, k, from, base] of layers) {
      const pts = [], segs = 18, span = n / 3;
      for (let j = 0; j <= segs; j++) {
        const i0 = Math.floor(from * n + (j / segs) * span), lv = ((vizBars[i0] || 0) + (vizBars[i0 + 1] || 0)) / 200;
        const sway = Math.sin(t / (700 + k * 260) + j * 0.7 + k * 2) * H * 0.04;
        pts.push([(j / segs) * W, H * base - lv * H * 0.38 + sway]);
      }
      const top = Math.min(...pts.map((p) => p[1]));
      const g = vctx.createLinearGradient(0, top, 0, H);
      g.addColorStop(0, `hsla(${hue}, 95%, 62%, .55)`); g.addColorStop(1, `hsla(${hue}, 95%, 40%, 0)`);
      vctx.beginPath(); smoothPath(pts); vctx.lineTo(W, H); vctx.lineTo(0, H); vctx.closePath();
      vctx.fillStyle = g; vctx.fill();
      vctx.beginPath(); smoothPath(pts); vctx.strokeStyle = `hsl(${hue}, 95%, 68%)`; vctx.lineWidth = 2.5; vctx.stroke();
    }
  }
  function drawLed(W, H, n) {
    // segmented columns like a hi-fi meter (or cava in a terminal)
    const cols = Math.min(n, 32), segs = 16, cw = W / cols, sh = (H * 0.82) / segs, top = H * 0.1;
    for (let c = 0; c < cols; c++) {
      const i = Math.floor((c / cols) * n), lit = Math.round((vizBars[i] / 100) * segs), peak = Math.round((vizPeaks[i] / 100) * segs);
      for (let s = 0; s < segs; s++) {
        const on = s < lit || s === peak - 1, f = s / segs;
        vctx.fillStyle = on ? (f > 0.8 ? "#ff5d6c" : f > 0.55 ? "#ffd84d" : "#5dffa8") : "#0d1a14";
        vctx.fillRect(c * cw + cw * 0.12, top + (segs - 1 - s) * sh + sh * 0.18, cw * 0.76, sh * 0.64);
      }
    }
  }
  const silkTrail = [];
  function drawSilk(W, H, n) {
    // mirrored line spectrum with fading echoes of the last few frames
    const pts = vizBars.slice(0, n).map((v, i) => [(i / (n - 1)) * W, v]);
    silkTrail.unshift(pts);
    if (silkTrail.length > 6) silkTrail.pop();
    const cy = H / 2, amp = H * 0.42;
    vctx.lineWidth = 2.5;
    silkTrail.forEach((p, k) => {
      const hue = 190 + k * 25, alpha = 1 - k / silkTrail.length;
      for (const dir of [-1, 1]) {
        vctx.beginPath();
        smoothPath(p.map(([x, v]) => [x, cy + dir * (v / 100) * amp * (1 - k * 0.06)]));
        vctx.strokeStyle = `hsla(${hue}, 95%, 65%, ${alpha * (dir < 0 ? 1 : 0.55)})`;
        vctx.stroke();
      }
    });
  }
  function cycleViz() {
    vizStyle = VIZ_STYLES[(VIZ_STYLES.indexOf(vizStyle) + 1) % VIZ_STYLES.length];
    store.set("vizStyle", vizStyle);
    $("#viz-hint").textContent = `style: ${vizStyle} · tap: change · swipe: back`;
  }

  // ---------------------------------------------------------------- drawer (apps + toggles)
  const APPS = [
    ["browser", "🌐", "Browser"], ["termux", "⌨️", "Termux"],
    ["files", "📁", "Files"], ["settings", "⚙️", "Settings"], ["home", "🏠", "Home"],
  ];
  $("#tiles").innerHTML = APPS.map(([id, ic, label]) => `<button class="tile" data-app="${id}"><i>${ic}</i>${label}</button>`).join("");
  function renderToggles() {
    const set = (k, on, label) => { const b = $(`[data-toggle="${k}"]`); b.textContent = label; b.classList.toggle("on", on); };
    set("sounds", prefs.sounds, prefs.sounds ? "🔊 Sounds on" : "🔈 Sounds off");
    set("talk", prefs.talk, prefs.talk ? "🗣️ Talking on" : "🤐 Talking off");
    set("fastDictation", prefs.fastDictation, prefs.fastDictation ? "⚡ Fast dictation" : "🎙 Best dictation");
    set("dictEngine", prefs.dictEngine !== "phone", `${ENGINE_ICON[prefs.dictEngine] || "📱"} Dictation: ${ENGINE_NAME[prefs.dictEngine] || "Phone"}`);
    set("flashlight", !!state.flashlight, state.flashlight ? "🔦 Torch on" : "🔦 Torch off");
  }
  function openDrawer() { renderToggles(); $("#tiles").style.display = phone.canLaunch ? "" : "none"; $("#drawer").classList.add("open"); }
  $("#drawer").addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.app) { $("#drawer").classList.remove("open"); return phone.launch(b.dataset.app); }
    const k = b.dataset.toggle;
    if (["sounds", "talk", "fastDictation"].includes(k)) setPrefs({ [k]: !prefs[k] });
    if (k === "dictEngine") setPrefs({ dictEngine: ENGINES[(ENGINES.indexOf(prefs.dictEngine) + 1) % ENGINES.length] });  // phone -> laptop -> cloud
    if (k === "flashlight") { state.flashlight = !state.flashlight; post(`/api/torch?on=${state.flashlight ? 1 : 0}`); }
    if (k === "reload") return location.reload();
    if (k === "viz") { $("#drawer").classList.remove("open"); return go(VIZ); }
    renderToggles();
  });

  $$("[data-media]").forEach((b) => b.addEventListener("click", () => laptop(`/media/${b.dataset.media}`).then(() => setTimeout(pollLaptopOnce, 400))));
  $$("[data-vol]").forEach((b) => b.addEventListener("click", () => laptop(`/volume/${b.dataset.vol}`).then(() => setTimeout(pollLaptopOnce, 200))));
  $("#open-viz").addEventListener("click", () => go(VIZ));
  $("#f-ring").addEventListener("click", () => timerToggle());
  $("#f-start").addEventListener("click", () => timerToggle());
  $("#f-reset").addEventListener("click", timerReset);
  $("#f-skip").addEventListener("click", timerSkip);
  $("#tpill").addEventListener("click", () => (alarmUntil ? stopAlarm() : go(3)));
  function switchTo(mode) {
    if (mode === focus.mode && !alarmUntil) return;
    if (focus.running && !confirmTap("Timer is running: tap again to switch")) return;
    alarmUntil = 0; stopAlerts(); timerSet(mode);
  }
  $$("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.mode === "pomodoro") { if (!isPomo()) switchTo("focus"); }  // Pomodoro starts with focus
    else switchTo(b.dataset.mode);
  }));
  $$(".ph-name").forEach((b) => b.addEventListener("click", () => switchTo(b.dataset.phase)));
  $("#f-phases").addEventListener("click", (e) => {  // − / + beside each phase: its length (a setting)
    const b = e.target.closest("[data-step]");
    if (!b) return;
    const p = b.dataset.step, k = POMO[p];
    setPrefs({ [k]: Math.max(1, Math.min(POMO_MAX[p], prefs[k] + Number(b.dataset.d))) });
  });
  $("#f-presets").addEventListener("click", (e) => { const b = e.target.closest("[data-preset]"); if (b) timerSet(focus.mode, Number(b.dataset.preset)); });
  $$("[data-adj]").forEach((b) => b.addEventListener("click", () => timerAdjust(Number(b.dataset.adj))));
  $("#f-cycle").addEventListener("click", () => {
    if (!confirmTap("Tap again to start a new round of the cycle")) return;
    focus.cycle = 0; saveFocus(); hint = ["", 0]; render();
  });
  $("#f-opts").addEventListener("click", (e) => {
    const k = (e.target.closest("[data-opt]") || {}).dataset?.opt;
    if (k === "pomoLongEvery") setPrefs({ pomoLongEvery: prefs.pomoLongEvery >= 8 ? 2 : prefs.pomoLongEvery + 1 });
    else if (k) setPrefs({ [k]: !prefs[k] });
  });
  // Some taps need a second one within 3 s (no browser dialogs in the kiosk).
  let armed = ["", 0], hint = ["", 0];
  function confirmTap(text) {
    if (armed[0] === text && now() - armed[1] < 3000) return true;
    armed = [text, now()]; hint = [text, now() + 3000]; render(); return false;
  }
  async function pollLaptopOnce() {
    const d = await getJSON(C.laptop + "/stats", 2500);
    if (d) { state.laptop = d; render(); }
  }

  // ---------------------------------------------------------------- preferences (from the laptop dashboard)
  // The laptop keeps the settings and bumps settingsRev in /stats whenever they change; the phone then
  // fetches them. Drawer toggles go the other way, and wait in pendingPrefs while the laptop is away.
  const onPhone = location.port === "8080";  // the dashboard's preview runs this page on the laptop too
  const SHOWS = {
    dock: "#strip", timerPill: "#tpill", focusBar: "#focusbar", tabViz: "#open-viz, [data-toggle=viz]",
    clockNow: "#cp-now", clockHours: "#cp-hours", clockAir: "#cp-air", mediaCard: ".media",
    ringCpu: '.ring[data-k="cpu"]', ringRam: '.ring[data-k="ram"]', ringGpu: '.ring[data-k="gpu"]', ringBattery: '.ring[data-k="battery"]',
  };
  let prefsRev = -1, pendingPrefs = store.get("prefsPending", {}), prefsBusy = false;
  const brightnessNow = () => (state.night ? prefs.brightnessNight : prefs.brightnessDay);
  // the accent colour (Chip's eyes, glow and scenes), from the design's palettes in robot.js: the active skin's own
  // accent if it has one, else the chosen one
  function paintAccent() {
    const sk = window.ChipSkin && app.dataset.skin ? window.ChipSkin : null;
    const skinPal = sk && typeof sk.accent === "string" && /^#[0-9a-f]{6}$/i.test(sk.accent) ? window.chipCustomPalette(sk.accent.toLowerCase()) : null;
    const pal = skinPal || (prefs.accent === "custom" && /^#[0-9a-f]{6}$/i.test(prefs.accentColor) ? window.chipCustomPalette(prefs.accentColor)
      : window.CHIP_PALETTES[prefs.accent] || window.CHIP_PALETTES.cyan), rgb = (hex, a) =>
      `rgba(${parseInt(hex.slice(1, 3), 16)}, ${parseInt(hex.slice(3, 5), 16)}, ${parseInt(hex.slice(5, 7), 16)}, ${a})`;
    for (const [k, v] of [["--eye", pal.main], ["--glow", rgb(pal.main, 0.5)], ["--eye-night", pal.dark], ["--glow-night", rgb(pal.dark, 0.3)]]) {
      document.documentElement.style.setProperty(k, v);
    }
    app.dataset.accent = prefs.accent;
    app.dataset.accentHex = pal.main;  // chip.js bakes the pack in this colour
  }

  // ---------------------------------------------------------------- skins (chip-skin/1, made and checked on the laptop)
  // The skin is fetched from the bridge, kept in localStorage per id (so the phone keeps its skin after a reboot with
  // the laptop away), and handed to chip.js through window.ChipSkin + data-skin. chip.js merges it over the pack; if
  // that fails it says so in data-skin-err and sends chip:skinfail, and we go back to the base pack.
  const SKIN_ID = /^[a-z0-9-]{1,32}$/, SKIN_MAX = 600 * 1024;
  let skinWant = null, skinText = "", skinBad = "", skinSeq = 0, skinGreeted = "";  // id wanted, the text shown, the text chip.js refused, data-skin counter, the name last introduced
  // the name Chip goes by: the active skin's display name (set when it was installed on the dashboard), else config.js's
  const buddyName = () => {
    const sk = app.dataset.skin && window.ChipSkin;
    return sk && typeof sk.name === "string" && sk.name.trim() ? sk.name.trim().slice(0, 40) : C.name;
  };
  function skinShow(skin, text) {
    if (text && (text === skinBad || text === skinText)) return;
    skinText = text;
    window.ChipSkin = skin;
    app.dataset.skin = skin ? skin.id + "@" + ++skinSeq : "";
    paintAccent();
    phonesPick();  // the rule depends on the skin's own headphones
    // a new look after start-up (installed, picked or renamed on the dashboard) introduces itself by its name
    const name = buddyName();
    if (performance.now() > 8000 && name !== skinGreeted && !state.night) setTimeout(() => { if (buddyName() === name) { express("joy", 1500); say(`Hi! I'm ${name} 👋`, 2500); } }, 1200);
    skinGreeted = name;
  }
  let skinsRev = null;   // the laptop's skin-files counter, as last seen (null until the first /stats)
  function skinsReload() {
    if (skinWant) loadSkin(skinWant);   // unchanged text is ignored in skinShow
    if (phonesWant && phonesWant !== "skin" && phonesWant !== "chip") loadPhones(phonesWant);   // a borrowed pair
  }
  async function loadSkin(id) {
    skinWant = id;
    if (!id) { skinShow(null, ""); app.dataset.skinErr = ""; return; }
    const fail = (why) => { skinShow(null, ""); app.dataset.skinErr = why; };
    if (!SKIN_ID.test(id)) return fail("bad skin id");
    const phonesDraft = preview.has("hpdraft") && id !== "draft";   // dashboard preview: this skin with its unsaved headphones on
    const cacheable = id !== "draft" && !phonesDraft, key = "skin." + id;
    const cached = cacheable ? store.get(key, null) : null;
    if (cached && cached.id === id) skinShow(cached, JSON.stringify(cached));  // at once, and without the laptop
    const retry = () => setTimeout(() => { if (skinWant === id) loadSkin(id); }, 30000);
    let res, text;
    try {
      const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 5000);
      res = await fetch(C.laptop + (id === "draft" ? "/skins/draft.json" : "/skins/" + id + (phonesDraft ? "/with-headphones.json" : ".json")), { signal: ctl.signal, cache: "no-store" });
      text = res.ok ? await res.text() : "";
      clearTimeout(t);
    } catch (e) {  // the laptop is away: keep the cached skin, try again later
      if (skinWant === id && !cached) app.dataset.skinErr = "skin " + id + " not loaded: laptop unreachable and no copy saved";
      return retry();
    }
    if (skinWant !== id) return;  // something else was wanted meanwhile
    if (res.status === 404) { if (cacheable) store.set(key, null); return fail("skin " + id + " is not on the laptop"); }
    if (!res.ok || text.length > SKIN_MAX) return retry();
    let skin;
    try { skin = JSON.parse(text); } catch (e) { return fail("skin " + id + " is not valid JSON"); }
    if (!skin || (id !== "draft" && skin.id !== id)) return fail("skin " + id + ": the file has another id");  // the draft has its own id
    if (cacheable) store.set(key, skin);
    skinShow(skin, JSON.stringify(skin));
  }
  document.addEventListener("chip:skinfail", () => {  // chip.js refused it: the base pack is back
    skinBad = skinText;
    skinShow(null, "");
  });

  // ---------------------------------------------------------------- headphones (chip-phones/1, borrowed from another skin)
  // Which pair Chip wears: the active skin's own if phonesFollowSkin and it has a pair; else phonesDefault ("" =
  // Chip's own; the active skin's id = its own pair; another installed skin's id = that skin's pair, borrowed).
  // &phones=skin|chip|<id> in the preview overrides it. A borrowed pair is fetched from the bridge and kept in
  // localStorage per id (phones.<id>); chip.js gets it through window.ChipPhones + data-phones ("id:<id>@<seq>").
  // Anything that fails is Chip's own pair (chip.js drops a file it refuses to "chip" itself).
  let phonesWant = "", phonesSeq = 0;   // "skin" | "chip" | the id wanted ("" = nothing yet, or retry on the next pick)
  function phonesRule() {
    const sk = app.dataset.skin && window.ChipSkin ? window.ChipSkin : null, p = preview.get("phones");
    if (p === "skin" || p === "chip") return p;
    if (!preview.has("phones") && prefs.phonesFollowSkin && sk && typeof sk.headphones === "string") return "skin";
    const id = preview.has("phones") ? p : prefs.phonesDefault;
    return !id ? "chip" : sk && id === sk.id ? "skin" : id;
  }
  function phonesShow(mode, part) {
    window.ChipPhones = part || null;
    app.dataset.phones = part ? "id:" + part.from + "@" + ++phonesSeq : mode;
  }
  function phonesPick() {
    const want = phonesRule();
    if (want === phonesWant) return;
    if (want === "skin" || want === "chip") { phonesWant = want; return phonesShow(want); }
    loadPhones(want);
  }
  async function loadPhones(id) {
    phonesWant = id;
    if (!SKIN_ID.test(id)) return phonesShow("chip");
    const key = "phones." + id, cached = store.get(key, null);
    phonesShow("chip", cached && cached.from === id ? cached : null);  // at once, and without the laptop
    const retry = () => setTimeout(() => { if (phonesWant === id) loadPhones(id); }, 30000);
    let res, text;
    try {
      const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 5000);
      res = await fetch(C.laptop + "/skins/" + id + "/headphones.json", { signal: ctl.signal, cache: "no-store" });
      text = res.ok ? await res.text() : "";
      clearTimeout(t);
    } catch (e) {  // the laptop is away: keep the cached pair (or Chip's own), try again later
      return retry();
    }
    if (phonesWant !== id) return;  // something else was wanted meanwhile
    const fail = () => { phonesWant = ""; phonesShow("chip"); };  // "" = the next pick asks again
    if (res.status === 404) { store.set(key, null); return fail(); }
    if (!res.ok || text.length > SKIN_MAX) return retry();
    let part;
    try { part = JSON.parse(text); } catch (e) { return fail(); }
    if (!part || part.from !== id) return fail();
    store.set(key, part);
    if (!cached || JSON.stringify(cached) !== JSON.stringify(part)) phonesShow("chip", part);
  }

  function applyPrefs(p) {
    const was = brightnessNow(), placeWas = placeKey();
    for (const k in DEFAULT_PREFS) if (typeof p[k] === typeof DEFAULT_PREFS[k]) prefs[k] = p[k];
    if (preview.get("accent")) prefs.accent = preview.get("accent");
    store.set("prefs", prefs);
    if (want("gazeFollow") && !preview.has("gaze")) gazeOpen();
    else if (gazeSrc) gazeClose();
    paintAccent();
    app.dataset.chipGlow = prefs.chipGlow;
    app.dataset.eyeGap = prefs.eyeGap;  // px added to each eye's distance from the centre
    app.dataset.phonesGap = preview.has("hpgap") ? preview.get("hpgap") : prefs.phonesGap;  // the same for each headphone ear cup
    phonesPick();  // whose headphones Chip wears
    const size = preview.has("size") ? +preview.get("size") || 100 : prefs.faceSize;  // % of the screen-filling size (player.js fit)
    if (app.dataset.faceSize !== String(size)) { app.dataset.faceSize = size; window.dispatchEvent(new Event("resize")); }
    app.dataset.eyes = preview.get("eyes") || prefs.eyeStyle;  // chip.js picks them up
    app.dataset.pupil = (preview.get("pupil") || prefs.pupilSize).toUpperCase();
    app.dataset.pupils = prefs.showPupils ? "1" : "0";
    const wantSkin = preview.has("skin") ? preview.get("skin") : prefs.skin;
    if (wantSkin !== skinWant) loadSkin(wantSkin);
    if (isPomo() && !timerActive() && !alarmUntil && focus.total !== prefs[POMO[focus.mode]] * 60000) {
      focus.total = focus.left = prefs[POMO[focus.mode]] * 60000; saveFocus();
    }
    for (const [k, sel] of Object.entries(SHOWS)) $$(sel).forEach((el) => el.classList.toggle("off", !want(k)));
    $("#c-panel").classList.toggle("off", !prefs.clockNow && !prefs.clockHours && !prefs.clockAir);
    $(".rings").classList.toggle("off", !want("ringCpu") && !want("ringRam") && !want("ringGpu") && !want("ringBattery"));
    $$("#dots i").forEach((d, k) => d.classList.toggle("off", !tabOn(k)));
    $("#dots").classList.toggle("off", !prefs.dots || [1, 2, 3].every((k) => !tabOn(k)));
    if (!tabOn(screenIdx)) go(screenIdx);  // go() moves off a tab that was just hidden
    if (brightnessNow() !== was) phone.brightness(brightnessNow());
    burnGuard(prefs.burnGuard);
    if (placeKey() !== placeWas) {  // a new place: drop the old place's forecast and fetch the new one
      state.weather = state.aqi = null; store.set("weather", null); store.set("aqi", null); fetchWeather();
    }
    refreshMood(); render(); renderToggles();
  }
  // OLED burn-in guard: every 3 minutes the face screen steps through a 3x3 orbit of 0..2 px offsets (nothing per frame)
  const BURN_ORBIT = [[0, 0], [1, 0], [2, 0], [2, 1], [1, 1], [0, 1], [0, 2], [1, 2], [2, 2]];
  let burnTimer = 0, burnStep = 0;
  function burnNudge(x, y) {
    const st = document.documentElement.style;
    st.setProperty("--bx", x + "px"); st.setProperty("--by", y + "px");
    window.dispatchEvent(new CustomEvent("chip:nudge", { detail: { x, y } }));  // player.js fit() moves the canvas
  }
  function burnGuard(on) {
    if (on === !!burnTimer) return;
    clearInterval(burnTimer); burnTimer = 0; burnStep = 0;
    if (on) burnTimer = setInterval(() => { burnStep = (burnStep + 1) % BURN_ORBIT.length; burnNudge(...BURN_ORBIT[burnStep]); }, 180000);
    burnNudge(0, 0);
  }
  async function syncPrefs() {
    if (prefsBusy) return;
    prefsBusy = true;
    const s = await getJSON(C.laptop + "/settings", 2500);
    prefsBusy = false;
    if (!s) return;
    // Nothing saved on the laptop yet: hand it what the drawer toggles were before there was a dashboard.
    if (s.rev === 0 && onPhone) return setPrefs({ sounds: prefs.sounds, talk: prefs.talk, fastDictation: prefs.fastDictation });
    prefsRev = s.rev; store.set("prefsRev", s.rev); applyPrefs(s);
  }
  function setPrefs(p) {  // changed on this screen
    applyPrefs(p);
    Object.assign(pendingPrefs, p); store.set("prefsPending", pendingPrefs);
    if (state.laptopOnline) pushPrefs();
  }
  async function pushPrefs() {
    if (prefsBusy) return;
    prefsBusy = true;
    const sent = pendingPrefs;
    pendingPrefs = {};
    const s = await fetch(C.laptop + "/settings", { method: "POST", body: JSON.stringify(sent) })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    prefsBusy = false;
    if (s) { prefsRev = s.rev; store.set("prefsRev", s.rev); applyPrefs(Object.assign(s, pendingPrefs)); }
    else pendingPrefs = Object.assign(sent, pendingPrefs);
    store.set("prefsPending", pendingPrefs);
  }
  // The dashboard's preview gets changes straight away instead of on the next poll, and can switch tabs.
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin || e.source !== window.parent || window.parent === window || !e.data) return;
    if (e.data.prefs) { prefsRev = e.data.prefs.rev; applyPrefs(e.data.prefs); }
    if (typeof e.data.screen === "number") go(e.data.screen);
  });

  // ---------------------------------------------------------------- clock tick
  function tick() {
    const d = new Date(), n = isNight(d);
    if (n !== state.night) {
      state.night = n;
      app.classList.toggle("night", n);
      if (now() - bootAt > 3000) {
        if (n) { if (prefs.greetings) say("Good night! 😴", 3000); }
        else { express("surprised", 800); setTimeout(() => { anim("hop", 500); if (prefs.greetings) say(greeting(), 6000); }, 800); }
      }
      phone.brightness(brightnessNow());
    }
    if (prefs.hourly && !n && d.getMinutes() === 0 && state.lastHour !== d.getHours() && d.getHours() >= 8 && d.getHours() <= 22) {
      state.lastHour = d.getHours();
      anim("hop", 500); express("happy", 1500); chirp(880, 880, 0.08, "sine", 0.08);
      const t = fmt12(d);
      say(`It's ${t.h} ${t.ap}! ⏰`, 3000);
    }
    const scene = app.classList.contains("scene");  // the face is put away
    if (state.music && prefs.musicMode && screenIdx === 0 && !state.night && !scene && d.getSeconds() % 3 === 0) {
      particles(["♪", "♫"], 1, "var(--pink)");
    }
    if (mood === "asleep" && screenIdx === 0 && d.getSeconds() % 8 === 0) particles(["z", "Z", "z"], 1, "#5d7f99");
    focusCheck();
    attentionCheck();
    refreshMood();
    render();
  }

  // Reload by itself when ~/deskbuddy/deploy.sh pushes a new version.
  let version = null;
  async function checkVersion() {
    const v = await fetch("version.txt", { cache: "no-store" }).then((r) => (r.ok ? r.text() : null)).catch(() => null);
    if (v && version && v !== version) location.reload();
    if (v) version = v;
  }

  // ---------------------------------------------------------------- start
  state.night = isNight(new Date());
  app.classList.toggle("night", state.night);
  phone.brightness(brightnessNow());
  applyPrefs({});
  blinkLoop(); lookLoop(); setTimeout(idleLoop, 20000);
  if (preview.has("timer")) { timerSet(preview.get("tmode") || "countdown", Number(preview.get("timer"))); timerToggle(); }
  else if (MODES[preview.get("tmode")]) timerSet(preview.get("tmode"));  // ?screen=3&tmode=stopwatch
  // Pomodoro lengths used to be kept here on the phone: hand them to the laptop's settings once.
  if (savedTimer.mins && onPhone) setPrefs({ pomoFocus: savedTimer.mins.focus || 25, pomoShort: savedTimer.mins.break || 5 });
  go(preview.has("screen") ? Number(preview.get("screen")) : store.get("screen", 0));
  setInterval(tick, 1000);
  setInterval(fetchWeather, 20 * 60000);
  setInterval(checkVersion, 60000);
  fetchWeather(); pollLaptop(); pollPhone(); checkVersion();

  // Chrome web app: the screen stays on while Chip is showing (kiFOSSk keeps it on itself; a browser without the API skips this).
  // The lock is released whenever the page is hidden, so it is asked for again each time it is visible.
  let wakeLock = null;
  async function keepAwake() {
    if (!onPhone || !navigator.wakeLock || document.visibilityState !== "visible" || wakeLock) return;
    try { wakeLock = await navigator.wakeLock.request("screen"); wakeLock.addEventListener("release", () => { wakeLock = null; }); }
    catch (e) { wakeLock = null; }  // refused (battery saver): tried again at the next visibilitychange
  }
  document.addEventListener("visibilitychange", keepAwake);
  keepAwake();
  // a service worker that does nothing, only so Chrome offers "Install app" (it must cache nothing: deploys rely on reloads)
  if (onPhone && "serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  if (!state.night && prefs.greetings) setTimeout(() => { express("surprised", 700); setTimeout(() => { anim("hop", 500); express("joy", 1500); say(`Hi! I'm ${buddyName()} 👋`, 2500); }, 700); }, 900);
})();
