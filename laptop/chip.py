#!/usr/bin/env python3
"""Stops, starts and restarts Chip's bridge on this laptop, and switches start-at-login, the same on every OS:
  python3 laptop/chip.py stop | start | restart | status | autostart on|off       (Windows: py -3 laptop\\chip.py …)
Linux: the systemd user service deskbuddy-bridge. Windows: supervise.py + the HKCU Run value "Chip". macOS: the
LaunchAgent org.deskbuddy.bridge. It only calls the OS's service manager (platforms.service_*), so it works while
the bridge is down. status exits 0 when the bridge answers, 3 when it doesn't (like systemctl is-active)."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I skips the script's folder
import platforms  # noqa: E402
import supervise  # noqa: E402  (chip_answers: anything answering /caps on the port, standard library only)

USAGE = "usage: chip.py stop | start | restart | status | autostart on|off"


def wait(up, seconds):
    deadline = time.time() + seconds
    while supervise.chip_answers() != up and time.time() < deadline:
        time.sleep(0.5)
    return supervise.chip_answers() == up


def status():
    up = supervise.chip_answers()
    auto = platforms.autostart_get()
    print(f"Chip's bridge: {'running' if up else 'stopped'} (127.0.0.1:{supervise.PORT}, {platforms.SERVICE})")
    print("Start when the laptop starts: " + {True: "on", False: "off", None: "not set up (run install)"}[auto])
    if not up:
        print("To start it: " + platforms.start_command())
    return 0 if up else 3


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if argv not in (["stop"], ["start"], ["restart"], ["status"], ["autostart", "on"], ["autostart", "off"]):
        print(USAGE, file=sys.stderr)
        return 2
    action = argv[0]
    if action == "status":
        return status()
    if action == "autostart":
        ok, msg = platforms.autostart_set(argv[1] == "on")
        print(msg)
        return 0 if ok else 1
    ok, msg = {"stop": platforms.service_stop, "start": platforms.service_start,
               "restart": platforms.service_restart}[action]()
    print(msg)
    if not ok:
        return 1
    if action == "stop":
        if not wait(False, 15):
            print(f"something still answers on 127.0.0.1:{supervise.PORT}")
            return 1
        print("Chip is stopped. To start it again: " + platforms.start_command())
        return 0
    if not wait(True, 30):
        print(f"the bridge didn't answer on 127.0.0.1:{supervise.PORT} within 30 s")
        return 1
    print("Chip is running")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
