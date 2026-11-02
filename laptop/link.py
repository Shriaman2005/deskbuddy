"""The link to the phone, over the home Wi-Fi only (no cable, no adb): PhoneLink keeps the ssh tunnel up and finds
the phone again when its address changes; Pairing pairs a new phone from the dashboard; Phone files are synced by
deploy.py when the tunnel comes up and the phone's copy differs. Every ssh call goes through sshlink.py (the
phone's host key pinned under an alias, equally strict on every OS)."""
import concurrent.futures
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import deploy
import platforms
import sshlink
from platforms import paths
from platforms.proc import DEVNULL, PIPE, TimeoutExpired, run
from sshlink import HOST_ALIAS, KNOWN_HOSTS, tool

PORT = int(os.environ.get("CHIP_PORT") or 8765)  # the bridge's port (CHIP_PORT / CHIP_PAIR_PORT only for tests)
# the phone's end of the tunnel: the same port as the bridge, except in tests against the fake phone
REMOTE_PORT = int(os.environ.get("CHIP_TUNNEL_REMOTE_PORT") or PORT)
PAIR_PORT = int(os.environ.get("CHIP_PAIR_PORT") or 8766)  # the one-shot download server for pairing a new phone (laptop's LAN address only)
STATE_FILE = paths.config("state.json")


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


class PhoneLink:
    """Keeps `ssh -R` open to Termux so the phone's 127.0.0.1:8765 reaches this bridge, over the home Wi-Fi.
    The phone's ssh host key is pinned under an alias, so its address can change: when the saved address stops
    answering, the Wi-Fi subnet is scanned for sshd's port and the host that presents the pinned key is the phone.
    Settings read live: linkPaused, linkAutoFind, linkHomeOnly + linkNetworks, linkKeepAlive, linkRetry, sshPort.
    Each time the tunnel comes up, the phone's copy of phone/ is compared with the laptop's and deployed once if it
    differs (files: "checking" / "up to date" / "updating" / "failed", for the Connections card)."""
    HOST_KEY_CHANGED = ("Host key verification failed", "REMOTE HOST IDENTIFICATION HAS CHANGED")

    def __init__(self, settings):
        self.settings = settings  # () -> the bridge's settings dict
        self.state = load_state()
        self.up = False
        self.since = 0.0       # when the tunnel came up
        self.started = 0.0     # when the current ssh started (0 = none running)
        self.fails = 0         # tunnels in a row that died within seconds of starting
        self.last_scan = 0.0
        self.scans = 0
        self.error = None      # why the last attempt failed: "not found" / "key mismatch", None = no failure
        self.detail = ""       # ssh's last stderr line, for the dashboard
        self.restart = False   # set by the endpoints: the running ssh should stop (the loop decides what next)
        self.wake = threading.Event()
        self.lock = threading.Lock()       # state["ip"] and the key file
        self.scan_lock = threading.Lock()  # one sweep at a time (the loop's or /link/find's)
        self._net = (0.0, None)            # (when, network())
        self._rtt = (0.0, None, None)      # (when, (ip, port), ms)
        self._fp = (None, None)            # (key file mtime, (fingerprint, type))
        self.files = None                  # the phone's copy of phone/: None (not checked yet), "checking", ...
        self.files_detail = ""
        self.files_at = 0.0
        self.syncs = 0                     # deploys started by the sync (tests count them)

    def cfg(self):
        return self.settings()

    def port(self):
        return self.cfg()["sshPort"]

    # ---- the laptop's network
    @staticmethod
    def interface():
        """(iface, address, its network) of the first global IPv4 address that isn't docker's or a VM bridge."""
        return platforms.interface()

    def network(self):
        """{iface, ip, ssid, subnet}; ssid is "wired" on a non-wireless interface. Cached 5 s."""
        when, net = self._net
        if net and time.time() - when < 5:
            return net
        iface, ip, subnet = self.interface()
        ssid = security = None
        if iface:
            ssid, security = platforms.wifi_ssid(iface) if platforms.is_wireless(iface) else ("wired", None)
        net = {"iface": iface, "ip": ip, "ssid": ssid, "security": security, "subnet": str(subnet) if subnet else None}
        self._net = (time.time(), net)
        return net

    def blocked(self):
        """Why the link must stay down right now (no scanning, no connecting), or None."""
        c = self.cfg()
        if c["linkPaused"]:
            return "paused"
        if c["linkHomeOnly"] and self.network()["ssid"] not in c["linkNetworks"]:
            return "not home network"
        return None

    # ---- the pinned host key
    @staticmethod
    def pinned():
        return sshlink.pinned()

    def fingerprint(self):
        """(SHA256 fingerprint, key type) of the pinned key, ED25519 first; (None, None) if nothing is pinned."""
        try:
            mtime = os.stat(KNOWN_HOSTS).st_mtime
        except OSError:
            return None, None
        if self._fp[0] != mtime:
            keys = {}
            for line in run(tool("ssh-keygen"), "-lf", KNOWN_HOSTS).splitlines():
                m = re.match(r"\d+ (SHA256:\S+) .*\((\w+)\)$", line)
                if m:
                    keys.setdefault(m.group(2), m.group(1))
            kind = next((k for k in ("ED25519", "ECDSA", "RSA") if k in keys), next(iter(keys), None))
            self._fp = (mtime, (keys[kind], kind) if kind else (None, None))
        return self._fp[1]

    def pin(self, ip):
        """First run only: take the key the phone already has in ~/.ssh/known_hosts (or, failing that, what it
        offers now) and keep it under the alias."""
        if self.pinned():
            return True
        port = self.port()
        lines = [l for l in run(tool("ssh-keygen"), "-F", f"[{ip}]:{port}").splitlines() if l and not l.startswith("#")]
        if not lines:
            lines = [l for l in run(tool("ssh-keyscan"), "-T", "4", "-p", str(port), ip, timeout=10).splitlines()
                     if l and not l.startswith("#")]
        keys = [f"{HOST_ALIAS} {' '.join(l.split()[1:3])}\n" for l in lines if len(l.split()) >= 3]
        if not keys:
            return False
        with self.lock:
            os.makedirs(os.path.dirname(KNOWN_HOSTS), exist_ok=True)
            with open(KNOWN_HOSTS, "w", encoding="utf-8", newline="\n") as f:
                f.writelines(keys)
        print("pinned the phone's ssh host key", flush=True)
        return True

    # ---- finding the phone
    def offered(self, ip):
        return {tuple(l.split()[1:3]) for l in
                run(tool("ssh-keyscan"), "-T", "3", "-p", str(self.port()), ip, timeout=8).splitlines()
                if len(l.split()) >= 3 and not l.startswith("#")}

    def is_phone(self, ip):
        return bool(self.pinned() & self.offered(ip))

    def subnet(self):
        """The network to sweep (never more than a /24) and the laptop's own address."""
        _, mine, net = self.interface()
        if not net:
            return None, None
        return ipaddress.ip_network(f"{mine}/{max(24, net.prefixlen)}", strict=False), mine

    def discover(self, force=False):
        """The phone's current address, or None. At most one sweep every 20 s, unless forced (/link/find)."""
        with self.scan_lock:
            if self.blocked() or (not force and time.time() - self.last_scan < 20):
                return None
            self.last_scan = time.time()
            net, mine = self.subnet()
            if not net or not self.pinned():
                return None
            port = self.port()

            def open_port(ip):
                try:
                    with socket.create_connection((ip, port), timeout=0.6):
                        return ip
                except OSError:
                    return None

            hosts = [str(h) for h in net.hosts() if str(h) != mine]
            with concurrent.futures.ThreadPoolExecutor(48) as pool:
                candidates = [ip for ip in pool.map(open_port, hosts) if ip]
            self.scans += 1
            for ip in candidates:
                if self.is_phone(ip):
                    self.use(ip)
                    return ip
            # the saved address answers, with another key: say so rather than "not found"
            self.error = "key mismatch" if self.state.get("ip") in candidates else "not found"
            return None

    def use(self, ip):
        """Save ip as the phone's address; a tunnel running to another address is restarted."""
        with self.lock:
            if ip != self.state.get("ip"):
                print(f"found the phone at {ip}", flush=True)
                self.state["ip"] = ip
                save_state(self.state)
                self.restart = bool(self.started)
            self.fails, self.error = 0, None
        self.wake.set()

    def forget(self):
        """Drop the pinned key and the saved address, and stop the tunnel."""
        with self.lock:
            try:
                os.remove(KNOWN_HOSTS)
            except FileNotFoundError:
                pass
            self.state.pop("ip", None)
            save_state(self.state)
            self.fails, self.error, self.detail = 0, None, ""
            self.restart = True
        print("forgot the phone's key and address", flush=True)
        self.wake.set()

    def replace_pin(self, ip, keys):
        """Pairing confirmed: these keys only (old phone's dropped), this address, and a fresh tunnel."""
        with self.lock:
            os.makedirs(os.path.dirname(KNOWN_HOSTS), exist_ok=True)
            with open(KNOWN_HOSTS + ".tmp", "w", encoding="utf-8", newline="\n") as f:
                f.writelines(f"{HOST_ALIAS} {kind} {key}\n" for kind, key in keys)
            os.replace(KNOWN_HOSTS + ".tmp", KNOWN_HOSTS)
            self.state["ip"] = ip
            save_state(self.state)
            self.fails, self.error, self.detail, self.restart = 0, None, "", True
        self.wake.set()

    def reconnect(self):
        self.fails, self.restart = 0, True
        self.wake.set()

    def rtt(self, ip):
        """TCP connect time to the phone's sshd in ms (None if it doesn't answer). Cached 10 s."""
        when, key, ms = self._rtt
        target = (ip, self.port())
        if key == target and time.time() - when < 10:
            return ms
        t = time.monotonic()
        try:
            with socket.create_connection(target, timeout=1.5):
                ms = round((time.monotonic() - t) * 1000, 1)
        except OSError:
            ms = None
        self._rtt = (time.time(), target, ms)
        return ms

    # ---- the tunnel
    def reason(self):
        """Why the tunnel is down, or None when it's up."""
        if self.up:
            return None
        why = self.blocked()
        if why:
            return why
        if not self.pinned():
            return "no key pinned"
        if self.started:  # ssh running but not up yet
            return "connecting"
        return self.error or "not found"

    def snapshot(self):
        ip = self.state.get("ip")
        fp, kind = self.fingerprint()
        why = self.reason()
        probe = ip and why not in ("paused", "not home network")
        return {"tunnel": self.up, "ip": ip, "up_for": round(time.time() - self.since) if self.up else 0,
                "scans": self.scans, "pinned": bool(self.pinned()), "port": self.port(),
                "laptop": self.network(), "fingerprint": fp, "key_type": kind,
                "reason": why, "detail": self.detail if why else "",
                "rtt_ms": self.rtt(ip) if probe else None,
                "files": self.files, "files_detail": self.files_detail,
                "files_ago": round(time.time() - self.files_at) if self.files_at else None}

    # ---- the phone's copy of phone/
    def sync_files(self, ip, port):
        """Just after the tunnel came up: deploy once if the phone's stored hash of phone/ isn't the laptop's.
        Checking and deploying hold deploy.LOCK, so a deploy from pairing (or a second sync) is never doubled."""
        if not deploy.LOCK.acquire(timeout=300):
            return
        try:
            if not self.up or self.state.get("ip") != ip:
                return
            self.files, self.files_detail, self.files_at = "checking", "", time.time()
            want = deploy.digest()
            have = deploy.phone_digest(ip, port)
            if have == want:
                self.files, self.files_at = "up to date", time.time()
                return
            if have is None:  # couldn't ask (the tunnel just dropped?): say so, try again next time it comes up
                self.files, self.files_detail, self.files_at = "failed", "couldn't read the phone's version", time.time()
                return
            self.files, self.syncs = "updating", self.syncs + 1
            print(f"phone files differ from the laptop's: deploying to {ip}", flush=True)
            ok, lines = deploy.deploy(ip, port, locked=True)
            self.files, self.files_at = ("up to date" if ok else "failed"), time.time()
            self.files_detail = "" if ok else (lines[-1][:160] if lines else "deploy failed")
        finally:
            deploy.LOCK.release()

    def loop(self):
        while True:
            try:
                self.tick()
            except Exception as e:
                print("link:", e, flush=True)
            self.wake.wait(self.cfg()["linkRetry"])
            self.wake.clear()

    def tick(self):
        self.restart = False
        if self.blocked():
            return
        ip = self.state.get("ip")
        if ip and not self.pinned():
            self.pin(ip)
        if (not ip or self.fails >= 2) and self.cfg()["linkAutoFind"]:  # the saved address doesn't answer: look for the phone
            found = self.discover()
            if found:
                ip = found
        if ip and self.pinned():
            self.run_tunnel(ip)

    def run_tunnel(self, ip):
        port, keepalive = self.port(), self.cfg()["linkKeepAlive"]
        cmd = [tool("ssh"), "-N", *sshlink.options(port), "-o", "ExitOnForwardFailure=yes",
               "-o", "ConnectTimeout=8", "-o", f"ServerAliveInterval={keepalive}", "-o", "ServerAliveCountMax=3",
               "-R", f"{REMOTE_PORT}:127.0.0.1:{PORT}", ip]
        self.started = started = time.time()
        proc = platforms.proc.popen(cmd, stdin=DEVNULL, stdout=DEVNULL, stderr=PIPE)
        stopped = False
        try:
            while proc.poll() is None:
                if self.restart or self.blocked() or (self.port(), self.cfg()["linkKeepAlive"]) != (port, keepalive):
                    stopped = True  # paused, off the home network, reconnect/forget/new address, or new settings
                    proc.terminate()
                    try:
                        proc.wait(5)
                    except TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
                if not self.up and time.time() - started > 4:  # ssh -N prints nothing; alive after 4 s means connected
                    self.up, self.since, self.fails, self.error, self.detail = True, time.time(), 0, None, ""
                    threading.Thread(target=self.sync_files, args=(ip, port), daemon=True).start()
                time.sleep(1)
            err = proc.stderr.read() if not stopped else ""
        finally:
            proc.stderr.close()
            self.up, self.started, self.restart = False, 0.0, False
        if stopped:
            return
        lines = [l.strip() for l in err.splitlines() if l.strip()]
        self.detail = lines[-1][:160] if lines else ""
        self.error = "key mismatch" if any(t in err for t in self.HOST_KEY_CHANGED) else "not found"
        if time.time() - started < 10:
            self.fails += 1


# ---------------------------------------------------------------- pairing a new phone (Wi-Fi only, no adb)

class Pairing:
    """One pairing at a time, started from the dashboard. Threat: anyone else on the Wi-Fi, who can read and even
    rewrite the plain-HTTP traffic. Design:
    - A one-shot server on the laptop's LAN address only (PAIR_PORT, never 0.0.0.0/loopback), open 10 min.
    - Integrity: the script's URL is its own SHA-256 (first 128 bits), and the command you type on the phone checks
      the downloaded script against it before running it; the script carries the bundle's full SHA-256. So nobody
      on the network can change what runs on the phone, even though they can see it.
    - The script is served only to the first address that asks for it, the bundle once and only to that address.
    - Nothing is pinned by itself: the phone prints its ssh key's pairing code at the end of setup and you type it
      into the dashboard; the laptop keyscans the phone at that moment and pins only the key matching that code
      (96 bits: no one can make a key that matches). The candidate's fingerprint is never shown by the laptop, so
      it can't be copied from the dashboard instead of read off the phone. 5 wrong codes end the pairing.
    - The bundle holds nothing secret (phone/ code + the laptop's public key)."""
    SERVE_FOR = 600      # the download server closes after 10 min, or once the bundle has been fetched
    CONFIRM_FOR = 1800   # after the fetch, how long the phone has to finish setup and you to type the code
    MAX_WRONG = 5
    CODE_LEN = 16        # base64 characters of the fingerprint the code covers (96 bits)

    def __init__(self, link):
        self.link = link  # the PhoneLink whose pin a confirmed pairing replaces
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(8)  # requests handled at once by the pairing server
        self.server = None
        self.session = None

    # ---- what's handed out
    @staticmethod
    def public_key():
        """The public half of the key the tunnel's ssh uses (Chip's own, or the first identity ssh -G lists)."""
        return sshlink.public_key()

    @staticmethod
    def bundle(pubkey):
        """phone/ as deploy.py sends it (minus __pycache__ and setup.sh), plus authorized_keys: the layout setup.sh's
        $SRC expects."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            deploy.add_files(tar, "phone/")
            data = (pubkey + "\n").encode()
            info = tarfile.TarInfo("authorized_keys")
            info.size, info.mode, info.mtime = len(data), 0o600, int(time.time())
            tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    @staticmethod
    def script(ip, bundle_token, digest):
        """Downloads and checks the bundle, then runs phone/setup.sh on the extracted folder."""
        with open(os.path.join(deploy.PHONE, "setup.sh"), encoding="utf-8") as f:
            setup = f.read()
        if "DESKBUDDY_SETUP_EOF" in setup:
            raise ValueError("setup.sh contains the heredoc marker")
        return f"""#!/data/data/com.termux/files/usr/bin/bash
# Chip pairing script from the laptop at {ip}. Checked against its SHA-256 before it ran.
{{
set -e
DIR="$HOME/deskbuddy-pair"
rm -rf "$DIR" && mkdir -p "$DIR"
if ! curl -fsS "http://{ip}:{PAIR_PORT}/{bundle_token}/bundle.tar.gz" -o "$DIR/bundle.tar.gz"; then
  echo "!! Couldn't get the setup files. If this phone didn't already fetch them, someone else did:"
  echo "!! cancel pairing on the laptop's dashboard and start again. Don't confirm anything."
  exit 1
fi
echo "{digest}  $DIR/bundle.tar.gz" | sha256sum -c --quiet || {{ echo "!! setup files altered: cancel pairing"; exit 1; }}
tar xzf "$DIR/bundle.tar.gz" -C "$DIR" && rm -f "$DIR/bundle.tar.gz"
cat >"$DIR/setup.sh" <<'DESKBUDDY_SETUP_EOF'
{setup}DESKBUDDY_SETUP_EOF
bash "$DIR/setup.sh" "$DIR" </dev/null
exit
}}
"""

    # ---- the session
    def start(self):
        """(answer, http status). The handler has checked the Origin, the replace rule and blocked()."""
        net_info = self.link.network()
        _, ip, net = self.link.interface()
        if not ip:
            return {"ok": False, "error": "no network"}, 409
        security = net_info.get("security")  # "" = an open Wi-Fi; None = unknown (refused only if this OS can tell)
        if net_info["ssid"] != "wired" and (security == "" or (security is None and platforms.caps()["wifiName"])):
            return {"ok": False, "error": "open wifi", "message": "this Wi-Fi has no password: pair on your home network"}, 409
        homes = self.link.cfg()["linkNetworks"]
        if homes and net_info["ssid"] not in homes:
            return {"ok": False, "error": "not home network", "message": "pairing only on the networks in linkNetworks"}, 409
        pubkey = self.public_key()
        if not pubkey:
            return {"ok": False, "error": "no ssh key", "message": "run laptop/install.py, or make one with ssh-keygen -t ed25519"}, 409
        self.cancel()
        bundle_token = secrets.token_hex(16)  # 128 bits
        bundle = self.bundle(pubkey)
        script = self.script(ip, bundle_token, hashlib.sha256(bundle).hexdigest()).encode()
        script_id = hashlib.sha256(script).hexdigest()[:32]  # the script's URL is its own hash
        pairing = self

        class PairHandler(BaseHTTPRequestHandler):
            server_version, sys_version = "", ""
            timeout = 15  # a slow or idle client can't hold a thread

            def handle(self):
                if not pairing.slots.acquire(blocking=False):  # too many at once: drop the connection
                    return
                try:
                    super().handle()
                finally:
                    pairing.slots.release()

            def answer(self, code, body=b"", kind="application/octet-stream"):
                self.send_response_only(code)
                if body:
                    self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command == "GET":
                    self.wfile.write(body)
                self.close_connection = True

            def do_GET(self):
                s, who = pairing.session, self.client_address[0]
                if not s or self.headers.get("Host") != f"{ip}:{PAIR_PORT}" or time.time() > s["until"]:
                    return self.answer(404)
                parts = self.path.split("/")
                if len(parts) == 2 and hmac.compare_digest(parts[1].encode(), s["script_id"].encode()):
                    if pairing.take_script(s, who):
                        return self.answer(200, s["script"], "text/x-shellscript")
                elif parts[1:] == [parts[1], "bundle.tar.gz"] and len(parts) == 3 \
                        and hmac.compare_digest(parts[1].encode(), s["bundle_token"].encode()):
                    if pairing.take_bundle(s, who):
                        self.answer(200, s["bundle"], "application/gzip")
                        threading.Thread(target=pairing.close_server, daemon=True).start()
                        return
                return self.answer(404)

            def do_HEAD(self):
                self.answer(404)

            do_POST = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = do_HEAD

            def send_error(self, code, message=None, explain=None):  # malformed requests: a bare status, no page
                self.close_connection = True
                try:
                    self.send_response_only(404 if code == 404 else 400)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                except OSError:
                    pass

            def log_message(self, *args):  # the request line carries the URL: never log it
                pass

        class PairServer(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 8

            def handle_error(self, request, client_address):  # no tracebacks (they could show the request)
                pass

        try:
            server = PairServer((ip, PAIR_PORT), PairHandler)
        except OSError as e:
            return {"ok": False, "error": "port busy", "message": f"{ip}:{PAIR_PORT}: {e.strerror}"}, 409
        with self.lock:
            self.server = server
            self.session = {"script_id": script_id, "bundle_token": bundle_token, "ip": ip, "net": net,
                            "until": time.time() + self.SERVE_FOR, "script": script, "bundle": bundle,
                            "script_by": None, "fetched_by": None, "fetched_at": 0.0, "ready": None,
                            "error": None, "wrong": 0}
        threading.Thread(target=server.serve_forever, daemon=True).start()
        timer = threading.Timer(self.SERVE_FOR, self.close_server, args=(server,))
        timer.daemon = True
        timer.start()
        print(f"pairing: download server open on {ip}:{PAIR_PORT} for {self.SERVE_FOR // 60} min", flush=True)
        return dict(self.status(), ok=True), 200

    def take_script(self, s, addr):
        """The script goes to the first address that asks (again to it, e.g. after a failed download), no one else."""
        with self.lock:
            if self.session is not s or s["fetched_by"] or (s["script_by"] and s["script_by"] != addr):
                return False
            if not s["script_by"]:
                s["script_by"] = addr
                print(f"pairing: script fetched by {addr}", flush=True)
            return True

    def take_bundle(self, s, addr):
        """Once, and only to the address that got the script; that address is the candidate phone."""
        with self.lock:
            if self.session is not s or s["fetched_by"] or s["script_by"] != addr:
                return False
            s["fetched_by"], s["fetched_at"] = addr, time.time()
        print(f"pairing: bundle fetched by {addr}", flush=True)
        threading.Thread(target=self.watch_candidate, args=(s,), daemon=True).start()
        return True

    def close_server(self, server=None):
        with self.lock:
            if self.server is None or (server is not None and server is not self.server):
                return
            server, self.server = self.server, None
        server.shutdown()
        server.server_close()
        print("pairing: download server closed", flush=True)

    def host_keys(self, addr):
        """[(kind, key, fingerprint base64)] that addr's sshd offers now."""
        keys = []
        for l in run(tool("ssh-keyscan"), "-T", "3", "-p", str(self.link.port()), addr, timeout=8).splitlines():
            f = l.split()
            if len(f) >= 3 and not l.startswith("#"):
                fp = run(tool("ssh-keygen"), "-lf", "-", input=f"x {f[1]} {f[2]}\n").split()
                if len(fp) >= 2 and fp[1].startswith("SHA256:"):
                    keys.append((f[1], f[2], fp[1][7:]))
        return keys

    def watch_candidate(self, s):
        """sshd on the new phone starts at the end of setup: notice when it answers (for the dashboard's progress)."""
        addr = s["fetched_by"]
        if ipaddress.ip_address(addr) not in s["net"]:
            s["error"] = "fetched from outside the local network"
            return
        while self.session is s and time.time() < s["fetched_at"] + self.CONFIRM_FOR:
            if self.host_keys(addr):
                s["ready"] = time.time()
                return
            time.sleep(5)

    def status(self):
        s = self.session
        if not s:
            return {"active": False}
        serving = self.server is not None
        left = (s["until"] if serving else s["fetched_at"] + self.CONFIRM_FOR if s["fetched_by"] else 0) - time.time()
        if left <= 0:
            return {"active": False, "expired": True}
        h = s["script_id"]
        out = {"active": True, "expires_in": round(left), "serving": serving,
               "command": f"h={h}; curl -fsSo chip.sh http://{s['ip']}:{PAIR_PORT}/$h && sha256sum chip.sh | "
                          f"grep -q ^$h && bash chip.sh || echo PAIRING FAILED",
               "script_by": s["script_by"], "fetched_by": s["fetched_by"],
               # no fingerprint here on purpose: the code must be read off the phone, not copied from the laptop
               "candidate": {"ip": s["fetched_by"], "ready": bool(s["ready"])} if s["fetched_by"] else None,
               "wrong_codes": s["wrong"], "code_length": self.CODE_LEN}
        if s["error"]:
            out["error"] = s["error"]
        if platforms.firewall_on():
            out["firewall"] = (f"ufw is on, so the phone can't reach port {PAIR_PORT}: for this pairing only, "
                               f"sudo ufw allow from {s['net']} to any port {PAIR_PORT} proto tcp   "
                               f"(after: sudo ufw delete allow from {s['net']} to any port {PAIR_PORT} proto tcp)")
        return out

    def confirm(self, code):
        """code: the pairing code the phone printed (or its full SHA256 fingerprint)."""
        code = re.sub(r"\s+", "", code) if isinstance(code, str) else ""
        code = code[7:] if code.startswith("SHA256:") else code
        if len(code) < self.CODE_LEN or not re.fullmatch(r"[A-Za-z0-9+/]+=*", code):
            return {"ok": False, "error": "bad code", "message": f"type the {self.CODE_LEN}-character code the phone shows"}, 400
        with self.lock:
            s = self.session
            if not self.status().get("active") or not s["fetched_by"] or s["error"]:
                return {"ok": False, "error": "no candidate", "message": "no phone has finished setup yet"}, 409
            ip = s["fetched_by"]
        keys = [k for k in self.host_keys(ip) if k[2].startswith(code.rstrip("="))]  # what the phone offers right now
        with self.lock:
            if self.session is not s:
                return {"ok": False, "error": "no candidate"}, 409
            if not keys:
                s["wrong"] += 1
                if s["wrong"] >= self.MAX_WRONG:
                    self.session = None
                    print("pairing: cancelled after too many wrong codes", flush=True)
                    return {"ok": False, "error": "too many wrong codes", "message": "pairing cancelled"}, 409
                return {"ok": False, "error": "code mismatch", "tries_left": self.MAX_WRONG - s["wrong"]}, 409
            self.session = None
        self.link.replace_pin(ip, [keys[0][:2]])
        print(f"pairing: pinned the phone at {ip}", flush=True)
        ok, lines = deploy.deploy(ip, self.link.port())
        return {"ok": True, "ip": ip, "fingerprint": "SHA256:" + keys[0][2],
                "deploy": {"ok": ok, "lines": lines[-20:]}}, 200

    def cancel(self):
        with self.lock:
            self.session = None
        self.close_server()
        return {"ok": True}
