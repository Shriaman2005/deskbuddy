#!/usr/bin/env python3
"""Desk buddy bridge (runs on the laptop as a systemd user service).

- Serves laptop stats plus media and volume controls on 127.0.0.1:8765.
  The phone reaches it as its own 127.0.0.1:8765 through an ssh reverse tunnel to Termux.
- Types text dictated on the phone into the focused window (POST /type; refused while locked).
  When the dashboard's dictation engine is the laptop or a cloud API, the phone sends the clip to POST /transcribe
  and this laptop's whisper.cpp or the chosen provider turns it into text (laptop/stt.py; keys: /stt/key).
- Notices when you're typing (how long and how fast, never which keys) so Chip can type along on the phone.
- Collects moments when an AI agent or app needs you (agent hooks call POST /attention via attention.py,
  and desktop notifications are watched on the session bus); the phone blinks its torch and plays a sound,
  as chosen per app on the dashboard.
- Streams a cava-style audio spectrum of what the laptop is playing at /viz (server-sent events).
- Streams where Chip should look to follow the mouse pointer at /gaze (server-sent events). The pointer position
  comes from the chip-gaze GNOME Shell extension (laptop/gnome-extension), which Wayland apps cannot do themselves.
- Stores Chip skins (chip-skin/1 JSON made with a chatbot) under /skins: the chatbot prompt, the check, draft,
  install, list, delete. laptop/skin.js does the checking; photos never reach the laptop, only JSON.
- Keeps the ssh tunnel to the phone up over the home Wi-Fi, and finds the phone again by itself if its
  address changes (PhoneLink). Nothing needs a cable or adb.
- Serves the dashboard at http://127.0.0.1:8765/ for showing/hiding the buddy's features and setting
  its sleep time. The phone picks up changes on its next /stats poll (a few seconds).
"""
import collections
import concurrent.futures
import glob
import hashlib
import hmac
import io
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import subprocess
import tarfile
import threading
import time
import urllib.request
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I skips the script's folder
import stt  # noqa: E402
import typer  # noqa: E402

PORT = 8765
PAIR_PORT = 8766  # the one-shot download server for pairing a new phone (laptop's LAN address only)
HOST_ALIAS = "chip-phone"  # the phone's ssh host key is pinned under this name, whatever its IP is
KNOWN_HOSTS = os.path.expanduser("~/.config/deskbuddy/known_hosts")
STATE_FILE = os.path.expanduser("~/.config/deskbuddy/state.json")
SETTINGS_FILE = os.path.expanduser("~/.config/deskbuddy/settings.json")
GAZE_FILE = os.path.expanduser("~/.config/deskbuddy/gaze.json")  # where the phone sits, per monitor layout
DASHBOARD = os.path.join(HERE, "dashboard.html")
PREVIEW = os.path.realpath(os.path.join(HERE, "..", "phone", "www"))  # the buddy page itself, for the dashboard's preview
PACK_FILE = os.path.join(PREVIEW, "pack.json")
SKINS_DIR = os.path.expanduser("~/.config/deskbuddy/skins")  # <id>.json per installed skin, _draft.json for the passing upload
SKIN_JS = os.path.join(HERE, "skin.js")
SKIN_ID = re.compile(r"[a-z0-9-]{1,32}")
SKIN_MAX = 600 * 1024  # bytes of a skin file (skin.js enforces the same)
SKIN_LIMIT = 30        # installed skins
# Who may use the bridge: the dashboard (served from here) and the buddy page on the phone (through the tunnel).
# Other websites open in the laptop's browser can reach 127.0.0.1 too, so requests from them are refused.
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ORIGINS = {f"http://{h}" for h in HOSTS} | {"http://127.0.0.1:8080", "http://localhost:8080"}
DASHBOARD_ORIGIN = f"http://127.0.0.1:{PORT}"  # the only origin allowed to manage the link (Handler.dashboard_only)
DOCTOR = os.path.join(HERE, "doctor.py")
# Dictation engines (laptop/stt.py): whisper.cpp v1.9.5 built here (static, AVX2), models from ggerganov/whisper.cpp
# on Hugging Face in ~/.local/share/deskbuddy/stt/models; for a 4 s sentence on this Ryzen 5 3450U: small ~2 s
# (best with Hinglish), base ~0.8 s (fast mode). Or a cloud API, with keys in ~/.config/deskbuddy/secrets.json.


def run(*cmd, timeout=6, input=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


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


# ---------------------------------------------------------------- settings (edited on the dashboard)

TOGGLES = (
    "tabClock", "tabLaptop", "tabTimer", "tabViz",                                  # swipe tabs
    "dock", "dockTime", "dockWeather", "dockAqi", "dockCpu", "dockLaptopTemp", "dockLaptopBattery",
    "dockPhoneBattery", "dockPhoneTemp", "timerPill", "focusBar", "dots", "musicMode", "mask",
    "clockNow", "clockHours", "clockAir", "ringCpu", "ringRam", "ringGpu", "ringBattery", "mediaCard",
    "sounds", "talk", "idle", "greetings", "hourly", "trackToasts", "laptopAlerts", "phoneAlerts", "shake",
    "stretch", "dictation", "fastDictation", "sleep", "drowsy",
    # attention alerts: "torch" is the master switch (it was torch-only at first), the rest say what, how and when
    "torch", "torchAsk", "torchDone", "torchApps", "notifyAllApps", "alertTorch", "alertSound",
    "torchAway", "torchRepeat", "torchNight", "behaviourTorch",
    "pomoAutoBreak", "pomoAutoFocus", "workScene",                                  # timer
    "typingScene",                                                                  # Chip types along with you
)


_pack_eyes = {"mtime": None, "default": "classic", "ids": ("classic",)}


def pack_eyes():
    """(default eye style, style ids) from pack.json, re-read when the file changes."""
    try:
        mtime = os.stat(PACK_FILE).st_mtime
        if mtime != _pack_eyes["mtime"]:
            with open(PACK_FILE) as f:
                eyes = json.load(f)["eyes"]
            _pack_eyes.update(mtime=mtime, default=eyes["default"], ids=tuple(eyes["styles"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return _pack_eyes["default"], _pack_eyes["ids"]


def skin_path(skin_id):
    return os.path.join(SKINS_DIR, skin_id + ".json")


DEFAULTS = dict.fromkeys(TOGGLES, True) | {
    "fastDictation": False, "torchAway": False, "torchNight": False, "notifyAllApps": False, "pomoAutoFocus": False, "burnGuard": False, "gazeFollow": False,
    "stretchMin": 50, "brightnessDay": 90,
    "sleepAt": "23:00", "wakeAt": "06:30", "brightnessNight": 3, "drowsyMin": 45,
    "torchSeconds": 3, "soundSeconds": 2, "soundVolume": 80, "soundStyle": "chime", "remindEvery": 20, "remindMinutes": 3,
    "pomoFocus": 25, "pomoShort": 5, "pomoLong": 15, "pomoLongEvery": 4, "pomoGoal": 8, "typingAfter": 10,
    "accent": "cyan", "accentColor": "#2ee6f2", "chipGlow": 100, "eyeGap": 0, "phonesGap": 0, "idleRate": "normal", "idleOff": [],
    "eyeStyle": pack_eyes()[0], "pupilSize": "M", "showPupils": True, "skin": "", "phonesFollowSkin": True, "phonesDefault": "",  # eye style (a style id of the pack), pupil size, pupils on/off, installed skin id ("" = none)
    "locName": "", "locLat": 0.0, "locLon": 0.0,  # weather place picked on the dashboard; "" = the one in phone/www/config.js
    "apps": {},  # app name -> APP_RULES choice; apps not listed follow the switches above
    # dictation: engine, one language for all engines (stt.LANGS), cloud provider/model/URL, laptop whisper model
    "dictEngine": "phone", "dictLang": "hinglish", "dictProvider": "groq", "dictCloudModel": "", "dictCloudUrl": "",
    "dictAzureRegion": "", "dictModelLaptop": "auto",
    # the link to the phone (PhoneLink): paused, sweep the Wi-Fi for it, only on the networks listed ("wired" = a cable)
    "linkPaused": False, "linkAutoFind": True, "linkHomeOnly": False, "linkNetworks": [],
    "linkKeepAlive": 10, "linkRetry": 5, "sshPort": 8022,  # ssh keep-alive / retry seconds, sshd's port in Termux
}
RANGES = {"stretchMin": (10, 180), "brightnessDay": (5, 255), "brightnessNight": (0, 100), "drowsyMin": (5, 240),
          "torchSeconds": (1, 60), "soundSeconds": (1, 60), "soundVolume": (5, 100), "remindEvery": (10, 300),
          "remindMinutes": (1, 30), "pomoFocus": (1, 180), "pomoShort": (1, 60), "pomoLong": (1, 90),
          "pomoLongEvery": (2, 8), "pomoGoal": (1, 24), "typingAfter": (3, 120), "chipGlow": (0, 200), "eyeGap": (-14, 24), "phonesGap": (-16, 24),
          "linkKeepAlive": (5, 60), "linkRetry": (5, 60), "sshPort": (1024, 65535)}
CHOICES = {"soundStyle": ("chime", "beep", "alarm", "ping"),  # the sounds in phone/alert.py
           "accent": ("cyan", "terracotta", "sage", "violet", "rose", "amber", "sky", "custom"),  # accent names chip.js knows
           "idleRate": ("rare", "normal", "often"),
           "pupilSize": ("S", "M", "L"),
           "dictEngine": ("phone", "laptop", "cloud"), "dictLang": stt.LANGS, "dictProvider": tuple(stt.PROVIDERS)}
# the idle clips in pack.json personality (idle + idleAway); idleOff lists the ones switched off
IDLE_CLIPS = ("curious", "happyBlip", "suspicious", "look", "wink", "whistle", "sneeze", "peek", "spin", "wiggle",
              "smirkBlip", "yawn", "bored", "nod")
APP_RULES = ("both", "torch", "sound", "off")
# settings only the dashboard may change (the phone's page and local programs can't pause or redirect the link)
LINK_KEYS = ("linkPaused", "linkAutoFind", "linkHomeOnly", "linkNetworks", "linkKeepAlive", "linkRetry", "sshPort")


class Settings:
    """Saved in SETTINGS_FILE. `rev` goes up on every change so the phone knows when to fetch them;
    rev 0 means nothing was ever saved, and the phone then hands over the toggles it had in its drawer."""

    def __init__(self):
        self.lock = threading.Lock()
        try:
            with open(SETTINGS_FILE) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.rev = saved.get("rev", 0)
        values = dict(saved.get("values", {}))
        if "dictateOnLaptop" in values:  # replaced by dictEngine
            old = values.pop("dictateOnLaptop")
            values.setdefault("dictEngine", "laptop" if old is True else "phone")
        self.values = {k: v for k, v in values.items() if self.clean(k, v) == v}

    @staticmethod
    def clean(key, value):
        """The value to store for this setting, or None if it doesn't fit."""
        default = DEFAULTS.get(key)
        if key == "dictModelLaptop":  # "auto" (small, base in fast mode) or a ggml model present in the stt folder
            return value if value == "auto" or (isinstance(value, str) and value in stt.laptop_models()) else None
        if key == "dictCloudModel":  # "" = the provider's default
            return value if isinstance(value, str) and re.fullmatch(r"[\w.:/@+-]{0,100}", value) else None
        if key == "dictCloudUrl":  # "" or https only (for the custom provider)
            return value.strip() if value == "" or (isinstance(value, str) and stt.custom_endpoint(value)) else None
        if key == "dictAzureRegion":
            return value if isinstance(value, str) and re.fullmatch(r"[a-z0-9]{0,30}", value) else None
        if key == "locName":
            return " ".join(value.split())[:80] if isinstance(value, str) else None
        if key in ("locLat", "locLon"):
            lim = 90 if key == "locLat" else 180
            ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and abs(value) <= lim
            return round(float(value), 4) if ok else None
        if isinstance(default, bool):
            return value if isinstance(value, bool) else None
        if isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            lo, hi = RANGES[key]
            return max(lo, min(hi, round(value)))
        if key in CHOICES:
            return value if value in CHOICES[key] else None
        if key == "linkNetworks":  # home network names (SSIDs), up to 10
            if not isinstance(value, list):
                return None
            names = [n for n in value if isinstance(n, str) and 0 < len(n) <= 32]
            return list(dict.fromkeys(names))[:10]
        if isinstance(default, list):  # idle clips switched off
            if not isinstance(value, list):
                return None
            return [c for c in IDLE_CLIPS if c in value]
        if key == "accentColor":
            return value.lower() if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else None
        if isinstance(default, dict):  # per-app choices
            if not isinstance(value, dict):
                return None
            return {k[:60]: v for k, v in list(value.items())[:300] if isinstance(k, str) and v in APP_RULES}
        if key == "eyeStyle":  # a style id of the pack
            return value if isinstance(value, str) and value in pack_eyes()[1] else None
        if key == "skin":  # "" or the id of an installed skin
            if value == "" or (isinstance(value, str) and SKIN_ID.fullmatch(value) and os.path.isfile(skin_path(value))):
                return value
            return None
        if key == "phonesDefault":  # "" (Chip's own) or an installed skin that has headphones
            if value == "" or (isinstance(value, str) and SKIN_ID.fullmatch(value) and skins.headphones(value) is not None):
                return value
            return None
        if isinstance(default, str):  # a time of day, HH:MM
            return value if isinstance(value, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value) else None
        return None

    def get(self):
        with self.lock:
            values = dict(DEFAULTS, **self.values, rev=self.rev)
        values["dictateOnLaptop"] = values["dictEngine"] == "laptop"  # read-only, for phone pages from before dictEngine
        return values

    def update(self, changes, reset=False, keep=()):
        """keep: keys a reset leaves as they are."""
        if isinstance(changes.get("dictateOnLaptop"), bool) and "dictEngine" not in changes:  # older phone pages
            changes = dict(changes, dictEngine="laptop" if changes["dictateOnLaptop"] else "phone")
        with self.lock:
            values = {k: v for k, v in self.values.items() if k in keep} if reset else dict(self.values)
            for k, v in changes.items():
                v = self.clean(k, v)
                if v is not None:
                    values[k] = v
            if reset or values != self.values:
                self.values, self.rev = values, self.rev + 1
                os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
                with open(SETTINGS_FILE + ".tmp", "w") as f:
                    json.dump({"rev": self.rev, "values": values}, f, indent=1)
                os.replace(SETTINGS_FILE + ".tmp", SETTINGS_FILE)
        return self.get()


def geocode(query):
    """Up to 6 places matching the text: [{name, region, country, lat, lon}]; [] if there are none or the search is down."""
    query = " ".join(query.split())[:80]
    if len(query) < 2:
        return []
    url = "https://geocoding-api.open-meteo.com/v1/search?count=6&language=en&format=json&name=" + quote(query)
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            found = json.load(r).get("results") or []
    except (OSError, ValueError):
        return []
    return [{"name": f["name"], "region": f.get("admin1", ""), "country": f.get("country", ""),
             "lat": f["latitude"], "lon": f["longitude"]} for f in found if "name" in f and "latitude" in f and "longitude" in f]


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- attention (the phone's torch and alert sound)

# Desktop apps whose notifications count as AI ones, by app name, and AI sites when the notification comes from
# a browser (Chrome puts the site on the first line of the text).
AI_APPS = re.compile(r"claude|chatgpt|openai|codex|gemini|antigravity|copilot|cursor|windsurf|perplexity|deepseek|opencode", re.I)
AI_SITES = {"claude.ai": "Claude", "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT", "gemini.google.com": "Gemini",
            "aistudio.google.com": "AI Studio", "perplexity.ai": "Perplexity", "copilot.microsoft.com": "Copilot",
            "chat.deepseek.com": "DeepSeek", "grok.com": "Grok", "chat.mistral.ai": "Le Chat"}
BROWSERS = re.compile(r"chrom|brave|firefox|edge|opera|vivaldi", re.I)
KNOWN_AI = ("Claude Code", "Gemini CLI", "opencode", "Claude", "ChatGPT", "Antigravity")  # listed on the dashboard from the start
KINDS = ("ask", "done", "app", "notify", "test")  # agent asks / agent finished / AI app notification / any other app / test
APPS_FILE = os.path.expanduser("~/.config/deskbuddy/apps.json")


def who(app, body):
    """(name, is_ai) for a desktop notification: an app by its name, a browser by the site that sent it."""
    if BROWSERS.search(app):
        lines = body.split("\n", 1)[0] + " " + " ".join(re.findall(r'href="([^"]+)"', body))
        hosts = re.findall(r"(?:https?://)?((?:[\w-]+\.)+[a-z]{2,})", lines.lower())
        for host in hosts:
            for site, name in AI_SITES.items():
                if host == site or host.endswith("." + site):
                    return name, True
        return (hosts[0] if hosts else app), False
    name = app.rsplit(".", 1)[-1] if "." in app and " " not in app else app  # com.anthropic.Claude -> Claude
    pretty = {"chatgpt": "ChatGPT", "openai": "OpenAI", "deepseek": "DeepSeek"}
    return pretty.get(name.lower()) or (name.capitalize() if name.islower() else name), bool(AI_APPS.search(app))


def how_to_alert(source, kind):
    """{"torch": bool, "sound": bool} for an event, from the dashboard's settings, or None to let it pass.
    A choice made for the app itself wins over the general "how" switches."""
    s = settings.get()
    if kind == "test":
        return {"torch": True, "sound": True}
    rule = s["apps"].get(source, "default")
    if not s["torch"] or rule == "off":
        return None
    if kind == "notify":  # any other app: with "all other apps" on, or when picked on its own
        if rule == "default" and not s["notifyAllApps"]:
            return None
    elif not s[{"ask": "torchAsk", "done": "torchDone", "app": "torchApps"}[kind]]:
        return None
    if rule == "default":
        how = {"torch": s["alertTorch"], "sound": s["alertSound"]}
    else:
        how = {"torch": rule in ("both", "torch"), "sound": rule in ("both", "sound")}
    return how if how["torch"] or how["sound"] else None


class Apps:
    """Every app that has asked for attention or sent a desktop notification: just its name, whether it's an
    AI, how often and when last, so the dashboard can offer a choice per app. Saved in APPS_FILE."""

    def __init__(self):
        self.lock = threading.Lock()
        try:
            with open(APPS_FILE) as f:
                self.apps = json.load(f)
        except (OSError, ValueError):
            self.apps = {}
        for name in KNOWN_AI:
            self.apps.setdefault(name, {"ai": True, "count": 0, "last": None})

    def saw(self, name, ai):
        with self.lock:
            app = self.apps.setdefault(name, {"ai": ai, "count": 0, "last": None})
            app["ai"], app["count"], app["last"] = app["ai"] or ai, app["count"] + 1, time.time()
            if len(self.apps) > 300:  # forget the longest-quiet app that isn't an AI
                del self.apps[min((n for n, a in self.apps.items() if not a["ai"]), key=lambda n: self.apps[n]["last"] or 0)]
            os.makedirs(os.path.dirname(APPS_FILE), exist_ok=True)
            with open(APPS_FILE + ".tmp", "w") as f:
                json.dump(self.apps, f)
            os.replace(APPS_FILE + ".tmp", APPS_FILE)

    def listing(self):
        with self.lock:
            now = time.time()
            rows = [{"name": n, "ai": a["ai"], "count": a["count"], "age": round(now - a["last"]) if a["last"] else None}
                    for n, a in self.apps.items()]
        return sorted(rows, key=lambda r: (not r["ai"], r["age"] is None, r["age"] or 0, r["name"].lower()))


class Attention:
    """Moments when something wants you: AI agents (through their hooks), AI apps and, if chosen, any other app.
    The ones the settings let through go to the phone with /stats, marked torch and/or sound; the phone then
    checks the rest (night, whether you're at the laptop), blinks, plays and keeps reminding you."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = collections.deque(maxlen=20)
        self.last_note = (None, 0)

    def add(self, source, kind, text, project="", ai=True):
        source, kind = str(source)[:40], kind if kind in KINDS else "ask"
        if kind != "test":
            apps.saw(source, ai)
        how = how_to_alert(source, kind)
        if not how:
            return None
        event = {"id": int(time.time() * 1000), "at": time.time(), "source": source, "kind": kind,
                 "text": str(text)[:120], "project": str(project)[:40], **how}
        with self.lock:
            self.events.appendleft(event)
        return event["id"]

    def recent(self):
        with self.lock:
            return [dict(e, age=round(time.time() - e["at"], 1)) for e in self.events]

    def pending(self):
        """The last minute's alerts, newest first, for the phone (it polls every few seconds)."""
        return [e for e in self.recent() if e["age"] < 60][:5]

    def watch_notifications(self):
        """Desktop notifications from the session bus: libnotify-style ones and GNOME's GTK ones.
        Only who sent it is kept, never what it says."""
        cmd = ["busctl", "--user", "monitor", "--json=short",
               "--match", "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
               "--match", "type='method_call',interface='org.gtk.Notifications',member='AddNotification'"]
        while True:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                    data = msg["payload"]["data"]
                    if msg.get("member") == "Notify":
                        app, title, body, hints = data[0], data[3], data[4], data[6]
                        quiet = hints.get("urgency", {}).get("data") == 0 or hints.get("transient", {}).get("data")
                    else:
                        d = data[2]
                        app, title, body = data[0], d.get("title", {}).get("data", ""), d.get("body", {}).get("data", "")
                        quiet = d.get("priority", {}).get("data") == "low"
                except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                    continue
                key = (app, title, body)  # GNOME Shell passes each notification on once more; count it once
                if key == self.last_note[0] and time.time() - self.last_note[1] < 5:
                    continue
                self.last_note = (key, time.time())
                name, ai = who(str(app), str(body))
                if ai:
                    self.add(name, "app", "sent a notification")
                elif not quiet:  # low-priority and passing ones (media, progress) never count
                    self.add(name, "notify", "sent a notification", ai=False)
            proc.wait()
            time.sleep(5)


# ---------------------------------------------------------------- typing

class Typing:
    """Whether you're typing, for how long and roughly how fast, from counters anyone can read: a USB
    keyboard's transfer count (/sys/bus/usb/devices/*/urbnum goes up by one per key press and per release;
    devices that are also a mouse are left out) and the built-in keyboard's interrupt in /proc/interrupts.
    Nothing about which keys. A pause longer than GAP seconds ends a stretch of typing."""
    GAP = 3  # short, so Chip leaves its laptop right when you stop (a longer pause starts a new stretch)

    def __init__(self):
        self.lock = threading.Lock()
        self.since = self.last = 0.0
        self.recent = collections.deque()  # (time, key reports) over the last 10 s
        self.devices, self.found_at = [], 0

    @staticmethod
    def usb_keyboards():
        found = []
        for dev in glob.glob("/sys/bus/usb/devices/*"):
            protos = {read(i + "/bInterfaceProtocol") for i in glob.glob(dev + "/*:*")
                      if read(i + "/bInterfaceClass") == "03" and read(i + "/bInterfaceSubClass") == "01"}
            if "01" in protos and "02" not in protos:  # a keyboard boot interface and no mouse one
                found.append(dev + "/urbnum")
        return found

    def count(self):
        if time.time() - self.found_at > 30:  # keyboards come and go
            self.devices, self.found_at = self.usb_keyboards(), time.time()
        total = sum(int(read(p) or 0) for p in self.devices)
        with open("/proc/interrupts") as f:
            for line in f:
                if line.split(":", 1)[0].strip() == "1" and "i8042" in line:  # the laptop's own keyboard
                    total += sum(int(x) for x in line.split()[1:] if x.isdigit())
        return total

    def loop(self):
        prev = None
        while True:
            try:
                n = self.count()
                if prev is not None and n > prev:
                    now = time.time()
                    with self.lock:
                        if now - self.last > self.GAP:
                            self.since = now
                        self.last = now
                        self.recent.append((now, n - prev))
                prev = n  # (a replugged keyboard starts again from 0; that just skips one reading)
            except (OSError, ValueError) as e:
                print("typing:", e, flush=True)
            time.sleep(0.5)

    def snapshot(self):
        now = time.time()
        with self.lock:
            while self.recent and now - self.recent[0][0] > 10:
                self.recent.popleft()
            if now - self.last > self.GAP:
                return {"typing_for": 0, "wpm": 0, "idle": 0}
            window = max(2.0, min(10.0, now - self.since))
            reports = sum(c for t, c in self.recent if now - t <= window)
            return {"typing_for": round(now - self.since), "wpm": round(reports / 2 / window * 60 / 5),  # 5 keys a word
                    "idle": round(now - self.last, 1)}


# ---------------------------------------------------------------- stats

class Stats:
    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()
        self._cpu = None
        self._net = None

    def snapshot(self):
        with self.lock:
            return dict(self.data, ts=time.time())

    def update(self, **kw):
        with self.lock:
            self.data.update(kw)

    def cpu(self):
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:9]]
        idle, total = v[3] + v[4], sum(v)
        prev, self._cpu = self._cpu, (idle, total)
        if not prev or total == prev[1]:
            return None
        return round(100 * (1 - (idle - prev[0]) / (total - prev[1])))

    def cores(self):
        with open("/proc/stat") as f:
            rows = [l.split() for l in f if re.match(r"cpu\d", l)]
        now = [(int(r[4]) + int(r[5]), sum(int(x) for x in r[1:9])) for r in rows]
        prev, self._cores = getattr(self, "_cores", None), now
        if not prev or len(prev) != len(now):
            return []
        return [round(100 * (1 - (i - pi) / (t - pt))) if t != pt else 0 for (i, t), (pi, pt) in zip(now, prev)]

    @staticmethod
    def ram():
        m = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                m[k] = int(v.split()[0])
        return round(100 * (1 - m["MemAvailable"] / m["MemTotal"]))

    @staticmethod
    def temp():
        for hw in glob.glob("/sys/class/hwmon/hwmon*"):
            if read(hw + "/name") == "k10temp":
                t = read(hw + "/temp1_input")
                return round(int(t) / 1000) if t else None
        return None

    @staticmethod
    def battery():
        for bat in glob.glob("/sys/class/power_supply/BAT*"):
            cap = read(bat + "/capacity")
            if cap is not None:
                return int(cap), read(bat + "/status") in ("Charging", "Full", "Not charging")
        return None, None

    def net(self):
        rx = tx = 0
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                name, rest = line.split(":", 1)
                if name.strip() == "lo":
                    continue
                v = rest.split()
                rx, tx = rx + int(v[0]), tx + int(v[8])
        t = time.monotonic()
        prev, self._net = self._net, (t, rx, tx)
        if not prev:
            return 0, 0
        dt = t - prev[0]
        return round((rx - prev[1]) / dt), round((tx - prev[2]) / dt)

    @staticmethod
    def sensors():
        hw = {read(h + "/name"): h for h in glob.glob("/sys/class/hwmon/hwmon*")}
        def temp(name, n=1):
            v = read(f"{hw[name]}/temp{n}_input") if name in hw else None
            return round(int(v) / 1000) if v else None
        fan = read(hw["dell_smm"] + "/fan1_input") if "dell_smm" in hw else None
        gpu = next(iter(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")), None)
        m = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                m[k] = int(v.split()[0])
        st = os.statvfs("/")
        disk_total, disk_free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        wifi = None
        try:
            with open("/proc/net/wireless") as f:
                line = f.readlines()[2].split()
                wifi = {"iface": line[0].rstrip(":"), "dbm": int(float(line[3]))}
        except (OSError, IndexError, ValueError):
            pass
        bat = next(iter(glob.glob("/sys/class/power_supply/BAT*")), None)
        b = {}
        if bat:
            cur, volt = read(bat + "/current_now"), read(bat + "/voltage_now")
            now_, full, design = read(bat + "/charge_now"), read(bat + "/charge_full"), read(bat + "/charge_full_design")
            status = read(bat + "/status")
            watts = int(cur) * int(volt) / 1e12 if cur and volt else 0
            b = {"watts": round(watts, 1), "cycles": int(read(bat + "/cycle_count") or 0),
                 "health": round(100 * int(full) / int(design)) if full and design else None, "status": status}
            if cur and int(cur) > 0 and now_ and full:
                hours = (int(now_) if status == "Discharging" else int(full) - int(now_)) / int(cur)
                b["minutes_left"] = round(hours * 60)
        with open("/proc/loadavg") as f:
            load = [float(x) for x in f.read().split()[:3]]
        return {
            "temps": {"cpu": temp("k10temp"), "gpu": temp("amdgpu"), "ssd": temp("nvme"), "board": temp("dell_smm")},
            "fan": int(fan) if fan else None,
            "gpu": int(read(gpu)) if gpu else None,
            "ram_used_gb": round((m["MemTotal"] - m["MemAvailable"]) / 1048576, 1),
            "ram_total_gb": round(m["MemTotal"] / 1048576, 1),
            "swap": round(100 * (1 - m["SwapFree"] / m["SwapTotal"])) if m.get("SwapTotal") else 0,
            "disk": round(100 * (1 - disk_free / disk_total)), "disk_free_gb": round(disk_free / 1e9),
            "load": load, "wifi": wifi, "bat": b,
        }

    def fast_loop(self):
        while True:
            try:
                bat, charging = self.battery()
                rx, tx = self.net()
                with open("/proc/uptime") as f:
                    uptime = int(float(f.read().split()[0]))
                self.update(cpu=self.cpu(), cores=self.cores(), ram=self.ram(), temp=self.temp(), battery=bat,
                            charging=charging, net_rx=rx, net_tx=tx, uptime=uptime, **self.sensors())
            except Exception as e:  # keep serving even if one sensor misbehaves
                print("stats:", e, flush=True)
            time.sleep(2)

    def slow_loop(self):
        while True:
            try:
                vol = run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
                m = re.search(r"Volume:\s*([\d.]+)", vol)
                self.update(
                    media=media_status(),
                    volume=round(float(m.group(1)) * 100) if m else None,
                    muted="MUTED" in vol,
                    idle_ms=gnome_idle_ms(),
                    locked=gnome_locked(),
                )
            except Exception as e:
                print("stats:", e, flush=True)
            time.sleep(3)


def gdbus(dest, path, method, *args):
    return run("gdbus", "call", "--session", "--dest", dest, "--object-path", path, "--method", method, *args)


def gnome_idle_ms():
    m = re.search(r"uint64 (\d+)", gdbus("org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
                                         "org.gnome.Mutter.IdleMonitor.GetIdletime"))
    return int(m.group(1)) if m else None


def gnome_locked():
    return gdbus("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive") == "(true,)"


# ---------------------------------------------------------------- media (MPRIS over D-Bus)

def mpris_players():
    names = gdbus("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.ListNames")
    return re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", names)


def mpris_prop(name, prop):
    return gdbus(name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                 "org.mpris.MediaPlayer2.Player", prop)


def gvariant_str(text, key):
    m = re.search(r"'%s': <\[?(['\"])(.*?)(?<!\\)\1" % re.escape(key), text)
    return m.group(2).replace("\\'", "'") if m else ""


def media_status():
    paused = None
    for name in mpris_players():
        status = re.search(r"'(Playing|Paused|Stopped)'", mpris_prop(name, "PlaybackStatus"))
        status = status.group(1) if status else "Stopped"
        if status == "Stopped":
            continue
        meta = mpris_prop(name, "Metadata")
        item = {"name": name, "player": name.split(".")[3].capitalize(), "status": status,
                "title": gvariant_str(meta, "xesam:title"), "artist": gvariant_str(meta, "xesam:artist")}
        if status == "Playing":
            return item
        paused = paused or item
    return paused


def media_control(action):
    method = {"playpause": "PlayPause", "next": "Next", "previous": "Previous"}[action]
    current = media_status()
    names = [current["name"]] if current else mpris_players()[:1]
    for name in names:
        gdbus(name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player." + method)


def volume_control(action):
    if action == "mute":
        run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
    else:
        run("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+" if action == "up" else "5%-")


# ---------------------------------------------------------------- the link to the phone (Wi-Fi only)

class PhoneLink:
    """Keeps `ssh -R` open to Termux so the phone's 127.0.0.1:8765 reaches this bridge, over the home Wi-Fi.
    The phone's ssh host key is pinned under an alias, so its address can change: when the saved address stops
    answering, the Wi-Fi subnet is scanned for sshd's port and the host that presents the pinned key is the phone.
    Settings read live: linkPaused, linkAutoFind, linkHomeOnly + linkNetworks, linkKeepAlive, linkRetry, sshPort."""
    HOST_KEY_CHANGED = ("Host key verification failed", "REMOTE HOST IDENTIFICATION HAS CHANGED")

    def __init__(self):
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

    @staticmethod
    def cfg():
        return settings.get()

    def port(self):
        return self.cfg()["sshPort"]

    # ---- the laptop's network
    @staticmethod
    def interface():
        """(iface, address, its network) of the first global IPv4 address that isn't docker's or a VM bridge."""
        for line in run("ip", "-4", "-o", "addr", "show", "scope", "global").splitlines():
            m = re.search(r"inet ([\d.]+)/(\d+)", line)
            if m and "docker" not in line and "virbr" not in line:
                return line.split()[1], m.group(1), ipaddress.ip_network(f"{m.group(1)}/{m.group(2)}", strict=False)
        return None, None, None

    @staticmethod
    def wifi_ssid(iface):
        """(SSID, security e.g. "WPA2", "" = open) of the network iface is on (cached scan results only:
        --rescan no), or (None, None)."""
        for line in run("nmcli", "-t", "-f", "active,ssid,device,security", "dev", "wifi", "list", "--rescan", "no").splitlines():
            fields = [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]
            if len(fields) == 4 and fields[0] == "yes" and fields[2] == iface:
                return fields[1] or None, fields[3].strip("- ")
        return None, None

    def network(self):
        """{iface, ip, ssid, subnet}; ssid is "wired" on a non-wireless interface. Cached 5 s."""
        when, net = self._net
        if net and time.time() - when < 5:
            return net
        iface, ip, subnet = self.interface()
        ssid = security = None
        if iface:
            ssid, security = self.wifi_ssid(iface) if os.path.isdir(f"/sys/class/net/{iface}/wireless") else ("wired", None)
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
        try:
            with open(KNOWN_HOSTS) as f:
                return {tuple(l.split()[1:3]) for l in f if len(l.split()) >= 3 and not l.startswith("#")}
        except OSError:
            return set()

    def fingerprint(self):
        """(SHA256 fingerprint, key type) of the pinned key, ED25519 first; (None, None) if nothing is pinned."""
        try:
            mtime = os.stat(KNOWN_HOSTS).st_mtime
        except OSError:
            return None, None
        if self._fp[0] != mtime:
            keys = {}
            for line in run("ssh-keygen", "-lf", KNOWN_HOSTS).splitlines():
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
        lines = [l for l in run("ssh-keygen", "-F", f"[{ip}]:{port}").splitlines() if l and not l.startswith("#")]
        if not lines:
            lines = [l for l in run("ssh-keyscan", "-T", "4", "-p", str(port), ip, timeout=10).splitlines()
                     if l and not l.startswith("#")]
        keys = [f"{HOST_ALIAS} {' '.join(l.split()[1:3])}\n" for l in lines if len(l.split()) >= 3]
        if not keys:
            return False
        with self.lock:
            os.makedirs(os.path.dirname(KNOWN_HOSTS), exist_ok=True)
            with open(KNOWN_HOSTS, "w") as f:
                f.writelines(keys)
        print("pinned the phone's ssh host key", flush=True)
        return True

    # ---- finding the phone
    def offered(self, ip):
        return {tuple(l.split()[1:3]) for l in
                run("ssh-keyscan", "-T", "3", "-p", str(self.port()), ip, timeout=8).splitlines()
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
            with open(KNOWN_HOSTS + ".tmp", "w") as f:
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
                "rtt_ms": self.rtt(ip) if probe else None}

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
        cmd = ["ssh", "-N", "-p", str(port), "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
               "-o", "ConnectTimeout=8", "-o", f"ServerAliveInterval={keepalive}", "-o", "ServerAliveCountMax=3",
               "-o", f"UserKnownHostsFile={KNOWN_HOSTS}", "-o", "GlobalKnownHostsFile=/dev/null",
               "-o", f"HostKeyAlias={HOST_ALIAS}", "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no",
               "-o", "ForwardAgent=no", "-o", "ForwardX11=no", "-o", "PermitLocalCommand=no",
               "-R", f"{PORT}:127.0.0.1:{PORT}", ip]
        self.started = started = time.time()
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        stopped = False
        try:
            while proc.poll() is None:
                if self.restart or self.blocked() or (self.port(), self.cfg()["linkKeepAlive"]) != (port, keepalive):
                    stopped = True  # paused, off the home network, reconnect/forget/new address, or new settings
                    proc.terminate()
                    try:
                        proc.wait(5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
                if not self.up and time.time() - started > 4:  # ssh -N prints nothing; alive after 4 s means connected
                    self.up, self.since, self.fails, self.error, self.detail = True, time.time(), 0, None, ""
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

    def __init__(self):
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(8)  # requests handled at once by the pairing server
        self.server = None
        self.session = None

    # ---- what's handed out
    @staticmethod
    def public_key():
        """The public half of the key the tunnel's ssh uses (the first identity ssh -G lists that exists)."""
        for line in run("ssh", "-G", "chip-pairing.invalid").splitlines():
            if line.startswith("identityfile "):
                path = os.path.expanduser(line.split(None, 1)[1]) + ".pub"
                if os.path.isfile(path):
                    with open(path) as f:
                        return f.read().strip()
        return None

    @staticmethod
    def bundle(pubkey):
        """phone/ minus __pycache__ and setup.sh, plus authorized_keys: the same layout setup.sh's $SRC expects."""
        root = os.path.join(HERE, "..", "phone")

        def keep(info):
            if "__pycache__" in info.name.split("/") or info.name == "phone/setup.sh" or info.name.endswith(".pyc") \
                    or not (info.isfile() or info.isdir()):  # no links or devices
                return None
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            return info

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(root, arcname="phone", filter=keep)
            data = (pubkey + "\n").encode()
            info = tarfile.TarInfo("authorized_keys")
            info.size, info.mode, info.mtime = len(data), 0o600, int(time.time())
            tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    @staticmethod
    def script(ip, bundle_token, digest):
        """Downloads and checks the bundle, then runs phone/setup.sh on the extracted folder."""
        with open(os.path.join(HERE, "..", "phone", "setup.sh")) as f:
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
        net_info = phone_link.network()
        _, ip, net = phone_link.interface()
        if not ip:
            return {"ok": False, "error": "no network"}, 409
        if net_info["ssid"] != "wired" and not net_info.get("security"):
            return {"ok": False, "error": "open wifi", "message": "this Wi-Fi has no password: pair on your home network"}, 409
        homes = phone_link.cfg()["linkNetworks"]
        if homes and net_info["ssid"] not in homes:
            return {"ok": False, "error": "not home network", "message": "pairing only on the networks in linkNetworks"}, 409
        pubkey = self.public_key()
        if not pubkey:
            return {"ok": False, "error": "no ssh key", "message": "make one with ssh-keygen -t ed25519"}, 409
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

    @staticmethod
    def host_keys(addr):
        """[(kind, key, fingerprint base64)] that addr's sshd offers now."""
        keys = []
        for l in run("ssh-keyscan", "-T", "3", "-p", str(phone_link.port()), addr, timeout=8).splitlines():
            f = l.split()
            if len(f) >= 3 and not l.startswith("#"):
                fp = run("ssh-keygen", "-lf", "-", input=f"x {f[1]} {f[2]}\n").split()
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
        if run("systemctl", "is-active", "ufw") == "active":
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
        phone_link.replace_pin(ip, [keys[0][:2]])
        print(f"pairing: pinned the phone at {ip}", flush=True)
        try:
            r = subprocess.run([os.path.join(HERE, "..", "deploy.sh")], capture_output=True, text=True, timeout=180)
            deploy = {"ok": r.returncode == 0, "lines": (r.stdout + r.stderr).splitlines()[-20:]}
        except (OSError, subprocess.TimeoutExpired) as e:
            deploy = {"ok": False, "lines": [type(e).__name__]}
        return {"ok": True, "ip": ip, "fingerprint": "SHA256:" + keys[0][2], "deploy": deploy}, 200

    def cancel(self):
        with self.lock:
            self.session = None
        self.close_server()
        return {"ok": True}


# ---------------------------------------------------------------- audio visualizer (cava-style)

class Visualizer:
    """Captures what the laptop is playing (the default sink's monitor) and turns it into
    BARS levels 0-100, about 25 times a second. Runs only while a phone is watching."""
    RATE, N, BARS = 22050, 1024, 40

    def __init__(self):
        self.lock = threading.Condition()
        self.frame, self.seq, self.clients = None, 0, 0
        n = self.N
        self.window = [0.5 - 0.5 * __import__("math").cos(2 * 3.141592653589793 * i / (n - 1)) for i in range(n)]
        import cmath
        self.twiddle = [cmath.exp(-2j * cmath.pi * k / n) for k in range(n // 2)]
        self.rev = [int(f"{i:010b}"[::-1], 2) for i in range(n)]
        # log-spaced bands 50 Hz .. 10 kHz, at least one FFT bin each
        edges = [50 * (10000 / 50) ** (i / self.BARS) for i in range(self.BARS + 1)]
        hz_per_bin = self.RATE / n
        self.bands = []
        for lo, hi in zip(edges, edges[1:]):
            a = max(1, int(lo / hz_per_bin))
            self.bands.append((a, max(a + 1, int(hi / hz_per_bin))))
        self.peak = 1.0

    def fft(self, x):
        n, a = self.N, [complex(x[i]) for i in self.rev]
        size = 2
        while size <= n:
            half, step = size // 2, n // size
            for start in range(0, n, size):
                for k in range(half):
                    t = self.twiddle[k * step] * a[start + k + half]
                    u = a[start + k]
                    a[start + k], a[start + k + half] = u + t, u - t
            size *= 2
        return a

    def run(self):
        import array
        hop = self.RATE // 25
        while True:
            with self.lock:
                while self.clients == 0:
                    self.lock.wait()
            proc = subprocess.Popen(["parec", "--device=@DEFAULT_MONITOR@", "--format=s16le", f"--rate={self.RATE}",
                                     "--channels=1", "--latency-msec=40"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            buf = [0.0] * self.N
            try:
                while self.clients > 0:
                    data = proc.stdout.read(hop * 2)
                    if not data:
                        break
                    samples = array.array("h", data)
                    buf = (buf + [s / 32768 for s in samples])[-self.N:]
                    spec = self.fft([v * w for v, w in zip(buf, self.window)])
                    mags = [abs(c) for c in spec[:self.N // 2]]
                    levels = [max(mags[a:b]) * (1 + i / 12) for i, (a, b) in enumerate(self.bands)]  # tilt up the highs
                    top = max(levels)
                    # auto sensitivity like cava: follow loud parts quickly, quiet parts slowly
                    self.peak = max(top, self.peak * 0.995, 0.5)
                    frame = ",".join(str(min(100, int(100 * (lv / self.peak) ** 0.8))) for lv in levels)
                    with self.lock:
                        self.frame, self.seq = frame, self.seq + 1
                        self.lock.notify_all()
            finally:
                proc.kill()
                proc.wait()

    def stream(self, wfile):
        with self.lock:
            self.clients += 1
            self.lock.notify_all()
        seq = -1
        try:
            while True:
                with self.lock:
                    self.lock.wait_for(lambda: self.seq != seq, timeout=5)
                    frame, seq = self.frame, self.seq
                wfile.write(f"data: {frame or ''}\n\n".encode())
                wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self.lock:
                self.clients -= 1


# ---------------------------------------------------------------- gaze (Chip's eyes follow the mouse)

GAZE_BUS = ("org.deskbuddy.Gaze", "/org/deskbuddy/Gaze", "org.deskbuddy.Gaze")  # the chip-gaze Shell extension


def gaze_call(method):
    """The values the extension answers with, or None while it isn't loaded (it needs a new login after install)."""
    try:
        return json.loads(run("busctl", "--user", "--json=short", "call", *GAZE_BUS, method))["data"]
    except (ValueError, KeyError, TypeError):
        return None


def gaze_pointer():
    data = gaze_call("Pointer")
    if isinstance(data, list) and len(data) == 2 and all(type(v) is int for v in data):
        return tuple(data)
    return None


def gaze_monitors():
    data = gaze_call("Monitors")
    try:
        monitors = json.loads(data[0])
        return [{k: m[k] for k in ("x", "y", "w", "h", "primary")} for m in monitors]
    except (ValueError, KeyError, IndexError, TypeError):
        return []


class Gaze:
    """Works out where Chip should look: the direction from the phone to the mouse pointer, -1..1 on both axes.
    Runs only while a phone is connected to /gaze, gazeFollow is on and the screen isn't locked."""
    STEP = 0.34       # at most 3 updates a second: every one costs the phone a redraw
    IDLE_AFTER = 20   # seconds without the pointer moving
    NEAR = 0.15       # the pointer counts as near the phone within this share of the layout's diagonal

    def __init__(self):
        self.lock = threading.Condition()
        self.frame, self.seq, self.clients = "idle", 0, 0
        self.proc, self.proc_at, self.active = None, 0, False
        self.cursor, self.moved_at, self.sync_at = None, 0, 0
        self.monitors = []
        self.locked, self.locked_at = False, 0
        try:
            with open(GAZE_FILE) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.spots = {k: [float(v[0]), float(v[1])] for k, v in saved.items() if isinstance(saved, dict) and isinstance(k, str)
                      and isinstance(v, list) and len(v) == 2 and all(type(n) in (int, float) and math.isfinite(n) for n in v)}

    # -- layout and the phone's spot

    @staticmethod
    def layout_key(monitors):
        return "|".join(sorted(f"{m['w']}x{m['h']}+{m['x']}+{m['y']}" for m in monitors))

    @staticmethod
    def bounds(monitors):
        return (min(m["x"] for m in monitors), min(m["y"] for m in monitors),
                max(m["x"] + m["w"] for m in monitors), max(m["y"] + m["h"] for m in monitors))

    @staticmethod
    def primary(monitors):
        return next((m for m in monitors if m["primary"]), monitors[0])

    def phone_spot(self, monitors):
        """Saved for this monitor setup, else centered under the primary monitor, 10% of its height below its bottom edge."""
        if not monitors:
            return None
        spot = self.spots.get(self.layout_key(monitors))
        if spot:
            return spot
        m = self.primary(monitors)
        return [m["x"] + m["w"] / 2, m["y"] + m["h"] * 1.1]

    def layout(self):
        """For the dashboard: what the extension sees, fresh each time."""
        cursor, monitors = gaze_pointer(), gaze_monitors()
        if monitors:
            self.monitors = monitors
        spot = self.phone_spot(monitors)
        g = self.gaze_of(cursor, monitors, spot) if cursor and monitors else None
        return {"ok": cursor is not None or bool(monitors), "monitors": monitors,
                "phone": [round(v) for v in spot] if spot else None, "cursor": list(cursor) if cursor else None,
                "gaze": [g[0], g[1]] if g else None}

    def set_phone(self, x, y):
        """Remember the phone's spot for the current monitor setup, kept within one monitor height of the screens."""
        monitors = gaze_monitors()
        if not monitors:
            return None
        self.monitors = monitors
        x0, y0, x1, y1 = self.bounds(monitors)
        pad = self.primary(monitors)["h"]
        with self.lock:
            self.spots[self.layout_key(monitors)] = [max(x0 - pad, min(x1 + pad, x)), max(y0 - pad, min(y1 + pad, y))]
            os.makedirs(os.path.dirname(GAZE_FILE), exist_ok=True)
            with open(GAZE_FILE + ".tmp", "w") as f:
                json.dump(self.spots, f, indent=1)
            os.replace(GAZE_FILE + ".tmp", GAZE_FILE)
        return self.layout()

    # -- where to look

    @classmethod
    def gaze_of(cls, cursor, monitors, spot):
        """(gx, gy, near): per axis, the pointer's offset from the phone over the distance from the phone to the
        edge of the monitors' bounding box on that side, so each edge is full deflection; eased, in 0.1 steps."""
        px, py = spot
        x0, y0, x1, y1 = cls.bounds(monitors)
        def axis(d, e):
            g = max(-1, min(1, d / e)) if e > 0 else 0
            return round(math.copysign(abs(g) ** 0.6, g), 1) + 0.0
        dx, dy = cursor[0] - px, cursor[1] - py
        gx = axis(dx, x1 - px if dx > 0 else px - x0)
        gy = axis(dy, y1 - py if dy > 0 else py - y0)
        return gx, gy, math.hypot(dx, dy) <= cls.NEAR * math.hypot(x1 - x0, y1 - y0)

    def look(self):
        """"gx,gy,near(0|1)" for the phone, or "idle". The phone only applies it."""
        cursor, monitors = self.cursor, self.monitors
        if not cursor or not monitors or time.monotonic() - self.moved_at > self.IDLE_AFTER:
            return "idle"
        gx, gy, near = self.gaze_of(cursor, monitors, self.phone_spot(monitors))
        return f"{gx:.1f},{gy:.1f},{int(near)}"

    def publish(self, frame):
        with self.lock:
            if frame != self.frame:
                self.frame, self.seq = frame, self.seq + 1
                self.lock.notify_all()

    # -- the loop

    def screen_locked(self):
        if time.monotonic() - self.locked_at >= 5:
            self.locked, self.locked_at = gnome_locked(), time.monotonic()
        return self.locked

    def read_moves(self, proc):
        for line in proc.stdout:
            try:
                x, y = json.loads(line)["payload"]["data"]
            except (ValueError, KeyError, TypeError):
                continue
            if type(x) is int and type(y) is int:
                self.cursor, self.moved_at = (x, y), time.monotonic()

    def start_watching(self):
        cmd = ["busctl", "--user", "monitor", "--json=short", "--match",
               f"type='signal',interface='{GAZE_BUS[2]}',member='Moved'"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.proc_at = time.monotonic()
        threading.Thread(target=self.read_moves, args=(self.proc,), daemon=True).start()

    def stop_watching(self):
        if self.proc:
            self.proc.kill()
            self.proc.wait()
            self.proc = None

    def deactivate(self):
        self.stop_watching()
        self.active = False
        self.publish("idle")

    def tick(self):
        now = time.monotonic()
        if not self.active:
            self.active, self.cursor, self.moved_at, self.sync_at = True, None, now, 0
        if (self.proc is None or self.proc.poll() is not None) and now - self.proc_at >= 5:
            self.start_watching()
        if now - self.sync_at >= 10:  # the extension's timer stops 15 s after the last Start()
            self.sync_at = now
            gaze_call("Start")
            monitors = gaze_monitors()
            if monitors:
                self.monitors = monitors
            if self.cursor is None:
                self.cursor = gaze_pointer()
        self.publish(self.look())

    def run(self):
        while True:
            if self.clients == 0:
                self.deactivate()
            with self.lock:
                while self.clients == 0:
                    self.lock.wait()
            if settings.get()["gazeFollow"] and not self.screen_locked():
                self.tick()
                time.sleep(self.STEP)
            else:   # gazeFollow off or locked: no pointer polling, checked once a second
                if self.active:
                    self.deactivate()
                time.sleep(1)

    def stream(self, wfile):
        with self.lock:
            self.clients += 1
            self.lock.notify_all()
        seq = -1
        try:
            while True:
                with self.lock:
                    changed = self.lock.wait_for(lambda: self.seq != seq, timeout=15)
                    frame, seq = self.frame, self.seq
                wfile.write(f"data: {frame}\n\n".encode() if changed else b": ping\n\n")
                wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self.lock:
                self.clients -= 1


# ---------------------------------------------------------------- skins (custom looks for Chip)

class Skins:
    """Skin files (chip-skin/1) made with a chatbot and uploaded from the dashboard. laptop/skin.js does the checking
    (a subprocess with 10 s, so a hostile file can't hang the bridge); only JSON ever gets here, never pictures.
    A passing upload becomes the draft; installing the draft stores it as <id>.json."""

    def __init__(self):
        self.lock = threading.Lock()
        self.rev = 0  # bumped whenever an installed skin's file changes; /stats carries it, so a phone re-reads the skin it wears

    @staticmethod
    def run(*args, stdin=b""):
        done = subprocess.run(["node", SKIN_JS, *args], input=stdin, capture_output=True, timeout=10)
        if done.returncode:
            raise subprocess.SubprocessError(done.stderr.decode("utf-8", "replace")[:300])
        return done.stdout

    def prompt(self):
        return self.run("prompt").decode()

    @staticmethod
    def write(path, text):
        os.makedirs(SKINS_DIR, exist_ok=True)
        with open(path + ".tmp", "w") as f:
            f.write(text)
        os.replace(path + ".tmp", path)

    def check(self, body):
        """The report for an upload; a passing one is kept as the draft."""
        report = json.loads(self.run("check", "-", "--clean", stdin=body))
        clean = report.pop("clean", None)
        if report.get("ok") and clean:
            with self.lock:
                self.write(os.path.join(SKINS_DIR, "_draft.json"), clean)
        return report

    def draft(self):
        try:
            with open(os.path.join(SKINS_DIR, "_draft.json")) as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def clean_name(name):
        """The display name to store (1-40 printable characters, spaces squeezed), or None."""
        if not isinstance(name, str):
            return None
        name = " ".join("".join(ch for ch in name if ch.isprintable()).split())[:40]
        return name or None

    @staticmethod
    def named(text, name):
        """The skin JSON text with its display name replaced (name None = as it is)."""
        if name is None:
            return text
        skin = json.loads(text)
        skin["name"] = name
        return json.dumps(skin, separators=(",", ":"), ensure_ascii=False)

    def install(self, name=None):
        """(list, None) after installing the draft, else (None, (status, error body)). name: the display name the
        user picked on the dashboard (the phone greets with it), None keeps the file's own."""
        draft = self.draft()
        if draft is None:
            return None, (404, {"error": "no draft: check a skin first"})
        report = json.loads(self.run("check", "-", "--clean", stdin=draft.encode()))  # the pack may have changed since
        if not report.get("ok"):
            return None, (409, {"error": "the draft no longer passes the check", "report": {k: v for k, v in report.items() if k != "clean"}})
        skin_id = report["skin"]["id"]
        with self.lock:
            if not os.path.isfile(skin_path(skin_id)) and len(self.listing()) >= SKIN_LIMIT:
                return None, (409, {"error": f"at most {SKIN_LIMIT} skins: delete one first"})
            self.write(skin_path(skin_id), self.named(report["clean"], name))
            self.rev += 1
            try:
                os.remove(os.path.join(SKINS_DIR, "_draft.json"))
            except OSError:
                pass
        return self.listing(), None

    @staticmethod
    def listing():
        out = []
        try:
            names = sorted(os.listdir(SKINS_DIR))
        except OSError:
            return out
        for n in names:
            m = re.fullmatch(r"([a-z0-9-]{1,32})\.json", n)
            if not m:
                continue  # _draft.json and strays
            try:
                with open(os.path.join(SKINS_DIR, n)) as f:
                    skin = json.load(f)
                out.append({"id": m.group(1), "name": str(skin.get("name", ""))[:40], "author": str(skin.get("author", ""))[:40],
                            "bytes": os.path.getsize(os.path.join(SKINS_DIR, n)), "hasHeadphones": Skins.phones_of(skin) is not None})
            except (OSError, ValueError, AttributeError, TypeError):
                continue
        return out

    @staticmethod
    def phones_of(skin):
        """chip-phones/1, a skin's headphones on their own for another skin to borrow: the headphones sprite, every
        sprite its mirror chain reaches, and only the skin colours those sprites' keys name. None if it has none."""
        sprites = skin.get("sprites") if isinstance(skin, dict) else None
        name = skin.get("headphones") if isinstance(skin, dict) else None
        if not isinstance(sprites, dict) or not isinstance(name, str) or not isinstance(sprites.get(name), dict):
            return None
        out, n = {}, name
        while isinstance(sprites.get(n), dict) and n not in out and len(out) < 9:
            out[n] = sprites[n]
            n = sprites[n].get("mirror")
            if not isinstance(n, str):
                break
        colors = skin.get("colors") if isinstance(skin.get("colors"), dict) else {}
        used = {c for sp in out.values() if isinstance(sp.get("keys"), dict) for c in sp["keys"].values() if isinstance(c, str)}
        return {"format": "chip-phones/1", "from": skin.get("id"), "colors": {k: v for k, v in colors.items() if k in used},
                "sprites": out, "headphones": name}

    def headphones(self, skin_id):
        text = self.get(skin_id)
        try:
            part = self.phones_of(json.loads(text)) if text is not None else None
        except ValueError:
            return None
        if part:
            part["from"] = skin_id  # the file name is the id the phone asked for
        return part

    @staticmethod
    def get(skin_id):
        try:
            with open(skin_path(skin_id)) as f:
                return f.read()
        except OSError:
            return None

    # -- headphones made for an installed skin (chip-phones/1): prompt, check, draft, install
    @staticmethod
    def phones_draft_path(skin_id):
        return os.path.join(SKINS_DIR, f"_phones-{skin_id}.json")  # the underscore keeps listing() from taking it for a skin

    def phones_prompt(self, skin_id):
        """The chatbot prompt for this skin's headphones, or None if it isn't installed."""
        if not os.path.isfile(skin_path(skin_id)):
            return None
        return self.run("prompt-phones", skin_path(skin_id)).decode()

    def check_phones(self, skin_id, body, replace):
        """The report for a chip-phones/1 reply against the installed skin (None if it isn't installed); a passing one is
        kept as that skin's phones draft, with whether it replaces a pair."""
        if not os.path.isfile(skin_path(skin_id)):
            return None
        args = ["check-phones", skin_path(skin_id), "-", "--clean"] + (["--replace"] if replace else [])
        report = json.loads(self.run(*args, stdin=body))
        report.pop("clean", None)
        phones = report.pop("phones", None)
        if report.get("ok") and phones:
            with self.lock:
                self.write(self.phones_draft_path(skin_id), json.dumps({"replace": bool(replace), "phones": phones}, separators=(",", ":")))
        return report

    def phones_draft(self, skin_id):
        """{"replace", "phones"} of the kept draft, or None."""
        try:
            with open(self.phones_draft_path(skin_id)) as f:
                draft = json.load(f)
            return draft if isinstance(draft, dict) and isinstance(draft.get("phones"), dict) else None
        except (OSError, ValueError):
            return None

    def with_phones_draft(self, skin_id):
        """The installed skin with its phones draft put on (text), for the dashboard's preview; None without a draft."""
        draft = self.phones_draft(skin_id)
        if draft is None or not os.path.isfile(skin_path(skin_id)):
            return None
        args = ["check-phones", skin_path(skin_id), "-", "--clean"] + (["--replace"] if draft.get("replace") else [])
        report = json.loads(self.run(*args, stdin=json.dumps(draft["phones"]).encode()))
        return report.get("clean") if report.get("ok") else None

    def install_phones(self, skin_id):
        """(list, None) after merging the phones draft into the installed skin file, else (None, (status, error body)).
        Reads, re-checks and writes under the lock, with the same atomic write as every other skin change."""
        with self.lock:
            draft = self.phones_draft(skin_id)
            if not os.path.isfile(skin_path(skin_id)):
                return None, (404, {"error": "not found"})
            if draft is None:
                return None, (404, {"error": "no headphones draft: check a pair first"})
            args = ["check-phones", skin_path(skin_id), "-", "--clean"] + (["--replace"] if draft.get("replace") else [])
            report = json.loads(self.run(*args, stdin=json.dumps(draft["phones"]).encode()))  # the skin or the pack may have changed since
            if not report.get("ok") or not report.get("clean"):
                return None, (409, {"error": "the headphones no longer pass the check", "report": {k: v for k, v in report.items() if k not in ("clean", "phones")}})
            self.write(skin_path(skin_id), report["clean"])
            self.rev += 1
            try:
                os.remove(self.phones_draft_path(skin_id))
            except OSError:
                pass
        return self.listing(), None

    def rename(self, skin_id, name):
        """True if the installed skin exists and now has this display name."""
        with self.lock:
            text = self.get(skin_id)
            if text is None:
                return False
            self.write(skin_path(skin_id), self.named(text, name))
            self.rev += 1
        return True

    def delete(self, skin_id):
        """True if it existed. The skin setting goes back to none when it was the active one."""
        with self.lock:
            try:
                os.remove(skin_path(skin_id))
            except OSError:
                return False
            try:
                os.remove(self.phones_draft_path(skin_id))
            except OSError:
                pass
        if settings.get()["skin"] == skin_id:
            settings.update({"skin": ""})
        if settings.get()["phonesDefault"] == skin_id:
            settings.update({"phonesDefault": ""})
        return True


# ---------------------------------------------------------------- http

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".txt": "text/plain; charset=utf-8", ".woff2": "font/woff2",
         ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    def allowed(self):
        # Host guards against DNS rebinding (a website whose name points at 127.0.0.1), Origin against
        # other websites calling the bridge directly. Requests without an Origin come from local programs.
        origin = self.headers.get("Origin")
        if self.headers.get("Host") in HOSTS and (origin is None or origin in ORIGINS):
            return True
        self.send_json({"error": "forbidden"}, 403)
        return False

    def dashboard_only(self, reading=False):
        """For actions only the dashboard may take (after allowed()): Origin must be exactly DASHBOARD_ORIGIN.
        The phone's page (:8080) and requests without an Origin are refused. reading=True (GETs) also lets a
        missing Origin through, since browsers send none on a same-origin GET; :8080 is still refused."""
        origin = self.headers.get("Origin")
        if origin == DASHBOARD_ORIGIN or (reading and origin is None):
            return True
        self.send_json({"ok": False, "error": "forbidden", "message": "only the dashboard may do this"}, 403)
        return False

    def cors(self):
        if self.headers.get("Origin") in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.cors()
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, code=200):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.cors()
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self.send_json({"error": "not found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", TYPES[os.path.splitext(path)[1]])
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = min(int(self.headers.get("Content-Length") or 0), 16384)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def read_body(self, limit):
        """The raw request body, or None after answering 413 when it is longer than limit."""
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            self.close_connection = True
            self.send_json({"error": f"too large (at most {limit // 1024} KB)"}, 413)
            return None
        return self.rfile.read(length)

    def skin_failed(self, e):
        print("skins:", e, flush=True)
        self.send_json({"error": "the skin checker failed or timed out"}, 503)

    def do_OPTIONS(self):
        if not self.allowed():
            return
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if not self.allowed():
            return
        url = urlsplit(self.path)
        if url.path == "/stats":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if q.get("who") == "phone":  # the buddy reports back, for the dashboard's status line
                phone.update(seen=time.time(), rev=number(q.get("rev")), mood=q.get("mood", "")[:20],
                             screen=number(q.get("screen")), battery=number(q.get("bat")),
                             charging=q.get("chg") == "1", temp=number(q.get("temp")),
                             skinErr=q.get("skinErr", "")[:120],  # why the phone fell back to the base pack, "" = fine
                             wifi=({"ssid": q["ssid"][:32], "rssi": number(q.get("rssi")), "speed": number(q.get("speed")),
                                    "freq": number(q.get("freq")),
                                    "ip": q.get("pip", "") if re.fullmatch(r"[\d.]{7,15}", q.get("pip", "")) else None}
                                   if q.get("ssid") else None))  # the phone's own Wi-Fi: names and numbers only
            return self.send_json(dict(stats.snapshot(), **typing.snapshot(), settingsRev=settings.rev, skinsRev=skins.rev,
                                       attention=attention.pending()))
        if url.path == "/viz":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.cors()
            self.end_headers()
            return visualizer.stream(self.wfile)
        if url.path == "/gaze":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.cors()
            self.end_headers()
            return gaze.stream(self.wfile)
        if url.path == "/gaze/layout":  # for the dashboard, which polls it while open
            return self.send_json(gaze.layout())
        if url.path == "/settings":
            return self.send_json(settings.get())
        if url.path == "/stt/status":  # keys (keySet/last4 only), models and languages per engine
            return self.send_json(stt.status(settings.get()))
        if url.path == "/geocode":  # the dashboard's place search (Open-Meteo's free geocoder, the same service the phone's forecast uses)
            return self.send_json(geocode(parse_qs(url.query).get("q", [""])[0]))
        if url.path.startswith("/skins"):
            return self.get_skins(url)
        if url.path == "/attention":
            return self.send_json({"events": attention.recent(), "apps": apps.listing()})
        if url.path == "/phone":
            return self.send_json(dict(phone, age=round(time.time() - phone["seen"], 1)) if phone else {})
        if url.path == "/link/pair":  # carries the pairing token: never to the phone's page
            return self.dashboard_only(reading=True) and self.send_json(pairing.status())
        if url.path == "/link":  # for the dashboard and doctor.py
            return self.send_json(phone_link.snapshot())
        if url.path == "/api/status":  # the preview's stand-in for the phone server: what the phone last reported
            return self.send_json({k: phone.get(k) for k in ("battery", "charging", "temp")})
        if url.path in ("/", "/dashboard"):
            return self.send_file(DASHBOARD)
        if url.path.startswith("/preview/"):
            path = os.path.realpath(os.path.join(PREVIEW, unquote(url.path[9:]) or "index.html"))
            if path.startswith(PREVIEW + os.sep) and os.path.splitext(path)[1] in TYPES:
                return self.send_file(path)
        self.send_json({"error": "not found"}, 404)

    def get_skins(self, url):
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/skins/prompt":  # the master prompt for the chatbot, built from the pack
            try:
                return self.send_text(skins.prompt())
            except (OSError, subprocess.SubprocessError) as e:
                return self.skin_failed(e)
        if url.path == "/skins":
            return self.send_json(skins.listing())
        if url.path == "/skins/draft.json":
            text = skins.draft()
            return self.send_json({"error": "no draft"}, 404) if text is None else self.send_raw_json(text)
        m = re.fullmatch(r"/skins/([a-z0-9-]{1,32})/(phones-prompt|with-headphones\.json)", url.path)
        if m:  # making headphones for an installed skin: dashboard only (the phone's page never needs these)
            if not self.dashboard_only(reading=True):
                return
            try:
                if m.group(2) == "phones-prompt":
                    text = skins.phones_prompt(m.group(1))
                    return self.send_text(text) if text is not None else self.send_json({"error": "not found"}, 404)
                text = skins.with_phones_draft(m.group(1))   # the preview: the skin with the checked pair on
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                return self.skin_failed(e)
            return self.send_raw_json(text) if text else self.send_json({"error": "no headphones draft"}, 404)
        m = re.fullmatch(r"/skins/([a-z0-9-]{1,32})/headphones\.json", url.path)
        if m:  # another skin's headphones, for Chip to borrow (chip-phones/1)
            part = skins.headphones(m.group(1))
            return self.send_json(part) if part else self.send_json({"error": "no headphones"}, 404)
        m = re.fullmatch(r"/skins/([a-z0-9-]{1,32})\.json", url.path)
        text = skins.get(m.group(1)) if m else None
        if text is None:
            return self.send_json({"error": "not found"}, 404)
        self.send_raw_json(text)

    def send_raw_json(self, text):
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.cors()
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def post_skins(self, path):
        if path == "/skins/check":  # the body is the skin JSON text; a passing one becomes the draft
            body = self.read_body(SKIN_MAX)
            if body is None:
                return
            try:
                return self.send_json(skins.check(body))
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                return self.skin_failed(e)
        if path == "/skins/install":  # installs the draft; an optional {"name"} sets the name Chip goes by
            body = self.read_json()
            name = Skins.clean_name((body or {}).get("name"))
            if body is None or ("name" in body and name is None):
                return self.send_json({"error": "expected {\"name\": 1-40 characters} or nothing"}, 400)
            try:
                listing, failed = skins.install(name)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
                return self.skin_failed(e)
            return self.send_json(listing) if failed is None else self.send_json(failed[1], failed[0])
        m = re.fullmatch(r"/skins/([a-z0-9-]{1,32})/headphones/(check|install)", path)
        if m:  # headphones made for an installed skin: dashboard only, like /link/*
            if not self.dashboard_only():
                return
            skin_id = m.group(1)
            try:
                if m.group(2) == "check":  # the body is the chip-phones/1 text; ?replace=1 when the skin has a pair
                    body = self.read_body(SKIN_MAX)
                    if body is None:
                        return
                    report = skins.check_phones(skin_id, body, parse_qs(urlsplit(self.path).query).get("replace") == ["1"])
                    return self.send_json(report) if report is not None else self.send_json({"error": "not found"}, 404)
                listing, failed = skins.install_phones(skin_id)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
                return self.skin_failed(e)
            return self.send_json(listing) if failed is None else self.send_json(failed[1], failed[0])
        m = re.fullmatch(r"/skins/([a-z0-9-]{1,32})/rename", path)
        if m:  # {"name"}: the display name of an installed skin
            name = Skins.clean_name((self.read_json() or {}).get("name"))
            if name is None:
                return self.send_json({"error": "expected {\"name\": 1-40 characters}"}, 400)
            try:
                if not skins.rename(m.group(1), name):
                    return self.send_json({"error": "not found"}, 404)
            except (OSError, ValueError) as e:
                return self.skin_failed(e)
            return self.send_json(skins.listing())
        m = re.fullmatch(r"/skins/([a-z0-9-]{1,32})/delete", path)
        if m:
            if not skins.delete(m.group(1)):
                return self.send_json({"error": "not found"}, 404)
            return self.send_json(skins.listing())
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.allowed():
            return
        if self.path.split("?")[0].startswith("/skins/"):
            return self.post_skins(self.path.split("?")[0])
        if self.path.split("?")[0].startswith("/link/"):
            if not self.dashboard_only():
                return
            return self.post_link(self.path.split("?")[0])
        if self.path.split("?")[0] in ("/settings", "/settings/reset"):
            changes = self.read_json()
            if changes is None:
                return self.send_json({"error": "expected a JSON object"}, 400)
            if self.headers.get("Origin") != DASHBOARD_ORIGIN:
                changes = {k: v for k, v in changes.items() if k not in LINK_KEYS}
            values = settings.update(changes, reset=self.path.startswith("/settings/reset"),
                                     keep=() if self.headers.get("Origin") == DASHBOARD_ORIGIN else LINK_KEYS)
            if self.path.startswith("/settings/reset") or any(k.startswith("link") or k == "sshPort" for k in changes):
                phone_link.wake.set()  # unpaused, new port, ...: act now, not after linkRetry
            return self.send_json(values)
        url = urlsplit(self.path)
        if url.path == "/attention":  # an AI agent needs you (attention.py, the opencode plugin, the dashboard's test)
            a = self.read_json()
            if a is None:
                return self.send_json({"error": "expected a JSON object"}, 400)
            event = attention.add(a.get("source") or "An AI agent", a.get("kind"), a.get("text") or "needs you",
                                  a.get("project") or "")
            return self.send_json({"ok": True, "id": event, "alert": event is not None})
        if url.path == "/gaze/phone":  # where the phone sits, set from the dashboard
            g = self.read_json()
            nums = [g.get(k) for k in ("x", "y")] if g is not None else []
            if len(nums) != 2 or not all(type(n) in (int, float) and math.isfinite(n) for n in nums):
                return self.send_json({"error": "expected numbers x and y"}, 400)
            layout = gaze.set_phone(*nums)
            return self.send_json(layout or {"error": "the chip-gaze extension is not running"}, 200 if layout else 503)
        if url.path == "/transcribe":  # a dictated clip from the phone (16 kHz WAV, at most 60 s)
            # ?engine=laptop|cloud&lang=<stt.LANGS>&fast=1, each defaulting to the settings. No fallback: on failure
            # the answer is {ok: false, error: <stt.ERRORS code>, message} and the clip goes nowhere else.
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 4_000_000:
                return self.send_json({"ok": False, "error": "too_large", "message": "Clip too large"}, 413)
            audio = self.rfile.read(length)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            cfg = settings.get()
            engine, lang = q.get("engine") or "laptop", q.get("lang") or cfg["dictLang"]
            if engine not in ("laptop", "cloud"):
                return self.send_json({"ok": False, "error": "bad_engine", "message": "engine must be laptop or cloud"}, 400)
            if gnome_locked():
                return self.send_json(stt.SttError("locked").json(), 423)  # nothing would be typed anyway
            try:
                return self.send_json(stt.transcribe(audio, engine, lang, cfg, fast=q.get("fast") == "1"))
            except (wave.Error, EOFError):
                return self.send_json({"ok": False, "error": "bad_audio", "message": "Not a 16-bit WAV clip"}, 400)
            except stt.SttError as e:
                print("transcribe:", engine, e.code, flush=True)  # the code only: never audio, text or keys
                return self.send_json(e.json(), e.status)
        if url.path == "/stt/key":  # {provider, key|null}: write-only, the answer is {provider, keySet, last4}
            body = self.read_json()
            if body is None or body.get("provider") not in stt.PROVIDERS or not (body.get("key") is None or isinstance(body.get("key"), str)):
                return self.send_json({"ok": False, "error": "bad_request", "message": "expected {provider, key|null}"}, 400)
            key = body["key"].strip() if isinstance(body.get("key"), str) else None
            try:
                state = stt.set_key(body["provider"], key or None)
            except ValueError as e:
                return self.send_json({"ok": False, "error": "bad_key", "message": str(e)}, 400)
            return self.send_json({"ok": True, "provider": body["provider"], **state})
        if url.path == "/stt/test":  # a generated 1 s clip through the chosen engine (or {engine, provider} to try another)
            body = self.read_json() or {}
            cfg = settings.get()
            engine = body.get("engine") or cfg["dictEngine"]
            if body.get("provider") in stt.PROVIDERS:
                cfg["dictProvider"] = body["provider"]
            if engine == "phone":
                return self.send_json({"ok": False, "error": "not_here", "engine": "phone",
                                       "message": "The phone engine runs on the phone; hold Chip's face to try it"}, 400)
            if engine not in ("laptop", "cloud"):
                return self.send_json({"ok": False, "error": "bad_engine", "message": "engine must be laptop or cloud"}, 400)
            try:
                r = stt.transcribe(stt.test_clip(), engine, cfg["dictLang"], cfg, fast=cfg["fastDictation"], check_audio=False)
            except stt.SttError as e:
                return self.send_json({**e.json(), "engine": engine}, e.status)
            return self.send_json({"ok": True, "engine": engine, "ms": r["ms"]})  # the hum's "text" is meaningless
        if self.path.split("?")[0] == "/type":  # dictated text from the phone
            length = min(int(self.headers.get("Content-Length") or 0), 8192)
            text = self.rfile.read(length).decode("utf-8", "replace")[:2000]
            if gnome_locked():
                return self.send_json({"ok": False, "error": "locked", "message": "The laptop is locked"}, 423)  # never type into the lock screen
            try:
                typed = typer.type_text(text)
            except typer.TypingError as e:
                return self.send_json({"ok": False, "error": e.code, "message": str(e)}, 409)
            except Exception as e:
                print("type:", type(e).__name__, flush=True)
                return self.send_json({"ok": False, "error": "typing_failed", "message": "Typing failed"}, 500)
            return self.send_json({"ok": True, "typed": typed})
        parts = self.path.split("?")[0].strip("/").split("/")
        if len(parts) == 2:
            kind, action = parts
            if kind == "media" and action in ("playpause", "next", "previous"):
                media_control(action)
                return self.send_json({"ok": True})
            if kind == "volume" and action in ("up", "down", "mute"):
                volume_control(action)
                return self.send_json({"ok": True})
        self.send_json({"error": "not found"}, 404)

    def post_link(self, path):
        """/link/reconnect, /link/find, /link/ip {ip}, /link/forget, /link/doctor (dashboard only)."""
        link = phone_link
        if path == "/link/pair/start":  # {replace: true} to pair a new phone while the old one is linked
            body = self.read_json() or {}
            if link.pinned() and link.up and body.get("replace") is not True:
                return self.send_json({"ok": False, "error": "phone linked",
                                       "message": "a phone is pinned and connected; send {replace: true} to pair another"}, 409)
            why = link.blocked()
            if why:
                return self.send_json({"ok": False, "error": why}, 409)
            answer, code = pairing.start()
            return self.send_json(answer, code)
        if path == "/link/pair/confirm":
            body = self.read_json() or {}
            answer, code = pairing.confirm(body.get("code") or body.get("fingerprint"))
            return self.send_json(answer, code)
        if path == "/link/pair/cancel":
            return self.send_json(pairing.cancel())
        if path == "/link/doctor":
            try:
                r = subprocess.run([sys.executable, "-I", DOCTOR], capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                return self.send_json({"ok": False, "lines": ["doctor.py took more than 60 s"]}, 504)
            return self.send_json({"ok": r.returncode == 0, "lines": r.stdout.splitlines()})
        if path == "/link/forget":
            link.forget()
            return self.send_json({"ok": True})
        if path not in ("/link/reconnect", "/link/find", "/link/ip"):
            return self.send_json({"error": "not found"}, 404)
        if path == "/link/ip":  # checked before blocked(), so a bad request is a 400 whatever the link's state
            body = self.read_json()
            raw = body.get("ip") if body else None
            iface, mine, net = link.interface()
            try:
                addr = ipaddress.IPv4Address(raw) if isinstance(raw, str) else None
            except ValueError:
                addr = None
            if not addr or not net or not addr.is_private or addr.is_loopback or addr.is_link_local or addr not in net \
                    or addr in (net.network_address, net.broadcast_address) or str(addr) == mine:
                return self.send_json({"ok": False, "error": "bad_ip",
                                       "message": f"expected a private IPv4 address in {net or 'the current subnet'}"}, 400)
        why = link.blocked()
        if why:
            return self.send_json({"ok": False, "error": why}, 409)
        if path == "/link/reconnect":
            link.reconnect()
            return self.send_json({"ok": True})
        if not link.pinned():
            return self.send_json({"ok": False, "error": "no key pinned"}, 409)
        if path == "/link/find":  # a sweep now, whatever the 20 s limit says
            ip = link.discover(force=True)
            return self.send_json({"ok": bool(ip), "ip": ip, **({} if ip else {"error": link.error or "not found"})},
                                  200 if ip else 404)
        offered = link.offered(str(addr))
        if not offered:
            return self.send_json({"ok": False, "error": "not found", "message": f"no sshd on {addr}:{link.port()}"}, 404)
        if not link.pinned() & offered:
            return self.send_json({"ok": False, "error": "key mismatch",
                                   "message": f"{addr} doesn't present the pinned key"}, 409)
        link.use(str(addr))
        return self.send_json({"ok": True, "ip": str(addr)})

    def log_message(self, *args):
        pass


stats = Stats()
phone_link = PhoneLink()
pairing = Pairing()
visualizer = Visualizer()
gaze = Gaze()
skins = Skins()  # before settings: loading them checks phonesDefault against the installed skins
settings = Settings()
phone = {}  # what the buddy said about itself on its last /stats poll
apps = Apps()
attention = Attention()
typing = Typing()

if __name__ == "__main__":
    for target in (stats.fast_loop, stats.slow_loop, phone_link.loop, visualizer.run, gaze.run,
                   attention.watch_notifications, typing.loop):
        threading.Thread(target=target, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
