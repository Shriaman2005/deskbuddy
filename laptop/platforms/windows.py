"""Windows backend: PC stats (psutil), the network for the phone link, idle time and the lock state (user32), and
typing into the focused window (SendInput). ctypes + psutil only. Imports cleanly on every OS (the ctypes structs are
laid out explicitly, so their sizes can be tested anywhere); the calls themselves only work on Windows."""
import ctypes
import os
import re
import socket
import sys
import time

from . import base, psstats
from .base import *  # noqa: F401,F403
from .base import TypingError, caps as _none, interface
from .proc import run
from textclean import typable, utf16_units  # noqa: F401  laptop/textclean.py (every entry point has laptop/ on sys.path)

IS_WIN = sys.platform == "win32"

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


# ---------------------------------------------------------------- stats (psutil, platforms/psstats.py)

class Sampler(psstats.Sampler):
    """No load average, GPU or temperatures on Windows; the disk is the system drive."""
    disk_root = os.environ.get("SystemDrive", "C:") + "\\"


# ---------------------------------------------------------------- idle time and the lock screen (user32)

_u32 = _k32 = None


def _libs():
    """(user32, kernel32) with argument types set, loaded on first use. Windows only."""
    global _u32, _k32
    if _u32 is None:
        from ctypes import c_int, c_uint, c_uint32, c_void_p, POINTER
        u, k = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        u.GetLastInputInfo.argtypes, u.GetLastInputInfo.restype = [POINTER(LASTINPUTINFO)], c_int
        u.OpenInputDesktop.argtypes, u.OpenInputDesktop.restype = [c_uint32, c_int, c_uint32], c_void_p
        u.SwitchDesktop.argtypes, u.SwitchDesktop.restype = [c_void_p], c_int
        u.CloseDesktop.argtypes, u.CloseDesktop.restype = [c_void_p], c_int
        u.SendInput.argtypes, u.SendInput.restype = [c_uint, POINTER(INPUT), c_int], c_uint
        k.GetTickCount.argtypes, k.GetTickCount.restype = [], c_uint32
        _u32, _k32 = u, k
    return _u32, _k32


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("dwTime", ctypes.c_uint32)]


def idle_ms():
    """Milliseconds since the last keyboard/mouse input (GetLastInputInfo), None if Windows won't say."""
    if not IS_WIN:
        return None
    u, k = _libs()
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not u.GetLastInputInfo(ctypes.byref(info)):
        return None
    return (k.GetTickCount() - info.dwTime) & 0xFFFFFFFF  # both are 32-bit tick counts that wrap


DESKTOP_SWITCHDESKTOP = 0x0100
ERROR_ACCESS_DENIED = 5


def locked():
    """True while the lock screen (or the sign-in screen, a UAC prompt) is in front: the input desktop is Winlogon's
    and can't be opened. None when Windows says something else (no interactive session): then nothing is typed."""
    if not IS_WIN:
        return None
    u, _ = _libs()
    desk = u.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not desk:
        return True if ctypes.get_last_error() == ERROR_ACCESS_DENIED else None
    try:
        return not u.SwitchDesktop(desk)
    finally:
        u.CloseDesktop(desk)


# ---------------------------------------------------------------- typing (SendInput)

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class _InputUnion(ctypes.Union):  # MOUSEINPUT is the largest member: without it INPUT would be 32 bytes, not 40
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _InputUnion)]


INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x0002, 0x0004
BATCH = 32          # characters per SendInput call (2 events each)
BATCH_PAUSE = 0.004  # s between calls, so a slow app keeps up


def input_size_ok():
    """sizeof(INPUT) must be 40 on 64-bit Windows (28 on 32-bit): SendInput refuses any other cbSize."""
    return ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def type_text(text):
    """Types text into the focused window and returns what was typed. Never sends Enter (newlines and tabs become
    spaces), refuses while locked. Each UTF-16 unit goes as a KEYEVENTF_UNICODE key down + up, so any language and
    emoji work without touching the clipboard."""
    if not IS_WIN:
        return base.type_text(text)
    text = typable(text)
    if not text:
        return ""
    text += " "  # so back-to-back dictations don't run together
    if locked() is not False:
        raise TypingError("locked", "The laptop is locked")
    u, _ = _libs()
    units = utf16_units(text)
    for i in range(0, len(units), BATCH):
        events = []
        for unit in units[i:i + BATCH]:
            for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                e = INPUT(type=INPUT_KEYBOARD)
                e.u.ki = KEYBDINPUT(0, unit, flags, 0, 0)
                events.append(e)
        arr = (INPUT * len(events))(*events)
        if u.SendInput(len(events), arr, ctypes.sizeof(INPUT)) != len(events):
            raise TypingError("blocked", "Windows didn't accept the typing: the focused window may be running as "
                                         "administrator (Windows lets a normal program type only into normal windows)")
        time.sleep(BATCH_PAUSE)
    return text


# ---------------------------------------------------------------- the port, caps

def prepare_listener(sock):
    """SO_EXCLUSIVEADDRUSE instead of SO_REUSEADDR: with SO_REUSEADDR another program could bind the same port on
    Windows and take Chip's connections."""
    if IS_WIN:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def caps():
    """What this Windows can do. wifiName: Windows shows the Wi-Fi name (or the laptop is wired, where "wired" is the
    network's name). On another OS (the selftest imports this everywhere) only wifiName can be true."""
    iface = interface()[0]
    out = dict(_none(), wifiName=bool(iface) and (not is_wireless(iface) or wifi_ssid(iface)[0] is not None))
    if IS_WIN:
        ps = psstats.psutil_or_none()
        is_locked = locked()
        out.update(stats=ps is not None, battery=bool(ps) and psstats.attempt(ps.sensors_battery) is not None,
                   idle=idle_ms() is not None, locked=is_locked is not None,
                   typing=input_size_ok() and is_locked is not None)
    return out


# ---------------------------------------------------------------- the bridge as a service (chip.py, /bridge/*)
# install.py's venv runs supervise.py (pythonw, no window), started at login by the HKCU Run value "Chip".

from . import paths as _paths  # noqa: E402

SERVICE = "supervise.py (started at login by HKCU Run \"Chip\")"
VENV_PY = _paths.data("venv", "Scripts", "python.exe")
VENV_PYW = _paths.data("venv", "Scripts", "pythonw.exe")
SUPERVISE = _paths.laptop("supervise.py")
RUN_COMMAND = f'"{VENV_PYW}" -I -X utf8 "{SUPERVISE}"'   # the same as install.py writes
NOT_INSTALLED = "Chip isn't installed here: run py -3 laptop\\install.py"


def start_command(action="start"):
    path = _paths.laptop("chip.py")
    return f'py -3 "{path}" {action}' if " " in path else f"py -3 {path} {action}"


def service_stop():
    """supervise.py --stop (the venv's Python has psutil): the supervisors first, then the bridges."""
    from .proc import TimeoutExpired, complete
    if not os.path.isfile(VENV_PY):
        return False, NOT_INSTALLED
    try:
        r = complete([VENV_PY, "-I", "-X", "utf8", SUPERVISE, "--stop"], timeout=60)
    except (OSError, TimeoutExpired) as e:
        return False, f"supervise.py --stop: {e}"
    return r.returncode == 0, (r.stdout or r.stderr).strip() or "stopped"


def service_start():
    from .proc import DEVNULL, popen
    if not os.path.isfile(VENV_PYW):
        return False, NOT_INSTALLED
    try:
        popen([VENV_PYW, "-I", "-X", "utf8", SUPERVISE], text=False, detached=True, cwd=_paths.REPO,
              stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)
    except OSError as e:
        return False, f"couldn't start supervise.py: {e}"
    return True, "started supervise.py (the bridge answers in a few seconds)"


def autostart_get():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return "supervise.py" in winreg.QueryValueEx(k, RUN_VALUE)[0]
    except OSError:
        return False if os.path.isfile(VENV_PYW) else None
    except ImportError:  # not Windows (the selftest imports this everywhere)
        return None


def autostart_set(on):
    try:
        import winreg
    except ImportError:
        return False, "not Windows"
    if on and not os.path.isfile(VENV_PYW):
        return False, NOT_INSTALLED
    try:
        if on:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, RUN_COMMAND)
            return True, "Chip starts at login (HKCU Run \"Chip\")"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_VALUE)
    except FileNotFoundError:
        pass  # it wasn't there
    except OSError as e:
        return False, f"HKCU Run: {e}"
    return True, "Chip won't start at login"


def service_restart():
    ok, msg = service_stop()
    return service_start() if ok else (ok, msg)
