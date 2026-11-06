#!/usr/bin/env python3
"""Sets Chip up on this laptop, once (run it again to update or repair; it restarts Chip).
  Windows:  py -3 laptop/install.py         or double-click it
  macOS:    python3 laptop/install.py       (in Terminal, from the Chip folder)
  Linux:    laptop/install.sh               (this script only points there)
Windows steps: find Python 3.12+ (python.org's, not the Microsoft Store one), make a venv in
~/.local/share/deskbuddy/venv with laptop/requirements.txt, make Chip's own ssh key if there is none, start Chip at
login (HKCU Run -> pythonw supervise.py), start it now, wait for the bridge, open the dashboard.
macOS steps: find Python 3.12+ (python.org's or Homebrew's; the Xcode python3 is too old), check HTTPS certificates,
the same venv and key, a LaunchAgent (org.deskbuddy.bridge: starts at login, restarted if it stops, log in
~/Library/Logs/deskbuddy-bridge.log), wait for the bridge, open the dashboard and the Accessibility settings.
  --repair      same as a normal run, but throws the venv away and builds it again first (use it after a Python update
                or a broken venv). Settings, Chip's ssh key and phones.json stay; start-at-login stays as it was
                (on, or off if you had switched it off)
  --uninstall   remove the start-at-login entry and stop Chip; settings, keys and the venv stay
  --ci          no browser, no settings pane, no "press Enter" (for GitHub Actions)
Standard library only; the Python it runs under only needs to be 3.9+ to get as far as finding a newer one."""
import argparse
import glob
import os
import re
import shutil
import sys
import time

if sys.version_info < (3, 9):
    sys.exit("Chip needs Python 3.12 or newer: install it from https://www.python.org/downloads/")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I skips the script's folder
from platforms import paths, proc  # noqa: E402
from platforms.windows import RUN_KEY, RUN_VALUE  # noqa: E402
from platforms.macos import ACCESSIBILITY_PANE, LAUNCH_AGENT  # noqa: E402

IS_WIN = sys.platform == "win32"
REPO = paths.REPO
SUPERVISE = os.path.join(HERE, "supervise.py")
BRIDGE = os.path.join(HERE, "bridge.py")
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
VENV = paths.data("venv")
VENV_PY = os.path.join(VENV, "Scripts", "python.exe") if IS_WIN else os.path.join(VENV, "bin", "python")
VENV_PYW = os.path.join(VENV, "Scripts", "pythonw.exe")
PORT = int(os.environ.get("CHIP_PORT") or 8765)
DASHBOARD = f"http://127.0.0.1:{PORT}/"
NEEDS = (3, 12)
PYTHON_ORG = "https://www.python.org/downloads/" + (" (tick 'Add python.exe to PATH')" if IS_WIN else "")
PLIST = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", LAUNCH_AGENT + ".plist")
MAC_LOG = os.path.join(os.path.expanduser("~"), "Library", "Logs", "deskbuddy-bridge.log")
MAC_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"  # ssh, node, whisper-cli (Homebrew)
LOG_MAX = 1 << 20


def say(text=""):
    print(text, flush=True)


def fail(text):
    say("\nProblem: " + text)
    sys.exit(1)


# ---------------------------------------------------------------- finding Python

def is_store_python(path):
    """The Microsoft Store's Python runs in a sandbox that redirects the files Chip writes under your home folder."""
    return bool(re.search(r"WindowsApps|PythonSoftwareFoundation", path or "", re.I))


def version_of(exe):
    out = proc.run(exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])", timeout=15)
    m = re.fullmatch(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def launcher_pythons():
    """Paths of the Pythons the `py` launcher knows (py -0p), newest first."""
    out = proc.run("py", "-0p", timeout=15)
    found = []
    for line in out.splitlines():
        m = re.match(r"^\s*-(?:V:)?(\d+)\.(\d+)\S*\s+\*?\s*(\S.*python\w*\.exe)\s*$", line, re.I)
        if m:
            found.append(((int(m.group(1)), int(m.group(2))), m.group(3)))
    return [exe for _, exe in sorted(found, reverse=True)]


def mac_pythons():
    """Pythons a Mac may have besides the one running this: python.org's framework, Homebrew's, PATH's."""
    found = [shutil.which(f"python3.{minor}") for minor in range(20, NEEDS[1] - 1, -1)]
    for pattern in ("/Library/Frameworks/Python.framework/Versions/3.*/bin/python3",
                    "/opt/homebrew/bin/python3.*", "/usr/local/bin/python3.*"):
        found += sorted(glob.glob(pattern), reverse=True)
    return [p for p in found + [shutil.which("python3")] if p and re.search(r"python3(\.\d+)?$", p)]


def find_python():
    """(path, was_store_python_skipped) of a Python >= 3.12 that isn't the Store's. The one running this first."""
    skipped = False
    candidates = [sys.executable] + (launcher_pythons() if IS_WIN else mac_pythons())
    for exe in candidates:
        if is_store_python(exe):
            skipped = True
            continue
        v = sys.version_info[:2] if exe == sys.executable else version_of(exe)
        if v and v >= NEEDS:
            return exe, skipped
    return None, skipped


# ---------------------------------------------------------------- shared steps

def bridge_answers():
    import supervise
    return supervise.chip_answers()


def wait_until_stopped(seconds=10):
    deadline = time.time() + seconds
    while bridge_answers() and time.time() < deadline:
        time.sleep(0.5)
    return not bridge_answers()


def stop_strays():
    """Stops Chip's supervisors and bridges, from any Chip folder (supervise.py --stop, run by the venv's Python
    which has psutil)."""
    if os.path.isfile(VENV_PY):
        r = proc.complete([VENV_PY, "-I", "-X", "utf8", SUPERVISE, "--stop"], timeout=60)
        say("  " + (r.stdout.strip() or r.stderr.strip() or "nothing to stop"))


def log_tail(path, lines=15):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return "(no log yet)"


def make_venv(python):
    if os.path.isfile(VENV_PY) and version_of(VENV_PY) is None:  # its base Python was uninstalled or moved
        say("  the old venv is broken: making a new one")
        shutil.rmtree(VENV, ignore_errors=True)
    if not os.path.isfile(VENV_PY):
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        r = proc.complete([python, "-m", "venv", VENV], timeout=300)
        if r.returncode != 0:
            fail("could not make the venv:\n" + (r.stderr or r.stdout)[-1500:])
    r = proc.complete([VENV_PY, "-I", "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", REQUIREMENTS],
                      timeout=900)
    if r.returncode != 0:
        fail("pip could not install psutil (is there an internet connection?):\n" + (r.stderr or r.stdout)[-1500:])


def repair_prepare():
    """--repair: stop Chip (it runs from the venv, which Windows won't let go of) and delete the venv; remember
    whether start-at-login was on, so repair_finish can put that back."""
    import platforms
    was = platforms.autostart_get()
    say("  repair: stopping Chip and removing the old venv")
    if sys.platform == "darwin":
        unload_launch_agent()
    stop_strays()
    if not wait_until_stopped():
        fail(f"something still answers on 127.0.0.1:{PORT}; close it and run this again.")
    shutil.rmtree(VENV, ignore_errors=True)
    return was


def repair_finish(was):
    if was is False:  # install turns start-at-login on; it was off before, so keep it off
        import platforms
        ok, note = platforms.autostart_set(False)
        say("  start at login stays off" if ok else f"  could not keep start-at-login off: {note}")


def make_key(fix):
    import sshlink
    miss = sshlink.missing()
    if miss:
        say(f"  ssh tools missing ({', '.join(miss)}): {fix}")
        say("  Chip still starts; the phone link needs OpenSSH, run this again after adding it.")
    else:
        key = sshlink.ensure_own_key()
        say(f"  Chip's key: {key}" if key else "  an existing phone link keeps using its current key")


def wait_for_bridge(log):
    deadline = time.time() + 45
    while not bridge_answers():
        if time.time() > deadline:
            fail(f"the bridge doesn't answer on 127.0.0.1:{PORT}. Its log ({log}):\n" + log_tail(log))
        time.sleep(0.5)


# ---------------------------------------------------------------- Windows

def double_clicked():
    """True when this console was opened just for this script (it closes the moment we exit)."""
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleProcessList((ctypes.c_uint * 4)(), 4) <= 2
    except (AttributeError, OSError):
        return False


def set_run_entry(command):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, command)


def remove_run_entry():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_VALUE)
        return True
    except OSError:
        return False  # it wasn't there


def install_windows(args):
    from sshlink import OPENSSH_FIX
    say("Chip: setting up on Windows" + (" (repair)" if args.repair else ""))
    was = repair_prepare() if args.repair else None
    python, skipped = find_python()
    if not python:
        fail("no Python 3.12 or newer found" + (" (the one from the Microsoft Store doesn't work for Chip)" if skipped else "")
             + ".\n  Install Python from " + PYTHON_ORG + " and run this again.")
    say(f"1/6 Python: {python}")
    say("2/6 venv + psutil (a minute the first time)")
    make_venv(python)
    say("3/6 ssh key")
    make_key(OPENSSH_FIX)
    say("4/6 stopping the old Chip, if one runs")
    stop_strays()
    if not wait_until_stopped():
        fail(f"something still answers on 127.0.0.1:{PORT}; close it (Task Manager -> python) and run this again.")
    say("5/6 start at login + start now")
    set_run_entry(f'"{VENV_PYW}" -I -X utf8 "{SUPERVISE}"')
    proc.popen([VENV_PYW, "-I", "-X", "utf8", SUPERVISE], text=False, detached=True, cwd=REPO,
               stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL)
    say("6/6 waiting for the bridge")
    wait_for_bridge(paths.data("bridge.log"))
    if args.repair:
        repair_finish(was)
    say(f"\nChip is running. Dashboard: {DASHBOARD}")
    say("It starts by itself at login. To remove it: py -3 laptop\\install.py --uninstall")
    if not args.ci:
        import webbrowser
        webbrowser.open(DASHBOARD)
        say("Next: open the dashboard's Connections card to pair the phone.")


def uninstall_windows(args):
    say("Chip: removing from Windows")
    say("  start-at-login entry: " + ("removed" if remove_run_entry() else "wasn't there"))
    stop_strays()
    if not wait_until_stopped():
        fail(f"something still answers on 127.0.0.1:{PORT}; close it (Task Manager -> python).")
    say(f"Chip is stopped and won't start at login. Settings and keys stay in {paths.CONFIG_DIR}; "
        f"the venv in {VENV} can be deleted.")


# ---------------------------------------------------------------- macOS

def gui_domain():
    return f"gui/{os.getuid()}"


def launchctl(*args):
    return proc.complete(["launchctl", *args], timeout=30)


def certificates_ok(python):
    """(ok, problem) of an HTTPS request from python. python.org's Python has no certificates until its
    "Install Certificates.command" ran: then downloads (speech models) and cloud dictation fail."""
    code = "import urllib.request; urllib.request.urlopen('https://pypi.org/simple/psutil/', timeout=20).read(1)"
    try:
        r = proc.complete([python, "-I", "-c", code], timeout=40)
    except proc.TimeoutExpired:
        return False, "timed out"
    lines = (r.stderr or r.stdout).strip().splitlines()
    return r.returncode == 0, lines[-1] if lines else "no answer"


def check_certificates(python):
    ok, problem = certificates_ok(python)
    if ok:
        return say("  HTTPS works")
    if "CERTIFICATE_VERIFY_FAILED" not in problem:
        return say(f"  HTTPS failed ({problem}); no internet? Chip still installs.")
    v = version_of(python)
    command = f"/Applications/Python {v[0]}.{v[1]}/Install Certificates.command" if v else ""
    if not os.path.isfile(command):
        return say("  this Python has no HTTPS certificates and its 'Install Certificates.command' wasn't found: "
                   "downloads and cloud dictation will fail until you run it (Applications → Python 3.x).")
    say(f"  installing this Python's certificates ({command})")
    proc.complete(["/bin/bash", command], timeout=300)
    say("  HTTPS works now" if certificates_ok(python)[0] else "  HTTPS still fails: downloads and cloud dictation "
        "may not work (check the date and time, or a proxy)")


def accessibility_target():
    """What to switch on under Accessibility: the Python.app that the venv's python runs as (python.org's and
    Homebrew's Pythons are framework builds), else the real interpreter file."""
    code = ("import os, sys; app = os.path.join(sys.base_prefix, 'Resources', 'Python.app');"
            "print(app if os.path.isdir(app) else os.path.realpath(getattr(sys, '_base_executable', sys.executable)))")
    return proc.run(VENV_PY, "-I", "-c", code, timeout=15) or os.path.realpath(VENV_PY)


def write_launch_agent():
    import plistlib
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    os.makedirs(os.path.dirname(MAC_LOG), exist_ok=True)
    try:
        if os.path.getsize(MAC_LOG) > LOG_MAX:
            os.replace(MAC_LOG, MAC_LOG + ".1")
    except OSError:
        pass
    agent = {
        "Label": LAUNCH_AGENT,
        "ProgramArguments": [VENV_PY, "-I", "-X", "utf8", BRIDGE],
        "WorkingDirectory": REPO,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 5,          # started again within 5 s if it stops
        "ProcessType": "Interactive",   # typing and the stats shouldn't be throttled like a background job
        "EnvironmentVariables": {"PATH": MAC_PATH, "PYTHONUTF8": "1"},
        "StandardOutPath": MAC_LOG,
        "StandardErrorPath": MAC_LOG,
    }
    with open(PLIST, "wb") as f:
        plistlib.dump(agent, f)


def unload_launch_agent():
    """True if the LaunchAgent was loaded (launchd stops the bridge with it)."""
    return launchctl("bootout", f"{gui_domain()}/{LAUNCH_AGENT}").returncode == 0


def install_macos(args):
    say("Chip: setting up on macOS" + (" (repair)" if args.repair else ""))
    python, _ = find_python()
    if not python:
        fail("no Python 3.12 or newer found (the python3 that comes with Xcode is too old).\n"
             f"  Install Python from {PYTHON_ORG} (or `brew install python@3.12`) and run this again.")
    if sys.version_info[:2] < NEEDS:  # the rest of Chip's code is for 3.12+: carry on in the newer one
        say(f"  carrying on with {python}")
        os.execv(python, [python, "-I", "-X", "utf8", os.path.abspath(__file__)] + sys.argv[1:])
    was = repair_prepare() if args.repair else None
    say(f"1/7 Python: {python}")
    say("2/7 HTTPS certificates")
    check_certificates(python)
    say("3/7 venv + psutil (a minute the first time)")
    make_venv(python)
    say("4/7 ssh key")
    make_key("macOS comes with ssh; is /usr/bin/ssh missing?")
    say("5/7 stopping the old Chip, if one runs")
    unload_launch_agent()
    stop_strays()
    if not wait_until_stopped():
        fail(f"something still answers on 127.0.0.1:{PORT}; quit it (Activity Monitor -> python) and run this again.")
    say(f"6/7 start at login + start now ({PLIST})")
    write_launch_agent()
    launchctl("enable", f"{gui_domain()}/{LAUNCH_AGENT}")
    r = launchctl("bootstrap", gui_domain(), PLIST)
    if r.returncode != 0:
        fail(f"launchctl bootstrap {gui_domain()} failed: {(r.stderr or r.stdout).strip()}")
    say("7/7 waiting for the bridge")
    wait_for_bridge(MAC_LOG)
    if args.repair:
        repair_finish(was)
    app = accessibility_target()
    say(f"\nChip is running. Dashboard: {DASHBOARD}")
    say("It starts by itself at login. To remove it: python3 laptop/install.py --uninstall")
    say("\nTyping dictated text needs Accessibility for the Python that runs Chip:")
    say(f"  {app}")
    say("  System Settings → Privacy & Security → Accessibility: switch on \"Python\". If it isn't in the list, click +,")
    say("  press ⌘⇧G, paste the path above, choose Open, then switch it on.")
    say("  Note: macOS gives this to Python itself, so other programs this same Python runs in the background could")
    say("  type too. (A signed Chip app, planned for later, will fix that.)")
    if not args.ci:
        import webbrowser
        webbrowser.open(DASHBOARD)
        proc.run("open", ACCESSIBILITY_PANE, timeout=10)
        say("\nNext: open the dashboard's Connections card to pair the phone.")


def uninstall_macos(args):
    say("Chip: removing from macOS")
    say("  LaunchAgent: " + ("stopped" if unload_launch_agent() else "wasn't loaded"))
    try:
        os.remove(PLIST)
        say(f"  removed {PLIST}")
    except FileNotFoundError:
        pass
    stop_strays()
    if not wait_until_stopped():
        fail(f"something still answers on 127.0.0.1:{PORT}; quit it (Activity Monitor -> python).")
    say(f"Chip is stopped and won't start at login. Settings and keys stay in {paths.CONFIG_DIR}; "
        f"the venv in {VENV} can be deleted. To take Python's Accessibility back: System Settings → "
        "Privacy & Security → Accessibility.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--repair", action="store_true", help="rebuild the venv, keep settings, keys, phones and autostart")
    ap.add_argument("--ci", action="store_true")
    args = ap.parse_args()
    if IS_WIN:
        try:
            (uninstall_windows if args.uninstall else install_windows)(args)
        finally:
            if not args.ci and not os.environ.get("CHIP_LAUNCHER") and double_clicked():  # Install Chip.cmd pauses itself
                input("\nPress Enter to close this window. ")
        return 0
    if sys.platform == "darwin":
        (uninstall_macos if args.uninstall else install_macos)(args)
        return 0
    say("On Linux run laptop/install.sh (the bridge runs as a systemd user service)."
        + (" It is safe to run again: it keeps your settings, keys and phones.json." if args.repair else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
