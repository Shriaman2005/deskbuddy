# Chip (desk buddy) — brief for Claude

Retired Samsung M01 Core (Android Go, weak CPU) shows "Chip" in the kiFOSSk kiosk WebView; the laptop runs a
bridge. README.md has the full feature list: read only the section you need.

## Layout
- `phone/www/` — the face page (http://127.0.0.1:8080 on the phone)
  - `buddy.js` (1300 lines: prefs, screens, timer/pomodoro, attention, dock; grep for the function you need,
    don't read it whole), `buddy.css`, `config.js`
  - `pack.json` ("chip-pack/1", ~160 KB: never open it whole, use jq) holds all of Chip's art and motion, from the
    user's Claude Design (project 694b6073-5a87-491b-8bb4-c9897ff95882). `pack.js` derives the palette and bakes
    sprites, `player.js` draws the rig (stepped 12 fps), `chip.js` is the state machine fed by #app data-*/classes,
    #face m-* mood classes and chip:react / chip:notify events. Follow the pack; don't invent visuals.
- `phone/*.py` — Termux side: server.py, alert.py (torch/sounds), dictation.py
- `laptop/bridge.py` — systemd user service `deskbuddy-bridge`, 127.0.0.1:8765, ssh -R tunnel to the phone.
  Settings schema = DEFAULTS/RANGES/CHOICES/APP_RULES; stored in ~/.config/deskbuddy/settings.json
- `laptop/dashboard.html` — served at http://127.0.0.1:8765/ (cards built with sw/range/choice/section)
- `laptop/gnome-extension/chip-gaze@deskbuddy/` — GNOME Shell extension, session bus org.deskbuddy.Gaze: the pointer position for Chip's eyes (install.sh links it; needs a login)
- New setting = DEFAULTS (+RANGES/CHOICES) in bridge.py, DEFAULT_PREFS + applyPrefs in buddy.js, a row in
  dashboard.html.

## Commands
- Deploy to phone: `./deploy.sh` (page reloads itself within a minute; to force it, close and reopen the
  kiFOSSk app on the phone). After bridge.py edits: `systemctl --user restart deskbuddy-bridge`.
  Links broken? `python3 -I laptop/doctor.py`.
- Syntax check: `node laptop/check_pack.js`, `node laptop/check_budget.js` (peak moving/rotated layers, needs the bridge), `node -e 'new Function(require("fs").readFileSync("phone/www/player.js","utf8"))'`,
  `python3 -m py_compile laptop/bridge.py`
- Preview without the phone: headless Chrome at 1480x720 on
  `http://127.0.0.1:8765/preview/index.html?screen=0&typing` (also `mood=focus`, `&sceneT=`, `&wpm=`, `&idle=`,
  `&accent=sage`, `&music`, `&gaze=x,y` pins the eyes' look, -1..1).
- Phone: ssh port 8022 (Termux), `curl 127.0.0.1:8765/phone` = its state, `/link` = the tunnel. No adb anywhere
  in the project (removed on purpose): everything goes over the Wi-Fi ssh tunnel; don't add adb back.
  CPU budget: ~80% during scenes, ~7% per extra frame/s.

## Rules
- Dictation: never press Enter, never type while the laptop is locked, mic on only while holding, only the
  phone through the tunnel can trigger typing. Bridge rejects other origins/hosts.
- Attention/notifications keep only the source app's name, never content. No webcam.
- Don't clear caches; don't touch GNOME Builder/Flatpak setups.
- Testing on the phone: undo what you started (e.g. reset a test focus timer so it doesn't count).
