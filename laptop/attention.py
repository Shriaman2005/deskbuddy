#!/usr/bin/env python3
"""Tells the desk buddy that an AI agent needs you: the phone's torch blinks and Chip says who.

Agent hooks run it with the hook's JSON on stdin:
    attention.py claude-code    (Claude Code: Notification and Stop hooks, ~/.claude/settings.json)
    attention.py gemini         (Gemini CLI: Notification and AfterAgent hooks, ~/.gemini/settings.json)
Only the event type, the alert's short message and the project folder's name are passed on, never prompts
or replies. It never fails or slows down the agent: errors are ignored and the bridge gets 2 s at most.
"""
import json
import os
import sys
import urllib.request

BRIDGE = "http://127.0.0.1:8765/attention"


def event(source, hook):
    """(name, kind, text) for a hook's input, or None if it isn't worth a blink."""
    name = hook.get("hook_event_name", "")
    message = str(hook.get("message") or "").strip()
    if source == "claude-code":
        if name == "Stop":
            return "Claude Code", "done", "finished, waiting for you"
        if name == "Notification":
            kind = hook.get("notification_type", "")
            if kind in ("idle_prompt", "auth_success"):  # idle: the buddy keeps reminding you itself
                return None
            return "Claude Code", "ask", message or "needs your input"
    if source == "gemini":
        if name == "AfterAgent" and not hook.get("stop_hook_active"):
            return "Gemini CLI", "done", "finished, waiting for you"
        if name == "Notification":
            return "Gemini CLI", "ask", message or "needs your permission"
    return None


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else ""
    if source == "gemini":
        print("{}")  # Gemini CLI reads hook output as JSON
    try:
        hook = json.load(sys.stdin)
        found = event(source, hook)
    except (ValueError, AttributeError):
        return
    if not found:
        return
    name, kind, text = found
    project = os.path.basename(os.path.normpath(str(hook.get("cwd") or "")))
    body = json.dumps({"source": name, "kind": kind, "text": text[:120], "project": project}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(BRIDGE, data=body, method="POST"), timeout=2).close()
    except OSError:
        pass  # bridge not running


if __name__ == "__main__":
    main()
