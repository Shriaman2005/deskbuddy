"""Controls for Chip's server on the phone, sent over the same pinned ssh as deploy (sshlink.command):
restart (chip-restart: face server, supervisor and PulseAudio, never sshd), stop (chip-stop: also sshd, so the laptop
can't start it again) and the Termux:Boot file that starts Chip when the phone starts. Each call returns
(ok, lines); the bridge's /link/phone/* endpoints (dashboard only) are the only callers.
The remote commands are constants so the test's fake phone can recognise them."""
import deploy
import sshlink
from platforms import proc

# chip-restart is linked into $PREFIX/bin too, so typing `chip-restart` in Termux works on phones set up before it existed
RESTART_CMD = ('chmod +x ~/deskbuddy/chip-restart 2>/dev/null; ln -sf ~/deskbuddy/chip-restart "$PREFIX/bin/" 2>/dev/null; '
               'bash ~/deskbuddy/chip-restart')
STOP_CMD = "bash ~/deskbuddy/chip-stop"
BOOT_FILE = "~/.termux/boot/deskbuddy"
AUTOSTART_ON_CMD = ("mkdir -p ~/.termux/boot && printf '#!/data/data/com.termux/files/usr/bin/bash\\n"
                    "exec ~/deskbuddy/services.sh\\n' >" + BOOT_FILE + " && chmod +x " + BOOT_FILE)
AUTOSTART_OFF_CMD = "rm -f " + BOOT_FILE
AUTOSTART_GET_CMD = f"test -f {BOOT_FILE} && echo on || echo off"
STOPPED_NOTE = "To start it again you need the phone: open Termux or type chip-start."


def _run(ip, port, remote, timeout):
    """(returncode or None, output lines); a deploy running at the same time is waited for, not interleaved."""
    if not deploy.LOCK.acquire(timeout=20):
        return None, ["the phone is busy with an update: try again in a moment"]
    try:
        r = proc.complete(sshlink.command(ip, port, remote, timeout=8), timeout=timeout)
    except (OSError, proc.TimeoutExpired) as e:
        return None, [f"{type(e).__name__}: {e}"]
    finally:
        deploy.LOCK.release()
    return r.returncode, (r.stdout + r.stderr).splitlines()


def restart(ip, port):
    code, lines = _run(ip, port, RESTART_CMD, 60)
    ok = code == 0 and not any("✗" in l for l in lines)
    return ok, lines


def stop(ip, port):
    """chip-stop ends with `pkill -x sshd`, which cuts this very session: ssh then exits 255 (or 0 if the last lines made
    it out), so a session the phone closed on us counts as done."""
    code, lines = _run(ip, port, STOP_CMD, 30)
    closed = any("closed by remote host" in l or "reset by" in l for l in lines)
    ok = code == 0 or any("Chip stopped" in l for l in lines) or (code == 255 and closed)
    return ok, [l for l in lines if "Connection to" not in l] + ([STOPPED_NOTE] if ok else [])


def autostart(ip, port, on):
    code, lines = _run(ip, port, AUTOSTART_ON_CMD if on else AUTOSTART_OFF_CMD, 20)
    return code == 0, lines


def read_autostart(ip, port):
    """True/False: is the Termux:Boot file there; None if the phone couldn't be asked."""
    code, lines = _run(ip, port, AUTOSTART_GET_CMD, 20)
    if code != 0 or not lines:
        return None
    return lines[-1].strip() == "on"
