"""macOS backend: the network for the phone link (S2); everything else is S6 (psutil). Imports cleanly on every OS."""
import re

from .base import *  # noqa: F401,F403
from .base import caps as _none, interface
from .proc import run

NAME = "macos"
LAUNCH_AGENT = "org.deskbuddy.bridge"  # ~/Library/LaunchAgents/<label>.plist, made by install.py (doctor checks it)


def _summary(iface):
    return run("ipconfig", "getsummary", iface, timeout=6) if iface else ""


def is_wireless(iface):
    if re.search(r"InterfaceType\s*:\s*WiFi", _summary(iface)):
        return True
    ports = run("networksetup", "-listallhardwareports", timeout=6)
    return bool(iface) and bool(re.search(r"Hardware Port: (Wi-Fi|AirPort)\s*\nDevice: " + re.escape(iface) + r"\s*$",
                                          ports, re.M))


def wifi_ssid(iface):
    """(SSID, security) from `ipconfig getsummary`; macOS 14+ shows <redacted> unless the app may use Location
    Services: then (None, None). security: "" for an open network, "unknown" when not listed."""
    out = _summary(iface)
    m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", out, re.M)
    if not m or m.group(1).lower() in ("<redacted>", "<private>"):
        return None, None
    sec = re.search(r"^\s*Security\s*:\s*(.+?)\s*$", out, re.M)
    sec = sec.group(1) if sec else "unknown"
    return m.group(1), "" if sec.lower() in ("none", "open") else sec


def caps():
    """wifiName: macOS shows the Wi-Fi name (or the laptop is wired, where "wired" is the network's name)."""
    iface = interface()[0]
    return dict(_none(), wifiName=bool(iface) and (not is_wireless(iface) or wifi_ssid(iface)[0] is not None))
