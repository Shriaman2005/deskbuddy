# Desk buddy

The old Samsung Galaxy M01 Core (SM-M013F) as an animated desk companion for this laptop.

## On the phone
- **Face** (home screen, via kiFOSSk): blinks, looks around, reacts.
  - Pixel look (the only look): `phone/www/chip.js` plays `pack.json` (all art and motion) on a 320×180 canvas scaled up with whole-number crisp pixels,
    plus the VT323 pixel font, notched pixel borders and CRT scanlines.
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
  - Chip's two scenes are from the Claude Design project "Robot Focus" / "Robot Typing", now carried by
    `pack.json` (pixel art, in the accent colour):
    - Focus mode, while a focus session runs (dashboard > Timer & Pomodoro > "Focus mode on the face screen"):
      the room dims, a moon comes up and Chip types away on a laptop; it gets into flow (closer camera) while you
      type fast, and notifications that arrive meanwhile pop up as muted bubbles. It lets go when the session ends.
    - Typing along, once you've been typing on the laptop for 10 s (dashboard > Face screen > "Chip types along
      with you", 3–60 s): Chip boots up a laptop of its own and types at your pace, thinks when you pause for 2 s,
      gets an idea when you carry on, bursts into sparks above 60 wpm, hits a big Enter when you stop (8 s
      without a key) and powers down. The bridge only counts key presses (the USB keyboard's transfer count in
      /sys/bus/usb/devices/*/urbnum, the built-in keyboard's interrupts), never which keys.
    - Previews: `?typing` or `?mood=focus`, plus `&wpm=90`, `&idle=3`, `&sceneT=<seconds into the design>`,
      `&accent=sage`.
    - Cost on the phone: ~80% of a core for kiFOSSk during a scene (8 fps while a section loops, 12 for the
      moves; the canvas is drawn at the design's grid size and scaled up by CSS).
  - Accent colour (dashboard > Look): cyan, terracotta, sage, violet, rose, amber, sky, or any colour from the
    picker (the pack derives its whole palette from one accent). It colours Chip's eyes and glow, the scenes and
    the dashboard itself.
  - Chip's character (dashboard): idle animations on/off, how often (rarely/normal/often) and which of the pack's
    14 idle clips may play (the last three only while you're away).
  - Rotates with the phone (kiFOSSk orientation: Auto-rotate); every screen has a portrait layout.
  - swipe up: apps (Brave, Termux, Files, Settings, All apps) and toggles (sounds, talking,
    dictation speed, visualizer, reload)
  - **Dictation:** hold Chip's face with two fingers, speak, let go: the text is typed wherever the cursor is on
    the laptop (`laptop/typer.py`, GNOME's remote-desktop D-Bus API). Slide a finger away before letting go to
    cancel. Never presses Enter, won't type while the laptop is locked, and the mic is only open while you hold.
    One finger can't be used: kiFOSSk grabs that long-press.
    - **Engine** ("Speech model runs on" on the dashboard, or 📱/💻/☁️ in the swipe-up drawer), `dictEngine`:
      **Phone** runs whisper.cpp on the phone, fully offline (`phone/dictation.py`, binary and models in `~/stt`
      in Termux). **Laptop** sends the clip through the ssh tunnel to the bridge's `POST /transcribe`, which runs
      whisper.cpp (`laptop/stt.py`, models in `~/.local/share/deskbuddy/stt`; the clip only touches RAM).
      **Cloud** does the same through a provider API: `dictProvider` (Groq by default, or OpenAI, Deepgram,
      ElevenLabs, AssemblyAI, Google, Azure, Gemini, or a custom URL), with `dictCloudModel`, `dictCloudUrl`
      and `dictAzureRegion` for the details.
    - **Language** (`dictLang`): one setting for every engine: Hinglish (romanised, the default), auto-detect,
      or a Whisper language code. An engine that doesn't support the language is flagged on the dashboard.
    - **Fast mode** (drawer "⚡ Fast dictation", `fastDictation`): a smaller model. Phone ~3 s, laptop under 1 s
      for a 4 s sentence, but weaker with Hinglish. The default is ~6 s on the phone.
    - **No fallback:** if the chosen engine fails, nothing is typed and Chip's bubble says why (for example
      "can't reach the speech engine", "no cloud key yet", "timeout").
    - **Cloud keys** are entered on the dashboard and stored only in `~/.config/deskbuddy/secrets.json` (owner-only).
      They are never sent to the phone, never returned or logged; the dashboard shows just the last 4 characters.
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
  brightness) and Chip's sleep time, with a live preview of the face. Changes save instantly
  (`~/.config/deskbuddy/settings.json`) and reach the phone on its next poll (~3 s); the drawer toggles on
  the phone write back to the same settings. Served by the bridge, so `deskbuddy-bridge` must be running.
- `systemctl --user start deskbuddy-bridge` — laptop stats, media and volume controls for the
  phone (ssh tunnel to Termux on the phone, port 8765, localhost only).
- `ssh -p 8022 <phone-ip>` — Termux shell (key login only). Phone IP: `~/.config/deskbuddy/state.json`.
- `python3 -I laptop/doctor.py` — checks every link (bridge, Wi-Fi tunnel, Termux services, face page) and says
  what to do about any that are down.
- Edit `phone/www/*` (location and fallback defaults in `phone/www/config.js`), then `./deploy.sh`; the face reloads itself.

## Eyes follow the cursor
Chip's eyes can follow the laptop's mouse pointer across all monitors. Off by default.
- Turn it on in the dashboard's **Eyes follow the cursor** card. The card also shows your monitors and where the
  phone sits; drag Chip's phone to where the phone really is. The spot is saved per monitor setup, so each
  arrangement (say, with and without the HDMI screen) remembers its own spot.
- Wayland doesn't let apps read the pointer, so a small GNOME Shell extension
  (`laptop/gnome-extension/chip-gaze@deskbuddy`) provides it. `laptop/install.sh` links it; GNOME loads it at
  login, so **log out and back in once** after the first install. `python3 -I laptop/doctor.py` says if it's
  missing, disabled or waiting for that login.
- Privacy: the extension reads only the pointer position, and only while the bridge is asking (a phone is
  connected, the setting is on and the screen is unlocked). Nothing is logged or sent anywhere except to the
  bridge on this laptop, and the only thing stored is the phone's spot in `~/.config/deskbuddy/gaze.json`.

## Eye styles
Chip's eyes come in three styles from its pack (`phone/www/pack.json`, `eyes.styles`): **Classic** (its own scanline
eyes), **Toon** (big bright eyes with an accent-coloured iris) and **Button** (round accent eyes with a big black pupil).
- Pick one in the dashboard's **Eyes follow the cursor** card, where a live preview shows it looking around. The
  setting is `eyeStyle` (empty = the pack's default, Classic).
- The pupil is S, M or L (`pupilSize`, default M). Only styles that offer a size show the choice.
- The pupil follows the cursor: it moves inside its box, converges a little when the pointer is near the phone,
  and returns to the centre after a while without movement.
- While a custom skin is on, its own eye style replaces these and the card says so.

## Make your own Chip
A skin changes Chip's art only: its eyes, mouth, and the face plate and ears, plus its accent and colours.
Animation, moods and timing stay Chip's. You make it with any AI chat (ChatGPT, Gemini, Claude…), and the dashboard's
**Make your own Chip** card checks the result before Chip uses it.
1. **Get the prompt.** Pick what it's based on (my pet, me, a character or theme, my concept art, or just an idea).
   Copy the prompt and paste it into the chat, and attach your pictures there. Your photos go only to that chatbot.
2. **Upload the result.** Save the JSON the chat gives you and pick the file, or paste it into the box.
3. **Read the result.** A skin that fails lists each problem with its path (`$.sprites.eyeL.frames.open`), what is
   wrong and how to fix it. **Copy message for your AI** copies a ready reply: paste it into the same chat, and it
   fixes exactly those problems and sends the whole file again. A skin that passes shows a live preview, and
   **Use on Chip** installs it and switches it on. The phone picks it up within a minute.
- Your skins are listed below, with **Use** and **Delete** (Delete asks first, inside the card). **Back to Chip's
  own look** switches the skin off.
- A skin is one JSON file under 600 KB (`chip-skin/1`). Only that file reaches the laptop, never the pictures.
  The phone keeps a copy of the skin it is using, so it still shows it when the laptop is away.
- Checks and previews run on the laptop: `laptop/skin.js` (`check`, `prompt`, `example`), `laptop/test_skins.py`
  tests it. Installed skins are stored in `~/.config/deskbuddy/skins/`.

## Pieces
| Where | What |
|---|---|
| `phone/www/` | the face and screens (HTML/CSS/JS) |
| `phone/server.py` | Termux server on the phone's 127.0.0.1:8080: page, brightness, speech, app launching, dictation |
| `phone/dictation.py` | records the mic (PulseAudio's Android source); transcribes on the phone (`~/stt/whisper-cli`) or sends the clip to the bridge, per the dashboard's engine; no fallback |
| `laptop/typer.py` | types text into the focused window (used by the bridge's `POST /type`); non-ASCII goes through the clipboard, never Enter |
| `phone/alert.py` | torch blinking, the flashlight and the alert sounds (`/api/alert`, `/api/torch` on the phone server) |
| `laptop/attention.py` | agent hooks call it when an AI agent needs you; tells the bridge (`POST /attention`) |
| `phone/services.sh`, `phone/supervisor.sh` | Termux:Boot (or any new Termux session) starts them; the supervisor restarts sshd and the server within 10 s if they die |
| `laptop/doctor.py`, `laptop/install.sh` | link health check; (re)installs the bridge as a boot-time systemd user service |
| `laptop/bridge.py` | `deskbuddy-bridge.service`: stats/media API, Wi-Fi ssh tunnel (finds the phone again if its IP changes), settings and the dashboard, dictation transcription (`POST /transcribe`, `/stt/*`, via `laptop/stt.py`) |
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
- **Connections card (dashboard):** shows whether the tunnel is up, the phone's address, why it's down, and
  buttons: Reconnect, Find phone, Replace phone (pairing wizard), Forget this phone, and Doctor (runs doctor.py).
- **Link settings:** `linkPaused` (close the tunnel and stop looking), `linkAutoFind` (scan the Wi-Fi /24 when the
  saved address stops answering), `linkHomeOnly` + `linkNetworks` (only scan or connect on the listed network
  names; "wired" = a cable), `linkKeepAlive` and `linkRetry` (seconds), and `sshPort` (sshd's port in Termux, 8022).
  They are set on the dashboard only: `/link/*` writes are refused unless the request's Origin is exactly
  `http://127.0.0.1:8765`, and link keys sent from any other origin are ignored. So the phone's page and other
  sites can't pause or redirect the link.
- **Phone key pinning:** the bridge pins the phone's ssh host key under the alias `chip-phone` in
  `~/.config/deskbuddy/known_hosts`. If the phone's IP changes, the bridge scans the /24 for `sshPort` and accepts
  only the host that presents that key, then saves the new IP.
- **Pairing a new phone** (or after Termux is reinstalled): dashboard, Connections, Replace phone. The laptop shows a
  one-time download for 10 minutes; the new phone runs the pairing script from Termux and shows a code, and you
  type that code on the laptop. Nothing is trusted before that. Don't edit known_hosts by hand.
- **Reason field:** `curl 127.0.0.1:8765/link` gives `reason`: `paused`, `not home network`, `no key pinned`,
  `key mismatch` (something answers at the phone's address with another key), `connecting`, `not found`, or null
  when up. `doctor.py` checks the first three of these.
- **After a laptop reboot:** nothing to do. `deskbuddy-bridge` is a systemd user service with linger (set up by
  `laptop/install.sh`), so it starts at boot and the tunnel comes back within a minute.
- **After a phone reboot:** Termux:Boot starts sshd and the server, the tunnel reconnects by itself; open the Chip
  app (kiFOSSk). On the phone keep Termux, Termux:Boot and kiFOSSk on "Unrestricted" battery use (Android Go
  otherwise kills them).
- Something wrong? `python3 -I laptop/doctor.py`; the dashboard's status line also says why Chip is offline.
