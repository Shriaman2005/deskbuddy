#!/usr/bin/env python3
"""Copies phone/ to the phone's Termux (~/deskbuddy) over the pinned ssh and restarts Chip's server there; the face
notices the new version.txt and reloads itself within a minute. Same on every OS: the tar is built here in Python.
Run: python3 -I laptop/deploy.py [phone ip]   (default: the address the bridge saved; ./deploy.sh calls this)

The bundle ends with .chip-hash, the SHA-256 of what was sent (deploy.digest()), so it lands only if everything
before it did; the bridge reads it back when the tunnel comes up and deploys again only when phone/ changed.
Used by the bridge too: pairing deploys to the new phone, PhoneLink.sync_files keeps the phone current."""
import hashlib
import io
import json
import os
import sys
import tarfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I skips the script's folder
import sshlink  # noqa: E402
from platforms import paths, proc  # noqa: E402

PHONE = os.path.join(paths.REPO, "phone")
HASH_FILE = ".chip-hash"   # in ~/deskbuddy on the phone
SKIP = ("setup.sh", "www/version.txt", HASH_FILE)  # setup.sh runs once at pairing; version.txt is made per deploy
DEPLOY_CMD = 'mkdir -p ~/deskbuddy && tar xz -C ~/deskbuddy && { pkill -f "[d]eskbuddy/server.py"; bash ~/deskbuddy/services.sh; }'
HASH_CMD = f"cat ~/deskbuddy/{HASH_FILE} 2>/dev/null; true"
LOCK = threading.Lock()  # one deploy (or sync check) at a time within the bridge


def files():
    """[(path relative to phone/ with forward slashes, full path)] of what goes to the phone, sorted."""
    out = []
    for root, dirs, names in os.walk(PHONE):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, PHONE).replace(os.sep, "/")
            if rel in SKIP or name.endswith(".pyc") or os.path.islink(full) or not os.path.isfile(full):
                continue
            out.append((rel, full))
    return sorted(out)


def digest():
    """SHA-256 over the names and contents of files(): what the phone should have."""
    h = hashlib.sha256()
    for rel, full in files():
        with open(full, "rb") as f:
            h.update(rel.encode() + b"\0" + hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def _mode(rel, full):
    if os.name == "nt":  # Windows has no exec bits: the scripts Termux runs get them anyway
        return 0o755 if rel.endswith((".sh", ".py")) else 0o644
    return os.stat(full).st_mode & 0o777


def add_files(tar, prefix=""):
    """Adds files() under prefix, a fresh www/version.txt and, last, .chip-hash. No owners, no links."""
    def add(name, data, mode, mtime):
        info = tarfile.TarInfo(prefix + name)
        info.size, info.mode, info.mtime = len(data), mode, int(mtime)
        tar.addfile(info, io.BytesIO(data))

    h, newest = hashlib.sha256(), 0
    for rel, full in files():
        with open(full, "rb") as f:
            data = f.read()
        h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
        newest = max(newest, os.path.getmtime(full))
        add(rel, data, _mode(rel, full), os.path.getmtime(full))
    # the generated files are dated like the newest file, not "now": a phone clock a second behind makes tar complain
    add("www/version.txt", f"{int(time.time())}\n".encode(), 0o644, newest)  # the face reloads when this changes
    add(HASH_FILE, (h.hexdigest() + "\n").encode(), 0o644, newest)


def bundle():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        add_files(tar)
    return buf.getvalue()


def phone_digest(ip, port):
    """The hash the phone stored at its last deploy, "" if none, None if the phone couldn't be asked."""
    try:
        r = proc.complete(sshlink.command(ip, port, HASH_CMD), timeout=30)
    except (OSError, proc.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def deploy(ip, port, locked=False):
    """(ok, output lines). locked: the caller already holds LOCK."""
    if not locked:
        with LOCK:
            return deploy(ip, port, locked=True)
    try:
        r = proc.complete(sshlink.command(ip, port, DEPLOY_CMD), timeout=180, input=bundle(), text=False)
    except (OSError, proc.TimeoutExpired) as e:
        return False, [f"{type(e).__name__}: {e}"]
    lines = (r.stdout + r.stderr).decode("utf-8", "replace").splitlines()
    if r.returncode == 0:
        lines.append(f"Deployed to {ip}")
    return r.returncode == 0, lines


def saved():
    """(ip, sshd port) the bridge saved: state.json's ip, the sshPort setting (8022 unless changed)."""
    try:
        with open(paths.config("state.json"), encoding="utf-8") as f:
            ip = json.load(f).get("ip")
    except (OSError, ValueError):
        ip = None
    try:
        with open(paths.config("settings.json"), encoding="utf-8") as f:
            port = int(json.load(f)["values"].get("sshPort", 8022))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        port = 8022
    return ip, port


def main(argv):
    ip, port = saved()
    ip = argv[1] if len(argv) > 1 else ip
    if not ip:
        print("No phone address saved yet: pair a phone on the dashboard (Connections), or give its IP.", file=sys.stderr)
        return 1
    if not sshlink.pinned():
        print("No phone key pinned: pair the phone on the dashboard first (Connections → Replace phone).", file=sys.stderr)
        return 1
    ok, lines = deploy(ip, port)
    print("\n".join(lines), file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
