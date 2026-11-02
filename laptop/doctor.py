#!/usr/bin/env python3
"""Checks every link of the desk buddy and says what to do about the ones that are down.
Run: python3 -I ~/deskbuddy/laptop/doctor.py   (exit status 1 if anything failed)
The Laptop part is per OS (Linux: the systemd service and GNOME extension; Windows: the HKCU Run entry; macOS: the
LaunchAgent), then the same Wi-Fi link and phone checks everywhere, over the pinned ssh (sshlink.py)."""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I skips the script's folder
import sshlink  # noqa: E402
from platforms import proc  # noqa: E402

BRIDGE = f"http://127.0.0.1:{os.environ.get('CHIP_PORT') or 8765}"
failed = 0
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ✓ and → on a Windows console too


def check(ok, what, fix=""):
    global failed
    failed += not ok
    print(f"  {'✓' if ok else '✗'} {what}" + ("" if ok else f"\n      → {fix}"))
    return ok


def run(*cmd, timeout=15):
    return proc.run(*cmd, timeout=timeout)


def get(path):
    try:
        with urllib.request.urlopen(BRIDGE + path, timeout=4) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


def laptop_linux():
    check(run("systemctl", "--user", "is-active", "deskbuddy-bridge") == "active", "bridge service running",
          "systemctl --user restart deskbuddy-bridge   (journalctl --user -u deskbuddy-bridge -n 30)")
    check(run("systemctl", "--user", "is-enabled", "deskbuddy-bridge") == "enabled", "bridge starts at boot",
          "bash ~/deskbuddy/laptop/install.sh")
    check("Linger=yes" in run("loginctl", "show-user", os.environ.get("USER", "")), "runs before you log in (linger)",
          "bash ~/deskbuddy/laptop/install.sh")
    gaze = run("gdbus", "call", "--session", "--dest", "org.deskbuddy.Gaze", "--object-path", "/org/deskbuddy/Gaze",
               "--method", "org.deskbuddy.Gaze.Monitors")
    info = run("gnome-extensions", "info", "chip-gaze@deskbuddy")
    if "Name:" not in info:
        gaze_fix = "bash ~/deskbuddy/laptop/install.sh, then log out and back in"  # the extension isn't linked
    elif "Enabled: No" in info:
        gaze_fix = "gnome-extensions enable chip-gaze@deskbuddy, then log out and back in"
    else:
        gaze_fix = "enabled but not loaded yet: log out and back in (GNOME loads it at login)"
    check(bool(gaze), "eyes-follow extension answers on the session bus (only for the cursor)", gaze_fix)


def ssh_and_key():
    miss = sshlink.missing()
    check(not miss, "ssh found" if not miss else f"ssh found ({', '.join(miss)} missing)",
          sshlink.OPENSSH_FIX if sys.platform == "win32" else "install OpenSSH's client")
    check(bool(sshlink.public_key()), "Chip's ssh key present" + (" (its own)" if sshlink.own_key() else ""),
          "run laptop/install.py again (it makes the key)")


def laptop_windows():
    from platforms import windows
    check(get("/link") is not None, f"bridge answering on {BRIDGE[7:]}", "log out and back in, or run laptop/install.py again")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, windows.RUN_KEY) as k:
            entry = winreg.QueryValueEx(k, windows.RUN_VALUE)[0]
    except OSError:
        entry = ""
    check("supervise.py" in entry, "bridge starts at login (HKCU Run → supervise.py)", "run laptop/install.py again")
    ssh_and_key()


def laptop_macos():
    from platforms import macos
    check(get("/link") is not None, f"bridge answering on {BRIDGE[7:]}", "log out and back in, or run laptop/install.py again")
    check(bool(run("launchctl", "print", f"gui/{os.getuid()}/{macos.LAUNCH_AGENT}")),
          f"LaunchAgent {macos.LAUNCH_AGENT} loaded", "run laptop/install.py again")
    ssh_and_key()
    print("  · Accessibility (typing dictated text) isn't checked yet")


print("Laptop")
{"win32": laptop_windows, "darwin": laptop_macos}.get(sys.platform, laptop_linux)()

print("Wi-Fi link")
link = get("/link")
if not check(link is not None, f"bridge answers on {BRIDGE[7:]}", "start the bridge (see above)"):
    sys.exit(1)
check(link["pinned"], "phone's ssh key pinned", "open Termux on the phone once; the bridge pins its key when it connects")
why = link.get("reason")  # why the tunnel is down (None when it's up), see PhoneLink.reason()
check(why != "paused", "link not paused", "dashboard: Connections, turn off “Pause the link”")
check(why != "not home network", "laptop on a home network" + (f" ({link['laptop']['ssid']})" if link.get("laptop", {}).get("ssid") else ""),
      "join a network listed in linkNetworks, or turn off “Only on home networks” in the dashboard")
check(why != "key mismatch", "something at the phone's address presents the pinned key",
      "a different device answers there, or the phone was reset: dashboard, Connections, “Replace phone”")
check(link["tunnel"], f"ssh tunnel up to {link['ip']}",
      "phone and laptop on the same Wi-Fi? Termux open (or Termux:Boot installed)? The bridge rescans the network by itself")
if link.get("files"):  # PhoneLink.sync_files: the phone's copy of phone/, checked when the tunnel comes up
    check(link["files"] != "failed", f"phone's files match the laptop's ({link['files']})",
          f"python3 -I laptop/deploy.py (or ./deploy.sh) and read its error: {link.get('files_detail') or 'deploy failed'}")
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
command -v pulseaudio >/dev/null && echo pulseinst=1
[ -x ~/.termux/boot/deskbuddy ] && echo boot=1
[ -f ~/stt/whisper-cli ] && echo stt=1
"""
out = run(*sshlink.command(ip, link.get("port", 8022), script, timeout=6)) if ip else ""  # the pinned key only
f = dict(l.split("=") for l in out.split() if "=" in l)
if check(f.get("sshd") == "1", "can ssh into Termux", "open Termux on the phone; check the phone's Wi-Fi"):
    check(f.get("supervisor") == "1", "supervisor running", "in Termux: chip-start")
    check(f.get("server") == "1", "face server on :8080", "in Termux: chip-start")
    check(f.get("tunnel") == "1", "phone reaches the bridge through the tunnel", "wait ~45 s (an old tunnel is timing out) and re-run")
    check(f.get("pulseinst") == "1", "PulseAudio installed (alert sounds and the mic)", "in Termux: pkg install pulseaudio")
    # optional: an always-on phone wants Termux:Boot, and only the phone engine needs the speech build
    print("  " + ("✓ Termux:Boot script in place" if f.get("boot") == "1" else
                  "· no Termux:Boot script: Chip starts when you open Termux (an always-on phone: ./deploy.sh, then open Termux:Boot once)"))
    print("  " + ("✓ offline speech engine installed" if f.get("stt") == "1" else
                  "· no offline speech engine (only the Phone dictation engine needs it): in Termux, bash ~/deskbuddy/stt-setup.sh"))
    if f.get("pulse") != "1":
        print("  · PulseAudio isn't running yet: normal, it starts on the first dictation or alert")
sys.exit(1 if failed else 0)
