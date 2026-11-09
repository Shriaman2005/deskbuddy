"""The dashboard's "AI agents" card: puts Chip's attention hook into Claude Code, Gemini CLI and opencode, and takes it out.

Claude Code: ~/.claude/settings.json (hooks Notification, Stop). Gemini CLI: ~/.gemini/settings.json (hooks
Notification, AfterAgent). opencode: the plugin file ~/.config/opencode/plugin/deskbuddy-attention.js.
Each hook runs `<python> -I <repo>/laptop/attention.py claude-code|gemini`.

Edits keep everything else in the file, back it up once to <file>.chip-bak, are idempotent, and recognise any
existing Chip hook (a command naming attention.py with claude-code/gemini, whatever python or folder it uses).
Remove takes out only Chip's entries. A file that isn't valid JSON is never touched. HOME is read on every call, so a
test can point it at a temp folder."""
import json
import os
import shutil
import sys

from platforms import paths, proc

ATTENTION = paths.laptop("attention.py")
PLUGIN_NAME = "deskbuddy-attention.js"
PLUGIN = """// Desk buddy: blinks the phone's torch when opencode needs you (asks for permission, or finishes and waits).
// Tells the bridge (laptop/bridge.py); does nothing if it isn't running. Installed by the dashboard's AI agents card.
export const DeskbuddyAttention = async ({ directory }) => {
  const project = (directory || "").split(/[\\\\/]/).filter(Boolean).pop() || "";
  const tell = (kind, text) =>
    fetch("http://127.0.0.1:8765/attention", {
      method: "POST",
      body: JSON.stringify({ source: "opencode", kind, text, project }),
      signal: AbortSignal.timeout(2000),
    }).catch(() => {});
  return {
    event: async ({ event }) => {
      if (event.type === "permission.asked" || event.type === "permission.updated") await tell("ask", "needs your permission");
      else if (event.type === "session.idle") await tell("done", "finished, waiting for you");
    },
  };
};
"""

# agent id -> label, file under HOME, hook events
AGENTS = {
    "claude-code": {"label": "Claude Code", "file": (".claude", "settings.json"), "events": ("Notification", "Stop"), "exe": "claude"},
    "gemini": {"label": "Gemini CLI", "file": (".gemini", "settings.json"), "events": ("Notification", "AfterAgent"), "exe": "gemini"},
    "opencode": {"label": "opencode", "file": (".config", "opencode", "plugin", PLUGIN_NAME), "events": (), "exe": "opencode"},
}


class HookError(Exception):
    """Something the user can fix; the message is shown on the card."""


def home():
    return os.path.expanduser("~")


def target(agent):
    return os.path.join(home(), *AGENTS[agent]["file"])


def _short(path):
    """Windows: the 8.3 form of a path with spaces (no quoting needed in cmd, PowerShell or Git Bash), else the path."""
    if os.name != "nt" or " " not in path:
        return path
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(520)
        if 0 < ctypes.windll.kernel32.GetShortPathNameW(path, buf, 520) < 520 and " " not in buf.value:
            return buf.value
    except (OSError, AttributeError):
        pass
    return path


def python_exe():
    """python3 on Linux (as before); elsewhere the venv's python the bridge runs in (pythonw -> python)."""
    if sys.platform.startswith("linux"):
        return "python3"
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base.startswith("pythonw"):
        exe = os.path.join(os.path.dirname(exe), "python" + os.path.splitext(base)[1])
    return exe


def command(agent):
    """The hook command line. Windows: forward slashes (Git Bash eats backslashes; cmd and PowerShell accept them),
    8.3 names so there is nothing to quote; if a path still has a space it is double-quoted (works in Git Bash)."""
    parts = [python_exe(), ATTENTION]
    if os.name == "nt":
        parts = [_short(p).replace("\\", "/") for p in parts]
    parts = [f'"{p}"' if " " in p else p for p in parts]
    return f"{parts[0]} -I {parts[1]} {agent}"


def _is_chip(entry, agent):
    cmd = entry.get("command") if isinstance(entry, dict) else None
    return isinstance(cmd, str) and "attention.py" in cmd and cmd.rstrip().endswith(agent)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise HookError(f"can't read {path}: {e.strerror}")
    if not text.strip():
        return {}
    try:
        data = json.loads(text.lstrip("﻿"))
    except ValueError:
        raise HookError(f"{path} isn't plain JSON (comments or a typo?), so Chip left it alone")
    if not isinstance(data, dict):
        raise HookError(f"{path} isn't a JSON object, so Chip left it alone")
    return data


def _write(path, data, backup=True):
    """backup: keep the file as it was before Chip's first edit. Removing never makes one (it would only hold Chip's own hooks)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if backup and os.path.exists(path) and not os.path.exists(path + ".chip-bak"):
        shutil.copy2(path, path + ".chip-bak")
    tmp = path + ".chip-tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _hooks(data, create=False):
    hooks = data.get("hooks")
    if hooks is None:
        if not create:
            return {}
        hooks = data["hooks"] = {}
    if not isinstance(hooks, dict):
        raise HookError("the file's \"hooks\" isn't an object, so Chip left it alone")
    return hooks


def _chip_entries(groups, agent):
    """Every Chip hook entry (dict) in an event's list of groups."""
    out = []
    for g in groups if isinstance(groups, list) else []:
        for h in (g.get("hooks") if isinstance(g, dict) and isinstance(g.get("hooks"), list) else []):
            if _is_chip(h, agent):
                out.append(h)
    return out


def _new_entry(agent):
    cmd = command(agent)
    if agent == "gemini":
        return {"matcher": "*", "hooks": [{"name": "deskbuddy-torch", "type": "command", "command": cmd,
                                           "description": "Blink the desk buddy phone's torch when Gemini needs you",
                                           "timeout": 5000}]}
    return {"hooks": [{"type": "command", "command": cmd, "timeout": 5, "async": True}]}


def on_laptop(agent):
    """Is this agent on the laptop? Its command is on PATH, or its settings folder exists (a fresh install makes one)."""
    import shutil
    spec = AGENTS[agent]
    return bool(shutil.which(spec["exe"])) or os.path.isdir(os.path.dirname(target(agent)))


def status(agent):
    """{id, label, file, installed, current, note?}. installed = every event has a Chip hook; current = and it is
    the command this install would write (False: the repo or python moved, Install refreshes it)."""
    spec = AGENTS[agent]
    path = target(agent)
    info = {"id": agent, "label": spec["label"], "file": path, "installed": False, "current": False, "found": on_laptop(agent)}
    try:
        if agent == "opencode":
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                info["installed"] = "DeskbuddyAttention" in text
                info["current"] = text == PLUGIN
                if not info["installed"]:
                    info["note"] = "A different file with this name is there; Chip won't overwrite it"
            return info
        hooks = _hooks(_read(path))
        found = [_chip_entries(hooks.get(ev), agent) for ev in spec["events"]]
        info["installed"] = all(found)
        info["current"] = info["installed"] and all(h.get("command") == command(agent) for hs in found for h in hs)
        if any(found) and not info["installed"]:
            info["note"] = "Only some of the hooks are there; Install adds the rest"
    except HookError as e:
        info["note"] = str(e)
    return info


def listing():
    return {"agents": [status(a) for a in AGENTS]}


def install(agent):
    spec = AGENTS[agent]
    path = target(agent)
    if agent == "opencode":
        if os.path.exists(path) and not status(agent)["installed"]:
            raise HookError(f"{path} exists and isn't Chip's, so Chip left it alone")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(PLUGIN)
        return status(agent)
    data = _read(path)
    hooks = _hooks(data, create=True)
    cmd = command(agent)
    for ev in spec["events"]:
        groups = hooks.get(ev)
        if groups is None:
            groups = hooks[ev] = []
        if not isinstance(groups, list):
            raise HookError(f"the \"{ev}\" hook in {path} isn't a list, so Chip left it alone")
        mine = _chip_entries(groups, agent)
        if mine:
            for h in mine:
                h["command"] = cmd  # refresh a moved repo/python; the rest of the entry stays as the user has it
        else:
            groups.append(_new_entry(agent))
    _write(path, data)
    return status(agent)


def remove(agent):
    spec = AGENTS[agent]
    path = target(agent)
    if agent == "opencode":
        if os.path.exists(path):
            if not status(agent)["installed"]:
                raise HookError(f"{path} isn't Chip's, so Chip left it alone")
            os.remove(path)
        return status(agent)
    if not os.path.exists(path):
        return status(agent)
    data = _read(path)
    hooks = _hooks(data)
    changed = False
    for ev in spec["events"]:
        groups = hooks.get(ev)
        if not isinstance(groups, list):
            continue
        kept = []
        for g in groups:
            inner = g.get("hooks") if isinstance(g, dict) else None
            if isinstance(inner, list) and any(_is_chip(h, agent) for h in inner):
                changed = True
                inner[:] = [h for h in inner if not _is_chip(h, agent)]
                if not inner:
                    continue  # the group held only Chip's hook
            kept.append(g)
        if len(kept) != len(groups):
            changed = True
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]
    if changed:
        if not hooks:
            data.pop("hooks", None)
        _write(path, data, backup=False)
    return status(agent)


def test(agent):
    """Runs the hook exactly as the agent would (same command, a sample event on stdin, no shell): the bridge shows an alert."""
    if agent == "opencode":
        raise HookError("opencode's plugin runs inside opencode; start opencode and let it ask for permission")
    sample = {"hook_event_name": "Notification", "message": "Chip test", "cwd": os.getcwd()}
    argv = [python_exe(), "-I", "-X", "utf8", ATTENTION, agent]
    try:
        r = proc.complete(argv, timeout=10, input=json.dumps(sample))
    except (OSError, proc.TimeoutExpired, proc.SubprocessError) as e:
        raise HookError(f"couldn't run {python_exe()}: {e}")
    if r.returncode:
        raise HookError((r.stderr or r.stdout or "the hook failed").strip()[-300:])
    return {"ok": True}


def handle(action, agent):
    """('install'|'remove'|'test', agent id) -> (http status, JSON body). The bridge calls this for POST /hooks/<action>."""
    if agent not in AGENTS or action not in ("install", "remove", "test"):
        return 400, {"ok": False, "error": "bad_request", "message": "unknown agent or action"}
    try:
        out = {"install": install, "remove": remove, "test": test}[action](agent)
    except HookError as e:
        return 200, {"ok": False, "error": "hooks", "message": str(e)}
    return 200, dict(out, ok=True) if action != "test" else out
