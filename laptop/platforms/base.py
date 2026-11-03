"""What an OS backend provides, with "this OS can't do it (yet)" for everything. linux.py replaces all of it;
windows.py and macos.py start from here (S5/S6 fill them in). Only the standard library at import time (psutil only
inside interface(), when installed): this must import anywhere."""
import ipaddress
import re
import socket

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


def prepare_listener(sock):
    """Socket options for the bridge's listening socket, before bind (SO_REUSEADDR: restart without waiting)."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


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


# adapters that aren't the home network: VMs, containers, VPNs, tunnels, Apple's peer-to-peer links
_VIRTUAL = re.compile(r"vethernet|virtualbox|vbox|vmware|vmnet|hyper-v|docker|wsl|loopback|tailscale|zerotier|"
                      r"wireguard|^wg\d|^utun|^tun|^tap|^ppp|ipsec|vpn|bridge|^awdl|^llw|^anpi|^gif|^stf|npcap|"
                      r"teredo|isatap|hamachi|nordlynx|bluetooth", re.I)
_LIKELY = re.compile(r"^en\d|wi-?fi|wlan|wireless|ethernet", re.I)  # tried first: macOS en0/en1, Windows Wi-Fi/Ethernet


def interface():
    """(iface, address, ipaddress network) of the first private IPv4 address that isn't a VM's or VPN's, or
    (None, None, None). Uses psutil (Windows/macOS); linux.py reads `ip` instead."""
    try:
        import psutil
    except ImportError:
        return None, None, None
    up = {name for name, st in psutil.net_if_stats().items() if st.isup}
    names = sorted(psutil.net_if_addrs().items(), key=lambda kv: not _LIKELY.search(kv[0]))
    for name, addrs in names:
        if name not in up or _VIRTUAL.search(name):
            continue
        for a in addrs:
            if a.family != socket.AF_INET or not a.netmask:
                continue
            ip = ipaddress.ip_address(a.address)
            if ip.is_private and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified):
                return name, a.address, ipaddress.ip_network(f"{a.address}/{a.netmask}", strict=False)
    return None, None, None


def is_wireless(iface):
    return False


def wifi_ssid(iface):
    """(SSID, security e.g. "WPA2", "" = open) of the Wi-Fi iface is on, or (None, None)."""
    return None, None


def firewall_on():
    """True if a firewall will likely block the pairing download port."""
    return False
