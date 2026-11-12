"""Chip's update check (the dashboard's Updates card and Chip's "I've got an update!" bubble).

Once a day the bridge asks GitHub for the latest release of the Chip repo and compares its tag with the VERSION
file at the top of the Chip folder. Nothing about this laptop is sent: one anonymous GET to api.github.com.
Settings: updateCheck (the daily check), updateBubble (Chip mentions it on the phone).

Updating (POST /update/apply, dashboard only):
- a git clone: `git fetch` the release's tag and `git merge --ff-only` it. Refused while tracked files have local
  edits, so nobody's changes are overwritten. If requirements.txt changed and the bridge runs in a venv (Windows,
  macOS), pip installs them there. Then the bridge exits and its supervisor starts the new one (systemd
  Restart=always, launchd KeepAlive, supervise.py); the phone gets the new files by itself when the tunnel is
  back (the .chip-hash check in link.py).
- a Download ZIP folder (most Windows and macOS installs): the release's ZIP from GitHub is downloaded, checked
  (one Chip folder inside, its VERSION = the tag, no path leaving the folder, no links) and unpacked into
  .chip-update/ inside the Chip folder; then each file is moved over the old one. The folder keeps its path, so the
  start-at-login entry stays right. Files a release removed stay behind (harmless). Then pip and the restart as for
  git. CHIP_UPDATE_ZIP replaces the GitHub ZIP URL (tests: a file:// URL).

Publishing an update: bump VERSION, commit, push, then make a GitHub release whose tag is "v" + VERSION
(e.g. v1.1.0); the release notes are what the dashboard shows.
"""
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

from platforms import paths, proc

REPO = "Shriaman2005/deskbuddy"
ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VERSION_FILE = os.path.join(ROOT, "VERSION")
REQUIREMENTS = os.path.join(ROOT, "laptop", "requirements.txt")
STATE_FILE = paths.config("update.json")  # the last check: when, and what GitHub said
# CHIP_UPDATE_URL points the check somewhere else (tests); "off" disables it
API = os.environ.get("CHIP_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"
ZIP_URL = os.environ.get("CHIP_UPDATE_ZIP") or f"https://github.com/{REPO}/archive/refs/tags/{{tag}}.zip"
ZIP_MAX = 64 * 1024 * 1024  # a release ZIP is about 3 MB
STAGING = ".chip-update"
EVERY = 24 * 3600
TAG = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")


def parse(text):
    """'v1.2' / '1.2.3' -> (1, 2, 0) / (1, 2, 3); None if it isn't a version."""
    m = TAG.fullmatch((text or "").strip())
    return tuple(int(g or 0) for g in m.groups()) if m else None


def current():
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


class ZipUpdateError(Exception):
    pass


def zip_files(data, tag):
    """The release ZIP's files as [(path inside the Chip folder, unix mode or 0, ZipInfo)], after the checks."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
    except (zipfile.BadZipFile, OSError) as e:
        raise ZipUpdateError(f"the download isn't a ZIP ({e})") from None
    tops = {i.filename.split("/", 1)[0] for i in infos}
    if len(tops) != 1:
        raise ZipUpdateError("the ZIP should hold one Chip folder")
    top = tops.pop() + "/"
    files = []
    for i in infos:
        rel = i.filename[len(top):]
        mode = i.external_attr >> 16
        if not rel or i.is_dir():
            continue
        parts = rel.split("/")
        if (not i.filename.startswith(top) or "\\" in rel or ":" in rel or rel.startswith("/")
                or any(p in ("", ".", "..") for p in parts) or parts[0] in (".git", STAGING)):
            raise ZipUpdateError(f"the ZIP has a path Chip won't write: {i.filename[:120]}")
        if stat.S_ISLNK(mode):
            raise ZipUpdateError(f"the ZIP has a link: {i.filename[:120]}")
        files.append((rel, mode, i))
    names = {rel for rel, _, _ in files}
    if "laptop/bridge.py" not in names or "VERSION" not in names:
        raise ZipUpdateError("the ZIP isn't a Chip folder")
    version = z.read(top + "VERSION").decode("utf-8", "replace").strip()
    if parse(version) != parse(tag):
        raise ZipUpdateError(f"the ZIP says version {version[:20]!r}, not {tag}")
    return z, files


def unpack_over(root, data, tag):
    """Unpacks the checked release ZIP over the Chip folder at root: everything into root/.chip-update first, then
    file by file into place (os.replace, so no file is ever half written)."""
    z, files = zip_files(data, tag)
    stage = os.path.join(root, STAGING)
    shutil.rmtree(stage, ignore_errors=True)
    try:
        for rel, mode, info in files:
            dest = os.path.join(stage, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            if os.name != "nt" and mode & 0o111:
                os.chmod(dest, 0o755)
        for rel, _, _ in files:
            dest = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.replace(os.path.join(stage, *rel.split("/")), dest)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return len(files)


def download(url, limit=ZIP_MAX):
    req = urllib.request.Request(url, headers={"User-Agent": "deskbuddy-bridge"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ZipUpdateError("the download is too big for a Chip release")
    return data


def file_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


class Updater:
    def __init__(self, settings_get):
        self.settings_get = settings_get
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.busy = ""  # "checking" | "updating" | ""
        self.error = ""
        self.restarting = False
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.checked = saved.get("checked", 0) if isinstance(saved.get("checked"), (int, float)) else 0
        self.latest = saved.get("latest") if isinstance(saved.get("latest"), dict) else None

    # ------------------------------------------------------------ what this folder is
    def git(self, *args, timeout=60):
        git = proc.which("git")
        if not git:
            raise OSError("git is not installed")
        return proc.complete([git, "-C", ROOT, *args], timeout=timeout)

    def mode(self):
        """'git' for a clone git can update, else 'zip'."""
        if not os.path.isdir(os.path.join(ROOT, ".git")) or not proc.which("git"):
            return "zip"
        return "git"

    def dirty(self):
        """Tracked files with local edits (an update would refuse to overwrite them)."""
        try:
            r = self.git("status", "--porcelain", "--untracked-files=no", timeout=15)
        except (OSError, proc.TimeoutExpired):
            return []
        return [line[3:] for line in r.stdout.splitlines() if line.strip()][:20]

    # ------------------------------------------------------------ the check
    def available(self):
        """The newer version's tag, or "" (also "" while the check is off)."""
        if not self.settings_get().get("updateCheck", True) or not self.latest:
            return ""
        have, new = parse(current()), parse(self.latest.get("tag"))
        return self.latest["tag"] if have and new and new > have else ""

    def check(self):
        if API == "off":
            return
        with self.lock:
            if self.busy:
                return
            self.busy = "checking"
        try:
            req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "deskbuddy-bridge"})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.load(r)
                latest = {"tag": str(data.get("tag_name", ""))[:40], "name": str(data.get("name") or "")[:120],
                          "notes": str(data.get("body") or "")[:6000], "url": str(data.get("html_url") or "")[:300],
                          "published": str(data.get("published_at") or "")[:30]}
                if not parse(latest["tag"]):
                    raise ValueError(f"the latest release's tag {latest['tag']!r} isn't a version like v1.2.0")
                self.latest, self.error = latest, ""
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                self.latest, self.error = None, ""  # no release published yet
            self.checked = time.time()
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"checked": self.checked, "latest": self.latest}, f, indent=1)
            os.replace(STATE_FILE + ".tmp", STATE_FILE)
        except (OSError, ValueError) as e:
            self.error = f"couldn't reach GitHub: {getattr(e, 'reason', None) or e}"[:200]
            print("updates:", self.error, flush=True)
        finally:
            self.busy = ""

    def loop(self):
        self.wake.wait(60)  # not in the middle of starting up
        while True:
            self.wake.clear()
            if self.settings_get().get("updateCheck", True) and time.time() - self.checked >= EVERY:
                self.check()
            self.wake.wait(3600)

    def state(self):
        m = self.mode()
        latest = self.latest or {}
        return {"current": current(), "latest": latest.get("tag", ""), "name": latest.get("name", ""),
                "notes": latest.get("notes", ""), "url": latest.get("url", "") or f"https://github.com/{REPO}/releases",
                "zip": f"https://github.com/{REPO}/archive/refs/tags/{latest['tag']}.zip" if latest.get("tag") else "",
                "available": self.available(), "mode": m, "dirty": self.dirty() if m == "git" else [],
                "checked": self.checked, "busy": self.busy, "error": self.error, "restarting": self.restarting,
                "on": bool(self.settings_get().get("updateCheck", True))}

    # ------------------------------------------------------------ the update
    def apply(self):
        """(answer, http code). On success the caller restarts the bridge (restart())."""
        tag = self.available()
        if not tag:
            return {"ok": False, "error": "no update", "message": "Chip is up to date"}, 409
        zip_mode = self.mode() != "git"
        if zip_mode and os.path.isdir(os.path.join(ROOT, ".git")):  # a clone on a laptop without git: not a ZIP's job
            return {"ok": False, "error": "git", "message": "this folder is a git clone but git isn't installed: "
                    "install git, or run git pull yourself"}, 409
        dirty = [] if zip_mode else self.dirty()
        if dirty:
            return {"ok": False, "error": "dirty", "files": dirty,
                    "message": "files in the Chip folder have local changes; undo or commit them first"}, 409
        with self.lock:
            if self.busy:
                return {"ok": False, "error": "busy", "message": f"already {self.busy}"}, 409
            self.busy = "updating"
        try:
            req_before = file_hash(REQUIREMENTS)
            if zip_mode:
                try:
                    data = download(ZIP_URL.format(tag=tag))
                except (OSError, ValueError) as e:
                    return {"ok": False, "error": "download",
                            "message": f"couldn't download {tag}: {getattr(e, 'reason', None) or e}"[:300]}, 502
                try:
                    unpack_over(ROOT, data, tag)
                except ZipUpdateError as e:
                    return {"ok": False, "error": "zip", "message": str(e)[:300]}, 502
                except OSError as e:
                    return {"ok": False, "error": "write", "message": "couldn't write the Chip folder ("
                            + str(e)[:200] + "): download the new version and run the installer again"}, 500
            else:
                r = self.git("fetch", "--quiet", "origin", f"refs/tags/{tag}:refs/tags/{tag}", timeout=120)
                if r.returncode:
                    return {"ok": False, "error": "fetch", "message": (r.stderr or r.stdout).strip()[-400:]}, 502
                r = self.git("merge", "--ff-only", "--quiet", tag)
                if r.returncode:
                    return {"ok": False, "error": "merge", "message": "this folder has commits the release doesn't: "
                            + (r.stderr or r.stdout).strip()[-300:]}, 409
            note = ""
            if file_hash(REQUIREMENTS) != req_before:
                if sys.prefix != sys.base_prefix:  # the installer's venv (Windows, macOS)
                    p = proc.complete([sys.executable, "-I", "-m", "pip", "install", "--disable-pip-version-check",
                                       "-q", "-r", REQUIREMENTS], timeout=300)
                    if p.returncode:
                        note = "pip couldn't install the new requirements: run the installer again"
                else:
                    note = "the requirements changed: run the installer again"
            return {"ok": True, "version": current(), "note": note}, 200
        except (OSError, proc.TimeoutExpired) as e:
            return {"ok": False, "error": "failed", "message": str(e)[:300]}, 500
        finally:
            self.busy = ""

    def restart(self):
        """Exit after the answer has gone out; systemd / launchd / supervise.py start the updated bridge."""
        self.restarting = True
        threading.Timer(1.5, os._exit, (0,)).start()
