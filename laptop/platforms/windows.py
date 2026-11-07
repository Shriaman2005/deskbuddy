"""Windows backend: PC stats (psutil), the network for the phone link, idle time and the lock state (user32), and
typing into the focused window (SendInput). ctypes + psutil only. Imports cleanly on every OS (the ctypes structs are
laid out explicitly, so their sizes can be tested anywhere); the calls themselves only work on Windows."""
import ctypes
import ipaddress
import json
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


def _session_locked():
    """True when WTSSessionInfoEx says this session is locked (WTS_SESSIONSTATE_LOCK = 0). Windows 10 shows its lock
    screen while OpenInputDesktop still answers "Default", so locked() asks both. False when unknown."""
    import struct
    from ctypes import POINTER, byref, c_void_p, wintypes
    try:
        w = ctypes.WinDLL("wtsapi32", use_last_error=True)
        w.WTSQuerySessionInformationW.argtypes = [c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p),
                                                  POINTER(wintypes.DWORD)]
        p, n = c_void_p(), wintypes.DWORD()
        if not w.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 25, byref(p), byref(n)):  # CURRENT_SESSION, SessionInfoEx
            return False
        try:
            raw = ctypes.string_at(p, n.value)
        finally:
            w.WTSFreeMemory.argtypes = [c_void_p]
            w.WTSFreeMemory(p)
        # WTSINFOEXW: Level (4) + padding (4) + level 1: SessionId, SessionState, SessionFlags (4 each)
        return len(raw) >= 20 and struct.unpack_from("<I", raw, 0)[0] == 1 and struct.unpack_from("<i", raw, 16)[0] == 0
    except (OSError, AttributeError):
        return False


def locked():
    """True while the lock screen (or the sign-in screen, a UAC prompt) is in front: the input desktop is Winlogon's
    and can't be opened. None when Windows says something else (no interactive session): then nothing is typed."""
    if not IS_WIN:
        return None
    if _session_locked():  # Windows 10's lock screen leaves the input desktop reachable, so ask the session too
        return True
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


def foreground_is_admin():
    """True when the window in front runs elevated (as administrator) and Chip doesn't: Windows (UIPI) then drops
    our key events silently, SendInput still reports success. An elevated process can't even be opened by a normal
    one for its token, so "access denied" counts as elevated too. False when unsure."""
    if not IS_WIN:
        return False
    from ctypes import POINTER, byref, c_int, c_uint32, c_void_p, wintypes
    u, k = _libs()
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    u.GetForegroundWindow.restype = c_void_p
    u.GetWindowThreadProcessId.argtypes = [c_void_p, POINTER(c_uint32)]
    k.OpenProcess.argtypes, k.OpenProcess.restype = [c_uint32, c_int, c_uint32], c_void_p
    k.GetCurrentProcess.restype = c_void_p
    k.CloseHandle.argtypes = [c_void_p]
    a.OpenProcessToken.argtypes = [c_void_p, c_uint32, POINTER(c_void_p)]
    a.GetTokenInformation.argtypes = [c_void_p, c_int, c_void_p, c_uint32, POINTER(c_uint32)]

    def elevated(proc):  # True / False / None (token not readable: access denied)
        tok = c_void_p()
        if not a.OpenProcessToken(proc, 0x0008, byref(tok)):  # TOKEN_QUERY
            return True if ctypes.get_last_error() == ERROR_ACCESS_DENIED else None
        try:
            val, n = c_uint32(0), c_uint32(0)
            if not a.GetTokenInformation(tok, 20, byref(val), 4, byref(n)):  # TokenElevation
                return None
            return bool(val.value)
        finally:
            k.CloseHandle(tok)

    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return False
    pid = c_uint32(0)
    u.GetWindowThreadProcessId(hwnd, byref(pid))
    if not pid.value:
        return False
    proc = k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not proc:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        theirs = elevated(proc)
    finally:
        k.CloseHandle(proc)
    return bool(theirs) and not elevated(k.GetCurrentProcess())


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
    if foreground_is_admin():
        raise TypingError("blocked", "The window in front is running as administrator, and Windows lets a normal "
                                     "program type only into normal windows. Click a normal window, or run it normally")
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


# ---------------------------------------------------------------- Windows Firewall vs the pairing download port
# Read through the HNetCfg.FwPolicy2 COM object: works on a standard account (WMI/CIM doesn't) and in any language.
# Only inbound, enabled TCP/any rules of the current profile(s), minus service and Store-app rules; a rule counts
# only if it covers this program, the port, the pairing address (Tailscale's allow-all is for its own address) and
# the whole LAN as senders.

_FW_PS = r"""$p = New-Object -ComObject HNetCfg.FwPolicy2
$cur = $p.CurrentProfileTypes; $on = $false; $blk = $false
foreach ($b in 1,2,4) { if (($cur -band $b) -and $p.FirewallEnabled($b)) { $on = $true; if ($p.DefaultInboundAction($b) -eq 0) { $blk = $true } } }
$r = @($p.Rules | Where-Object { $_.Direction -eq 1 -and $_.Enabled -and ($_.Profiles -band $cur) -and ($_.Protocol -eq 6 -or $_.Protocol -eq 256) -and -not $_.ServiceName -and -not $_.LocalAppPackageId } | ForEach-Object { @{n=[string]$_.Name; a=[string]$_.ApplicationName; p=[string]$_.LocalPorts; k=[int]$_.Action; l=[string]$_.LocalAddresses; r=[string]$_.RemoteAddresses; t=[string]$_.InterfaceTypes; i=[bool]$_.Interfaces} })
@{cur=$cur; on=$on; blk=$blk; rules=$r} | ConvertTo-Json -Compress -Depth 3"""
_PROFILES = ((2, "private"), (4, "public"), (1, "domain"))  # NET_FW_PROFILE2_* bits, the name netsh's profile= takes
_fw_cache = {}  # (ip, port) -> (time, answer): the wizard polls its status every couple of seconds


def _ports_cover(spec, port):
    """Does a rule's LocalPorts ("*", "", "80,443", "8000-9000", "RPC", ...) include port?"""
    for part in spec.split(","):
        part = part.strip()
        lo, _, hi = part.partition("-")
        if part in ("", "*") or (lo.isdigit() and int(lo) <= port <= int(hi if hi.isdigit() else lo)):
            return True
    return False


def _addrs_cover(spec, want):
    """Does a rule's address list ("*", "LocalSubnet", "10.0.0.0/255.0.0.0", "10.0.0.1-10.0.0.9", ...) include all
    of want (an ip_network)?"""
    for part in (spec or "*").split(","):
        part = part.strip()
        if part in ("", "*") or part.lower() == "localsubnet":
            return True
        try:
            if "-" in part:  # a range: it must hold every host address of want (not its network/broadcast)
                lo, hi = (ipaddress.ip_address(x) for x in part.split("-", 1))
                first, last = (want[1], want[-2]) if want.num_addresses > 2 else (want[0], want[-1])
                if lo.version == want.version and lo <= first and last <= hi:
                    return True
            elif want.subnet_of(ipaddress.ip_network(part, strict=False)):
                return True
        except (TypeError, ValueError):  # another IP version, or a keyword such as DHCP or Intranet
            pass
    return False


def _programs():
    """The executables Windows Firewall sees listening for this bridge: a venv's pythonw.exe is a launcher that starts
    the base interpreter's pythonw.exe, so the rule must name that one."""
    exe = os.path.abspath(sys.executable)
    base_dir = os.path.dirname(os.path.abspath(getattr(sys, "_base_executable", "") or exe))
    real = os.path.join(base_dir, os.path.basename(exe))
    return real, {os.path.normcase(exe), os.path.normcase(real)}


def firewall_verdict(policy, ip, net, port, programs):
    """None if a phone on net can reach ip:port, else ("allow", None) (nothing allows it) or ("blocked", rule name)
    (a rule blocks this Python, e.g. from Cancel on Windows' "allow this app" alert: block wins over allow)."""
    if not policy.get("on"):
        return None
    here, net = ipaddress.ip_network(ip), ipaddress.ip_network(net, strict=False)
    allowed = False
    for r in policy.get("rules") or []:
        app = os.path.normcase(os.path.expandvars(r.get("a") or ""))
        kinds = r.get("t") or "All"
        if (not app or app in programs) and _ports_cover(r.get("p") or "", port) and not r.get("i") \
                and (kinds == "All" or "Lan" in kinds or "Wireless" in kinds) \
                and _addrs_cover(r.get("l"), here) and _addrs_cover(r.get("r"), net):
            if r.get("k") == 0:
                return "blocked", r.get("n") or ""
            allowed = True
    return None if allowed or not policy.get("blk") else ("allow", None)


def firewall_rule(ip, net, port):
    """(why, allow command, undo command) if Windows Firewall will drop the phone's connection to port, else None.
    The commands need an administrator's Command Prompt (a standard account can't change the firewall)."""
    if not IS_WIN:
        return None
    hit = _fw_cache.get((ip, port))
    if hit and time.time() - hit[0] < 10:
        return hit[1]
    try:
        policy = json.loads(run("powershell", "-NoProfile", "-NonInteractive", "-Command", _FW_PS, timeout=10) or "{}")
    except ValueError:
        policy = {}
    real, programs = _programs()
    verdict = firewall_verdict(policy, ip, net, port, programs) if isinstance(policy, dict) else None
    answer = None
    if verdict:
        profile = next((name for bit, name in _PROFILES if int(policy.get("cur") or 0) & bit), "private")
        if verdict[0] == "blocked":
            rule = f'netsh advfirewall firewall set rule name="{verdict[1]}" dir=in program="{real}" new action='
            answer = (f"Windows Firewall has a rule blocking Python here, so the phone can't reach port {port}",
                      rule + "allow", rule + "block")
        else:
            answer = (f"Windows Firewall blocks Python on this {profile} network, so the phone can't reach port {port}",
                      f'netsh advfirewall firewall add rule name="Chip pairing" dir=in action=allow protocol=TCP '
                      f'localport={port} remoteip=localsubnet profile={profile} program="{real}"',
                      'netsh advfirewall firewall delete rule name="Chip pairing"')
    _fw_cache[(ip, port)] = (time.time(), answer)
    return answer


# ---------------------------------------------------------------- typing along: how many keys, never which

class KeyCounter:
    """Key presses from a low-level keyboard hook (WH_KEYBOARD_LL) on its own thread, the way Windows lets a program
    notice typing in other apps. Each key release adds 2 (Linux's counters go up once per press and once per release,
    and bridge.py's words-per-minute expects that); auto-repeat has no releases, so it isn't counted. Keys typed by
    Chip's own dictation (SendInput: LLKHF_INJECTED) don't count. Only this number is kept: the hook never reads,
    stores or sends which key it was."""
    WH_KEYBOARD_LL, WM_KEYUP, WM_SYSKEYUP, LLKHF_INJECTED = 13, 0x0101, 0x0105, 0x10

    def __init__(self):
        self.n = 0
        self.thread = None
        self.failed = not IS_WIN

    def count(self):
        if self.failed:
            return None
        if self.thread is None:
            import threading
            self.thread = threading.Thread(target=self._run, name="key-counter", daemon=True)
            self.thread.start()
        return self.n

    def _run(self):
        from ctypes import POINTER, WINFUNCTYPE, c_int, c_ssize_t, c_void_p, wintypes

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", c_ssize_t)]
        u, k = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        proc_type = WINFUNCTYPE(c_ssize_t, c_int, wintypes.WPARAM, wintypes.LPARAM)
        u.SetWindowsHookExW.argtypes, u.SetWindowsHookExW.restype = [c_int, proc_type, c_void_p, wintypes.DWORD], c_void_p
        u.CallNextHookEx.argtypes, u.CallNextHookEx.restype = [c_void_p, c_int, wintypes.WPARAM, wintypes.LPARAM], c_ssize_t
        u.GetMessageW.argtypes, u.GetMessageW.restype = [POINTER(wintypes.MSG), c_void_p, wintypes.UINT, wintypes.UINT], c_int
        k.GetModuleHandleW.argtypes, k.GetModuleHandleW.restype = [c_void_p], c_void_p

        def on_key(code, wparam, lparam):  # keep it tiny: Windows drops hooks that answer slowly
            if code == 0 and wparam in (self.WM_KEYUP, self.WM_SYSKEYUP) \
                    and not ctypes.cast(lparam, POINTER(KBDLLHOOKSTRUCT)).contents.flags & self.LLKHF_INJECTED:
                self.n += 2
            return u.CallNextHookEx(None, code, wparam, lparam)

        self._callback = proc_type(on_key)  # referenced for as long as the hook lives
        if not u.SetWindowsHookExW(self.WH_KEYBOARD_LL, self._callback, k.GetModuleHandleW(None), 0):
            print(f"typing: no keyboard hook (error {ctypes.get_last_error()})", flush=True)
            self.failed = True
            return
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:  # a low-level hook needs this thread's message loop
            pass


# ---------------------------------------------------------------- now playing (Windows' media controls)
# The sessions behind the volume flyout's media card (Spotify, browsers, Media Player), through the winrt package
# (requirements.txt, Windows only). Without it: no media cap, as before.

_PLAYBACK = {4: "Playing", 5: "Paused"}  # GlobalSystemMediaTransportControlsSessionPlaybackStatus


def _winrt_media():
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as manager
        return manager
    except Exception:  # not installed, or not Windows
        return None


def _player_name(app_id):
    """A readable player name from the session's app id: "Spotify.exe", "Microsoft.ZuneMusic_8wekyb3d8bbwe!App",
    "MSEdge", "308046B0AF4A39CB" (Firefox)."""
    name = re.split(r"[!_]", app_id or "")[0]
    name = re.sub(r"\.exe$", "", name, flags=re.I).split(".")[-1]
    return name[:1].upper() + name[1:] if name else "Media"


async def _sessions():
    manager = _winrt_media()
    if manager is None:
        return []
    m = await manager.request_async()
    return list(m.get_sessions() or [])


def media_status():
    if not IS_WIN or _winrt_media() is None:
        return None
    import asyncio

    async def ask():
        paused = None
        for s in await _sessions():
            try:  # one player failing (closing mid-question: "Class not registered") must not hide the others
                status = _PLAYBACK.get(int(s.get_playback_info().playback_status))
                if not status:
                    continue
                info = await s.try_get_media_properties_async()
                item = {"name": s.source_app_user_model_id, "player": _player_name(s.source_app_user_model_id),
                        "status": status, "title": info.title or "", "artist": info.artist or ""}
            except OSError:
                continue
            if status == "Playing":
                return item
            paused = paused or item
        return paused
    try:
        return asyncio.run(ask())
    except Exception as e:  # a player closing mid-question
        print("media:", e, flush=True)
        return None


def media_control(action):
    if not IS_WIN or _winrt_media() is None:
        return
    import asyncio
    current = media_status()

    async def press():
        sessions = await _sessions()
        chosen = [s for s in sessions if current and s.source_app_user_model_id == current["name"]] or sessions[:1]
        for s in chosen:
            await {"playpause": s.try_toggle_play_pause_async, "next": s.try_skip_next_async,
                   "previous": s.try_skip_previous_async}[action]()
    asyncio.run(press())


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
                   typing=input_size_ok() and is_locked is not None, typingRate=True,
                   media=_winrt_media() is not None, nowPlaying=_winrt_media() is not None)
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
