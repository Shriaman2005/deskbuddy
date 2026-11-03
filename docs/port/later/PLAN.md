# Stage 2 (later): the Chip Android app and real installers

> **Not active.** Start this only after Stage 1 (`docs/port/PLAN.md`: Windows/macOS over the existing Termux + ssh
> design) is done. Stage 1 already delivers this plan's T1 (platform layer; settings stay in `~/.config/deskbuddy`
> on every OS, so ignore the %APPDATA% paths below), most of T5 (CI), T6 and T7 (Windows/macOS backends) and T8
> (hooks card). When Stage 2 starts: tick those, re-read the code, trim the remaining tasks, and move this file to
> `docs/port/PLAN.md` (and Stage 1's to `docs/port/done/`).

How to use this file: a session reads **Overview**, **Rules** and its own task section only
(`grep -n '^## ' <this file>`, then `sed -n` those lines). **Status** is the record of what is done.
The prompts for each task are in `docs/port/later/PROMPTS.md` (for the user; sessions don't need to read it).

## Status
Tick a line when its task is committed: `- [x] T1 Platform layer — 2026-11-05 a1b2c3d: notes, follow-ups`.
- [ ] T0 Repo prep
- [ ] T1 Platform layer + selftest
- [ ] T2 App mode in the bridge (LAN HTTPS, pairing)
- [ ] R1 Review T1–T2
- [ ] T3 Android app: shell, pairing, pinned TLS
- [ ] T4 Android app: phone API, dictation, page tweaks
- [ ] R2 Review the Android app → M1: any Android phone + Linux laptop (merge port → main)
- [ ] T5 CI on Linux, Windows, macOS, Android
- [ ] T6 Windows backend
- [ ] T7 macOS backend
- [ ] T8 AI-agent hooks installer
- [ ] T9 Speech models and whisper binaries
- [ ] T10 Packaging and release pipeline
- [ ] R3 Pre-release review → M2: beta for friends (tag v0.1.0-beta.1)
- [ ] T11 Friend test kit
- [ ] T12 User docs
- [ ] F  Friend-test fixes (one line per round) → M3: v1.0

## Overview
Decided 2026-11-02.
- Two ways to run the phone side:
  - **App mode** (new; every OS; any Android 10+ phone, used for a while and then closed): the Chip Android app shows
    the face page, served by the laptop's bridge over Wi-Fi with HTTPS pinned to the bridge's own certificate and a
    per-phone token. The app answers the page's `/api/*` calls itself (torch, sounds, speech, brightness, battery,
    mic). Nothing runs on the phone once the app is closed.
  - **Termux mode** (existing; Linux; a dedicated always-on phone with Termux + kiFOSSk + the ssh tunnel): unchanged.
- First release on Windows and macOS: PC stats (CPU, RAM, battery, network, uptime); dictation (cloud, laptop
  whisper, Android speech on the phone) typed into the focused window; AI-agent alerts (Claude Code, Gemini CLI,
  opencode) aware of idle and lock. The face, timers, clock/weather, torch, sounds and talking are phone-side and
  work everywhere.
- Not in the first release on Windows/macOS: other apps' notifications, now-playing/visualizer, typing along, eyes
  following the cursor, GPU/temperatures, skins without Node.js, Termux mode.
- Shipping: GitHub Releases: `Chip-Setup.exe` (Windows 10/11 x64), `Chip.dmg` (macOS 14+, Apple Silicon),
  `Chip.apk` (Android 10+). Linux: `laptop/install.sh`. GitHub Actions builds and smoke-tests everything; friends
  test what needs a real desktop. The user has no Windows or Mac machine.
- Ports: 8765 = dashboard + local API on 127.0.0.1 (unchanged); 8766 = Termux pairing download (unchanged);
  8770 = `appPort`, the app listener on the LAN, open only while app mode is on.

## Rules
- Work on branch `port`, never on main. Commit at the end of the task: "Tn: <summary>". Push, tag, release or merge
  only when the user's prompt says so.
- Read only what you need: Overview, Rules, your section. Grep big files (bridge.py, buddy.js, dashboard.html,
  pack.json); never read them whole.
- Termux mode on Linux must keep working. Before committing run `python3 -m py_compile laptop/*.py phone/*.py`,
  `node laptop/check_pack.js`, `python3 -I laptop/test_skins.py`, and from T1 on `python3 -I laptop/chip.py selftest`.
  If the bridge changed: `systemctl --user restart deskbuddy-bridge`, then `python3 -I laptop/doctor.py`.
- All CLAUDE.md rules still hold (dictation, link writes, pairing, privacy, no adb, CPU budget). Loosen none.
- Linux: no new runtime dependencies. Windows/macOS: only what `packaging/requirements.txt` pins. Vendored code:
  small, permissive licence, listed in `docs/port/THIRD_PARTY.md`.
- New code goes in new modules; bridge.py should shrink, not grow.
- Ask the user before installing system packages, editing files outside the repo (e.g. ~/.claude/settings.json) or
  doing anything on a phone. No adb, ever: APKs reach the phone over Wi-Fi.
- End of task: tick your Status line (date, short hash, follow-ups), update the CLAUDE.md lines that changed (keep
  it short), commit.

## T0 Repo prep
- `git switch -c port` (it carries the uncommitted docs/port/ files and the CLAUDE.md pointer).
- `.gitignore`: `__pycache__/`, `*.pyc`, `dist/`, `build/`, `android/.gradle/`, `android/**/build/`,
  `android/local.properties`, `*.jks`, `*.keystore`, `.idea/`. `git rm -r --cached` the tracked `__pycache__` files.
- Secret scan of all history: grep `git log -p --all` for key-like strings (`sk-`, `gsk_`, `AIza`, `api[_-]?key`,
  `secret`, `token`, `password`, `BEGIN .*PRIVATE KEY`) and `git log --all --name-only` for settings.json,
  secrets.json, known_hosts, state.json, `*.pem`, `*.jks`. Report what you find; don't rewrite history.
- Ask the user for the licence (MIT is simplest for an app people install; GPL-3.0 if forks must stay open), add LICENSE.
- Done when branch `port` has one commit with .gitignore, LICENSE, docs/port/, the CLAUDE.md pointer, and the user
  has the scan result (the repo can go public only if it is clean).

## T1 Platform layer + selftest
Goal: every OS-specific call sits behind `laptop/platforms/`; Linux behaves exactly as today.
- `platforms/paths.py`: CONFIG_DIR, DATA_DIR. Linux keeps `~/.config/deskbuddy` and `~/.local/share/deskbuddy`;
  Windows `%APPDATA%\Chip` and `%LOCALAPPDATA%\Chip`; macOS `~/Library/Application Support/Chip` (both). Env overrides
  `CHIP_CONFIG_DIR` / `CHIP_DATA_DIR` for tests. Replace every hard-coded `~/.config/deskbuddy` path in laptop/*.py.
- `platforms/__init__.py` picks `linux.py` / `windows.py` / `macos.py` by sys.platform and exposes `CAPS` (bools:
  stats, gpu, temps, battery, idle, locked, typing, media, nowPlaying, volume, notifications, visualizer, typingRate,
  gaze, termuxLink, skins, laptopStt) and a small function set derived from today's code (stats sample, idle_ms,
  locked, type_text, media status/control, volume, start_watchers for notifications/typing rate/gaze, wifi_ssid).
  Its docstring lists the /stats keys; missing values are None.
- `linux.py`: today's code moved, not rewritten (typer.py stays and is imported). `windows.py` and `macos.py`: stubs
  with CAPS false (T6/T7 fill them); they must import cleanly on every OS.
- CAPS reach the phone page (in /stats) and the dashboard (`GET /caps`); both hide what is missing (GPU ring, music
  card, visualizer, typing along, eyes, notification switches) with "Linux only for now". `CHIP_FAKE_CAPS=gpu=0,media=0`
  fakes missing caps so this can be tested on Linux. caps.skins = node on PATH.
- The Termux link pieces (PhoneLink, Pairing, deploy) start only when caps.termuxLink.
- `laptop/chip.py`: `chip [bridge] | attention <source> | doctor | selftest` (`report` comes in T10). bridge.py and
  attention.py keep working when run directly (the systemd unit and the user's hooks call them).
- `selftest`: runs the bridge on free ports with temp CHIP_CONFIG_DIR/CHIP_DATA_DIR, checks the main GET routes return
  the documented keys, CAPS is sane and the Termux link stays off; prints JSON; exit 1 on failure. It must pass without
  GNOME/D-Bus (CI), reporting those caps as false.
- Checks: before changing anything, save the JSON key sets of /stats, /settings, /link, /phone and /stt/status from
  the running bridge to the scratchpad; afterwards restart the bridge and diff (values may differ; keys and shapes must
  not). Then ask the user to try one dictation and one dashboard alert test on the phone.

## T2 App mode in the bridge
Goal: the bridge serves the face page and the phone's routes to a paired Chip app over the LAN, safely.
New module (e.g. `laptop/appmode.py`) + `laptop/version.py` (CHIP_VERSION); bridge.py only wires them in.
- Settings `appEnabled` (default false) and `appPort` (8770): dashboard-only like LINK_KEYS (/settings drops them from
  any other Origin), never sent to the phone. The listener is up on 0.0.0.0:appPort only while appEnabled.
- TLS: self-signed ECDSA P-256 cert valid 10 years, made on first use in CONFIG_DIR (`app-cert.pem`, `app-key.pem`,
  owner-only); `cryptography` if importable, otherwise the `openssl` CLI. Fingerprint = base64url(SHA-256(DER)).
  Do the handshake in the request thread with a timeout, so a stalled client can't block accept.
- Pairing: dashboard-only `POST /app/pair/start` → one-time 128-bit secret, valid 3 min, shown as a QR:
  `chip://pair?v=1&h=<laptop's private IPv4s, comma-separated>&p=<port>&fp=<fingerprint>&s=<secret>&n=<hostname>`.
  The app calls `POST /app/pair` on the LAN listener (body {secret, device}) and gets a 256-bit token, stored as
  SHA-256 in CONFIG_DIR/app-phones.json with {name, created, lastSeen}. The secret works once; 5 wrong tries end the pairing.
- Every other LAN request needs the cookie `chip=<token>`, otherwise 401 with no detail. Rate-limit failures per peer IP.
- Accept peers from private ranges only (10/8, 172.16/12, 192.168/16, 169.254/16, 100.64/10, fc00::/7, fe80::/10).
  Host must be one of the laptop's addresses with appPort; Origin must be absent or the listener's own origin.
- Allowlist (derived from the page's real calls; re-check with grep): static phone/www files; GET /stats, /settings,
  /caps, /gaze, /viz, /skins/<id>.json, /skins/draft.json, /skins/<id>/headphones.json; POST /settings (LINK_KEYS and
  the app keys always dropped), /type, /media/<action>, /volume/<action>, /transcribe, /app/pair. Everything else is
  404: the dashboard, /link*, /app/pair/start, /stt/*, /attention, skin writes, and so on.
- `/config.js` on the LAN listener = phone/www/config.js + `BUDDY_CONFIG.laptop = location.origin; BUDDY_CONFIG.mode = "app";`.
  `/version.txt` = a hash of phone/www's files, so edits reload the page without deploy.sh. Send `Cache-Control: no-cache`.
- `/phone` status remembers which phone reported (tunnel, or the app's name); the latest one wins on the status line.
- Typing keeps today's rules; the trigger is the Termux tunnel or a valid app token.
- Dashboard card "Phone app" (every OS): on/off; "Connect a phone" → step 1 = QR to the APK
  (`https://github.com/Shriaman2005/deskbuddy/releases/download/v<CHIP_VERSION>/Chip.apk`, or the releases page for a
  source install), step 2 = the pairing QR with a 3-minute countdown; paired phones (name, last seen, Forget = revoke
  now and close its open streams). Before the first start on Windows, show "Windows will ask about the firewall: tick
  Private networks". QR code: vendor Project Nayuki's qrcodegen (MIT) JS into laptop/vendor/.
- Tests: `laptop/test_appmode.py` (stdlib unittest, temp dirs, real TLS sockets): pairing happy path; reused, expired
  and wrong secret; 401 without cookie; 403 on wrong Origin/Host; 404 for /link and /; LINK_KEYS dropped; Forget
  revokes; peer-range check. selftest runs it.
- Update the CLAUDE.md Rules (typing trigger, app keys dashboard-only) and add a short "Phone app" section to the README.

## R1 Review T1–T2
Fresh session: `/code-review high port --fix`. Focus: the app-mode rules in T2, and Linux unchanged. Then rerun
test_appmode.py and selftest, tick, commit "R1: review fixes".

## T3 Android app: shell, pairing, pinned TLS
Goal: an installable Chip.apk that pairs by QR code and shows the face from the laptop. Project in `android/`.
- Toolchain (the user installs it; see PROMPTS.md): JDK 21 and the Android SDK at ~/Android/Sdk (cmdline-tools,
  newest platform and build-tools). Commit the Gradle wrapper (make it once with a downloaded Gradle). This laptop has
  ~5 GB RAM: set `org.gradle.jvmargs=-Xmx1536m`. Use Java, not Kotlin (lighter build), and no AndroidX unless a
  dependency needs it.
- minSdk 29, targetSdk = newest installed, package `org.deskbuddy.chip`, label "Chip". Only dependency:
  zxing-android-embedded.
- Permissions: INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, CAMERA (asked when scanning), RECORD_AUDIO (T4,
  asked at the first dictation). No services, no boot receiver, nothing in the background.
- MainActivity: fullscreen immersive WebView; FLAG_KEEP_SCREEN_ON; sensor orientation; long-press and text selection
  off; WebView paused in onPause/onStop. JS and DOM storage on; media plays without a user gesture; mixed content
  never; file/content access off; user agent + " ChipApp/<versionCode>".
- Pairing: scan the QR code (ZXing) or paste the chip://pair link; connect, check fp, POST /app/pair, and save {hosts,
  port, fp, token, laptop name} in private SharedPreferences; set the cookie `chip=<token>` (Secure, HttpOnly,
  SameSite=Strict) for the origin.
- Pin: in WebViewClient.onReceivedSslError, proceed only if
  base64url(SHA-256(error.getCertificate().getX509Certificate().getEncoded())) == fp; otherwise cancel and show
  "This laptop's key changed. Pair again from its dashboard." Native HTTPS (pairing, probes, and /transcribe in T4)
  uses a TrustManager that makes the same check.
- Connect: try the saved hosts, else scan the phone's Wi-Fi /24 on appPort in parallel (short timeouts), accept only
  the pinned fp and save the new address. Offline screen (Retry, Pair again) with an auto-retry every 5 s; also
  shown when the page fails to load.
- The page's localStorage is per address: snapshot it (evaluateJavascript) on pause and before switching address,
  and restore it into a new address before the page's first run, so prefs and today's focus stats survive an IP change.
- Back button → menu: Reconnect, Pair with a laptop, Forget this laptop, Exit.
- Launcher icon: Chip's face from pack.json (render the preview in headless Chrome, crop, scale by whole numbers to
  the adaptive-icon sizes). Don't draw new art.
- Build with `./gradlew assembleDebug`. To get it onto a phone (no adb): `python3 -m http.server 8099 --bind <laptop
  LAN IP> -d android/app/build/outputs/apk/debug`, open that address on the phone, install, then stop the server.
- Done when (the user, on their phone): install, pair by QR, the face appears, laptop stats + settings sync + timers
  work, it reconnects after a bridge restart, and a wrong key is refused (test: stop the bridge, move
  app-cert.pem/app-key.pem aside, start it → the app refuses; put them back → it works).

## T4 Android app: phone API, dictation, page tweaks
Goal: the app does natively everything phone/server.py does in Termux, so buddy.js barely changes.
- In shouldInterceptRequest, same-origin `/api/*` is answered natively and never sent to the laptop. The contract is
  phone/server.py and phone/dictation.py exactly (paths, query params, JSON keys, error codes): read them first.
  Plus `GET /api/app` → {version, features}.
  - status: battery %, charging, temperature, flashlight, wifi {rssi, speed, freq, ip} (no SSID: that needs location).
  - brightness: this window's brightness only (0 → 0.01, so the screen never goes black).
  - say: TextToSpeech.
  - alert, alert/stop, torch: CameraManager.setTorchMode (same blink timing as alert.py); the chime/beep/alarm/ping
    sounds ported from alert.py's synthesis to Java (AudioTrack), volume 5–100; stop ends both and restores the flashlight.
  - launch: settings, files (CATEGORY_APP_FILES), launcher (home screen); brave/termux only if installed (declare
    `<queries>`), else 404.
  - dictate start/status/stop/cancel: for the laptop and cloud engines, record with AudioRecord (VOICE_RECOGNITION,
    16 kHz mono 16-bit, ≤60 s), make a WAV and POST it to /transcribe with the same query as dictation.py (pinned,
    with the cookie). The phone engine is Android's SpeechRecognizer (hinglish → en-IN, auto → device language,
    otherwise the code), started at /start; declare `<queries>` for android.speech.RecognitionService. Release the
    mic on every path.
- buddy.js (app mode = `BUDDY_CONFIG.mode === "app"`): also pass on= and lang= to /api/dictate/start (server.py
  ignores them); the drawer shows Settings/Files/Exit instead of Brave/Termux; hints mention the app's menu, not
  kiFOSSk. Optional, only if it doesn't disturb other gestures: in app mode a still one-finger hold (~0.6 s) starts
  dictation too.
- Dashboard: in app mode the "Phone" engine reads "Phone (Android speech)", with its language flags to match.
- Done when (the user, on their phone): the dashboard alert test blinks the torch and plays each sound; hourly talk
  works; night brightness dims; dictation with the laptop, cloud and phone engines types into a laptop window;
  cancelling (slide away) types nothing; after closing the app the mic indicator is off.

## R2 Review the Android app
Fresh session: `/code-review high android/ --fix`. Focus: the pin check can't be bypassed (every SSL error path, the
native client, redirects); the token never appears in URLs or logs; /api/* is answered for same-origin only; the mic
is always released; no background work. Build, tick, commit "R2: review fixes". Milestone M1: the user merges port → main.

## T5 CI on four platforms
- `.github/workflows/ci.yml` (push to port/main and PRs; `permissions: contents: read`; cancel superseded runs):
  - linux (ubuntu-latest): py_compile, check_pack.js, test_skins.py, test_appmode.py, chip.py selftest.
  - windows (windows-latest) and macos (macos-latest): setup-python 3.12, `pip install -r packaging/requirements.txt`,
    py_compile, test_appmode.py, chip.py selftest (caps may be false until T6/T7).
  - android (ubuntu-latest, JDK 21): `./gradlew assembleDebug lint`; upload the APK as an artifact.
- `packaging/requirements.txt`: psutil, cryptography, pyinstaller, all with exact versions.
- Pin actions to full commit SHAs, with the version in a comment.
- Push only when the user's prompt allows it; watch with `gh run watch` and fix until green.

## T6 Windows backend
`laptop/platforms/windows.py`, ctypes + psutil only.
- stats: CPU %, RAM, battery (percent, charging, time left), network rates and uptime via psutil; gpu/temps None.
- idle_ms: GetLastInputInfo. locked: OpenInputDesktop + SwitchDesktop fail while the screen is locked.
- type_text: SendInput with KEYEVENTF_UNICODE per UTF-16 unit (surrogate pairs as two units), key down + up, in small
  batches; \n and \t become spaces; refuse while locked; never Enter. Test `ctypes.sizeof(INPUT) == 40` on x64.
  Elevated (admin) windows ignore it (UIPI): say so in the error and the docs.
- media: VK_MEDIA_PLAY_PAUSE / NEXT / PREV and VK_VOLUME_UP / DOWN / MUTE through SendInput; caps.media and
  caps.volume true, nowPlaying false.
- Network profile: `Get-NetConnectionProfile` (no admin). If the Wi-Fi is Public, the dashboard and report warn:
  "Settings → Network & internet → Wi-Fi → <name> → Private network".
- Sockets: on Windows use SO_EXCLUSIVEADDRUSE instead of SO_REUSEADDR for 8765/8770 (otherwise another program can
  take the port).
- STT: whisper-cli.exe lives under DATA_DIR\stt (T9 downloads it).
- CI: a typing end-to-end step on windows-latest: start Notepad, focus it, type "héllo wörld नमस्ते 😀 a\nb" with
  type_text, copy it back (Ctrl+A, Ctrl+C, Get-Clipboard) and compare with "héllo wörld नमस्ते 😀 a b". If the runner
  has no usable desktop, keep the step with continue-on-error and write that down.
- Done when the CI windows job is green, with selftest caps stats, idle, locked, typing, media and volume true.

## T7 macOS backend
`laptop/platforms/macos.py`, ctypes + psutil only (no PyObjC).
- stats via psutil (as in T6); gpu/temps None.
- idle_ms: CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType).
- locked: CGSessionCopyCurrentDictionary → "CGSSessionScreenIsLocked" (CoreFoundation via ctypes; release what you copy).
- type_text: CGEventCreateKeyboardEvent + CGEventKeyboardSetUnicodeString, ≤20 UTF-16 units per event, down + up,
  CGEventPost(kCGHIDEventTap); \n and \t become spaces; never Enter; refuse while locked. Before typing, call
  AXIsProcessTrustedWithOptions with the prompt; if not trusted, fail with "Allow Chip in System Settings → Privacy &
  Security → Accessibility, then try again" (the phone shows it in Chip's bubble).
- media/volume: not in v1 (caps false) unless trivial and safe.
- CI test without permissions: create keyboard events, set and read back their unicode strings
  (CGEventKeyboardGetUnicodeString) to prove the ctypes signatures; check idle_ms returns a number and locked a bool.
- Note for T10: Accessibility is granted to the app bundle; unsigned/ad-hoc builds may need it again after updates.
- Done when the CI macos job is green with caps stats, idle, locked and typing true. List what only the friend test
  can confirm.

## T8 AI-agent hooks installer
- Dashboard card "AI agents" (every OS): per agent Installed / Not installed, Install, Remove, Test. Dashboard-only
  routes: GET /hooks, POST /hooks/install, POST /hooks/remove.
- Claude Code: ~/.claude/settings.json, hooks Notification and Stop → `<chip> attention claude-code`.
  Gemini CLI: ~/.gemini/settings.json, hooks Notification and AfterAgent → `<chip> attention gemini`.
  opencode: the plugin file ~/.config/opencode/plugin/deskbuddy-attention.js (see how the existing one reaches the bridge).
- `<chip>` = the absolute path of the packaged CLI (when frozen) or `python3 -I <repo>/laptop/attention.py` for a source
  install. Find out how each agent runs hook commands on Windows (cmd, PowerShell or Git Bash) and use a form that
  works there, including paths with spaces.
- JSON edits: keep everything else intact, back up once to `<file>.chip-bak`, be idempotent (recognise existing Chip
  hooks, including the user's current `python3 -I …/attention.py` lines); Remove takes out only Chip's entries.
- Test with a temp HOME. Don't touch the real files without asking the user.

## T9 Speech models and whisper binaries
- stt.py takes its paths from platforms.paths (Linux unchanged: ~/.local/share/deskbuddy/stt); binary name
  whisper-cli or whisper-cli.exe.
- Dashboard (Dictation card): Download / Remove for the models base-q8_0 (~80 MB) and small-q8_0 (~250 MB) from Hugging
  Face (ggerganov/whisper.cpp), pinned to the SHA-256 of the user's existing files in ~/.local/share/deskbuddy/stt/models.
  Show progress, resume, write to a temp file, verify, then rename.
- Windows: "Download the speech engine" = the official whisper.cpp release zip (whisper-bin-x64.zip) of a pinned
  version, SHA-256 pinned; extract whisper-cli.exe and its DLLs into DATA_DIR\stt.
- macOS: whisper-cli is built in CI (T10, Metal) and ships inside Chip.app; stt.py finds it there.
- Linux: unchanged (the user's own build). The cloud engine works everywhere with no downloads.
- Dashboard-only routes; downloads only from the pinned URLs.

## T10 Packaging and release pipeline
- `chip report`: JSON for testers: OS and version, Chip version, CAPS, permission states (Accessibility, network
  profile), app listener up, number of paired phones, the last 20 error lines. Never secrets, tokens or dictated text.
- PyInstaller specs in packaging/, bundling laptop/*.py, platforms/, vendor/, dashboard.html and phone/www.
  Windows: a windowed Chip.exe (the bridge) and a console chip.exe (attention, doctor, report, selftest).
  macOS: Chip.app (LSUIElement, so no Dock icon), a `Contents/MacOS/chip` CLI, and whisper-cli (Metal) inside;
  arm64; check the minimum macOS is ≤ 14.
- Start at login (a dashboard toggle on every OS): Windows HKCU\…\Run; macOS a LaunchAgent at
  ~/Library/LaunchAgents/org.deskbuddy.chip.plist; Linux the existing systemd user unit.
- Windows installer: Inno Setup, per-user (no admin) into %LOCALAPPDATA%\Programs\Chip; a Start-menu "Chip" that opens
  the dashboard (starting the bridge if needed); an uninstaller that keeps settings unless asked.
- macOS: Chip.dmg via hdiutil (Chip.app + an Applications link).
- `.github/workflows/release.yml` on tags v*: build Windows, macOS and Android (assembleRelease, signed with the
  secrets ANDROID_KEYSTORE_B64, ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS, ANDROID_KEY_PASSWORD); smoke-test the
  installed artifacts (Windows: installer /VERYSILENT, then chip.exe selftest; macOS: mount the DMG and run chip
  selftest); SHA256SUMS; a draft release (pre-release if the tag has -beta) with Chip-Setup.exe, Chip.dmg and Chip.apk.
- Push tags only when the user's prompt allows it.

## R3 Pre-release review
Fresh session: `/code-review medium laptop/platforms/ --fix`, then `/code-review medium packaging/ --fix`. Run the
checks, tick, commit. Then the user tags v0.1.0-beta.1 (M2).

## T11 Friend test kit
`docs/port/TESTING.md`, one checklist per OS (≤30 min, plain words, numbered; each step says what "pass" looks like):
install (the warning screens and how to get past them); the dashboard opens; Connect a phone (any Android 10+ phone on
the same Wi-Fi); stats roughly match Task Manager / Activity Monitor; dictation into Notepad / TextEdit with the laptop
engine (download the small model), and with the screen locked (it must refuse); the AI alert Test button (plus a real
Claude Code hook if they have it); log out and in → Chip starts by itself; uninstall. Then run `chip report` and send
its output plus screenshots of anything odd. Add a short message the user can send to friends.

## T12 User docs
`INSTALL.md`: phone (install the app, scan, done; daily use), Windows, macOS, Linux, 3 steps each. Troubleshooting:
Wi-Fi set to Public (Windows), the firewall prompt, SmartScreen "More info → Run anyway", Smart App Control blocking
unsigned apps, macOS "Open Anyway" in System Settings → Privacy & Security (macOS 15+ has no right-click bypass),
Accessibility, Wi-Fi that hides devices from each other (use the phone's hotspot), the Play Protect warning. README:
a short intro and a link. CLAUDE.md: layout lines for android/, platforms/, packaging/, docs/port/. Facts only from
this plan and the code.

## F Friend-test fixes
One fresh session per report and platform, with the `chip report` JSON and the friend's notes pasted in. Diagnose from
the evidence and fix what is clear. Where the cause isn't clear, add a check to `chip report` or selftest so the next
round shows it; don't guess-fix. CI green, add a Status line for the round, commit "F<n>: <platform> fixes".

## Later (not planned in detail)
Eyes following the cursor on Windows/macOS (GetCursorPos / CGEventGetLocation, cheap); now-playing and the visualizer on
Windows (media session API, WASAPI loopback); Windows app notifications (needs a packaged app identity); typing along
(keyboard hook / Input Monitoring); GPU on Windows; skins without Node; Intel Macs; code signing (Apple Developer,
Windows); Android developer verification before 2027; Play Store; an offline face cached in the app; typing on
non-GNOME Linux.
