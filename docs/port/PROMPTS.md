# Stage 1 prompts (Windows/macOS over Termux + ssh, no installers)

The plan is in `docs/port/PLAN.md`. Its Status list shows what's done. Each prompt below starts one task.
Stage 2 (the Android app and installers) has its own plan and prompts in `docs/port/later/`. Leave them until Stage 1 is done.

## How to run a task (this is what saves tokens)
1. Start fresh: `/clear`. Old tasks are in the code, the commits and the plan, not in the chat.
2. `/model` → pick the model and effort from the table.
3. Paste the prompt. Stay in that session only for that task: its fixes, its tests, your answers to its questions.
4. When it's done, check that its Status line in PLAN.md is ticked, then `/clear` and start the next one.
- Long session? `/compact keep task Sn progress`. Stuck after one honest try? Raise the effort one step
  (high → xhigh → max) for that session only.
- Avoid: subagents/workflows ("ultracode"), `/code-review ultra` or `max`, pasting whole logs (paste the failing lines).
- "Where are we?" at any time: Haiku 5.5, low: `Read the Status section of docs/port/PLAN.md and git log --oneline -10. Tell me in 5 lines what's done and what's next.`

## Your setup steps
1. Now: `sudo apt install gh`, then `gh auth login` (GitHub.com, HTTPS, log in with the browser).
2. S0 asks for a licence (MIT is simplest).
3. Before S4: make the repo public if S0's secret scan is clean. CI on Windows/macOS is then free, and friends can
   download the ZIP: `gh repo edit Shriaman2005/deskbuddy --visibility public --accept-visibility-change-consequences`
4. For S3: your personal phone with Termux and Termux:API, both from F-Droid (https://f-droid.org). Installing one from
   F-Droid and the other from somewhere else doesn't work. Afterwards you re-pair the M01 Core (one phone at a time).
5. Before the friend test: one friend with Windows 10/11 and one with a Mac (macOS 14+), ~30–45 min each. Each needs
   Python 3.12+ from python.org (on Windows, tick "Add python.exe to PATH") and an Android phone with Termux and
   Termux:API from F-Droid (theirs, or yours: then re-pair yours at home afterwards).

Stage 1 doesn't need the Android SDK, a signing key, code signing or Android developer registration.

## Which model, effort, session
| Step | What | Model | Effort | Why |
|---|---|---|---|---|
| S0 | Repo prep, secret scan | Haiku 5.5 | low | mechanical |
| S1 | Platform layer + selftest | Opus 5.5 | high | refactor of a 2,300-line file that mustn't break Linux |
| S2 | Link, pairing, deploy on every OS + fake phone | Opus 5.5 | high | the pinned ssh link is the security core |
| S3 | Phone side for any Android phone | Sonnet 5.5 | high | clear spec, you test it on your phone |
| S4 | CI on 3 OSes | Sonnet 5.5 | high | runner quirks (ssh on Windows/macOS) |
| S5 | Windows backend + install.py | Sonnet 5.5 | high | blind, but CI can run install and typing end to end |
| S6 | macOS backend + install.py | Opus 5.5 | high | blind, and CI can't test macOS permissions |
| S7 | AI-agent hooks card | Sonnet 5.5 | medium | JSON edits + a card |
| R1 | Review | Opus 5.5 | high | security review |
| S8 | Docs + friend test kit | Haiku 5.5 | medium | writing |
| M | Merge + beta tag | Haiku 5.5 | low | git only |
| F | Fixes from a friend's report | Opus 5.5 | high | debugging without the device |

Every row is a new session (`/clear`). The only same-session follow-up is R1's second message, plus your replies to a
task's own questions.

## The prompts

**S0** (Haiku 5.5, low)
```
Task S0 of docs/port/PLAN.md: read its Overview, Rules and "## S0" section only (grep -n '^## ' to find them), then do S0. Ask me for the licence before adding it.
```

**S1** (Opus 5.5, high)
```
Task S1 of docs/port/PLAN.md: read Overview, Rules and "## S1" only. This is a move, not a rewrite: Linux must behave exactly as now. Save the golden JSON shapes from the running bridge before you change anything and diff them after. Grep bridge.py for what you need instead of reading it whole. When the checks pass, tell me the two things to try on the phone, then tick S1 and commit.
```

**S2** (Opus 5.5, high)
```
Task S2 of docs/port/PLAN.md: read Overview, Rules and "## S2" only. The phone's host-key pinning must stay exactly as strict on every OS. Build the fake phone first and use it to prove the tunnel, rediscovery, pinning and deploy.py before touching my real link; then restart the bridge and run doctor. Test-only packages go into a venv in the scratchpad, nothing system-wide.
```

**S3** (Sonnet 5.5, high)
```
Task S3 of docs/port/PLAN.md: read Overview, Rules and "## S3" only. Read phone/setup.sh, phone/server.py and phone/dictation.py first; grep buddy.js and dashboard.html. I'll test on my personal phone with a fresh Termux: give me the steps one at a time, and ask before running anything on a phone. At the end, remind me to re-pair the M01 Core.
```

**S4** (Sonnet 5.5, high)
```
Task S4 of docs/port/PLAN.md: read Overview, Rules and "## S4" only. You may push branch port for this task. Watch the runs with gh and fix until all jobs are green; if a runner can't do something, write down which step and why.
```

**S5** (Sonnet 5.5, high)
```
Task S5 of docs/port/PLAN.md: read Overview, Rules and "## S5" only. I have no Windows machine, so CI is your test bench: install.py --ci, the bridge answering, the selftest caps and the Notepad typing test must all run there. You may push branch port. Stop at green CI plus a short list of what only a person can test, not at "should work".
```

**S6** (Opus 5.5, high)
```
Task S6 of docs/port/PLAN.md: read Overview, Rules and "## S6" only. I have no Mac, so CI is the only test bench: install.py --ci, the bridge answering and the ctypes read-back tests run there. List what only the friend test can confirm (Accessibility, real typing, certificates). You may push branch port.
```

**S7** (Sonnet 5.5, medium)
```
Task S7 of docs/port/PLAN.md: read Overview, Rules and "## S7" only. My current hooks call python3 -I /home/aman/deskbuddy/laptop/attention.py; the card must recognise them. Test only with a temp HOME and ask before touching my real settings files.
```

**R1** (Opus 5.5, high)
```
/code-review high port --fix
```
then, in the same session:
```
Run the checks from the Rules and the fake-phone tests, tick R1 in docs/port/PLAN.md and commit "R1: review fixes".
```

**S8** (Haiku 5.5, medium)
```
Task S8 of docs/port/PLAN.md: read Overview, Rules and "## S8" only. Write for people who aren't developers, in plain words, using only facts from the plan and the code (dashboard.html labels, doctor.py output). Keep INSTALL.md under 150 lines.
```

**M** (Haiku 5.5, low)
```
Merge branch port into main (fast-forward), push main and port, then tag v0.1.0-beta.1 and push the tag. Tick the S8 line's "tag" note in docs/port/PLAN.md.
```

**F** (Opus 5.5, high; one fresh session per friend's report)
```
Friend-test fixes: read Overview, Rules and "## F" of docs/port/PLAN.md. Platform: <Windows or macOS>. The doctor output and the friend's notes are below.
<paste the doctor output>
<paste the notes>
```
