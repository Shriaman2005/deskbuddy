# Desk buddy

The old Samsung Galaxy M01 Core (SM-M013F) as an animated desk companion for this laptop.

## On the phone
- **Face** (home screen, via kiFOSSk): blinks, looks around, reacts.
  - Pixel look (default): `phone/www/pixel.js` draws the face on a 62×42 canvas scaled up with crisp pixels,
    plus the VT323 pixel font, notched pixel borders and CRT scanlines. Swipe up → "👾 Pixel look" switches
    back to the smooth face (or set `pixel: false` in config.js).
  - tap: happy · double-tap: hearts · rub back and forth: pets · poke 6×: grumpy · shake: dizzy
  - drag a finger: the eyes follow it · tap while it wears its mask: takes it off for 15 s
  - idle: whistles, sneezes, peeks off-screen, spins, wiggles, smirks; yawns and nods off when you're away
  - headphones while music plays on the laptop, a mask when AQI ≥ 200, star eyes after a focus session,
    background glow follows the time of day and its mood. Preview: `?mood=love&music=1&aqi=250&timer=10&screen=3`
  - swipe left/right: Face → Clock & weather → Laptop → Timer
  - Laptop: CPU/RAM/GPU/battery rings and the music card (play/pause, next, volume).
    🎵 Visualizer on the music card opens a cava-style spectrum of what the laptop is playing:
    tap to cycle bars / mirror / radial / neon / waves / led / silk, swipe to go back. Streams only while open
    (~1 phone CPU core). Preview without music: `?screen=4&vizdemo&viz=neon`.
  - Timer: three tabs, Pomodoro, Countdown and Stopwatch, with a big ring on the left and the controls beside it.
    Pomodoro has one card for its three phases (Focus, Short, Long): −/+ for each length, tap a name to switch
    to that phase; then Start/Reset/Skip, this round's 🍅 (tap twice to start a new round), today's sessions
    against the daily goal, auto-start breaks/focus and "long break after N". Countdown has presets and
    −5/−1/+1/+5. While a timer runs, the controls slide away and the ring fills the middle of the screen; pause it
    (tap the ring) or let it finish to get them back. The pomodoro settings are also on the dashboard (Timer &
    Pomodoro). A running or paused timer shows as a pill on the face; tap it to open the timer. A finished
    countdown rings for up to 30 s — tap to stop it.
  - Chip's two scenes are from the Claude Design project "Robot Focus" / "Robot Typing", ported to a canvas in
    `robot.js` (pixel or smooth to match the look, in the accent colour):
    - Focus mode, while a focus session runs (dashboard > Timer & Pomodoro > "Focus mode on the face screen"):
      the room dims, a moon comes up and Chip types away on a laptop; it gets into flow (closer camera) while you
      type fast, and notifications that arrive meanwhile pop up as muted bubbles. It lets go when the session ends.
    - Typing along, once you've been typing on the laptop for 10 s (dashboard > Face screen > "Chip types along
      with you", 3–60 s): Chip boots up a laptop of its own and types at your pace, thinks when you pause for 2 s,
      gets an idea when you carry on, bursts into sparks above 60 wpm, hits a big Enter when you stop (8 s
      without a key) and powers down. The bridge only counts key presses (the USB keyboard's transfer count in
      /sys/bus/usb/devices/*/urbnum, the built-in keyboard's interrupts), never which keys.
    - Previews: `?typing` or `?mood=focus`, plus `&wpm=90`, `&idle=3`, `&sceneT=<seconds into the design>`,
      `&look=smooth`, `&accent=sage`.
    - Cost on the phone: ~80% of a core for kiFOSSk during a scene (8 fps while a section loops, 12 for the
      moves; the canvas is drawn at the design's grid size and scaled up by CSS).
  - Accent colour (dashboard > Look): cyan, terracotta or sage, the design's palettes. It colours Chip's eyes and
    glow, the scenes and the dashboard itself.
  - Rotates with the phone (kiFOSSk orientation: Auto-rotate); every screen has a portrait layout.
  - swipe up: apps (Brave, Termux, Files, Settings, All apps) and toggles (sounds, talking,
    pixel look, dictation speed, visualizer, reload)
  - **Dictation:** hold Chip's face with two fingers, speak (English or Hinglish), let go: the text is typed
    wherever the cursor is on the laptop. Slide a finger away before letting go to cancel. Fully offline:
    the phone records and runs whisper.cpp itself (`phone/dictation.py`, binary and models in `~/stt` in
    Termux), the laptop only types (`laptop/typer.py`, GNOME's remote-desktop D-Bus API). Never presses
    Enter, won't type while the laptop is locked, and the mic is only open while you hold.
    A 4 s sentence takes ~6 s with the default model (base, better Hinglish) or ~3 s with
    "⚡ Fast dictation" (tiny) from the swipe-up drawer. One finger can't be used: kiFOSSk grabs that long-press.
    **Phone or laptop:** "Speech model runs on" in the dashboard (or "📱/💻 Dictation on …" in the drawer) moves
    the transcription to the laptop: the phone still records, sends the clip through the ssh tunnel to the
    bridge's `POST /transcribe`, and the laptop's whisper.cpp answers in ~2 s (small model) or under 1 s in fast
    mode (base). The clip only touches RAM on the laptop. If the laptop doesn't answer, the phone transcribes it.
  - swipe down on the face: quick summary
- It sleeps 11 PM–6:30 AM (screen dims; change it on the dashboard), greets you, says the hour, nudges you to stretch after
  50 min at the laptop, warns when the laptop battery is low, bobs to music playing on the laptop.
- **Attention alerts:** when an AI agent or an app needs you, the phone blinks its torch and/or plays a sound
  (chime, beep, alarm or ping, made in `phone/alert.py` and played through Termux's PulseAudio), and Chip says
  who. Then it reminds you every N seconds until you use the laptop or tap Chip (a tap also silences it at once).
  Sources: Claude Code hooks (Notification, Stop in `~/.claude/settings.json`) and Gemini CLI hooks
  (Notification, AfterAgent in `~/.gemini/settings.json`), both running `laptop/attention.py`; an opencode plugin
  (`~/.config/opencode/plugin/deskbuddy-attention.js`); and desktop notifications, which the bridge watches on the
  session bus (only the sending app's name, or a browser notification's site, is kept). AI apps count by default;
  "All other apps" makes every notification count, and the dashboard's Apps card sets torch / sound / both / off
  per app (`~/.config/deskbuddy/apps.json` lists the apps seen). Durations, sound, volume, reminders, away-only
  and night are all on the dashboard, with a test button and the last alerts.
- **Torch in Chip's behaviour** (Behaviour > Torch on the dashboard): blinks when a focus session or break ends,
  for the whole countdown alarm (until you tap), at stretch time and for laptop battery/heat warnings.
  The swipe-up drawer also has a 🔦 torch on/off button (a flashlight).
- Long-press anywhere with one finger (~0.5 s) opens kiFOSSk's settings ("Switch to different launcher"
  gets the normal Samsung home screen back).

## On the laptop
- **Dashboard:** http://127.0.0.1:8765 (also **Chip Dashboard** in the app grid). Switches for every
  feature (tabs, dock items, clock and laptop panels, face extras, sounds, talking, alerts, dictation,
  pixel look, brightness) and Chip's sleep time, with a live preview of the face. Changes save instantly
  (`~/.config/deskbuddy/settings.json`) and reach the phone on its next poll (~3 s); the drawer toggles on
  the phone write back to the same settings. Served by the bridge, so `deskbuddy-bridge` must be running.
- `systemctl --user start deskbuddy-bridge` — laptop stats, media and volume controls for the
  phone (ssh tunnel to Termux on the phone, port 8765, localhost only).
- `ssh -p 8022 <phone-ip>` — Termux shell (key login only). Phone IP: `~/.config/deskbuddy/state.json`.
- `python3 -I laptop/doctor.py` — checks every link (bridge, Wi-Fi tunnel, Termux services, face page) and says
  what to do about any that are down.
- Edit `phone/www/*` (location and fallback defaults in `phone/www/config.js`), then `./deploy.sh`; the face reloads itself.

## Pieces
| Where | What |
|---|---|
| `phone/www/` | the face and screens (HTML/CSS/JS) |
| `phone/server.py` | Termux server on the phone's 127.0.0.1:8080: page, brightness, speech, app launching, dictation |
| `phone/dictation.py` | records the mic (PulseAudio's Android source) and transcribes with `~/stt/whisper-cli` |
| `laptop/typer.py` | types text into the focused window (used by the bridge's `POST /type`) |
| `phone/alert.py` | torch blinking, the flashlight and the alert sounds (`/api/alert`, `/api/torch` on the phone server) |
| `laptop/attention.py` | agent hooks call it when an AI agent needs you; tells the bridge (`POST /attention`) |
| `phone/services.sh`, `phone/supervisor.sh` | Termux:Boot (or any new Termux session) starts them; the supervisor restarts sshd and the server within 10 s if they die |
| `laptop/doctor.py`, `laptop/install.sh` | link health check; (re)installs the bridge as a boot-time systemd user service |
| `laptop/bridge.py` | `deskbuddy-bridge.service`: stats/media API, Wi-Fi ssh tunnel (finds the phone again if its IP changes), settings and the dashboard |
| `laptop/dashboard.html` | the dashboard page (its preview is `phone/www` served by the bridge) |

Phone apps: kiFOSSk, Termux, Termux:API (F-Droid); Brave (official GitHub release).
(The phone used to double as a webcam via Android IP Camera; that was removed on 2026-10-28 because it lagged.)

Dictation on the laptop: whisper.cpp v1.9.5 built from source (static, AVX2) in
`~/.local/share/deskbuddy/stt` (`whisper-cli`, `src/`, `models/ggml-small-q8_0.bin` and `ggml-base-q8_0.bin`,
checksums matched Hugging Face's). Rebuild: `cmake -B build -G Ninja -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release`
then `cmake --build build --target whisper-cli` in `src/`, and copy `build/bin/whisper-cli` up a level.

Dictation on the phone: whisper.cpp was built in Termux (armv7 NEON) and the build tools were removed
afterwards; `~/stt/whisper-cli` needs only Termux's libc++. Models: `~/stt/models/ggml-base-q8_0.bin` and
`ggml-tiny-q8_0.bin` (8-bit; this chip has no fp16 maths, so they're faster than the originals).

## Connections and reboots (Wi-Fi only, no adb, no cable)
Everything runs over the home Wi-Fi: the laptop keeps one `ssh -R 8765` tunnel open to Termux (port 8022); the
phone's face page (served from Termux on 127.0.0.1:8080) reaches the bridge through it. Stats, music, typing,
settings, alerts and dictation all use that one tunnel. The face page itself, timers and clock work without it.
- **Phone key pinning:** the bridge pins the phone's ssh host key in `~/.config/deskbuddy/known_hosts` (alias
  `chip-phone`). If the phone's IP changes, the bridge scans the /24 for port 8022 and accepts only the host with
  that key, then saves the new IP. If Termux is ever reinstalled, delete that file so the key is pinned again.
- **After a laptop reboot:** nothing to do. `deskbuddy-bridge` is a systemd user service with linger (set up by
  `laptop/install.sh`), so it starts at boot and the tunnel comes back within a minute.
- **After a phone reboot:** Termux:Boot starts sshd and the server, the tunnel reconnects by itself; open the Chip
  app (kiFOSSk). On the phone keep Termux, Termux:Boot and kiFOSSk on "Unrestricted" battery use (Android Go
  otherwise kills them).
- Something wrong? `python3 -I laptop/doctor.py`; the dashboard's status line also says why Chip is offline.
