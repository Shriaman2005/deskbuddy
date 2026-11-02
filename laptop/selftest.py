#!/usr/bin/env python3
"""Starts a throwaway bridge (free ports, empty temp CHIP_CONFIG_DIR / CHIP_DATA_DIR, link paused so it never
scans or calls the phone) and checks that the main GET routes answer with their documented keys, CAPS is sane and the
bridge still refuses what it must. Prints a JSON report; exit status 1 if any check failed.
Needs no GNOME, D-Bus or phone (CI): those caps are then simply false.
Run: python3 -I laptop/selftest.py"""
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I skips the script's folder
import platforms  # noqa: E402
from platforms import base, proc  # noqa: E402

STATS_KEYS = {"cpu", "cores", "ram", "temp", "battery", "charging", "net_rx", "net_tx", "uptime", "temps", "fan", "gpu",
              "ram_used_gb", "ram_total_gb", "swap", "disk", "disk_free_gb", "load", "wifi", "bat",
              "media", "volume", "muted", "idle_ms", "locked",
              "ts", "typing_for", "wpm", "idle", "settingsRev", "skinsRev", "attention", "caps"}
SETTINGS_KEYS = {"linkPaused", "linkAutoFind", "linkHomeOnly", "linkNetworks", "linkKeepAlive", "linkRetry", "sshPort",
                 "dictEngine", "dictLang", "eyeStyle", "pupilSize", "skin", "gazeFollow", "tabViz", "ringGpu", "mediaCard"}
LINK_KEYS = {"tunnel", "pinned", "port", "reason", "laptop"}
STT_KEYS = {"engine", "lang", "languageNames", "engines", "providers"}
BUS_CAPS = ("idle", "locked", "media", "nowPlaying", "notifications", "gaze", "typing")  # all need a session bus

checks = []


def check(name, ok, detail=""):
    checks.append({"name": name, "ok": bool(ok), **({"detail": detail} if detail and not ok else {})})
    return ok


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(port, path, host=None, method="GET", headers=None):
    """(status, parsed JSON or text) from the test bridge, or (0, error)."""
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


def missing(have, want):
    return sorted(want - set(have)) if isinstance(have, dict) else ["(not a JSON object)"]


def check_backends():
    """windows.py and macos.py must import on every OS and offer everything base.py does (and linux.py too)."""
    import importlib
    names = {n for n in vars(base) if not n.startswith("_") and n not in ("NAME",)}
    for mod in ("linux", "windows", "macos"):
        try:
            m = importlib.import_module("platforms." + mod)
        except Exception as e:  # noqa: BLE001  (any import failure is the finding)
            check(f"platforms.{mod} imports", False, f"{type(e).__name__}: {e}")
            continue
        check(f"platforms.{mod} offers the base.py set", not names - set(vars(m)), sorted(names - set(vars(m))))
        if mod != "linux":
            check(f"platforms.{mod} caps are all false", not any(m.caps().values()))


def main():
    check_backends()
    port, pair_port = free_port(), free_port()
    tmp = tempfile.mkdtemp(prefix="chip-selftest-")
    cfg, data = os.path.join(tmp, "config"), os.path.join(tmp, "data")
    os.makedirs(cfg)
    os.makedirs(data)
    with open(os.path.join(cfg, "settings.json"), "w") as f:
        json.dump({"rev": 1, "values": {"linkPaused": True}}, f)  # never scan the Wi-Fi or open a tunnel from a test
    fake = os.environ.get("CHIP_FAKE_CAPS") or "gpu=0"
    env = dict(os.environ, CHIP_PORT=str(port), CHIP_PAIR_PORT=str(pair_port), CHIP_CONFIG_DIR=cfg,
               CHIP_DATA_DIR=data, CHIP_FAKE_CAPS=fake)
    bridge = proc.popen([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "bridge.py")], env=env,
                        stdin=proc.DEVNULL, stdout=proc.PIPE, stderr=proc.STDOUT)
    caps = {}
    try:
        deadline = time.time() + 20
        status, caps = get(port, "/caps")
        while status != 200 and time.time() < deadline and bridge.poll() is None:
            time.sleep(0.3)
            status, caps = get(port, "/caps")
        if not check("bridge starts and answers /caps", status == 200, f"status {status}: {caps}"):
            return report(caps)

        # CAPS: every key a bool, the fake applied, the tool caps match what is installed, no bus = no bus caps
        caps = dict(caps)
        os_name = caps.pop("os", None)
        check("caps has exactly the CAP_KEYS", set(caps) == set(platforms.CAP_KEYS),
              sorted(set(caps) ^ set(platforms.CAP_KEYS)))
        check("caps are all bools", all(type(v) is bool for v in caps.values()))
        check("caps os is this OS's backend", os_name == platforms.NAME, os_name)
        for item in fake.split(","):
            k, _, v = item.partition("=")
            if k in caps and v in ("0", "1"):
                check(f"CHIP_FAKE_CAPS sets {k}={v}", caps[k] is (v == "1"))
        check("termuxLink = ssh found", caps.get("termuxLink") == bool(shutil.which("ssh")) or "termuxLink" in fake)
        check("skins = node found", caps.get("skins") == bool(shutil.which("node")) or "skins" in fake)
        check("laptopStt = false with an empty data dir", caps.get("laptopStt") is False or "laptopStt" in fake)
        if platforms.NAME == "linux" and not platforms.backend.session_bus():
            on = [k for k in BUS_CAPS if caps.get(k) and k not in fake]
            check("no session bus: bus caps are false", not on, on)

        # /stats: the fast keys arrive within one sampling round (2 s), the slow ones within 3 s
        deadline, stats = time.time() + 8, {}
        while time.time() < deadline:
            status, stats = get(port, "/stats")
            if status == 200 and not missing(stats, STATS_KEYS):
                break
            time.sleep(0.5)
        check("/stats has the documented keys", status == 200 and not missing(stats, STATS_KEYS), missing(stats, STATS_KEYS))
        if isinstance(stats, dict):
            check("/stats caps = /caps", stats.get("caps") == caps)
            check("/stats attention is a list", isinstance(stats.get("attention"), list))
            check("/stats cores is a list", isinstance(stats.get("cores"), list))
            if caps.get("stats"):
                check("/stats has a RAM figure", isinstance(stats.get("ram"), int), stats.get("ram"))

        status, settings = get(port, "/settings")
        check("/settings has the documented keys", status == 200 and not missing(settings, SETTINGS_KEYS),
              missing(settings, SETTINGS_KEYS))
        check("settings come from CHIP_CONFIG_DIR", isinstance(settings, dict) and settings.get("linkPaused") is True)
        status, link = get(port, "/link")
        check("/link has the documented keys", status == 200 and not missing(link, LINK_KEYS), missing(link, LINK_KEYS))
        if isinstance(link, dict):
            check("/link: nothing pinned in a fresh config", link.get("pinned") is False and link.get("tunnel") is False)
            check("/link laptop has iface/ip/ssid/security/subnet",
                  not missing(link.get("laptop"), {"iface", "ip", "ssid", "security", "subnet"}))
        status, phone = get(port, "/phone")
        check("/phone is {} before the phone reports", status == 200 and phone == {}, phone)
        status, stt = get(port, "/stt/status")
        check("/stt/status has the documented keys", status == 200 and not missing(stt, STT_KEYS), missing(stt, STT_KEYS))
        if isinstance(stt, dict) and isinstance(stt.get("engines"), dict):
            check("/stt/status engines phone/laptop/cloud", not missing(stt["engines"], {"phone", "laptop", "cloud"}))
        status, page = get(port, "/")
        check("dashboard page served", status == 200 and isinstance(page, str) and "<html" in page.lower(), status)

        # what must stay refused
        status, _ = get(port, "/stats", host="evil.example")
        check("refuses a foreign Host", status == 403, status)
        status, _ = get(port, "/stats", headers={"Origin": "http://evil.example"})
        check("refuses a foreign Origin", status == 403, status)
        status, _ = get(port, "/link/reconnect", method="POST", headers={"Origin": "http://127.0.0.1:8080"})
        check("link writes refused from the phone's page", status == 403, status)
        status, _ = get(port, "/link/forget", method="POST")
        check("link writes refused without an Origin", status == 403, status)
        check("no known_hosts written by the test", not os.path.exists(os.path.join(cfg, "known_hosts")))
    finally:
        bridge.terminate()
        try:
            out = bridge.communicate(timeout=5)[0]
        except proc.TimeoutExpired:
            bridge.kill()
            out = bridge.communicate()[0]
        if not all(c["ok"] for c in checks) and out:
            checks.append({"name": "bridge output", "ok": True, "detail": out[-2000:]})
        shutil.rmtree(tmp, ignore_errors=True)
    return report(caps)


def report(caps):
    failed = [c["name"] for c in checks if not c["ok"]]
    print(json.dumps({"ok": not failed, "os": platforms.NAME, "python": sys.version.split()[0], "caps": caps,
                      "failed": failed, "checks": checks}, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
