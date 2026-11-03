# Stage 2 prompts (later: the Android app and installers)

> **Not active yet.** Use these only after Stage 1 is done and this plan has been moved to `docs/port/PLAN.md`
> (see the note at the top of `docs/port/later/PLAN.md`). Until then the prompts below would point at the wrong plan.

The plan is in `docs/port/PLAN.md`. Its Status list shows what's done. Each prompt below starts one task.

## How to run a task (this is what saves tokens)
1. Start fresh: `/clear`. Old tasks are in the code, the commits and the plan, not in the chat.
2. `/model` → pick the model and effort from the table.
3. Paste the prompt. Stay in that session only for that task: its fixes, its tests, your answers to its questions.
4. When it's done, check that its Status line in PLAN.md is ticked, then `/clear` and start the next one.
- Long session? `/compact keep task Tn progress`. Stuck after one honest try? Raise the effort one step
  (high → xhigh → max) for that session only.
- Avoid: subagents/workflows ("ultracode"), `/code-review ultra` or `max`, pasting whole logs (paste the failing lines).
- "Where are we?" at any time: Haiku 5.5, low: `Read the Status section of docs/port/PLAN.md and git log --oneline -10. Tell me in 5 lines what's done and what's next.`

## Your setup steps
Now:
1. GitHub CLI: `sudo apt install gh`, then `gh auth login` (GitHub.com, HTTPS, log in with the browser).
2. Decide the licence (T0 asks: MIT is simplest), and whether the repo goes public after T0's secret scan.
   Recommended: public. CI on Windows/macOS is free and phones can download the APK without logging in. Private
   repos get 2,000 free minutes a month, and macOS minutes count 10×.

Before T3 (Android build tools, ~1.5 GB of disk):
3. ```
   sudo apt install openjdk-21-jdk-headless unzip
   # download "Command line tools only" for Linux from https://developer.android.com/studio into ~/Downloads, then:
   mkdir -p ~/Android/Sdk/cmdline-tools
   unzip ~/Downloads/commandlinetools-linux-*_latest.zip -d ~/Android/Sdk/cmdline-tools
   mv ~/Android/Sdk/cmdline-tools/cmdline-tools ~/Android/Sdk/cmdline-tools/latest
   echo 'export ANDROID_HOME=$HOME/Android/Sdk' >> ~/.bashrc && source ~/.bashrc
   yes | ~/Android/Sdk/cmdline-tools/latest/bin/sdkmanager --licenses
   ~/Android/Sdk/cmdline-tools/latest/bin/sdkmanager "platforms;android-36" "build-tools;36.0.0"
   ```
   If a name isn't found, run `sdkmanager --list | grep -E "platforms;|build-tools;"` and take the newest.
   Don't install "platform-tools" (that's adb). Close Chrome while it builds: this laptop has ~5 GB RAM.
4. Phone: Android 10 or newer. The first install asks to allow installs from your browser; allow it once.

Before T5:
5. Public repo (only if T0's scan was clean):
   `gh repo edit Shriaman2005/deskbuddy --visibility public --accept-visibility-change-consequences`

Before T10 (the Android release key: keep it forever, because without it users can't update the app):
6. ```
   keytool -genkeypair -v -keystore ~/chip-release.jks -alias chip -keyalg RSA -keysize 4096 -validity 10000
   cd ~/deskbuddy
   base64 -w0 ~/chip-release.jks | gh secret set ANDROID_KEYSTORE_B64
   gh secret set ANDROID_KEYSTORE_PASSWORD
   gh secret set ANDROID_KEY_ALIAS --body chip
   gh secret set ANDROID_KEY_PASSWORD
   ```
   Back up `~/chip-release.jks` and both passwords (password manager + a USB stick).

Before the friend test (M2):
7. Friends: one Windows 10/11 laptop and one Mac with Apple Silicon (macOS 14+), ~30 min each, on the same Wi-Fi as
   an Android phone (theirs or yours). Send them `docs/port/TESTING.md` (T11 writes it) and the beta link.
8. Android developer verification: register in the Android Developer Console before Google's rule reaches India
   (it starts in 4 countries in Sept 2026, then goes global from 2027). The free limited-distribution account covers
   up to 20 devices, which is enough for the beta. Public distribution needs full verification.

Before a public v1.0 (optional, costs money):
9. Apple Developer Program ($99/yr): no "Open Anyway" step, and Accessibility survives updates. A Windows code-signing
   certificate: no SmartScreen warning, and Smart App Control won't block Chip.

## Which model, effort, session
| Step | What | Model | Effort | Why |
|---|---|---|---|---|
| T0 | Repo prep, secret scan | Haiku 5.5 | low | mechanical |
| T1 | Platform layer + selftest | Opus 5.5 | high | refactor of a 2,300-line file that mustn't break Linux |
| T2 | App mode in the bridge | Opus 5.5 | high | security: LAN listener, pairing, typing |
| R1 | Review T1–T2 | Opus 5.5 | high | security review |
| T3 | Android app shell, pairing, pinned TLS | Opus 5.5 | high | new app + certificate pinning |
| T4 | Android phone API + dictation | Sonnet 5.5 | high | big but clear spec (copy server.py's contract) |
| R2 | Review the Android app | Opus 5.5 | high | pinning must be airtight |
| T5 | CI on 4 platforms | Sonnet 5.5 | medium | standard YAML |
| T6 | Windows backend | Sonnet 5.5 | high | blind, but CI can test typing end to end |
| T7 | macOS backend | Opus 5.5 | high | blind, and CI can't test macOS permissions |
| T8 | AI-agent hooks installer | Sonnet 5.5 | medium | JSON edits + a card |
| T9 | Speech models + whisper binaries | Sonnet 5.5 | medium | downloads + checksums |
| T10 | Packaging + release pipeline | Sonnet 5.5 | high | fiddly but well-trodden |
| R3 | Pre-release review | Sonnet 5.5 | medium | routine review |
| T11 | Friend test kit | Haiku 5.5 | medium | writing |
| T12 | User docs | Haiku 5.5 | medium | writing |
| F | Fixes from a friend's report | Opus 5.5 | high | debugging without the device |

Every row is a new session (`/clear`). The only same-session follow-ups are the second messages listed under R1, R2
and R3, and your replies to a task's own questions.

## The prompts

**T0** (Haiku 5.5, low)
```
Task T0 of docs/port/PLAN.md: read its Overview, Rules and "## T0" section only (grep -n '^## ' to find them), then do T0. Ask me for the licence before adding it.
```

**T1** (Opus 5.5, high)
```
Task T1 of docs/port/PLAN.md: read Overview, Rules and "## T1" only. This is a move, not a rewrite: Linux must behave exactly as now. Save the golden JSON shapes from the running bridge before you change anything and diff them after. Grep bridge.py for what you need instead of reading it whole. When the checks pass, tell me the two things to try on the phone, then tick T1 and commit.
```

**T2** (Opus 5.5, high)
```
Task T2 of docs/port/PLAN.md: read Overview, Rules and "## T2" only. This is security-critical: before coding, list in the scratchpad the abuse cases you will test, then implement and prove each one in test_appmode.py and with curl against the live listener. Put it in a new module; bridge.py only wires it in.
```

**R1** (Opus 5.5, high)
```
/code-review high port --fix
```
then, in the same session:
```
Rerun test_appmode.py and selftest, tick R1 in docs/port/PLAN.md and commit "R1: review fixes".
```

**T3** (Opus 5.5, high)
```
Task T3 of docs/port/PLAN.md: read Overview, Rules and "## T3" only. JDK 21 and the Android SDK (~/Android/Sdk) are installed; check them, and if something is missing tell me the command instead of installing it. Keep the build light (~5 GB RAM here). When it builds, serve the APK as the section says and walk me through the phone test step by step.
```

**T4** (Sonnet 5.5, high)
```
Task T4 of docs/port/PLAN.md: read Overview, Rules and "## T4" only. Read phone/server.py, phone/dictation.py and phone/alert.py first: the app must answer exactly like them. Grep buddy.js for the dictation and drawer code; don't read it whole. Then build, serve the APK and give me the phone checklist.
```

**R2** (Opus 5.5, high)
```
/code-review high android/ --fix
```
then, in the same session:
```
Build the APK, tick R2 in docs/port/PLAN.md, commit "R2: review fixes". Then merge port into main (fast-forward) and push main and port.
```

**T5** (Sonnet 5.5, medium)
```
Task T5 of docs/port/PLAN.md: read Overview, Rules and "## T5" only. You may push branch port for this task. Watch the runs with gh and fix until all four jobs are green.
```

**T6** (Sonnet 5.5, high)
```
Task T6 of docs/port/PLAN.md: read Overview, Rules and "## T6" only. I have no Windows machine, so CI is your test bench: put every check you can into the windows job (struct sizes, selftest caps, the Notepad typing test). You may push branch port. Stop at green CI plus a short list of what only a real person can test, not at "should work".
```

**T7** (Opus 5.5, high)
```
Task T7 of docs/port/PLAN.md: read Overview, Rules and "## T7" only. I have no Mac, so CI is the only test bench: prove the ctypes signatures there (events read back, idle number, lock dictionary) and list what only the friend test can confirm. You may push branch port.
```

**T8** (Sonnet 5.5, medium)
```
Task T8 of docs/port/PLAN.md: read Overview, Rules and "## T8" only. My current hooks call python3 -I /home/aman/deskbuddy/laptop/attention.py; the installer must recognise them. Test only with a temp HOME and ask before touching my real settings files.
```

**T9** (Sonnet 5.5, medium)
```
Task T9 of docs/port/PLAN.md: read Overview, Rules and "## T9" only. Take the model checksums from my existing files in ~/.local/share/deskbuddy/stt/models. Download the Windows zip only once, just to pin its SHA-256.
```

**T10** (Sonnet 5.5, high)
```
Task T10 of docs/port/PLAN.md: read Overview, Rules and "## T10" only. The Android keystore secrets are set in GitHub. You may push branch port and test the release workflow with the tag v0.0.1-test.1; delete that tag and its draft release afterwards.
```

**R3** (Sonnet 5.5, medium)
```
/code-review medium laptop/platforms/ --fix
```
then `/code-review medium packaging/ --fix`, then:
```
Run the checks from the Rules, tick R3 in docs/port/PLAN.md and commit. Then tag v0.1.0-beta.1 and push the tag.
```

**T11** (Haiku 5.5, medium)
```
Task T11 of docs/port/PLAN.md: read Overview, Rules and "## T11" only. Write for people who aren't developers. Use only facts from the plan and the code (dashboard.html labels, chip report fields).
```

**T12** (Haiku 5.5, medium)
```
Task T12 of docs/port/PLAN.md: read Overview, Rules and "## T12" only. Plain words, only facts from the plan and the code. Keep INSTALL.md under 150 lines.
```

**F** (Opus 5.5, high; one session per report)
```
Friend-test fixes: read Overview, Rules and "## F" of docs/port/PLAN.md. Platform: <Windows or macOS>. The chip report and the friend's notes are below.
<paste the chip report JSON>
<paste the notes>
```
