#!/usr/bin/env python3
"""Keeps Chip's bridge running on Windows (install.py starts it at login): runs bridge.py, starts it again within
5 s if it exits, and exits itself if a Chip bridge already answers on the port. The bridge's output goes to
DATA_DIR/bridge.log (the old log is kept as bridge.log.1 once it passes 1 MB).
  pythonw -I -X utf8 supervise.py           run (no console window under pythonw)
  python  -I -X utf8 supervise.py --stop    stop every Chip supervisor and bridge started from this folder (needs psutil)
Standard library only, except --stop."""
import http.client
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I skips the script's folder
from platforms import paths  # noqa: E402

PORT = int(os.environ.get("CHIP_PORT") or 8765)
LOG = paths.data("bridge.log")
LOG_MAX = 1 << 20
RESTART_AFTER = 5     # s
BRIDGE = os.path.join(HERE, "bridge.py")
ME = os.path.abspath(__file__)


def chip_answers():
    """True if a Chip bridge (anything answering /caps with an "os") is on the port."""
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3)
    try:
        conn.request("GET", "/caps", headers={"Host": f"127.0.0.1:{PORT}"})
        r = conn.getresponse()
        return r.status == 200 and "os" in json.loads(r.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return False
    finally:
        conn.close()


def open_log():
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    try:
        if os.path.getsize(LOG) > LOG_MAX:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass
    return open(LOG, "ab")


def note(log, text):
    log.write(f"[supervise {time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n".encode("utf-8"))
    log.flush()


def run():
    while True:
        if chip_answers():
            return 0  # another bridge is already serving: nothing to supervise
        log = open_log()
        note(log, f"starting {BRIDGE}")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        code = subprocess.call([sys.executable, "-I", "-X", "utf8", BRIDGE], stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, creationflags=flags, cwd=os.path.dirname(HERE))
        note(log, f"bridge exited with {code}; again in {RESTART_AFTER} s")
        log.close()
        time.sleep(RESTART_AFTER)


def stop():
    """Ends the supervisors first (so they can't start the bridge again), then the bridges, of this folder only."""
    import psutil
    def found(script):
        out = []
        for p in psutil.process_iter(["pid", "cmdline"]):
            cmd = (p.info["cmdline"] or [])[1:]
            args = [os.path.normcase(os.path.abspath(a)) for a in cmd if a.lower().endswith(".py")]
            if p.pid != os.getpid() and "--stop" not in cmd and os.path.normcase(script) in args:  # not this run's own launcher
                out.append(p)
        return out

    count = 0
    for script in (ME, BRIDGE):
        procs = found(script)
        for p in procs:
            try:
                p.terminate()
            except psutil.Error:
                pass
        gone, alive = psutil.wait_procs(procs, timeout=5)
        for p in alive:
            try:
                p.kill()
            except psutil.Error:
                pass
        count += len(procs)
    print(f"stopped {count} Chip process(es)")
    return 0


if __name__ == "__main__":
    sys.exit(stop() if "--stop" in sys.argv[1:] else run())
