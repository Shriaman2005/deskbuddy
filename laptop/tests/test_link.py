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
import phonectl  # noqa: E402
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


def fetch(port, path, method="GET", host=None, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=json.dumps(body or {}).encode() if method == "POST" else None,
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


def pair_in_process(fake, cfg):
    """A confirmed pairing (Pairing.confirm, the real code path) with the fake phone, without the download server:
    the session is the one Pairing.start leaves once the phone fetched the bundle."""
    lnk = link.PhoneLink(lambda: cfg)
    p = link.Pairing(lnk)
    now = time.time()
    p.session = {"script_id": "x", "bundle_token": "x", "ip": "127.0.0.1", "net": ipaddress.ip_network("127.0.0.0/8"),
                 "until": now, "script": b"", "bundle": b"", "script_by": fake.host, "fetched_by": fake.host,
                 "fetched_at": now, "ready": now, "error": None, "wrong": 0}
    code = p.host_keys(fake.host)[0][2][:link.Pairing.CODE_LEN]
    with contextlib.redirect_stdout(sys.stderr):
        answer, status = p.confirm(code)
    return answer if status == 200 else {"ok": False, "status": status, **answer}


def phones_checks(bport, dash, real, good_pub, remote):
    """Saved phones (P1): migration, pairing twice, switch (keys + ip + port, tunnel up), key changed, rename, remove,
    and every /link/phones* refused without the dashboard's Origin."""
    lk = lambda: fetch(bport, "/link")[1]  # noqa: E731
    saved = lambda: fetch(bport, "/link/phones", headers=dash)[1]  # noqa: E731
    post = lambda path, body, h=dash: fetch(bport, path, "POST", headers=h, body=body)  # noqa: E731
    first = saved()
    one = first.get("phones") or [{}]
    check("migration: the existing pin is saved as Phone 1, active",
          len(first.get("phones", [])) == 1 and one[0].get("name") == "Phone 1" and one[0].get("active")
          and one[0].get("ip") == "127.0.0.1" and one[0].get("sshPort") == real.port and one[0].get("online"), first)
    if os.name != "nt":
        check("phones.json is 0600", os.stat(link.PHONES_FILE).st_mode & 0o777 == 0o600, oct(os.stat(link.PHONES_FILE).st_mode))
    with open(link.PHONES_FILE, encoding="utf-8") as f:
        stored = json.load(f)
    check("phones.json holds only id, name, keys, ip, sshPort, pairedAt, lastSeen",
          all(set(p) <= {"id", "name", "keys", "ip", "sshPort", "pairedAt", "lastSeen"} for p in stored["phones"])
          and stored["phones"][0]["lastSeen"], stored)
    a_id = one[0].get("id")

    b_key, _ = host_key("second_phone_key")
    b = phone(b_key)
    cfg = {"sshPort": b.port, "linkKeepAlive": 10, "linkPaused": False, "linkHomeOnly": False,
           "linkNetworks": [], "linkAutoFind": False, "linkRetry": 5}
    r1 = pair_in_process(b, cfg)
    r2 = pair_in_process(b, cfg)  # the same phone again: updated, not a duplicate
    cfg["sshPort"] = real.port
    r3 = pair_in_process(real, cfg)  # Phone 1 paired again: still the same entry
    lst = saved().get("phones", [])
    check("pairing a second phone adds it as Phone 2; the same key again is no duplicate",
          r1.get("ok") and r2.get("ok") and r3.get("ok") and r1.get("id") == r2.get("id") != a_id and r3.get("id") == a_id
          and [p["name"] for p in lst] == ["Phone 1", "Phone 2"], [r1, r2, r3, lst])
    b_id = r1.get("id")

    status, ans = post("/link/phones/switch", {"id": b_id})
    up = wait(lambda: lk().get("tunnel") and lk().get("port") == b.port, 40)
    check("switch: Phone 2's port, address and key, tunnel up to it",
          status == 200 and up and sshlink.pinned() == {tuple(k[:2]) for k in link.Phones().get(b_id)["keys"]}
          and link.load_state().get("ip") == "127.0.0.1" and wait(lambda: remote in b.forwards, 10),
          [status, ans, sshlink.pinned(), link.load_state(), b.forwards, remote])
    check("switch: Phone 2 is the active one, online", wait(lambda: saved().get("active") == b_id
          and next(p for p in saved()["phones"] if p["id"] == b_id)["online"], 10), saved())
    status, _ = post("/link/phones/switch", {"id": a_id})
    up = wait(lambda: lk().get("tunnel") and lk().get("port") == real.port, 40)
    check("switch back: Phone 1's key + port again, no re-pairing, tunnel up",
          status == 200 and up and sshlink.pinned() == {tuple(good_pub.split())}, lk())

    port_b = b.port  # Termux reset on Phone 2: same address and port, a new host key
    b.stop()
    reset_key, _ = host_key("second_phone_reset_key")
    b2 = phone(reset_key, port=port_b)
    status, _ = post("/link/phones/switch", {"id": b_id})
    check("switch to a phone whose key changed: key mismatch, no tunnel",
          status == 200 and wait(lambda: lk().get("reason") == "key mismatch", 40) and not b2.forwards, lk())

    status, ans = post("/link/phones/rename", {"id": a_id, "name": "  Desk   phone "})
    check("rename trims the name", status == 200 and ans.get("name") == "Desk phone"
          and next(p for p in saved()["phones"] if p["id"] == a_id)["name"] == "Desk phone", ans)
    bad = [post("/link/phones/rename", {"id": a_id, "name": n})[0] for n in ("   ", "x" * 33, 5)]
    check("rename refuses empty, >32 characters and non-text", bad == [400, 400, 400], bad)
    check("unknown id: 404", post("/link/phones/switch", {"id": "nope"})[0] == 404)

    status, _ = post("/link/phones/remove", {"id": b_id})  # the active one: forget + remove
    after = saved()
    check("remove the active phone: unpinned, gone from the list, Phone 1 kept",
          status == 200 and after.get("active") is None and [p["id"] for p in after.get("phones", [])] == [a_id]
          and not sshlink.pinned(), after)
    status, _ = post("/link/forget", {})
    check("forget keeps the saved phone", status == 200 and [p["id"] for p in saved().get("phones", [])] == [a_id])

    phone_page = {"Origin": "http://127.0.0.1:8080"}
    refused = [fetch(bport, "/link/phones", headers=phone_page)[0], fetch(bport, "/link/phones", "POST")[0]]
    refused += [post(path, {"id": a_id, "name": "x"}, h)[0] for path in
                ("/link/phones/switch", "/link/phones/rename", "/link/phones/remove") for h in (phone_page, {})]
    check("every /link/phones* refused without the dashboard's Origin", set(refused) == {403}, refused)
    return a_id


def control_checks(bport, dash, real):
    """Phone server controls (P3): restart, stop and the Termux:Boot switch go over the tunnel's ssh with the pinned
    options; dashboard only; 409 while the tunnel is down. stop is only ever run against the fake phone."""
    lk = lambda: fetch(bport, "/link")[1]  # noqa: E731
    post = lambda path, body=None, h=dash: fetch(bport, path, "POST", headers=h, body=body or {})  # noqa: E731
    check("/link says whether Chip starts with the phone (the setup's Termux:Boot file is not there in the fake: off)",
          wait(lambda: lk().get("phone_autostart") is False, 20), lk())
    status, body = post("/link/phone/restart")
    check("restart: runs chip-restart on the phone and returns its lines",
          status == 200 and body.get("ok") and real.restarts == 1 and phonectl.RESTART_CMD in real.commands
          and any("Chip restarted" in l for l in body.get("lines", [])), [status, body])
    check("restart never touches sshd or runs chip-stop", real.stops == 0 and not any("sshd" in c and "pkill" in c for c in real.commands))
    boot = os.path.join(real.home, ".termux", "boot", "deskbuddy")
    status, body = post("/link/phone/autostart", {"on": True})
    check("autostart on: Termux:Boot file made, /link follows",
          status == 200 and body.get("on") is True and os.path.isfile(boot) and lk().get("phone_autostart") is True,
          [status, body, lk().get("phone_autostart")])
    status, body = post("/link/phone/autostart", {"on": False})
    check("autostart off: file removed, /link follows",
          status == 200 and body.get("on") is False and not os.path.exists(boot) and lk().get("phone_autostart") is False,
          [status, body, lk().get("phone_autostart")])
    check("autostart needs {on: true|false}", post("/link/phone/autostart", {"on": "yes"})[0] == 400
          and post("/link/phone/autostart", {})[0] == 400)
    status, body = post("/link/phone/stop")
    check("stop: runs chip-stop, and says the phone is needed to start Chip again",
          status == 200 and body.get("ok") and real.stops == 1 and "chip-start" in body.get("needs_hand", ""), [status, body])
    for path in ("/link/phone/restart", "/link/phone/stop", "/link/phone/autostart"):
        ran = len(real.commands)
        status, _ = post(path, {"on": True}, h={"Origin": "http://127.0.0.1:8080"})
        status2, _ = post(path, {"on": True}, h={})
        check(f"{path} refused from the phone's page and without an Origin ({status}, {status2})",
              status == 403 and status2 == 403 and len(real.commands) == ran)
    # the tunnel down: nothing is sent
    fetch(bport, "/settings", "POST", headers=dash, body={"linkPaused": True})
    check("(paused: the tunnel closes)", wait(lambda: not lk().get("tunnel"), 20), lk())
    ran = len(real.commands)
    answers = [post(p, {"on": True}) for p in ("/link/phone/restart", "/link/phone/stop", "/link/phone/autostart")]
    check("tunnel down: all three answer 409 phone offline and send nothing",
          all(a[0] == 409 and a[1].get("error") == "phone offline" for a in answers) and len(real.commands) == ran, answers)
    fetch(bport, "/settings", "POST", headers=dash, body={"linkPaused": False})
    check("(unpaused: the tunnel is back)", wait(lambda: lk().get("tunnel"), 40), lk())
    # stop over a session the phone cuts (sshd killed): ssh exits 255 with "closed by remote host", still a success
    orig = phonectl._run
    try:
        phonectl._run = lambda *a: (255, ["Chip stopped (wake lock released). Start again: chip-start",
                                          "Connection to 127.0.0.1 closed by remote host."])
        ok, lines = phonectl.stop("127.0.0.1", 1)
        phonectl._run = lambda *a: (255, ["ssh: connect to host 127.0.0.1 port 1: Connection refused"])
        bad, _ = phonectl.stop("127.0.0.1", 1)
    finally:
        phonectl._run = orig
    check("stop: a session cut by sshd's end is a success, a refused connection is not",
          ok and lines[-1] == phonectl.STOPPED_NOTE and not bad, [ok, lines, bad])


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

    # ---- Windows Firewall vs the pairing port (the rule logic; the COM query itself only runs on Windows)
    from platforms import windows
    pyw = os.path.normcase(os.path.join(TMP, "Python314", "pythonw.exe"))
    verdict = lambda rules, blk=True: windows.firewall_verdict(  # noqa: E731
        {"on": True, "blk": blk, "cur": 2, "rules": rules}, "192.168.0.141", "192.168.0.0/24", 8766, {pyw})
    rule = lambda **kw: dict({"n": "r", "a": "", "p": "*", "k": 1, "l": "*", "r": "*", "t": "All", "i": False}, **kw)  # noqa: E731
    check("firewall: nothing allows Python, the port or the address: say so",
          verdict([]) == ("allow", None) and verdict([rule(a=os.path.join(TMP, "other.exe"))]) == ("allow", None)
          and verdict([rule(p="RPC"), rule(l="100.97.243.70/255.255.255.255")]) == ("allow", None)  # Tailscale-In
          and verdict([rule(r="10.0.0.0/255.0.0.0"), rule(i=True), rule(t="RemoteAccess")]) == ("allow", None))
    check("firewall: a rule for this Python, the port, LocalSubnet or a range covers it",
          verdict([rule(a=pyw)]) is None and verdict([rule(p="8000-9000")]) is None
          and verdict([rule(r="LocalSubnet", l="192.168.0.141/255.255.255.255")]) is None
          and verdict([rule(r="192.168.0.1-192.168.0.254")]) is None and verdict([], blk=False) is None
          and windows.firewall_verdict({"on": False, "rules": []}, "192.168.0.141", "192.168.0.0/24", 8766, {pyw}) is None)
    check("firewall: a block rule for this Python wins over allow rules",
          verdict([rule(n="pythonw.exe", a=pyw, k=0), rule(p="8766")]) == ("blocked", "pythonw.exe")
          and verdict([rule(n="pythonw.exe", a=pyw, k=0)], blk=False) == ("blocked", "pythonw.exe"))

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

        control_checks(bport, dash, real)
        a_id = phones_checks(bport, dash, real, good_pub, remote)
        before = fetch(bport, "/link/phones", headers=dash)[1]
        bridge.terminate()
        bridge.communicate(timeout=8)
        bridge = proc.popen(py + [os.path.join(LAPTOP, "bridge.py")], env=env, stdin=proc.DEVNULL, stdout=proc.PIPE,
                            stderr=proc.STDOUT)
        after = wait(lambda: (lambda r: r[0] == 200 and r[1])(fetch(bport, "/link/phones", headers=dash)), 20)
        check("saved phones survive a bridge restart", after == before and after["phones"][0]["id"] == a_id
              and after["phones"][0]["name"] == "Desk phone", [before, after])
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
