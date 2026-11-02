# Stage 1: Chip on Windows and macOS, over the existing Termux + ssh design

How to use this file: a session reads **Overview**, **Rules** and its own task section only
(`grep -n '^## ' docs/port/PLAN.md`, then `sed -n` those lines). **Status** is the record of what is done.
The prompts are in `docs/port/PROMPTS.md` (for the user). Stage 2 (Android app + installers) waits in `docs/port/later/`.

## Status
Tick a line when its task is committed: `- [x] S1 Platform layer — 2026-11-05 a1b2c3d: notes, follow-ups`.
- [x] S0 Repo prep — 2026-11-02: MIT LICENSE (copyright "Aman"); history scan clean, no key formats or secret files ever committed
- [x] S1 Platform layer + selftest — 2026-11-02 24d45e8: Linux shapes unchanged (+ /stats caps, GET /caps); follow-ups: stubs answer locked()=None so /type and /transcribe say "locked" on Windows/macOS until S5/S6; doctor.py checks are still Linux-only; phone page with the caps hiding not deployed yet (no effect on Linux)
- [x] S2 Link, pairing and deploy on every OS (+ fake phone) — 2026-11-03 HASH: PhoneLink/Pairing moved to link.py
  (bridge.py −600 lines), sshlink.py, deploy.py (+ auto-sync, .chip-hash), doctor per OS, tests/test_link.py (29 checks,
  fake phone) pass; real link + doctor + ./deploy.sh OK. Follow-ups: install.py must call sshlink.ensure_own_key() (S5/S6)
  and set HKCU Run "Chip" / LaunchAgent org.deskbuddy.bridge (names doctor checks); rediscovery test skips on macOS (no
  127.0.0.2); Windows/macOS Wi-Fi parsing is untested on real machines (S4 CI, friends); localized netsh "Open" is a word list
- [ ] S3 Phone side for any Android phone
- [ ] S4 CI on Linux, Windows, macOS
- [ ] S5 Windows backend + install.py
- [ ] S6 macOS backend + install.py
- [ ] S7 AI-agent hooks card
- [ ] R1 Review → merge port → main
- [ ] S8 Docs and friend test kit → tag v0.1.0-beta.1, friends test
- [ ] F  Friend-test fixes (one line per round)

## Overview
Decided 2026-11-02: the Android app and real installers (Stage 2) wait. Stage 1 keeps today's design on every OS.
- **Laptop (Linux, Windows 10/11, macOS 14+):** the bridge runs from the Chip folder with the user's own Python 3.12+
  (python.org). Install = get the folder (git clone or GitHub's "Download ZIP") and run `laptop/install.py` once: a venv
  with psutil (Windows/macOS), the Chip ssh key, start at login (Windows: HKCU Run → supervise.py; macOS: a
  LaunchAgent; Linux: the existing install.sh), then the dashboard opens. No .exe, .pkg or .dmg, no signing.
  Settings and data stay in `~/.config/deskbuddy` and `~/.local/share/deskbuddy` on every OS.
- **Link:** unchanged. The laptop's ssh (built into Windows 10+ and macOS) keeps `ssh -R 8765` open to Termux's sshd
  (port 8022), with the phone's host key pinned; the bridge listens on 127.0.0.1 only. The pairing download (8766,
  10 minutes) is the only LAN listener. One phone ↔ one laptop at a time (pairing replaces both sides' keys).
- **Phone (any Android with Termux):** Termux + Termux:API from F-Droid (same source for both), set up by the dashboard's
  pairing command. The face is http://127.0.0.1:8080, either installed from Chrome as a web app (personal phone,
  temporary: open Termux to start, Exit in its notification to stop) or in kiFOSSk (a dedicated always-on phone, as now).
- **First features on Windows/macOS:** PC stats (CPU, RAM, battery, network, uptime); dictation (phone engine offline
  with the optional phone speech installer, cloud engine, laptop engine when a whisper-cli binary is found) typed into
  the focused window; AI-agent alerts that know about idle and lock. All phone-side features work.
- **Not yet on Windows/macOS:** other apps' notifications, music card/visualizer, typing along, eyes following the
  cursor, GPU/temperatures, "home Wi-Fi only" where the OS hides the Wi-Fi name.
- The user has no Windows or Mac: CI (S4) proves what it can, including the tunnel against a fake phone; friends test
  the rest.

## Rules
- Work on branch `port`, never on main. Commit at the end of the task: "Sn: <summary>". Push, tag or merge only when
  the user's prompt says so.
- Read only what you need: Overview, Rules, your section. Grep big files (bridge.py, buddy.js, dashboard.html,
  pack.json); never read them whole.
- Linux must keep working exactly as now. Before committing run `python3 -m py_compile laptop/*.py phone/*.py`,
  `node laptop/check_pack.js`, `python3 -I laptop/test_skins.py`, and from S1 on `python3 -I laptop/selftest.py`.
  If the bridge changed: `systemctl --user restart deskbuddy-bridge`, then `python3 -I laptop/doctor.py`.
- All CLAUDE.md rules still hold: pinned phone key, link writes dashboard-only, typing only through the tunnel, never
  Enter, never while locked, dictation keys only in secrets.json, notifications keep app names only, no adb. Loosen none.
- Runtime dependencies: Linux none new; Windows/macOS only psutil (pinned in `laptop/requirements.txt`). Test-only
  packages go in a venv in the scratchpad (locally) or the CI job, never system-wide.
- Every subprocess goes through one helper (no console windows on Windows, UTF-8 text). Python runs with `-I -X utf8`.
- New code goes in new modules; bridge.py should shrink, not grow.
- Ask the user before installing system packages, editing files outside the repo (e.g. ~/.claude/settings.json) or
  running anything on a phone.
- End of task: tick your Status line (date, short hash, follow-ups), update the CLAUDE.md lines that changed (keep it
  short), commit.

## S0 Repo prep
- `git switch -c port` (it carries the uncommitted docs/port/ files and the CLAUDE.md pointer).
- `.gitignore`: `__pycache__/`, `*.pyc`, `.venv/`, `dist/`, `build/`, `.idea/`. `git rm -r --cached` the tracked
  `__pycache__` files.
- Secret scan of all history: grep `git log -p --all` for key-like strings (`sk-`, `gsk_`, `AIza`, `api[_-]?key`,
  `secret`, `token`, `password`, `BEGIN .*PRIVATE KEY`) and `git log --all --name-only` for settings.json,
  secrets.json, known_hosts, state.json, `*.pem`. Report what you find; don't rewrite history.
- Ask the user for the licence (MIT is simplest; GPL-3.0 if forks must stay open), add LICENSE.
- Done when branch `port` has one commit with .gitignore, LICENSE, docs/port/ and the CLAUDE.md pointer, and the user
  has the scan result (the repo can go public only if it is clean).

## S1 Platform layer + selftest
Goal: every OS-specific call sits behind `laptop/platforms/`; Linux behaves exactly as today.
- `platforms/paths.py`: CONFIG_DIR = `~/.config/deskbuddy`, DATA_DIR = `~/.local/share/deskbuddy` on every OS, with
  env overrides `CHIP_CONFIG_DIR` / `CHIP_DATA_DIR` (tests). Every file path in laptop/*.py comes from here.
- `platforms/proc.py`: the one subprocess helper (run, Popen): `CREATE_NO_WINDOW` on Windows, UTF-8, timeouts.
- `platforms/__init__.py` picks `linux.py` / `windows.py` / `macos.py` by sys.platform and exposes `CAPS` (bools:
  stats, gpu, temps, battery, idle, locked, typing, media, nowPlaying, volume, notifications, visualizer, typingRate,
  gaze, wifiName, termuxLink (= ssh found), skins (= node found), laptopStt (= whisper-cli found)) and a small function
  set derived from today's code (stats sample, idle_ms, locked, type_text, media status/control, volume,
  start_watchers for notifications/typing rate/gaze, network info). Its docstring lists the /stats keys; missing
  values are None.
- `linux.py`: today's code moved, not rewritten (typer.py stays and is imported). `windows.py` and `macos.py`: stubs
  with CAPS false (S5/S6 fill them); they must import cleanly on every OS.
- CAPS reach the phone page (in /stats) and the dashboard (`GET /caps`); both hide what is missing (GPU ring, music
  card, visualizer, typing along, eyes, notification switches) with "Linux only for now". `CHIP_FAKE_CAPS=gpu=0,media=0`
  fakes missing caps so this can be tested on Linux.
- `laptop/selftest.py`: runs the bridge on free ports with temp CHIP_CONFIG_DIR/CHIP_DATA_DIR, checks the main GET
  routes return the documented keys and CAPS is sane; prints JSON; exit 1 on failure. It must pass without GNOME/D-Bus
  (CI), reporting those caps as false.
- Checks: before changing anything, save the JSON key sets of /stats, /settings, /link, /phone and /stt/status from
  the running bridge to the scratchpad; afterwards restart the bridge and diff (values may differ; keys and shapes must
  not). Then ask the user to try one dictation and one dashboard alert test on the phone.

## S2 Link, pairing and deploy on every OS
Goal: PhoneLink, pairing, deploy and doctor work on Windows and macOS with the same pinning as on Linux.
- Network info: Linux keeps `ip`/nmcli; Windows/macOS use psutil (first private IPv4 that isn't a VM/VPN adapter,
  its netmask; sweep never more than a /24 as now).
- Wi-Fi name: Windows `netsh wlan show interfaces`, macOS `ipconfig getsummary <iface>`. Both may hide it (location
  permission): then caps.wifiName is false and the dashboard greys "home Wi-Fi only" with a one-line reason; nothing else changes.
- ssh arguments that work everywhere: `GlobalKnownHostsFile` = an empty file in CONFIG_DIR (not /dev/null); paths in
  `-o` values with forward slashes and quoted (user names with spaces); ssh, ssh-keygen and ssh-keyscan found on PATH
  or in `%WINDIR%\System32\OpenSSH`; if missing, doctor says how to add Windows' "OpenSSH Client" optional feature.
- Chip's own key: if `CONFIG_DIR/id_ed25519` exists, the tunnel, deploy and doctor use only it (`-i`,
  `IdentitiesOnly=yes`) and pairing hands out its .pub; otherwise today's behaviour (the first `ssh -G` identity).
  install.py creates it (from Python, never PowerShell: PowerShell 5 drops empty `-N ""` arguments) only when no phone
  is pinned yet, so the user's working Linux link is never broken.
- `laptop/deploy.py` replaces deploy.sh's logic (tar built in Python, piped over the same pinned ssh); deploy.sh
  becomes a two-line wrapper. Pairing calls deploy.py. The bridge also syncs the phone's files by itself: when the tunnel
  comes up and the phone's stored hash of phone/ differs from the laptop's, deploy once and show "Phone files:
  up to date / updating / failed" on the Connections card.
- doctor.py per OS: Linux as now; Windows: bridge answering, HKCU Run entry, ssh found, key present; macOS: bridge
  answering, LaunchAgent loaded, ssh, key, Accessibility (S6 fills it). Same output format.
- Pairing download server on Windows/macOS: before it starts, the dashboard says "Your computer may ask to allow
  Python on the network: allow it (private networks)".
- Fake phone for tests: `laptop/tests/fake_phone.py` (asyncssh, test-only) = an ssh server on 127.0.0.1 with a fixed
  host key that accepts one client key, supports `-R` and runs the commands deploy/doctor send (tar into a temp dir).
  Env `CHIP_TUNNEL_REMOTE_PORT` lets tests forward to another port than 8765. Tests (`laptop/tests/test_link.py`):
  the tunnel comes up and reaches the bridge; a different host key is refused; rediscovery finds the phone on a new
  address only with the pinned key; deploy lands the files; auto-sync deploys once per change.
- Done when the tests pass on Linux, the real link to the user's phone still works (restart the bridge, run doctor),
  and `./deploy.sh` still works.

## S3 Phone side for any Android phone
Goal: a fresh phone can be set up from the dashboard in a few steps, and a personal phone can run Chip temporarily.
- setup.sh on a fresh phone: also install pulseaudio (alert sounds and the mic need it), check Termux:API answers
  (`termux-battery-status`), and tell the user which permissions to grant (microphone, "Modify system settings" only
  if they want brightness control). Termux:Boot and kiFOSSk are optional (always-on phone only).
- `chip-start` / `chip-stop` commands in Termux (start services; stop supervisor, server and sshd and release the wake
  lock). Termux's notification Exit also stops everything.
- server.py: open apps with generic intents (settings, files, home) instead of Samsung-only components. In a browser
  (not kiFOSSk) the drawer hides app launching (Android blocks launches from Termux in the background).
- Web app: `manifest.webmanifest` (name Chip, display fullscreen, icons rendered from Chip's face in pack.json at
  192/512 px with whole-number scaling, no new art), Screen Wake Lock while visible (feature-detected; kiFOSSk doesn't
  need it), and a minimal service worker only if Chrome needs one to offer "Install app". It must cache nothing:
  deploy relies on reloads.
- Dashboard "Personal phone" switch (Connections card): no brightness control, so the phone's own screen settings stay
  as they are. Pairing wizard text: F-Droid links for Termux and Termux:API (same source for both), then "open
  http://127.0.0.1:8080 in Chrome → Install app".
- Optional offline phone speech: `phone/stt-setup.sh` builds a pinned whisper.cpp tag in Termux and downloads
  ggml-base-q8_0 and ggml-tiny-q8_0 with pinned SHA-256 into `~/stt` (where dictation.py looks), then removes the build
  tools. Pins: the laptop's base model file, and the M01's tiny model (ask before running sha256sum there).
- Check on a modern phone (Android 12+) whether Android kills Termux's processes during a scene or a phone-side
  dictation ("signal 9"). If it does, the docs need the Developer-options switch (Android 14+: disable child process
  restrictions).
- Done when (the user, on their personal phone with a fresh Termux): pairing from the dashboard works, the face runs as
  an installed web app and keeps the screen on, alert sounds and dictation work, chip-stop stops everything. Then
  re-pair the M01 Core (one phone at a time).

## S4 CI on Linux, Windows, macOS
- `.github/workflows/ci.yml` (push to port/main and PRs; `permissions: contents: read`; cancel superseded runs;
  actions pinned to full commit SHAs, with the version in a comment):
  - linux: py_compile, check_pack.js, test_skins.py, selftest, tests/test_link.py with the fake phone.
  - windows and macos (latest runners, Python 3.12): `pip install -r laptop/requirements.txt asyncssh`, py_compile,
    selftest, tests/test_link.py (the real Windows/macOS ssh client against the fake phone).
- S5 and S6 add their install, typing and ctypes steps to these jobs.
- Push only when the user's prompt allows it; watch with `gh run watch`; fix until green. If a runner can't do a step,
  write down which step and why.

## S5 Windows backend + install.py
- `platforms/windows.py`, ctypes + psutil only:
  - stats: CPU %, RAM, battery (percent, charging, time left), network rates, uptime; gpu/temps None.
  - idle_ms: GetLastInputInfo. locked: OpenInputDesktop + SwitchDesktop fail while the screen is locked.
  - type_text: SendInput with KEYEVENTF_UNICODE per UTF-16 unit (surrogate pairs as two), key down + up, in small
    batches; \n and \t become spaces; refuse while locked; never Enter. Test `ctypes.sizeof(INPUT) == 40` on x64.
    Admin windows ignore it (UIPI): say so in the error and the docs.
  - Bind 127.0.0.1:8765 with SO_EXCLUSIVEADDRUSE instead of SO_REUSEADDR (otherwise another program can take the port).
- `laptop/install.py` (Windows part): find Python ≥ 3.12 (`py -3`), refuse the Microsoft Store Python with a pointer to
  python.org; venv at DATA_DIR/venv with `laptop/requirements.txt`; create the Chip key (S2 rule); HKCU Run entry →
  `venv\Scripts\pythonw.exe -I -X utf8 <repo>\laptop\supervise.py`; start it now; wait for the bridge; open the
  dashboard. Flags: `--uninstall` (remove the Run entry, stop Chip, keep settings), `--ci` (no prompts, no browser).
- `laptop/supervise.py`: runs bridge.py, restarts it within 5 s if it exits, exits if a Chip bridge already answers
  on 8765, writes the log to DATA_DIR/bridge.log (rotated).
- stt: find whisper-cli.exe in DATA_DIR/stt or on PATH (caps.laptopStt); no downloader in Stage 1.
- CI windows job: `install.py --ci`, the bridge answers /stats, selftest caps (stats, idle, locked, typing true), a typing
  test (start Notepad, focus it, type "héllo wörld नमस्ते 😀 a\nb", copy it back with Ctrl+A/Ctrl+C/Get-Clipboard, expect
  "héllo wörld नमस्ते 😀 a b"; continue-on-error with a note if the runner has no usable desktop), `install.py --uninstall`.

## S6 macOS backend + install.py
- `platforms/macos.py`, ctypes + psutil only (no PyObjC):
  - stats as in S5; gpu/temps None.
  - idle_ms: CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType).
  - locked: CGSessionCopyCurrentDictionary → "CGSSessionScreenIsLocked" (CoreFoundation via ctypes; release what you copy).
  - type_text: CGEventCreateKeyboardEvent + CGEventKeyboardSetUnicodeString, ≤20 UTF-16 units per event, down + up,
    CGEventPost(kCGHIDEventTap); \n and \t become spaces; never Enter; refuse while locked. First
    AXIsProcessTrustedWithOptions with the prompt; if not trusted, fail with "Allow Python in System Settings →
    Privacy & Security → Accessibility, then try again" (the phone shows it in Chip's bubble).
- `laptop/install.py` (macOS part): Python ≥ 3.12 (else point to python.org; the Xcode python3 is too old); venv as on
  Windows; test an HTTPS request and, if certificates fail, run that Python's "Install Certificates.command"; create
  the Chip key; LaunchAgent `~/Library/LaunchAgents/org.deskbuddy.bridge.plist` (RunAtLoad, KeepAlive, PATH including
  /opt/homebrew/bin and /usr/local/bin, logs in ~/Library/Logs/deskbuddy-bridge.log) loaded with `launchctl bootstrap
  gui/<uid>`; open the dashboard; open the Accessibility pane and print exactly which Python to switch on. Flags
  `--uninstall`, `--ci`. Docs must say plainly: Accessibility goes to Python, so other background Python programs
  could type too (Stage 2's signed app fixes that).
- stt: find whisper-cli on PATH (`brew install whisper-cpp`) or in DATA_DIR/stt.
- CI macos job: `install.py --ci`, the bridge answers /stats, ctypes checks without permissions (create keyboard
  events, set and read back their unicode strings with CGEventKeyboardGetUnicodeString; idle_ms a number; locked a
  bool), `install.py --uninstall`. List what only the friend test can confirm.

## S7 AI-agent hooks card
- Dashboard card "AI agents" (every OS): per agent Installed / Not installed, Install, Remove, Test. Dashboard-only
  routes: GET /hooks, POST /hooks/install, POST /hooks/remove.
- Claude Code: ~/.claude/settings.json, hooks Notification and Stop. Gemini CLI: ~/.gemini/settings.json, hooks
  Notification and AfterAgent. opencode: the plugin file ~/.config/opencode/plugin/deskbuddy-attention.js.
- Command: `<python> -I <repo>/laptop/attention.py claude-code|gemini` with absolute paths (the venv's python on
  Windows/macOS, python3 on Linux). Find out how each agent runs hook commands on Windows (cmd, PowerShell or Git
  Bash) and use a form that works there, including paths with spaces.
- JSON edits: keep everything else intact, back up once to `<file>.chip-bak`, be idempotent (recognise existing Chip
  hooks, including the user's current `python3 -I …/attention.py` lines); Remove takes out only Chip's entries.
- Test with a temp HOME. Don't touch the real files without asking the user.

## R1 Review
Fresh session: `/code-review high port --fix`. Focus: pinning on every OS (ssh arguments, the dedicated key,
rediscovery, deploy), typing rules on Windows/macOS, install.py (file permissions, no secrets printed), the subprocess
helper, the hooks card's JSON edits. Rerun the Rules' checks and the fake-phone tests, tick, commit "R1: review fixes".
Then the user merges port → main.

## S8 Docs and friend test kit
- `INSTALL.md` (≤150 lines, plain words): laptop on Windows, macOS, Linux (install Python → get the folder → run
  install.py); phone as a personal phone (Termux + Termux:API from F-Droid → pairing → install the web app → start/stop)
  or an always-on phone (+ Termux:Boot, kiFOSSk). Troubleshooting: the firewall prompt during pairing, the Store
  Python, macOS certificates and Accessibility for Python, Termux and Termux:API from different sources, Android
  killing Termux (if S3 found it), Wi-Fi that hides devices from each other (use the phone's hotspot), one phone at a time.
- `docs/port/TESTING.md`: one checklist per OS (≤30 min, numbered, each step says what "pass" looks like): install,
  dashboard opens, pair a phone, stats roughly match Task Manager / Activity Monitor, dictation into Notepad / TextEdit
  (cloud or phone engine), refused while the screen is locked, AI alert Test button (plus a real Claude Code hook if they
  have it), log out and in → Chip starts by itself, `install.py --uninstall`. Then send the doctor output and screenshots
  of anything odd. Add a short message the user can send to friends (including: pairing replaces the phone's laptop
  key, so the phone's owner re-pairs at home afterwards).
- README: a short "Install" link. CLAUDE.md: layout lines for platforms/, tests/, install.py, supervise.py, deploy.py.
  Facts only from this plan and the code.

## F Friend-test fixes
One fresh session per report and platform, with the doctor output and the friend's notes pasted in. Diagnose from the
evidence and fix what is clear. Where the cause isn't clear, add a check to doctor.py or selftest so the next round
shows it; don't guess-fix. CI green, add a Status line for the round, commit "F<n>: <platform> fixes".

## Later
Stage 2 (`docs/port/later/`): the Chip Android app and real installers. Also: a laptop speech downloader on
Windows/macOS, music controls and now-playing, eyes following the cursor, other apps' notifications, typing along,
several paired phones at once.
