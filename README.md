# Chip — a desk buddy for your old Android phone

Turn a spare Android phone into **Chip**, a little pixel-art companion that sits next to your laptop. Chip blinks,
reacts when you touch it, shows your laptop's stats, the time and weather, runs a Pomodoro timer, types what you say
into your laptop, and flashes the torch when an AI agent (Claude Code, Gemini CLI, opencode) needs you.

The phone and the laptop talk over your home Wi-Fi through one ssh tunnel. No cable, no cloud account, no app store.

<p align="center">
  <img src="docs/img/face.png" width="49%" alt="Chip's face">
  <img src="docs/img/face-happy.png" width="49%" alt="Chip smiling, with the status bar">
</p>
<p align="center">
  <img src="docs/img/clock.png" width="32%" alt="Clock and weather screen">
  <img src="docs/img/laptop.png" width="32%" alt="Laptop stats and music screen">
  <img src="docs/img/timer.png" width="32%" alt="Pomodoro timer screen">
</p>

> **Status: beta.** Linux (GNOME) is the main platform and has every feature. Windows 10/11 works for the core
> features and is tested in CI. macOS support is written but not finished yet. See the [comparison table](#what-works-where).

---

## Contents
- [What Chip does](#what-chip-does)
- [What works where](#what-works-where)
- [What you need](#what-you-need)
- [Install on the laptop](#1-install-on-the-laptop) — [Linux](#linux-gnome) · [Windows](#windows-1011) · [macOS](#macos-experimental)
- [Set up the phone](#2-set-up-the-phone)
- [Using Chip](#using-chip)
- [Privacy and security](#privacy-and-security)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [For developers](#for-developers)

---

## What Chip does

**On the phone** (swipe left/right between screens: Face → Clock & weather → Laptop → Timer)
- **Face:** blinks, looks around and reacts. Tap = happy, double-tap = hearts, rub = pets, poke 6× = grumpy,
  shake = dizzy, drag a finger = its eyes follow it. When idle it whistles, sneezes, peeks off-screen and naps when
  you are away. It wears headphones while music plays on the laptop and a mask when the air quality is bad.
- **Clock & weather:** big pixel clock, hourly forecast, air quality, sunrise and sunset (from Open-Meteo, no key needed).
- **Laptop:** CPU, RAM, GPU and battery rings, plus a music card (play/pause, next, volume) and a music visualizer.
- **Timer:** Pomodoro (focus / short / long break, daily goal), countdown and stopwatch. While you focus, Chip
  types away on its own little laptop in a dimmed room.
- **Typing along:** when you type on the laptop, Chip opens its laptop and types at your speed.
- **Dictation:** hold Chip's face with **two fingers**, speak, let go. The text is typed wherever your cursor is on
  the laptop. Speech-to-text runs on the phone (offline), on the laptop (offline), or a cloud provider of your choice
  (Groq, OpenAI, Deepgram, ElevenLabs, AssemblyAI, Google, Azure, Gemini or a custom URL). Hinglish by default.
- **Attention alerts:** when an AI agent finishes or needs input, the phone blinks its torch and/or plays a sound and
  Chip says who is calling, until you get back to the laptop or tap Chip.
- **Sleep:** dims at night (11 PM–6:30 AM by default), greets you in the morning, reminds you to stretch.
- **Swipe up** for app shortcuts and quick toggles; **swipe down** on the face for a summary.

**On the laptop**
- **Dashboard** at <http://127.0.0.1:8765> with a page for every setting: colour, eyes, skins, behaviour, sleep,
  screens, timer, alerts, AI agents, dictation and the phone connection. Changes reach the phone within ~3 seconds.

<p align="center"><img src="docs/img/dashboard.png" width="85%" alt="The Chip dashboard on the laptop"></p>

- **Skins:** make your own Chip with any AI chatbot. The Skins page gives you a prompt, checks the JSON the chatbot
  returns, previews it and installs it. See [Make your own Chip](#make-your-own-chip).
- **Eyes follow your mouse** across all your monitors (Linux/GNOME).

---

## What works where

Everything on the phone itself (face, reactions, clock, weather, timers, skins, sounds, torch) works the same with
every laptop. The differences are in what the laptop can report or do:

| Feature | Linux (GNOME) | Windows 10/11 | macOS 14+ |
|---|:---:|:---:|:---:|
| Wi-Fi link, pairing wizard, auto-reconnect, auto-update of the phone | ✅ | ✅ | 🧪 |
| Dashboard (all settings) | ✅ | ✅ | 🧪 |
| Start automatically at login / boot | ✅ systemd (at boot) | ✅ at login | 🧪 LaunchAgent |
| CPU, RAM, uptime, network | ✅ | ✅ | 🧪 |
| Laptop battery | ✅ | ✅ | 🧪 |
| GPU ring | ✅ (AMD) | ❌ | ❌ |
| Temperatures and fan | ✅ | ❌ | ❌ |
| Dictation typed into the focused window | ✅ | ✅ | 🧪 (needs Accessibility) |
| Dictation engine: phone (offline) | ✅ | ✅ | ✅ |
| Dictation engine: cloud | ✅ | ✅ | ✅ |
| Dictation engine: laptop (offline whisper.cpp) | ✅ | ⚠️ bring your own `whisper-cli.exe` | ⚠️ `whisper-cli` from Homebrew |
| Knows when you're idle or the screen is locked | ✅ | ✅ | 🧪 |
| AI-agent alerts (Claude Code, Gemini CLI, opencode) | ✅ | ✅ (hooks not yet tested by a person) | 🧪 |
| Alerts for other apps' notifications | ✅ | ❌ | ❌ |
| Music card: now playing, play/pause, next | ✅ | ❌ | ❌ |
| Volume control | ✅ | ❌ | ❌ |
| Music visualizer | ✅ | ❌ | ❌ |
| Headphones on Chip while music plays | ✅ | ❌ | ❌ |
| Chip types along with you | ✅ | ❌ | ❌ |
| Eyes follow the mouse pointer | ✅ (GNOME extension) | ❌ | ❌ |
| "Only connect on my home Wi-Fi" | ✅ | ✅ | ⚠️ macOS may hide the Wi-Fi name |
| Custom skins | ✅ | ✅ (needs Node.js) | ✅ (needs Node.js) |

✅ works · ⚠️ works with an extra step · 🧪 written, not proven yet · ❌ not yet (the dashboard greys it out and says so)

Linux was built and tested on Ubuntu with GNOME on Wayland. Other desktops will get the basics (stats, link, phone
features), but idle/lock, media, notifications, typing and eye tracking use GNOME's D-Bus APIs.

---

## What you need

**A laptop** running one of:
- **Linux** with GNOME (Ubuntu 24.04+ recommended), Python 3.12+, `ssh` (openssh-client), `git`
- **Windows 10 or 11** with Python 3.12+ from [python.org](https://www.python.org/downloads/) (not the Microsoft Store
  version). Windows' built-in OpenSSH client is used.
- **macOS 14+** (experimental) with Python 3.12+ from python.org or Homebrew

Optional: [Node.js](https://nodejs.org/) 18+ for custom skins.

**An Android phone** (any Android 7+ phone that can run Termux; it was built on a Samsung Galaxy M01 Core, a very weak
Android Go phone, so almost anything works) with these free apps from **[F-Droid](https://f-droid.org/)**:
- [Termux](https://f-droid.org/packages/com.termux/) — runs Chip's small server on the phone
- [Termux:API](https://f-droid.org/packages/com.termux.api/) — battery, torch and voice
- Optional, for a phone that stays on the desk all the time:
  [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) (start Chip when the phone boots) and
  kiFOSSk (a kiosk launcher that makes Chip the home screen)

> Install Termux and Termux:API **from the same place (F-Droid)**. Mixing F-Droid and Play Store versions breaks them,
> and the Play Store Termux is outdated.

**Both on the same Wi-Fi.** Some routers (guest networks, office Wi-Fi) stop devices from seeing each other; if pairing
can't find the phone, use a home network or the phone's own hotspot.

---

## 1. Install on the laptop

First get the code, either with git or with GitHub's **Code → Download ZIP** (then unzip it somewhere permanent;
Chip runs from that folder, so don't delete it afterwards):

```bash
git clone https://github.com/Shriaman2005/deskbuddy.git
cd deskbuddy
```

### Linux (GNOME)

```bash
laptop/install.sh
```

This installs the bridge as a systemd user service (`deskbuddy-bridge`) that starts at boot, even before you log in,
and links the small GNOME Shell extension that lets Chip's eyes follow your mouse. **Log out and back in once** so
GNOME loads the extension.

Then open the dashboard: <http://127.0.0.1:8765>

Optional extras:
- Music visualizer and volume need PipeWire/PulseAudio tools (`wpctl`, `parec`), which Ubuntu has by default.
- Offline dictation on the laptop: build [whisper.cpp](https://github.com/ggml-org/whisper.cpp) and put `whisper-cli`
  and a model (e.g. `ggml-base-q8_0.bin` in `models/`) in `~/.local/share/deskbuddy/stt/`. The dashboard's Dictation
  page shows whether it was found.

### Windows 10/11

1. Install **Python 3.12+** from <https://www.python.org/downloads/>. In the installer tick **"Add python.exe to PATH"**.
   (The Microsoft Store Python doesn't work for this; the installer will tell you if it finds it.)
2. Get the Chip folder (git clone or Download ZIP, see above).
3. Run the installer, either by double-clicking `laptop\install.py` or from a terminal in the Chip folder:
   ```powershell
   py -3 laptop\install.py
   ```
   It creates a private Python environment, creates Chip's own ssh key, sets Chip to start when you log in, starts it
   and opens the dashboard.
4. When Windows asks whether to allow Python on the network (during pairing), choose **Allow** on **private networks**.

Running the installer again updates or repairs Chip. Logs are in `%USERPROFILE%\.local\share\deskbuddy\bridge.log`.

Notes for Windows:
- Dictation can't type into a window that runs **as administrator** (Windows blocks this); click a normal window first.
- For offline dictation on the laptop, put `whisper-cli.exe` on your PATH or in `%USERPROFILE%\.local\share\deskbuddy\stt\`.
  The phone and cloud engines work without it.

### macOS (experimental)

macOS support is written but hasn't passed its tests yet. If you want to try it:

```bash
python3 laptop/install.py
```

Use Python 3.12+ from python.org or Homebrew (the one that comes with Xcode is too old). The installer adds a
LaunchAgent so Chip starts at login, and opens **System Settings → Privacy & Security → Accessibility**: allow the
**Python** it names there, otherwise dictation can't type. Log: `~/Library/Logs/deskbuddy-bridge.log`.
Please open an issue with what you see.

---

## 2. Set up the phone

Pairing is done from the dashboard and takes about 5 minutes (most of it is Termux installing packages).

1. On the phone, install **Termux** and **Termux:API** from F-Droid and open Termux once.
2. On the laptop, open the dashboard → **Connections** → **Replace phone** → **Start pairing**.
3. The dashboard shows a one-line command. Type it into Termux on the phone (it downloads the setup from your laptop,
   checks it, installs what's needed and starts Chip's server). The download is open for 10 minutes and only for one phone.
4. When it finishes, the phone prints a **PAIRING CODE** (4 groups of 4 characters). Type it into the dashboard and
   press **Pin this phone**. Nothing is trusted until you do this.
5. On the phone, give these permissions in **Settings → Apps** (the setup script lists them too):
   - Termux → **Microphone** (for dictation)
   - Termux → **Notifications: allowed**
   - Termux → **Battery: Unrestricted** (otherwise Android closes the connection when the screen is off)
   - Termux:API → **Modify system settings** — only on a phone that's dedicated to Chip, so Chip can control brightness

Now show Chip's face. Pick one:

**A phone you also use (personal phone)**
- Open `http://127.0.0.1:8080` in Chrome, then ⋮ → **Install app** (or **Add to Home screen**). Chip then opens full
  screen and keeps the screen on while it's showing.
- Turn on **Personal phone** on the dashboard's Connections page.
- Chip runs while Termux runs: open Termux (or type `chip-start`) to start it; type `chip-stop`, or tap **Exit** in
  Termux's notification, to stop it.

**A spare phone that lives on the desk (always on)**
- Install **Termux:Boot** (F-Droid) and open it once, so Chip starts by itself when the phone reboots.
- Install **kiFOSSk**, set it as the home app, and point it at `http://127.0.0.1:8080`. Set its orientation to
  Auto-rotate if you like; every screen has a portrait layout.
- Set Termux, Termux:Boot and kiFOSSk to **Battery: Unrestricted** (Android Go phones kill them otherwise).
- Long-press anywhere with one finger to reach kiFOSSk's own settings ("Switch to different launcher" gives you the
  normal home screen back).

**Optional: offline dictation on the phone.** In Termux run `bash ~/deskbuddy/stt-setup.sh`. It builds whisper.cpp
on the phone (about 10 minutes) and downloads a small model. Without it, use the laptop or cloud engine.

From now on everything is automatic: when the laptop or phone restarts, the link comes back by itself within a minute,
and when you update the Chip folder on the laptop, the phone gets the new files the next time it connects.

---

## Using Chip

### Gestures on the phone
| Gesture | What happens |
|---|---|
| Swipe left / right | Face → Clock & weather → Laptop → Timer |
| Swipe up | Apps and quick toggles (sounds, talking, dictation engine, torch, reload) |
| Swipe down on the face | Quick summary |
| Tap / double-tap | Happy / hearts |
| Rub back and forth | Pets |
| Poke 6 times | Grumpy |
| Shake the phone | Dizzy |
| Hold with **two fingers**, speak, let go | Dictation (slide a finger away before letting go to cancel) |
| Tap the timer pill on the face | Opens the running timer |

### Dictation
Pick the engine on the dashboard (**Dictation** page) or from the swipe-up drawer:
- **Phone:** whisper.cpp on the phone, fully offline (needs `stt-setup.sh`). About 6 seconds for a sentence on a weak
  phone, 3 seconds in Fast mode.
- **Laptop:** whisper.cpp on the laptop, offline, under a second. The audio is sent through the tunnel and stays in memory.
- **Cloud:** a provider you choose. Paste your API key on the dashboard; it's stored only in
  `~/.config/deskbuddy/secrets.json` on the laptop, never sent to the phone, never shown again (only the last 4 characters).

Safety rules that are always on: Chip never presses Enter, never types while the laptop is locked, the mic is only on
while you hold, and only the paired phone can trigger typing. If the engine fails, nothing is typed and Chip says why.

### AI agents
Dashboard → **AI agents** installs the hooks for **Claude Code**, **Gemini CLI** and **opencode** with one click (and
removes them again). It edits their settings files and keeps a `.chip-bak` backup the first time. Use **Test** to see
the alert on the phone. The **Attention** page sets torch/sound, reminders, "only when I'm away" and night mode;
the **Apps** page sets it per app.

### Make your own Chip
A skin changes Chip's eyes, mouth, face plate, ears, headphones and colours. Its animations stay the same.
1. Dashboard → **Skins** → pick what it's based on (your pet, yourself, a character, your art, or just an idea) and
   copy the prompt into any AI chat (ChatGPT, Gemini, Claude…), with your pictures attached there.
2. Save the JSON the chat gives you and upload it (or paste it).
3. If it has problems, the page lists each one; **Copy message for your AI** gives you a reply that asks the chatbot
   to fix exactly those. When it passes, you see a live preview; **Use on Chip** installs it.

Only the JSON file reaches the laptop, never your pictures. Skins need Node.js on the laptop.

---

## Privacy and security

- **Nothing leaves your home network** except weather/air-quality lookups (Open-Meteo, by city coordinates) and, only
  if you choose the cloud dictation engine, the audio clip to that provider.
- **The link** is ssh with keys only: the laptop opens one tunnel to Termux's sshd (port 8022) and pins the phone's
  host key, so another device can't pretend to be your phone, even if it takes over its IP address. Passwords,
  agent/X11 forwarding and port forwards into the phone are switched off in the phone's sshd config.
- **The bridge** listens only on `127.0.0.1:8765`. Only the dashboard (origin `http://127.0.0.1:8765`) can change link
  settings or pair a phone; web pages and the phone's page can't. The only port opened to the network is the
  10-minute pairing download.
- **Notifications:** only the sending app's name is kept, never the content. **Typing along** counts key presses,
  never which keys. **Eye tracking** reads only the pointer position while it's on. No webcam, no analytics.
- Your settings, keys and data live in `~/.config/deskbuddy/` and `~/.local/share/deskbuddy/` (the same folders on
  Windows and macOS, under your user folder). They're never in the repo.

---

## Troubleshooting

Run the doctor first. It checks every link and says what to do:
```bash
python3 -I laptop/doctor.py        # Windows: py -3 -I laptop\doctor.py
```
The dashboard's **Connections** page has a **Doctor** button too, and shows why the phone is offline.

| Problem | Fix |
|---|---|
| Pairing: the phone can't download the setup | Allow Python through the firewall (private networks). On Linux the wizard shows the exact `ufw` command to allow it for this pairing only. |
| Pairing: the laptop can't find the phone | Both must be on the same Wi-Fi. Guest/office networks often isolate devices: use your home Wi-Fi or the phone's hotspot. |
| Chip goes offline when the phone screen turns off | Set Termux (and Termux:Boot, kiFOSSk) to **Battery: Unrestricted**. |
| Torch, battery or voice don't work | Termux:API must be installed from F-Droid, like Termux, and opened once. Check with `termux-battery-status` in Termux. |
| "Key mismatch" on the Connections page | Something else answers at the phone's address, or Termux was reinstalled. Re-pair with **Replace phone**. |
| Dictation types nothing (Windows) | The focused window may be running as administrator. Click a normal window. |
| Dictation types nothing (macOS) | Allow the Python the installer named in **Accessibility**. |
| A feature is greyed out with "Linux only for now" | It isn't available on your OS yet (see the [table](#what-works-where)). |
| Eyes don't follow the mouse (Linux) | Log out and back in once after installing; `doctor.py` tells you if the extension is off. |

One phone pairs with one laptop at a time. Pairing a new laptop replaces the old one's key on the phone.

---

## Uninstall

- **Windows / macOS:** `py -3 laptop\install.py --uninstall` (macOS: `python3 laptop/install.py --uninstall`). This
  stops Chip and removes it from login; your settings stay in `~/.config/deskbuddy` and `~/.local/share/deskbuddy`
  (delete those folders to remove everything).
- **Linux:** `systemctl --user disable --now deskbuddy-bridge`, then delete
  `~/.config/systemd/user/deskbuddy-bridge.service` and the settings folders above.
- **Phone:** `chip-stop` in Termux, then uninstall the apps (or delete `~/deskbuddy` in Termux).
- **AI agent hooks:** remove them on the dashboard's **AI agents** page before uninstalling.

---

## For developers

### How it fits together
```
 Phone (Termux)                                     Laptop
 ┌────────────────────────────┐   ssh -R 8765    ┌──────────────────────────────────┐
 │ face page  127.0.0.1:8080  │ ◄──────────────► │ bridge.py  127.0.0.1:8765        │
 │ server.py  (page, torch,   │  one tunnel over │  stats, typing, dictation,       │
 │   speech, dictation)       │   home Wi-Fi     │  settings, dashboard, link       │
 │ sshd :8022 (keys only)     │                  │ platforms/{linux,windows,macos}  │
 └────────────────────────────┘                  └──────────────────────────────────┘
```

| Path | What it is |
|---|---|
| `phone/www/` | The face and screens (HTML/CSS/JS). `pack.json` holds all of Chip's art and motion; `chip.js` is its state machine, `player.js` draws it. |
| `phone/server.py`, `alert.py`, `dictation.py` | Termux side: serves the page, torch and sounds, records and transcribes the mic. |
| `phone/setup.sh`, `services.sh`, `supervisor.sh` | One-time Termux setup (run by pairing) and the services that keep sshd and the server alive. |
| `laptop/bridge.py` | The bridge service: stats, media, typing, dictation, settings, dashboard. |
| `laptop/link.py`, `sshlink.py`, `deploy.py` | The Wi-Fi ssh tunnel, pairing, key pinning, and auto-deploy of `phone/` to the phone. |
| `laptop/platforms/` | Everything OS-specific: `linux.py` (GNOME), `windows.py`, `macos.py`. |
| `laptop/dashboard.html` | The settings dashboard. |
| `laptop/install.sh`, `install.py`, `supervise.py` | Installers (Linux / Windows + macOS) and the Windows restart-on-crash supervisor. |
| `laptop/doctor.py` | Health check for every link. |
| `laptop/hooks.py`, `attention.py` | AI-agent hooks and the alert they send. |
| `laptop/skin.js`, `merge_pack.js` | Skin checker / prompt generator, and the pack merge tool. |
| `laptop/gnome-extension/` | The GNOME Shell extension for the mouse pointer. |
| `design/` | Design deltas and tools for the art pack. |
| `docs/port/` | The cross-platform port plan. |

### Useful commands
```bash
./deploy.sh                                   # push phone/ to the phone now (it also happens automatically)
systemctl --user restart deskbuddy-bridge     # after editing bridge.py (Linux)
python3 -I laptop/selftest.py                 # throwaway bridge, checks routes and capabilities
python3 -I laptop/test_skins.py               # skin checker tests
node laptop/check_pack.js                     # art pack check
CHIP_FAKE_CAPS=gpu=0,media=0 python3 -I laptop/selftest.py   # pretend a feature is missing
```
Preview the phone page without a phone (bridge running):
`http://127.0.0.1:8765/preview/index.html?screen=0&typing` — also `mood=focus`, `&accent=sage`, `&music`,
`&eyes=toon`, `&skin=<id>`, `&screen=1..3`.

CI (`.github/workflows/ci.yml`) runs the checks on Linux, Windows and macOS on every push, including a fake phone
for the tunnel and real typing into Notepad on Windows.

Contributions and bug reports are welcome: please include the output of `doctor.py`.

---

## Credits and license

Chip's art and animation were designed in Claude Design. Pixel font: VT323. Weather and air quality:
[Open-Meteo](https://open-meteo.com/). Speech: [whisper.cpp](https://github.com/ggml-org/whisper.cpp).

[MIT License](LICENSE) © 2026 Aman
