"""Linux backend (GNOME on Wayland): the code that was in bridge.py, moved here unchanged. Reads /proc and /sys,
talks to GNOME, MPRIS and the chip-gaze extension over the session bus (gdbus, busctl), PipeWire for volume (wpctl)
and audio (parec), NetworkManager for the Wi-Fi name, and types with typer.py (Mutter's remote-desktop API)."""
import glob
import ipaddress
import json
import os
import re
import shutil
import threading
import time

from . import base
from .proc import DEVNULL, PIPE, popen, run

NAME = "linux"

try:  # typer.py needs PyGObject (python3-gi); without it (CI, a bare Python) typing is simply missing
    import typer
    TypingError = typer.TypingError
except (ImportError, ValueError):
    typer = None
    TypingError = base.TypingError


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def session_bus():
    """True if there is a D-Bus session bus to talk to (the systemd user bus is there even before you log in)."""
    addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not addr:
        return os.path.exists(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/nonexistent"), "bus"))
    m = re.match(r"unix:path=([^,;]+)", addr)
    return os.path.exists(m.group(1)) if m else True


def caps():
    bus = session_bus()
    gdbus_ok, busctl_ok = bus and bool(shutil.which("gdbus")), bus and bool(shutil.which("busctl"))
    return {
        "stats": os.path.exists("/proc/stat"),
        "gpu": bool(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")),
        "temps": bool(glob.glob("/sys/class/hwmon/hwmon*")),
        "battery": bool(glob.glob("/sys/class/power_supply/BAT*")),
        "idle": gdbus_ok, "locked": gdbus_ok, "media": gdbus_ok, "nowPlaying": gdbus_ok,
        "typing": bus and typer is not None,
        "volume": bool(shutil.which("wpctl")),
        "notifications": busctl_ok, "gaze": busctl_ok,
        "visualizer": bool(shutil.which("parec")),
        "typingRate": os.path.exists("/proc/interrupts"),
        "wifiName": bool(shutil.which("nmcli")),
    }


# ---------------------------------------------------------------- stats

class Sampler:
    def __init__(self):
        self._cpu = None
        self._net = None
        self._cores = None

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
        prev, self._cores = self._cores, now
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

    def sample(self):
        bat, charging = self.battery()
        rx, tx = self.net()
        with open("/proc/uptime") as f:
            uptime = int(float(f.read().split()[0]))
        return dict(cpu=self.cpu(), cores=self.cores(), ram=self.ram(), temp=self.temp(), battery=bat,
                    charging=charging, net_rx=rx, net_tx=tx, uptime=uptime, **self.sensors())


def volume():
    vol = run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    m = re.search(r"Volume:\s*([\d.]+)", vol)
    return (round(float(m.group(1)) * 100) if m else None), "MUTED" in vol


# ---------------------------------------------------------------- GNOME: idle, lock, typing

def gdbus(dest, path, method, *args):
    return run("gdbus", "call", "--session", "--dest", dest, "--object-path", path, "--method", method, *args)


def idle_ms():
    m = re.search(r"uint64 (\d+)", gdbus("org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
                                         "org.gnome.Mutter.IdleMonitor.GetIdletime"))
    return int(m.group(1)) if m else None


def locked():
    return gdbus("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive") == "(true,)"


def type_text(text):
    if typer is None:
        return base.type_text(text)
    return typer.type_text(text)


# ---------------------------------------------------------------- media (MPRIS over D-Bus) and volume

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


# ---------------------------------------------------------------- typing rate

class KeyCounter:
    """Key presses from counters anyone can read: a USB keyboard's transfer count (/sys/bus/usb/devices/*/urbnum goes
    up by one per key press and per release; devices that are also a mouse are left out) and the built-in keyboard's
    interrupt in /proc/interrupts. Nothing about which keys."""

    def __init__(self):
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


# ---------------------------------------------------------------- desktop notifications

def watch_notifications(on_note):
    """libnotify-style and GNOME's GTK notifications from the session bus. Only who sent it is used by the bridge."""
    cmd = ["busctl", "--user", "monitor", "--json=short",
           "--match", "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
           "--match", "type='method_call',interface='org.gtk.Notifications',member='AddNotification'"]
    while True:
        proc = popen(cmd, stdout=PIPE, stderr=DEVNULL)
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
            on_note(app, title, body, quiet)
        proc.wait()
        time.sleep(5)


# ---------------------------------------------------------------- audio for the visualizer

def audio_monitor(rate):
    return popen(["parec", "--device=@DEFAULT_MONITOR@", "--format=s16le", f"--rate={rate}",
                  "--channels=1", "--latency-msec=40"], text=False, stdout=PIPE, stderr=DEVNULL)


# ---------------------------------------------------------------- gaze (the chip-gaze GNOME Shell extension)

GAZE_BUS = ("org.deskbuddy.Gaze", "/org/deskbuddy/Gaze", "org.deskbuddy.Gaze")


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


class GazeWatch:
    """The extension's Moved signals, read by a busctl monitor on its own thread."""

    def __init__(self, on_move):
        cmd = ["busctl", "--user", "monitor", "--json=short", "--match",
               f"type='signal',interface='{GAZE_BUS[2]}',member='Moved'"]
        self.on_move = on_move
        self.proc = popen(cmd, stdout=PIPE, stderr=DEVNULL)
        threading.Thread(target=self.read_moves, args=(self.proc,), daemon=True).start()

    def read_moves(self, proc):
        for line in proc.stdout:
            try:
                x, y = json.loads(line)["payload"]["data"]
            except (ValueError, KeyError, TypeError):
                continue
            if type(x) is int and type(y) is int:
                self.on_move(x, y)

    def alive(self):
        return self.proc.poll() is None

    def stop(self):
        self.proc.kill()
        self.proc.wait()


# ---------------------------------------------------------------- the laptop's network

def interface():
    for line in run("ip", "-4", "-o", "addr", "show", "scope", "global").splitlines():
        m = re.search(r"inet ([\d.]+)/(\d+)", line)
        if m and "docker" not in line and "virbr" not in line:
            return line.split()[1], m.group(1), ipaddress.ip_network(f"{m.group(1)}/{m.group(2)}", strict=False)
    return None, None, None


def is_wireless(iface):
    return os.path.isdir(f"/sys/class/net/{iface}/wireless")


def wifi_ssid(iface):
    """Cached scan results only (--rescan no)."""
    for line in run("nmcli", "-t", "-f", "active,ssid,device,security", "dev", "wifi", "list", "--rescan", "no").splitlines():
        fields = [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]
        if len(fields) == 4 and fields[0] == "yes" and fields[2] == iface:
            return fields[1] or None, fields[3].strip("- ")
    return None, None


def firewall_on():
    return run("systemctl", "is-active", "ufw") == "active"
