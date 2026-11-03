#!/usr/bin/env python3
"""Sets Chip up on this laptop, once (run it again to update or repair; it restarts Chip).
  Windows:  py -3 laptop/install.py         or double-click it
  Linux:    laptop/install.sh               (this script only points there)
  macOS:    comes with S6
Windows steps: find Python 3.12+ (python.org's, not the Microsoft Store one), make a venv in
~/.local/share/deskbuddy/venv with laptop/requirements.txt, make Chip's own ssh key if there is none, start Chip at
login (HKCU Run -> pythonw supervise.py), start it now, wait for the bridge, open the dashboard.
  --uninstall   remove the start-at-login entry and stop Chip; settings, keys and the venv stay
  --ci          no browser, no "press Enter" (for GitHub Actions)
Standard library only; the Python it runs under only needs to be 3.9+ to get as far as finding a newer one."""
import argparse
import os
import re
import sys
import time

if sys.version_info < (3, 9):
    sys.exit("Chip needs Python 3.12 or newer: install it from https://www.python.org/downloads/")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I skips the script's folder
from platforms import paths, proc  # noqa: E402
from platforms.windows import RUN_KEY, RUN_VALUE  # noqa: E402

REPO = paths.REPO
SUPERVISE = os.path.join(HERE, "supervise.py")
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
VENV = paths.data("venv")
VENV_PY = os.path.join(VENV, "Scripts", "python.exe")
VENV_PYW = os.path.join(VENV, "Scripts", "pythonw.exe")
PORT = int(os.environ.get("CHIP_PORT") or 8765)
DASHBOARD = f"http://127.0.0.1:{PORT}/"
NEEDS = (3, 12)
PYTHON_ORG = "https://www.python.org/downloads/ (tick 'Add python.exe to PATH')"


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


def find_python():
    """(path, was_store_python_skipped) of a Python >= 3.12 that isn't the Store's. The one running this first."""
    skipped = False
    candidates = [sys.executable] + launcher_pythons()
    for exe in candidates:
        if is_store_python(exe):
            skipped = True
            continue
        v = sys.version_info[:2] if exe == sys.executable else version_of(exe)
        if v and v >= NEEDS:
            return exe, skipped
    return None, skipped


# ---------------------------------------------------------------- Windows

def bridge_answers():
    import supervise
    return supervise.chip_answers()


def stop_chip():
    """Stops Chip's supervisor and bridge (supervise.py --stop, run by the venv's Python which has psutil)."""
    if os.path.isfile(VENV_PY):
        r = proc.complete([VENV_PY, "-I", "-X", "utf8", SUPERVISE, "--stop"], timeout=60)
        say("  " + (r.stdout.strip() or r.stderr.strip() or "nothing to stop"))
    deadline = time.time() + 10
    while bridge_answers() and time.time() < deadline:
        time.sleep(0.5)
    return not bridge_answers()


def log_tail(lines=15):
    try:
        with open(paths.data("bridge.log"), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return "(no log yet)"


def double_clicked():
    """True when this console was opened just for this script (it closes the moment we exit)."""
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleProcessList((ctypes.c_uint * 4)(), 4) <= 2
    except (AttributeError, OSError):
        return False


def make_venv(python):
    if os.path.isfile(VENV_PY) and version_of(VENV_PY) is None:  # its base Python was uninstalled or moved
        import shutil
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
    say("Chip: setting up on Windows")
    python, skipped = find_python()
    if not python:
        fail("no Python 3.12 or newer found" + (" (the one from the Microsoft Store doesn't work for Chip)" if skipped else "")
             + ".\n  Install Python from " + PYTHON_ORG + " and run this again.")
    say(f"1/6 Python: {python}")
    say("2/6 venv + psutil (a minute the first time)")
    make_venv(python)
    say("3/6 ssh key")
    import sshlink
    miss = sshlink.missing()
    if miss:
        say(f"  ssh tools missing ({', '.join(miss)}): {sshlink.OPENSSH_FIX}")
        say("  Chip still starts; the phone link needs OpenSSH, run this again after adding it.")
    else:
        key = sshlink.ensure_own_key()
        say(f"  Chip's key: {key}" if key else "  an existing phone link keeps using its current key")
    say("4/6 stopping the old Chip, if one runs")
    if not stop_chip():
        fail(f"something still answers on 127.0.0.1:{PORT}; close it (Task Manager -> python) and run this again.")
    say("5/6 start at login + start now")
    set_run_entry(f'"{VENV_PYW}" -I -X utf8 "{SUPERVISE}"')
    proc.popen([VENV_PYW, "-I", "-X", "utf8", SUPERVISE], text=False, detached=True, cwd=REPO,
               stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL)
    say("6/6 waiting for the bridge")
    deadline = time.time() + 45
    while not bridge_answers():
        if time.time() > deadline:
            fail(f"the bridge doesn't answer on 127.0.0.1:{PORT}. Its log ({paths.data('bridge.log')}):\n" + log_tail())
        time.sleep(0.5)
    say(f"\nChip is running. Dashboard: {DASHBOARD}")
    say("It starts by itself at login. To remove it: py -3 laptop\\install.py --uninstall")
    if not args.ci:
        import webbrowser
        webbrowser.open(DASHBOARD)
        say("Next: open the dashboard's Connections card to pair the phone.")


def uninstall_windows(args):
    say("Chip: removing from Windows")
    say("  start-at-login entry: " + ("removed" if remove_run_entry() else "wasn't there"))
    if not stop_chip():
        fail(f"something still answers on 127.0.0.1:{PORT}; close it (Task Manager -> python).")
    say(f"Chip is stopped and won't start at login. Settings and keys stay in {paths.CONFIG_DIR}; "
        f"the venv in {VENV} can be deleted.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--ci", action="store_true")
    args = ap.parse_args()
    if sys.platform == "win32":
        try:
            (uninstall_windows if args.uninstall else install_windows)(args)
        finally:
            if not args.ci and double_clicked():
                input("\nPress Enter to close this window. ")
        return 0
    if sys.platform.startswith("linux"):
        say("On Linux run laptop/install.sh (the bridge runs as a systemd user service).")
        return 0
    say("macOS isn't supported by this installer yet.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
