#!/usr/bin/env python3
"""hooks.py against a temp HOME: install/remove for Claude Code, Gemini CLI and opencode keep everything else,
recognise the user's existing `python3 -I .../attention.py` lines, back up once, are idempotent, and refuse bad JSON.
Run: python3 -I laptop/tests/test_hooks.py   (never touches the real home folder)"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
tmp = tempfile.mkdtemp(prefix="chip-hooks-")
os.environ["HOME"] = os.environ["USERPROFILE"] = tmp
os.environ["CHIP_CONFIG_DIR"] = os.path.join(tmp, "cfg")
import hooks  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def load(agent):
    with open(hooks.target(agent), encoding="utf-8") as f:
        return json.load(f)


def put(agent, data):
    os.makedirs(os.path.dirname(hooks.target(agent)), exist_ok=True)
    with open(hooks.target(agent), "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, indent=2))


check("temp home in use", hooks.home() == tmp, hooks.home())
check("nothing installed in an empty home", not any(a["installed"] for a in hooks.listing()["agents"]))

# the user's existing hooks (copied from their real files): recognised, left as they are
old = "python3 -I /home/aman/deskbuddy/laptop/attention.py claude-code"
put("claude-code", {"theme": "dark", "hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}],
    "Notification": [{"hooks": [{"type": "command", "command": old, "timeout": 5, "async": True}]}],
    "Stop": [{"hooks": [{"type": "command", "command": old, "timeout": 5, "async": True}]}]}})
st = hooks.status("claude-code")
check("existing python3 -I lines count as installed", st["installed"], st)
before = json.dumps(load("claude-code"), sort_keys=True)
hooks.install("claude-code")
after = load("claude-code")
if hooks.command("claude-code") == old:
    check("install on the user's lines changes nothing", json.dumps(after, sort_keys=True) == before)
else:  # another python/folder: only the command is refreshed
    check("install refreshes only the command", after["hooks"]["Stop"][0]["hooks"][0]["command"] == hooks.command("claude-code")
          and after["hooks"]["Stop"][0]["hooks"][0]["timeout"] == 5 and after["theme"] == "dark")
check("a backup is made", os.path.exists(hooks.target("claude-code") + ".chip-bak"))
hooks.install("claude-code")
check("install is idempotent (one Chip entry per event)",
      all(len(load("claude-code")["hooks"][e]) == 1 for e in ("Notification", "Stop")))
hooks.remove("claude-code")
after = load("claude-code")
check("remove leaves everything else", after["theme"] == "dark" and after["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "echo hi"
      and "Notification" not in after["hooks"] and "Stop" not in after["hooks"], after)
check("not installed after remove", not hooks.status("claude-code")["installed"])
bak = open(hooks.target("claude-code") + ".chip-bak", encoding="utf-8").read()
check("the backup is the original (made once)", old in bak)
hooks.install("claude-code")
check("install after remove adds both events", hooks.status("claude-code")["installed"])
hooks.remove("claude-code")

# a group shared with the user's own hook: only Chip's entry goes
put("gemini", {"hooks": {"AfterAgent": [{"matcher": "*", "hooks": [
    {"name": "mine", "type": "command", "command": "echo mine"},
    {"name": "deskbuddy-torch", "type": "command", "command": "python3 -I /x/attention.py gemini"}]}]}})
check("gemini line recognised under any path", hooks.status("gemini")["note"].startswith("Only some"), hooks.status("gemini"))
hooks.install("gemini")
g = load("gemini")
check("gemini: both events, user's hook kept", hooks.status("gemini")["installed"]
      and g["hooks"]["AfterAgent"][0]["hooks"][0]["command"] == "echo mine" and g["hooks"]["Notification"][0]["matcher"] == "*", g)
hooks.remove("gemini")
g = load("gemini")
check("gemini remove: only Chip's go, hooks key emptied", g["hooks"]["AfterAgent"][0]["hooks"] == [
    {"name": "mine", "type": "command", "command": "echo mine"}] and "Notification" not in g["hooks"], g)

# bad JSON is never overwritten
put("claude-code", "{ // comment\n}")
r = hooks.handle("install", "claude-code")[1]
check("invalid JSON refused, file untouched", not r["ok"] and open(hooks.target("claude-code")).read() == "{ // comment\n}", r)
check("bad request rejected", hooks.handle("install", "nope")[0] == 400 and hooks.handle("explode", "gemini")[0] == 400)

# opencode plugin
hooks.install("opencode")
check("opencode plugin written", hooks.status("opencode")["installed"] and hooks.status("opencode")["current"])
hooks.remove("opencode")
check("opencode plugin removed", not os.path.exists(hooks.target("opencode")))
put_path = hooks.target("opencode")
os.makedirs(os.path.dirname(put_path), exist_ok=True)
open(put_path, "w").write("// someone else's plugin\n")
r = hooks.handle("install", "opencode")[1]
hooks.handle("remove", "opencode")
check("a foreign opencode file is never overwritten or removed",
      not r["ok"] and open(put_path).read() == "// someone else's plugin\n", r)

# command form
cmd = hooks.command("gemini")
check("command shape", cmd.endswith("attention.py gemini") or cmd.endswith('attention.py" gemini'), cmd)
print("\nFAILED: " + ", ".join(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
