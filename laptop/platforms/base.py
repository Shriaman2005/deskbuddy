"""What an OS backend provides, with "this OS can't do it (yet)" for everything. linux.py replaces all of it;
windows.py and macos.py start from here (S5/S6 fill them in). Only the standard library: this must import anywhere."""

NAME = "unknown"


def caps():
    """The OS-specific caps (see platforms/__init__.py), all false here."""
    return {k: False for k in ("stats", "gpu", "temps", "battery", "idle", "locked", "typing", "media", "nowPlaying",
                               "volume", "notifications", "visualizer", "typingRate", "gaze", "wifiName")}


class Sampler:
    """Laptop stats every 2 s. sample() -> the fast /stats keys (platforms/__init__.py lists them), None when unknown."""

    def sample(self):
        return {"cpu": None, "cores": [], "ram": None, "temp": None, "battery": None, "charging": None,
                "net_rx": 0, "net_tx": 0, "uptime": None,
                "temps": {"cpu": None, "gpu": None, "ssd": None, "board": None}, "fan": None, "gpu": None,
                "ram_used_gb": None, "ram_total_gb": None, "swap": None, "disk": None, "disk_free_gb": None,
                "load": None, "wifi": None, "bat": {}}


def volume():
    """(volume 0-100, muted) of the default output, None where unknown."""
    return None, None


def idle_ms():
    """Milliseconds since the last keyboard/mouse input, or None."""
    return None


def locked():
    """True while the screen is locked; None when it can't be told (then nothing is typed: type_text refuses)."""
    return None


class TypingError(Exception):
    """code: why typing failed ('unsupported' here; typer.py adds 'paste_unserved' and 'clipboard')."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def type_text(text):
    raise TypingError("unsupported", "Typing into the laptop isn't supported on this OS yet")


def media_status():
    """{name, player, status, title, artist} of what is playing (or paused), or None."""
    return None


def media_control(action):
    """action: playpause | next | previous."""


def volume_control(action):
    """action: up | down | mute."""


class KeyCounter:
    """A number that goes up with every key press (never which key), for the typing rate; None = can't count."""

    def count(self):
        return None


def watch_notifications(on_note):
    """Blocks, calling on_note(app, title, body, quiet) for every desktop notification. Returns if it can't watch."""


def audio_monitor(rate):
    """A Popen whose stdout is what the laptop plays (s16le mono at rate), or None."""
    return None


def gaze_call(method):
    """Calls the pointer helper (Start, Pointer, Monitors); None while it isn't there."""
    return None


def gaze_pointer():
    """(x, y) of the mouse pointer, or None."""
    return None


def gaze_monitors():
    """[{x, y, w, h, primary}] of the screens, or []."""
    return []


class GazeWatch:
    """Calls on_move(x, y) whenever the pointer moves, until stop()."""

    def __init__(self, on_move):
        pass

    def alive(self):
        return False

    def stop(self):
        pass


def interface():
    """(iface, address, ipaddress network) of the first global IPv4 address that isn't docker's or a VM's."""
    return None, None, None


def is_wireless(iface):
    return False


def wifi_ssid(iface):
    """(SSID, security e.g. "WPA2", "" = open) of the Wi-Fi iface is on, or (None, None)."""
    return None, None


def firewall_on():
    """True if a firewall will likely block the pairing download port."""
    return False
