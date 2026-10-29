#!/data/data/com.termux/files/usr/bin/python
"""Desk buddy phone server (runs in Termux).

Serves the buddy UI from ./www on 127.0.0.1:8080 and does the few things a WebView
can't: set screen brightness, speak, launch apps, read the battery, take dictation, and blink the torch
and play an alert sound (alert.py).
"""
import json
import os
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import alert
from dictation import Dictation

WWW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")
PORT = 8080

# Launcher activities for the buddy's app drawer, resolved on this phone.
APPS = {
    "brave": "com.brave.browser/com.google.android.apps.chrome.Main",
    "termux": "com.termux/.app.TermuxActivity",
    "files": "com.google.android.apps.nbu.files/.home.HomeActivity",
    "settings": "com.android.settings/.Settings",
    "launcher": "com.sec.android.app.launcher/com.android.launcher3.infra.activity.Launcher",
}

battery = {}
dictation = Dictation()


def spawn(cmd):
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def battery_loop():
    while True:
        try:
            out = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=20).stdout
            battery.update(json.loads(out))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        time.sleep(60)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WWW, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path == "/api/status":
            return self.send_json({
                "battery": battery.get("percentage"),
                "charging": battery.get("status") in ("CHARGING", "FULL"),
                "temp": battery.get("temperature"),
                "flashlight": alert.flashlight,
            })
        if urlsplit(self.path).path == "/api/dictate/status":
            return self.send_json(dictation.status())
        super().do_GET()

    def do_POST(self):
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/brightness":
            try:
                level = max(0, min(255, int(q.get("level", ""))))
            except ValueError:
                return self.send_json({"error": "level must be 0-255"}, 400)
            spawn(["termux-brightness", str(level)])
        elif url.path == "/api/say":
            text = q.get("text", "").strip()[:300]
            if text:
                spawn(["termux-tts-speak", text])
        elif url.path == "/api/alert":  # blink the torch and/or play a sound for this many seconds
            try:
                torch_s, sound_s = (max(0, min(120, int(q.get(k, "0")))) for k in ("torch", "sound"))
                volume = max(5, min(100, int(q.get("volume", "80"))))
            except ValueError:
                return self.send_json({"error": "torch, sound and volume must be numbers"}, 400)
            style = q.get("style", "chime")
            if style not in alert.STYLES:
                return self.send_json({"error": "unknown sound"}, 400)
            alert.start(torch_s, sound_s, style, volume)
        elif url.path == "/api/alert/stop":
            alert.stop()
        elif url.path == "/api/torch":  # the drawer's flashlight switch
            alert.set_flashlight(q.get("on") == "1")
        elif url.path == "/api/launch":
            component = APPS.get(q.get("app", ""))
            if not component:
                return self.send_json({"error": "unknown app"}, 404)
            spawn(["am", "start", "-n", component])
        elif url.path in ("/api/dictate/start", "/api/dictate/stop", "/api/dictate/cancel"):
            action = url.path.rsplit("/", 1)[1]
            try:
                kwargs = {"fast": q.get("fast") == "1", "laptop": q.get("on") == "laptop"} if action == "stop" else {}
                return self.send_json(getattr(dictation, action)(**kwargs))
            except (OSError, subprocess.SubprocessError) as e:
                dictation.cancel()
                return self.send_json({"error": str(e)}, 500)
        else:
            return self.send_json({"error": "not found"}, 404)
        self.send_json({"ok": True})


if __name__ == "__main__":
    threading.Thread(target=battery_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
