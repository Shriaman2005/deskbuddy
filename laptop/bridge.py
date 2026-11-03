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
import ipaddress
import json
import math
import os
import re
import threading
import time
import urllib.request
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python -I skips the script's folder
import hooks  # noqa: E402
import link  # noqa: E402
import platforms  # noqa: E402
import stt  # noqa: E402
from platforms import paths  # noqa: E402
from platforms.proc import SubprocessError, TimeoutExpired  # noqa: E402

PORT = int(os.environ.get("CHIP_PORT") or 8765)  # CHIP_PORT / CHIP_PAIR_PORT only for selftest.py
SETTINGS_FILE = paths.config("settings.json")
GAZE_FILE = paths.config("gaze.json")  # where the phone sits, per monitor layout
DASHBOARD = os.path.join(HERE, "dashboard.html")
PREVIEW = os.path.realpath(os.path.join(HERE, "..", "phone", "www"))  # the buddy page itself, for the dashboard's preview
PACK_FILE = os.path.join(PREVIEW, "pack.json")
SKINS_DIR = paths.config("skins")  # <id>.json per installed skin, _draft.json for the passing upload
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
    "personalPhone": False,  # a phone that is also in use: no brightness control (the face runs as an installed web app)
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
APPS_FILE = paths.config("apps.json")


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
        """Desktop notifications, from the OS backend. Only who sent it is kept, never what it says."""
        platforms.watch_notifications(self.on_notification)

    def on_notification(self, app, title, body, quiet):
        key = (app, title, body)  # GNOME Shell passes each notification on once more; count it once
        if key == self.last_note[0] and time.time() - self.last_note[1] < 5:
            return
        self.last_note = (key, time.time())
        name, ai = who(str(app), str(body))
        if ai:
            self.add(name, "app", "sent a notification")
        elif not quiet:  # low-priority and passing ones (media, progress) never count
            self.add(name, "notify", "sent a notification", ai=False)


# ---------------------------------------------------------------- typing

class Typing:
    """Whether you're typing, for how long and roughly how fast, from the OS backend's key-press counter
    (platforms KeyCounter; on Linux USB keyboards' transfer counts and the built-in keyboard's interrupt).
    Nothing about which keys. A pause longer than GAP seconds ends a stretch of typing."""
    GAP = 3  # short, so Chip leaves its laptop right when you stop (a longer pause starts a new stretch)

    def __init__(self):
        self.lock = threading.Lock()
        self.since = self.last = 0.0
        self.recent = collections.deque()  # (time, key reports) over the last 10 s
        self.counter = platforms.KeyCounter()

    def loop(self):
        prev = None
        while True:
            try:
                n = self.counter.count()
                if n is None:  # this OS can't count key presses
                    time.sleep(5)
                    continue
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
    """The laptop's numbers for /stats, sampled by the OS backend (platforms/__init__.py lists the keys)."""

    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()
        self.sampler = platforms.Sampler()

    def snapshot(self):
        with self.lock:
            return dict(self.data, ts=time.time())

    def update(self, **kw):
        with self.lock:
            self.data.update(kw)

    def fast_loop(self):
        while True:
            try:
                self.update(**self.sampler.sample())
            except Exception as e:  # keep serving even if one sensor misbehaves
                print("stats:", e, flush=True)
            time.sleep(2)

    def slow_loop(self):
        while True:
            try:
                vol, muted = platforms.volume()
                self.update(media=platforms.media_status(), volume=vol, muted=muted,
                            idle_ms=platforms.idle_ms(), locked=platforms.locked())
            except Exception as e:
                print("stats:", e, flush=True)
            time.sleep(3)


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
            proc = platforms.audio_monitor(self.RATE)
            if proc is None:  # this OS can't capture what it plays
                time.sleep(5)
                continue
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
        cursor, monitors = platforms.gaze_pointer(), platforms.gaze_monitors()
        if monitors:
            self.monitors = monitors
        spot = self.phone_spot(monitors)
        g = self.gaze_of(cursor, monitors, spot) if cursor and monitors else None
        return {"ok": cursor is not None or bool(monitors), "monitors": monitors,
                "phone": [round(v) for v in spot] if spot else None, "cursor": list(cursor) if cursor else None,
                "gaze": [g[0], g[1]] if g else None}

    def set_phone(self, x, y):
        """Remember the phone's spot for the current monitor setup, kept within one monitor height of the screens."""
        monitors = platforms.gaze_monitors()
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
            self.locked, self.locked_at = platforms.locked(), time.monotonic()
        return self.locked

    def moved(self, x, y):
        self.cursor, self.moved_at = (x, y), time.monotonic()

    def start_watching(self):
        self.proc = platforms.GazeWatch(self.moved)
        self.proc_at = time.monotonic()

    def stop_watching(self):
        if self.proc:
            self.proc.stop()
            self.proc = None

    def deactivate(self):
        self.stop_watching()
        self.active = False
        self.publish("idle")

    def tick(self):
        now = time.monotonic()
        if not self.active:
            self.active, self.cursor, self.moved_at, self.sync_at = True, None, now, 0
        if (self.proc is None or not self.proc.alive()) and now - self.proc_at >= 5:
            self.start_watching()
        if now - self.sync_at >= 10:  # the extension's timer stops 15 s after the last Start()
            self.sync_at = now
            platforms.gaze_call("Start")
            monitors = platforms.gaze_monitors()
            if monitors:
                self.monitors = monitors
            if self.cursor is None:
                self.cursor = platforms.gaze_pointer()
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
        done = platforms.proc.complete(["node", SKIN_JS, *args], timeout=10, input=stdin, text=False)
        if done.returncode:
            raise SubprocessError(done.stderr.decode("utf-8", "replace")[:300])
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
                                       attention=attention.pending(), caps=platforms.caps()))
        if url.path == "/caps":  # what this laptop can do (platforms CAPS); the dashboard hides the rest
            return self.send_json(dict(platforms.caps(), os=platforms.NAME))
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
        if url.path == "/hooks":  # the AI agents card: which agents have Chip's hook (dashboard only)
            return self.dashboard_only(reading=True) and self.send_json(hooks.listing())
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
            except (OSError, SubprocessError) as e:
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
            except (OSError, ValueError, SubprocessError) as e:
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
            except (OSError, ValueError, SubprocessError) as e:
                return self.skin_failed(e)
        if path == "/skins/install":  # installs the draft; an optional {"name"} sets the name Chip goes by
            body = self.read_json()
            name = Skins.clean_name((body or {}).get("name"))
            if body is None or ("name" in body and name is None):
                return self.send_json({"error": "expected {\"name\": 1-40 characters} or nothing"}, 400)
            try:
                listing, failed = skins.install(name)
            except (OSError, ValueError, KeyError, SubprocessError) as e:
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
            except (OSError, ValueError, KeyError, SubprocessError) as e:
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
        if self.path.split("?")[0] in ("/hooks/install", "/hooks/remove", "/hooks/test"):
            if not self.dashboard_only():  # edits the agents' config files: never the phone's page or a script
                return
            body = self.read_json()
            if body is None:
                return self.send_json({"error": "expected a JSON object"}, 400)
            code, out = hooks.handle(self.path.split("?")[0].rsplit("/", 1)[1], body.get("agent"))
            return self.send_json(out, code)
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
            if platforms.locked() is not False:
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
            if platforms.locked() is not False:
                return self.send_json({"ok": False, "error": "locked", "message": "The laptop is locked"}, 423)  # never type into the lock screen
            try:
                typed = platforms.type_text(text)
            except platforms.TypingError as e:
                return self.send_json({"ok": False, "error": e.code, "message": str(e)}, 409)
            except Exception as e:
                print("type:", type(e).__name__, flush=True)
                return self.send_json({"ok": False, "error": "typing_failed", "message": "Typing failed"}, 500)
            return self.send_json({"ok": True, "typed": typed})
        parts = self.path.split("?")[0].strip("/").split("/")
        if len(parts) == 2:
            kind, action = parts
            if kind == "media" and action in ("playpause", "next", "previous"):
                platforms.media_control(action)
                return self.send_json({"ok": True})
            if kind == "volume" and action in ("up", "down", "mute"):
                platforms.volume_control(action)
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
                r = platforms.proc.complete([sys.executable, "-I", "-X", "utf8", DOCTOR], timeout=60)
            except TimeoutExpired:
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


class BridgeServer(link.QuickServer):
    allow_reuse_address = False  # platforms.prepare_listener sets the right option (Windows: exclusive bind)

    def server_bind(self):
        platforms.prepare_listener(self.socket)
        super().server_bind()


stats = Stats()
phone_link = link.PhoneLink(lambda: settings.get())  # the link to the phone and pairing live in link.py
pairing = link.Pairing(phone_link)
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
    BridgeServer(("127.0.0.1", PORT), Handler).serve_forever()
