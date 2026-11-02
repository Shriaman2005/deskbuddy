# Chip (desk buddy) — brief for Claude

Retired Samsung M01 Core (Android Go, weak CPU) shows "Chip" in the kiFOSSk kiosk WebView; the laptop runs a
bridge. README.md has the full feature list: read only the section you need.
Cross-platform port, Stage 1 (Windows/macOS laptops over the same Termux + ssh design, no installers):
`docs/port/PLAN.md` (Status = progress; read only Overview, Rules and your task's section); PROMPTS.md is for the
user. Stage 2 (Android app + installers) waits in `docs/port/later/`: don't start it unless asked.

## Layout
- `phone/www/` — the face page (http://127.0.0.1:8080 on the phone)
  - `buddy.js` (1300 lines: prefs, screens, timer/pomodoro, attention, dock; grep for the function you need,
    don't read it whole), `buddy.css`, `config.js`
  - `pack.json` ("chip-pack/2", ~300 KB: never open it whole, use jq) holds all of Chip's art and motion, from the
    user's Claude Design (project 694b6073-5a87-491b-8bb4-c9897ff95882). `pack.js` derives the palette and bakes
    sprites, `player.js` draws the rig (stepped 12 fps), `chip.js` is the state machine fed by #app data-*/classes,
    #face m-* mood classes and chip:react / chip:notify events. Follow the pack; don't invent visuals.
- `phone/*.py` — Termux side: server.py, alert.py (torch/sounds), dictation.py
- `laptop/bridge.py` — systemd user service `deskbuddy-bridge`, 127.0.0.1:8765, ssh -R tunnel to the phone
  (PhoneLink: pinned key in ~/.config/deskbuddy/known_hosts under alias chip-phone, `/link` = its state with a `reason`).
  Settings schema = DEFAULTS/RANGES/CHOICES/APP_RULES; stored in ~/.config/deskbuddy/settings.json
  Link settings: linkPaused, linkAutoFind, linkHomeOnly, linkNetworks, linkKeepAlive, linkRetry, sshPort (LINK_KEYS).
- Connections card in `laptop/dashboard.html` (Reconnect, Find phone, Replace phone = pairing wizard, Forget, Doctor).
  README "Connections and reboots" describes it.
- `laptop/doctor.py` — checks the laptop, the Wi-Fi link (incl. paused, home network, key mismatch from `/link` reason) and Termux.
- `laptop/skin.js` — chip-skin/1: `check -` (JSON report with path/problem/fix per error), `prompt <basis>`,
  `example`; the bridge runs it as a subprocess for /skins/*. Reuses pack.js (eyeLook, pupilFit), so it checks what
  the phone draws; `python3 -I laptop/test_skins.py` tests it. `laptop/merge_pack.js <delta>` merges a pack delta.
  Skins live in ~/.config/deskbuddy/skins/ (<id>.json, _draft.json). Settings eyeStyle, pupilSize, skin.
  A skin's "name" is what Chip calls itself ("Hi! I'm …"), set at install / renamed on the dashboard
  (/skins/install {name}, /skins/<id>/rename). Optional "headphones" slot (128x72, symmetric, anchor on the middle column).
- Borrowed headphones: GET /skins/<id>/headphones.json = chip-phones/1 (that skin's headphones sprite + its mirror chain + the
  colours they use); ChipPack.setPhones lays it over base + skin under "phones:<id>:"; chip.js reads #app data-phones
  ("skin" | "chip" | "id:<id>@<seq>", file in window.ChipPhones); buddy.js picks it from phonesFollowSkin/phonesDefault
  (cached as phones.<id>), preview `&phones=skin|chip|<id>`.
- `design/headphones.js` draws the default headphones sprite (`--write` puts it in pack.json). Setting phonesGap
  (ear-cup gap) is applied in player.js by repeating/cutting the headphones' anchor column, so it works for skins too.
- `design/` — design deltas from Claude Design (e.g. pack-v2-delta.json) and their changelog; merged into
  pack.json with `laptop/merge_pack.js <delta> [pack] [out]` (additions only, refuses renames and removals).
- Skins: ~/.config/deskbuddy/skins/<id>.json (installed, made in the dashboard) and _draft.json (the last upload that
  passed the check); the phone keeps its own copy in localStorage under buddy.skin.<id>.
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
  `&accent=sage`, `&music`, `&gaze=x,y` pins the eyes' look, -1..1, no /gaze stream; `&eyes=classic|toon|button`,
  `&pupil=S|M|L`; `&skin=<id>` an installed skin, `&skin=draft` the last upload that passed the check, for
  previewing before installing).
- Phone: ssh port 8022 (Termux), `curl 127.0.0.1:8765/phone` = its state, `/link` = the tunnel. No adb anywhere
  in the project (removed on purpose): everything goes over the Wi-Fi ssh tunnel; don't add adb back.
  CPU budget: ~80% during scenes, ~7% per extra frame/s.

## Rules
- Dictation: never press Enter, never type while the laptop is locked, mic on only while holding, only the
  phone through the tunnel can trigger typing. Bridge rejects other origins/hosts.
- Dictation keys live only in `~/.config/deskbuddy/secrets.json` (stt.SECRETS_FILE): never in settings.json, never returned or logged. Settings: dictEngine, dictLang, dictProvider, dictCloudModel/Url, dictAzureRegion, dictModelLaptop.
- Link writes are dashboard-only: `/link/*` POSTs are refused (`Handler.dashboard_only`) and `/settings` silently drops LINK_KEYS (incl. sshPort) unless Origin is exactly `http://127.0.0.1:8765`. Never let the phone's page or a script change them.
- Pairing a new phone: only through the dashboard's Replace phone wizard (`/link/pair/*`, the user types the phone's code). Don't delete known_hosts by hand.
- Attention/notifications keep only the source app's name, never content. No webcam.
- Don't clear caches; don't touch GNOME Builder/Flatpak setups.
- Testing on the phone: undo what you started (e.g. reset a test focus timer so it doesn't count).
