#!/usr/bin/env python3
"""Checks every link of the desk buddy and says what to do about the ones that are down.
Run: python3 -I ~/deskbuddy/laptop/doctor.py   (exit status 1 if anything failed)"""
import json
import os
import subprocess
import sys
import urllib.request

BRIDGE = "http://127.0.0.1:8765"
KNOWN_HOSTS = os.path.expanduser("~/.config/deskbuddy/known_hosts")
STATE = os.path.expanduser("~/.config/deskbuddy/state.json")
failed = 0


def check(ok, what, fix=""):
    global failed
    failed += not ok
    print(f"  {'✓' if ok else '✗'} {what}" + ("" if ok else f"\n      → {fix}"))
    return ok


def run(*cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def get(path):
    try:
        with urllib.request.urlopen(BRIDGE + path, timeout=4) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


print("Laptop")
check(run("systemctl", "--user", "is-active", "deskbuddy-bridge") == "active", "bridge service running",
      "systemctl --user restart deskbuddy-bridge   (journalctl --user -u deskbuddy-bridge -n 30)")
check(run("systemctl", "--user", "is-enabled", "deskbuddy-bridge") == "enabled", "bridge starts at boot",
      "bash ~/deskbuddy/laptop/install.sh")
check("Linger=yes" in run("loginctl", "show-user", os.environ.get("USER", "")), "runs before you log in (linger)",
      "bash ~/deskbuddy/laptop/install.sh")

print("Wi-Fi link")
link = get("/link")
if not check(link is not None, "bridge answers on 127.0.0.1:8765", "start the bridge (see above)"):
    sys.exit(1)
check(link["pinned"], "phone's ssh key pinned", "open Termux on the phone once; the bridge pins its key when it connects")
check(link["tunnel"], f"ssh tunnel up to {link['ip']}",
      "phone and laptop on the same Wi-Fi? Termux open (or Termux:Boot installed)? The bridge rescans the network by itself")
phone = get("/phone") or {}
check(bool(phone) and phone.get("age", 999) < 15, "face page on the phone is checking in" +
      (f" ({phone['age']:.0f} s ago)" if phone else ""), "open the Chip app (kiFOSSk) on the phone")

print("Phone (Termux)")
ip = link.get("ip")
script = r"""
pgrep -x sshd >/dev/null && echo sshd=1
pgrep -f "[d]eskbuddy/supervisor.sh" >/dev/null && echo supervisor=1
curl -s -m3 -o /dev/null 127.0.0.1:8080/ && echo server=1
curl -s -m3 -o /dev/null 127.0.0.1:8765/phone && echo tunnel=1
pactl info >/dev/null 2>&1 && echo pulse=1
[ -x ~/.termux/boot/deskbuddy ] && echo boot=1
[ -f ~/stt/whisper-cli ] && echo stt=1
"""
out = run("ssh", "-p", "8022", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
          "-o", "GlobalKnownHostsFile=/dev/null", "-o", "HostKeyAlias=chip-phone", "-o", "StrictHostKeyChecking=yes",
          ip or "", script) if ip else ""
f = dict(l.split("=") for l in out.split() if "=" in l)
if check(f.get("sshd") == "1", "can ssh into Termux", "open Termux on the phone; check the phone's Wi-Fi"):
    check(f.get("supervisor") == "1", "supervisor running", "in Termux: bash ~/deskbuddy/services.sh")
    check(f.get("server") == "1", "face server on :8080", "in Termux: bash ~/deskbuddy/services.sh")
    check(f.get("tunnel") == "1", "phone reaches the bridge through the tunnel", "wait ~45 s (an old tunnel is timing out) and re-run")
    check(f.get("boot") == "1", "Termux:Boot script in place", "bash ~/deskbuddy/deploy.sh, then open Termux:Boot once on the phone")
    check(f.get("stt") == "1", "offline speech engine installed", "see README: dictation setup")
    if f.get("pulse") != "1":
        print("  · PulseAudio isn't running yet: normal, it starts on the first dictation or alert")
sys.exit(1 if failed else 0)
