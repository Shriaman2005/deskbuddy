"""Windows backend: the network for the phone link (S2); everything else is S5 (psutil). Imports cleanly on every OS."""
import re

from .base import *  # noqa: F401,F403
from .base import caps as _none, interface
from .proc import run

NAME = "windows"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # HKCU: install.py's start-at-login value (doctor checks it)
RUN_VALUE = "Chip"
WIRELESS = re.compile(r"wi-?fi|wireless|wlan|802\.11", re.I)
SECURED = re.compile(r"(WPA\d?|WEP|802\.1X|SAE|OWE)\b", re.I)  # an authentication method's name
OPEN = {"open", "offen", "ouvert", "ouverte", "abierto", "abierta", "aperto", "aperta", "aberto", "aberta", "otwarte",
        "otevřené", "nyitott", "açık", "открытая", "открытый", "開放", "オープン", "개방", "开放"}  # "Open" in netsh's languages


def _wlan():
    """[{name, ssid, security}] per Wi-Fi adapter from `netsh wlan show interfaces`. ssid is None when not connected
    or when Windows hides it (Windows 11 24H2+ wants location access for it). Field names are localized, values and
    "SSID" are not: name = the block's first value, security = Authentication's value (or, in other languages, the
    value naming a WPA/WEP/... method), "" for "Open", "unknown" otherwise."""
    out = []
    for block in re.split(r"\n\s*\n", run("netsh", "wlan", "show", "interfaces", timeout=6).replace("\r", "")):
        fields = [(k.strip(), v.strip()) for k, sep, v in (l.partition(":") for l in block.splitlines()) if sep]
        fields = [(k, v) for k, v in fields if k and v]
        if not fields or not any(k.upper() == "GUID" for k, _ in fields):
            continue
        ssid = next((v for k, v in fields if k == "SSID"), None)
        auth = next((v for k, v in fields if re.fullmatch(r"auth\w*", k, re.I)), None)  # English field name
        sec = auth or next((v for _, v in fields[2:] if v != ssid and SECURED.match(v)), "unknown")
        sec = "" if sec.lower() in OPEN else sec
        out.append({"name": fields[0][1], "ssid": ssid or None, "security": sec if ssid else None})
    return out


def is_wireless(iface):
    return bool(iface) and (bool(WIRELESS.search(iface)) or any(w["name"] == iface for w in _wlan()))


def wifi_ssid(iface):
    """(SSID, security) of the Wi-Fi iface is on, (None, None) when unknown or hidden."""
    for w in _wlan():
        if w["name"] == iface and w["ssid"]:
            return w["ssid"], w["security"]
    return None, None


def caps():
    """wifiName: Windows shows the Wi-Fi name (or the laptop is wired, where "wired" is the network's name)."""
    iface = interface()[0]
    return dict(_none(), wifiName=bool(iface) and (not is_wireless(iface) or wifi_ssid(iface)[0] is not None))
