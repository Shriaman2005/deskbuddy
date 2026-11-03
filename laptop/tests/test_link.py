#!/usr/bin/env python3
"""The phone link against fake phones (fake_phone.py), in a throwaway CHIP_CONFIG_DIR: never the real phone, key or
settings. Proves, with the same pinned ssh options the real link uses (sshlink.py):
  - deploy.py (and ./deploy.sh) lands phone/ with its hash; a phone with another host key gets nothing
  - the tunnel (PhoneLink) refuses a different host key
  - rediscovery finds the phone on a new address only by the pinned key (Linux/Windows: needs 127.0.0.x addresses)
  - a real bridge's tunnel comes up and the phone side reaches the bridge through it
  - auto-sync deploys once per change, not on every reconnect; doctor.py reaches the phone
Needs asyncssh (test-only: a venv, never system-wide) and OpenSSH's ssh, ssh-keygen, ssh-keyscan.
Run: <venv>/bin/python -I laptop/tests/test_link.py   (prints a JSON report; exit 1 if a check failed)"""
import contextlib
import http.client
import ipaddress
import json
import os
import shutil
import socket
import sys
import tempfile
import time

LAPTOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="chip-linktest-")
CFG, DATA = os.path.join(TMP, "config"), os.path.join(TMP, "data")
os.environ.update(CHIP_CONFIG_DIR=CFG, CHIP_DATA_DIR=DATA)  # before anything reads platforms.paths
os.makedirs(CFG)
os.makedirs(DATA)
sys.path[:0] = [LAPTOP, os.path.join(LAPTOP, "tests")]
try:
    import asyncssh
except ImportError:
    sys.exit("test_link.py needs asyncssh: python3 -m venv <scratch>/venv && <scratch>/venv/bin/pip install asyncssh")
import deploy  # noqa: E402
import link  # noqa: E402
import sshlink  # noqa: E402
from fake_phone import FakePhone  # noqa: E402
from platforms import proc  # noqa: E402

checks = []
phones = []


def check(name, ok, detail=""):
    checks.append({"name": name, "ok": bool(ok), **({"detail": detail} if detail and not ok else {})})
    return ok


def free_port(host="127.0.0.1"):
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def wait(cond, timeout=20, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return cond()


def fetch(port, path, method="GET", host=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=b"{}" if method == "POST" else None,
                     headers={"Host": host or f"127.0.0.1:{port}", **(headers or {})})
        r = conn.getresponse()
        body = r.read().decode("utf-8", "replace")
        try:
            return r.status, json.loads(body)
        except ValueError:
            return r.status, body
    except OSError as e:
        return 0, str(e)
    finally:
        conn.close()


def host_key(name):
    """A fixed ed25519 host key for a fake phone: (private key file, 'type base64')."""
    key = asyncssh.generate_private_key("ssh-ed25519")
    path = os.path.join(TMP, name)
    key.write_private_key(path)
    kind, b64 = key.export_public_key("openssh").decode().split()[:2]
    return path, f"{kind} {b64}"


def phone(key_file, host="127.0.0.1", port=0, home=None):
    p = FakePhone(key_file, sshlink.OWN_KEY + ".pub", host=host, port=port, home=home).start()
    phones.append(p)
    return p


def write_json(name, data):
    with open(os.path.join(CFG, name), "w", encoding="utf-8") as f:
        json.dump(data, f)


def loopback_aliases():
    """127.0.0.2/.3 usable (Linux, Windows; macOS has only 127.0.0.1 unless aliased)."""
    try:
        for h in ("127.0.0.2", "127.0.0.3"):
            with socket.socket() as s:
                s.bind((h, 0))
        return True
    except OSError:
        return False


def main():
    check("ssh, ssh-keygen and ssh-keyscan found", not sshlink.missing(), sshlink.missing())
    # Chip's own key: made because nothing is pinned yet; after pinning it would never be made
    check("ensure_own_key makes CONFIG_DIR/id_ed25519", sshlink.ensure_own_key() == sshlink.OWN_KEY)
    check("the public key handed out is Chip's own", (sshlink.public_key() or "").startswith("ssh-ed25519 "))
    good_key, good_pub = host_key("phone_host_key")
    bad_key, _ = host_key("impostor_host_key")
    with open(sshlink.KNOWN_HOSTS, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{sshlink.HOST_ALIAS} {good_pub}\n")
    for ext in ("", ".pub"):  # the key away for a moment: with a phone pinned, ensure_own_key must not make one
        os.rename(sshlink.OWN_KEY + ext, sshlink.OWN_KEY + ext + ".away")
    check("no own key is made once a phone is pinned", sshlink.ensure_own_key() is None and not sshlink.own_key())
    for ext in ("", ".pub"):
        os.rename(sshlink.OWN_KEY + ext + ".away", sshlink.OWN_KEY + ext)

    opts = sshlink.options(8022)
    check("ssh options pin the key strictly",
          all(o in opts for o in ("StrictHostKeyChecking=yes", "UpdateHostKeys=no", f"HostKeyAlias={sshlink.HOST_ALIAS}",
                                  "BatchMode=yes", "IdentitiesOnly=yes")) and "GlobalKnownHostsFile=/dev/null" not in opts)
    check("GlobalKnownHostsFile is an empty file in CONFIG_DIR", os.path.getsize(sshlink.NO_GLOBAL) == 0)

    # ---- deploy.py lands the files, with the hash last
    real = phone(good_key)
    write_json("state.json", {"ip": "127.0.0.1"})
    write_json("settings.json", {"rev": 1, "values": {"sshPort": real.port, "linkAutoFind": False}})
    py = [sys.executable, "-I", "-X", "utf8"]
    r = proc.complete(py + [os.path.join(LAPTOP, "deploy.py")], timeout=60)
    check("deploy.py exits 0", r.returncode == 0, r.stdout + r.stderr)
    landed = lambda rel: os.path.isfile(os.path.join(real.files, rel))  # noqa: E731
    check("deploy lands phone/ (server.py, www/index.html, www/version.txt)",
          all(landed(x) for x in ("server.py", "services.sh", "www/index.html", "www/version.txt")))
    check("deploy leaves out setup.sh and __pycache__", not landed("setup.sh") and not os.path.isdir(os.path.join(real.files, "__pycache__")))
    check("phone's stored hash = the laptop's", deploy.phone_digest("127.0.0.1", real.port) == deploy.digest())
    if os.name != "nt":
        r = proc.complete([os.path.join(LAPTOP, "..", "deploy.sh")], timeout=60)
        check("./deploy.sh (the wrapper) works", r.returncode == 0 and real.deploys == 2, r.stdout + r.stderr)

    # ---- a different host key: nothing is sent, no tunnel
    multi = loopback_aliases()
    impostor = phone(bad_key, host="127.0.0.2" if multi else "127.0.0.1")
    ok, lines = deploy.deploy(impostor.host, impostor.port)
    check("deploy to a phone with another host key is refused", not ok and not impostor.commands
          and any("Host key verification failed" in l or "IDENTIFICATION HAS CHANGED" in l for l in lines), lines)
    cfg = {"sshPort": impostor.port, "linkKeepAlive": 10, "linkPaused": False, "linkHomeOnly": False,
           "linkNetworks": [], "linkAutoFind": True, "linkRetry": 5}
    lnk = link.PhoneLink(lambda: cfg)
    t = time.time()
    lnk.run_tunnel(impostor.host)
    check("tunnel to another host key is refused", lnk.error == "key mismatch" and not lnk.up
          and not impostor.forwards and time.time() - t < 15, f"{lnk.error} {lnk.detail}")
    check("is_phone: only the pinned key counts", lnk.is_phone(impostor.host) is False)

    # ---- rediscovery: the phone moved; an impostor answers on the same port elsewhere
    if multi:
        port = free_port("127.0.0.2")
        impostor2 = phone(bad_key, host="127.0.0.2", port=port)
        moved = phone(good_key, host="127.0.0.3", port=port)
        cfg["sshPort"] = port
        lnk = link.PhoneLink(lambda: cfg)
        lnk.interface = lambda: ("lo", "127.0.0.1", ipaddress.ip_network("127.0.0.0/24"))
        lnk.state["ip"] = "127.0.0.9"  # the old address: nothing there now
        with contextlib.redirect_stdout(sys.stderr):  # "found the phone at ..." stays out of the JSON report
            found = lnk.discover(force=True)
        check("rediscovery finds the phone by its pinned key", found == "127.0.0.3" and lnk.state.get("ip") == "127.0.0.3",
              found)
        check("rediscovery never picks the impostor", found != "127.0.0.2" and not impostor2.commands)
        check("the new address is saved", link.load_state().get("ip") == "127.0.0.3")
        moved.stop()
        lnk.state["ip"] = "127.0.0.2"
        found = lnk.discover(force=True)
        check("only the impostor left: not found, key mismatch", found is None and lnk.error == "key mismatch",
              f"{found} {lnk.error}")
        impostor2.stop()
    else:
        checks.append({"name": "rediscovery (skipped: no 127.0.0.2/.3 on this OS)", "ok": True})

    # ---- a real bridge: the tunnel reaches it, auto-sync deploys once per change
    shutil.rmtree(real.files)  # the phone has old files (none): the bridge must deploy once when the tunnel comes up
    bport, remote = free_port(), free_port()
    write_json("state.json", {"ip": "127.0.0.1"})
    write_json("settings.json", {"rev": 1, "values": {"sshPort": real.port, "linkAutoFind": False}})
    # CHIP_PORT in this process's environment too: doctor.py below must ask the test bridge, never the real one
    os.environ.update(CHIP_PORT=str(bport), CHIP_PAIR_PORT=str(free_port()), CHIP_TUNNEL_REMOTE_PORT=str(remote))
    env = dict(os.environ, CHIP_FAKE_CAPS="gpu=0")
    bridge = proc.popen(py + [os.path.join(LAPTOP, "bridge.py")], env=env, stdin=proc.DEVNULL, stdout=proc.PIPE,
                        stderr=proc.STDOUT)
    dash = {"Origin": f"http://127.0.0.1:{bport}"}
    try:
        lk = lambda: fetch(bport, "/link")[1]  # noqa: E731
        up = wait(lambda: isinstance(lk(), dict) and lk().get("tunnel"), 30)
        check("bridge's tunnel comes up to the fake phone", up, lk())
        check("the fake phone got -R on the test port", remote in real.forwards, real.forwards)
        status, caps = fetch(remote, "/caps", host=f"127.0.0.1:{bport}")  # as the phone's page: its 127.0.0.1
        check("phone side reaches the bridge through the tunnel", status == 200 and isinstance(caps, dict), status)
        synced = wait(lambda: lk().get("files") == "up to date", 30)
        check("auto-sync: deployed once when the tunnel came up", synced and real.deploys == 3 - (os.name == "nt")
              and deploy.phone_digest("127.0.0.1", real.port) == deploy.digest(), f"{lk()} deploys={real.deploys}")

        def reconnect():
            asked = real.commands.count(deploy.HASH_CMD)
            status, _ = fetch(bport, "/link/reconnect", "POST", headers=dash)
            ok = wait(lambda: real.commands.count(deploy.HASH_CMD) > asked and lk().get("files") == "up to date", 40)
            return status == 200 and ok

        before = real.deploys
        check("auto-sync: no deploy on a reconnect without changes", reconnect() and real.deploys == before,
              f"deploys {before} -> {real.deploys}")
        with open(os.path.join(real.files, deploy.HASH_FILE), "w") as f:
            f.write("an older version\n")
        check("auto-sync: one deploy after a change", reconnect() and real.deploys == before + 1,
              f"deploys {before} -> {real.deploys}")
        check("auto-sync: and none on the next reconnect", reconnect() and real.deploys == before + 1,
              f"deploys {before} -> {real.deploys}")
        status, _ = fetch(bport, "/link/reconnect", "POST", headers={"Origin": "http://127.0.0.1:8080"})
        check("link writes still refused from the phone's page", status == 403, status)

        wait(lambda: lk().get("tunnel"), 30)
        r = proc.complete(py + [os.path.join(LAPTOP, "doctor.py")], timeout=90, input="")
        check("doctor.py asked the test bridge", "ssh tunnel up to 127.0.0.1" in r.stdout, r.stdout[-1500:])
        lines = r.stdout.splitlines()
        check("doctor.py: ssh into the fake phone with the pinned key",
              any("✓ can ssh into Termux" in l for l in lines), r.stdout[-1500:])
        check("doctor.py: the phone reaches the bridge through the tunnel",
              any("✓ phone reaches the bridge through the tunnel" in l for l in lines), r.stdout[-1500:])
    finally:
        bridge.terminate()
        try:
            out = bridge.communicate(timeout=8)[0]
        except proc.TimeoutExpired:
            bridge.kill()
            out = bridge.communicate()[0]
        if not all(c["ok"] for c in checks):
            checks.append({"name": "bridge output", "ok": True, "detail": out[-2000:]})


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001  (a crash is a failed check, with the report still printed)
        import traceback
        check("test ran to the end", False, traceback.format_exc()[-1500:])
    finally:
        for p in phones:
            try:
                p.stop()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(TMP, ignore_errors=True)
    failed = [c["name"] for c in checks if not c["ok"]]
    print(json.dumps({"ok": not failed, "failed": failed, "checks": checks}, indent=1))
    sys.exit(1 if failed else 0)
