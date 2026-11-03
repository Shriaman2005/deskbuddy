"""macOS backend: PC stats (psutil), the network for the phone link, idle time and the lock state (CoreGraphics), and
typing into the focused window (CGEvent keyboard events with a Unicode string). ctypes + psutil only, no PyObjC.
Imports cleanly on every OS; the frameworks are loaded on first use, and only on macOS.
Typing needs Accessibility for the Python that runs the bridge (System Settings → Privacy & Security → Accessibility):
macOS gives it to that Python, so any background program run by the same Python could post keys too."""
import ctypes
import os
import re
import sys
import threading
import time

from . import base, psstats
from .base import *  # noqa: F401,F403
from .base import TypingError, caps as _none, interface
from .proc import run
from textclean import typable, utf16_units  # noqa: F401  laptop/textclean.py (every entry point has laptop/ on sys.path)

IS_MAC = sys.platform == "darwin"

NAME = "macos"
LAUNCH_AGENT = "org.deskbuddy.bridge"  # ~/Library/LaunchAgents/<label>.plist, made by install.py (doctor checks it)
ACCESSIBILITY_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
ACCESSIBILITY_HELP = "Allow Python in System Settings → Privacy & Security → Accessibility, then try again"


# ---------------------------------------------------------------- the network (S2)

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


# ---------------------------------------------------------------- stats (psutil, platforms/psstats.py)

class Sampler(psstats.Sampler):
    """psutil plus the load average. The disk is the Data volume (where your files are; "/" is the sealed system)."""
    disk_root = "/System/Volumes/Data" if os.path.isdir("/System/Volumes/Data") else "/"
    load = True


# ---------------------------------------------------------------- CoreGraphics / CoreFoundation / Accessibility

FRAMEWORKS = "/System/Library/Frameworks/"
kCFStringEncodingUTF8 = 0x08000100
kCGEventSourceStateHIDSystemState = 1
kCGAnyInputEventType = 0xFFFFFFFF   # ~0 as a CGEventType (uint32)
kCGHIDEventTap = 0
VK_ANSI_A = 0          # any key code: the Unicode string is what apps read
CHUNK = 20             # UTF-16 units per event: CGEventKeyboardSetUnicodeString keeps no more than 20
CHUNK_PAUSE = 0.008    # s between events, so a slow app keeps up

_libs_lock = threading.Lock()
_libs_cache = []


def _libs():
    """(CoreGraphics, CoreFoundation, ApplicationServices) with argument types set, or None (not macOS, or a
    framework missing). Loaded once."""
    with _libs_lock:
        if not _libs_cache:
            _libs_cache.append(_load() if IS_MAC else None)
        return _libs_cache[0]


def _load():
    from ctypes import POINTER, c_bool, c_double, c_long, c_uint16, c_uint32, c_uint64, c_ulong, c_void_p, c_char_p
    try:
        cg = ctypes.CDLL(FRAMEWORKS + "CoreGraphics.framework/CoreGraphics")
        cf = ctypes.CDLL(FRAMEWORKS + "CoreFoundation.framework/CoreFoundation")
        ax = ctypes.CDLL(FRAMEWORKS + "ApplicationServices.framework/ApplicationServices")
        sig = {
            cg.CGEventSourceSecondsSinceLastEventType: ([ctypes.c_int32, c_uint32], c_double),
            cg.CGSessionCopyCurrentDictionary: ([], c_void_p),
            cg.CGEventCreateKeyboardEvent: ([c_void_p, c_uint16, c_bool], c_void_p),
            cg.CGEventKeyboardSetUnicodeString: ([c_void_p, c_ulong, POINTER(c_uint16)], None),
            cg.CGEventKeyboardGetUnicodeString: ([c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_uint16)], None),
            cg.CGEventSetFlags: ([c_void_p, c_uint64], None),
            cg.CGEventGetFlags: ([c_void_p], c_uint64),
            cg.CGEventPost: ([c_uint32, c_void_p], None),
            cf.CFStringCreateWithCString: ([c_void_p, c_char_p, c_uint32], c_void_p),
            cf.CFDictionaryGetValue: ([c_void_p, c_void_p], c_void_p),
            cf.CFDictionaryCreate: ([c_void_p, POINTER(c_void_p), POINTER(c_void_p), c_long, c_void_p, c_void_p], c_void_p),
            cf.CFGetTypeID: ([c_void_p], c_ulong),
            cf.CFBooleanGetTypeID: ([], c_ulong),
            cf.CFBooleanGetValue: ([c_void_p], c_bool),
            cf.CFRelease: ([c_void_p], None),
            ax.AXIsProcessTrusted: ([], c_bool),
            ax.AXIsProcessTrustedWithOptions: ([c_void_p], c_bool),
        }
        for fn, (args, res) in sig.items():
            fn.argtypes, fn.restype = args, res
        return cg, cf, ax
    except (OSError, AttributeError):
        return None


def _cf_bool(cf, dictionary, name, default):
    """The CFBoolean under key name in a CFDictionary, default when it isn't there (or isn't a boolean)."""
    key = cf.CFStringCreateWithCString(None, name.encode(), kCFStringEncodingUTF8)
    if not key:
        return default
    try:
        value = cf.CFDictionaryGetValue(dictionary, key)
        if not value or cf.CFGetTypeID(value) != cf.CFBooleanGetTypeID():
            return default
        return bool(cf.CFBooleanGetValue(value))
    finally:
        cf.CFRelease(key)


def idle_ms():
    """Milliseconds since the last keyboard/mouse/trackpad input (CGEventSourceSecondsSinceLastEventType), or None."""
    libs = _libs()
    if not libs:
        return None
    s = libs[0].CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)
    return round(s * 1000) if s == s and 0 <= s < 1e9 else None  # NaN / nonsense -> unknown


def locked():
    """True while the screen is locked, the login window is up, or another user has the screen (fast user switching);
    None when there is no window-server session (then nothing is typed)."""
    libs = _libs()
    if not libs:
        return None
    cg, cf, _ = libs
    session = cg.CGSessionCopyCurrentDictionary()
    if not session:
        return None
    try:
        return (_cf_bool(cf, session, "CGSSessionScreenIsLocked", False)
                or not _cf_bool(cf, session, "kCGSSessionOnConsoleKey", True)
                or not _cf_bool(cf, session, "kCGSessionLoginDoneKey", True))
    finally:
        cf.CFRelease(session)


_asked = threading.Event()  # macOS's "allow Accessibility" prompt: once per bridge run, not on every dictation


def trusted(prompt=False):
    """True if this Python may post key events (Accessibility). prompt=True asks macOS to show its dialog, which also
    puts Python in the Accessibility list (switched off)."""
    libs = _libs()
    if not libs:
        return False
    _, cf, ax = libs
    if not prompt:
        return bool(ax.AXIsProcessTrusted())
    keys = (ctypes.c_void_p * 1)(ctypes.c_void_p.in_dll(ax, "kAXTrustedCheckOptionPrompt").value)
    values = (ctypes.c_void_p * 1)(ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue").value)
    options = cf.CFDictionaryCreate(None, keys, values, 1,
                                    ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
                                    ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
    if not options:
        return bool(ax.AXIsProcessTrusted())
    try:
        return bool(ax.AXIsProcessTrustedWithOptions(options))
    finally:
        cf.CFRelease(options)


def chunks(units):
    """units in runs of at most CHUNK, never splitting a surrogate pair."""
    i = 0
    while i < len(units):
        j = min(i + CHUNK, len(units))
        if j < len(units) and 0xD800 <= units[j - 1] <= 0xDBFF:
            j -= 1
        yield units[i:j]
        i = j


def key_events(units):
    """[(key down, key up)] CGEvents carrying the UTF-16 units, no modifier flags (a held ⌘ must not turn text into
    shortcuts). Nothing is posted; the caller releases them with release_events()."""
    cg = _libs()[0]
    made = []  # every event created so far, released if anything fails
    try:
        for part in chunks(units):
            buf = (ctypes.c_uint16 * len(part))(*part)
            for down in (True, False):
                e = cg.CGEventCreateKeyboardEvent(None, VK_ANSI_A, down)
                if not e:
                    raise TypingError("blocked", "macOS didn't make the key events")
                made.append(e)
                cg.CGEventSetFlags(e, 0)
                cg.CGEventKeyboardSetUnicodeString(e, len(part), buf)
    except BaseException:
        release_events([made])
        raise
    return list(zip(made[::2], made[1::2]))


def release_events(events):
    cf = _libs()[1]
    for pair in events:
        for e in pair:
            cf.CFRelease(e)


def unicode_of(event):
    """The UTF-16 units a keyboard CGEvent carries (CGEventKeyboardGetUnicodeString), for tests."""
    cg = _libs()[0]
    buf, n = (ctypes.c_uint16 * 64)(), ctypes.c_ulong(0)
    cg.CGEventKeyboardGetUnicodeString(event, 64, ctypes.byref(n), buf)
    return list(buf[:n.value])


def type_text(text):
    """Types text into the focused window and returns what was typed. Never sends Enter (newlines and tabs become
    spaces), refuses while locked or without Accessibility. Up to 20 UTF-16 units go per key down + up, so any
    language and emoji work without touching the clipboard."""
    if not _libs():
        return base.type_text(text)
    text = typable(text)
    if not text:
        return ""
    text += " "  # so back-to-back dictations don't run together
    if locked() is not False:
        raise TypingError("locked", "The laptop is locked")
    first = not _asked.is_set()
    _asked.set()
    if not trusted(prompt=first):
        raise TypingError("accessibility", ACCESSIBILITY_HELP)
    cg = _libs()[0]
    events = key_events(utf16_units(text))
    try:
        for down, up in events:
            cg.CGEventPost(kCGHIDEventTap, down)
            cg.CGEventPost(kCGHIDEventTap, up)
            time.sleep(CHUNK_PAUSE)
    finally:
        release_events(events)
    return text


# ---------------------------------------------------------------- caps

def caps():
    """What this Mac can do. wifiName: macOS shows the Wi-Fi name (or the laptop is wired, where "wired" is the
    network's name). On another OS (the selftest imports this everywhere) only wifiName can be true. typing is true
    without Accessibility too: then the phone shows ACCESSIBILITY_HELP when you dictate."""
    iface = interface()[0]
    out = dict(_none(), wifiName=bool(iface) and (not is_wireless(iface) or wifi_ssid(iface)[0] is not None))
    if _libs():
        ps = psstats.psutil_or_none()
        is_locked = locked()
        out.update(stats=ps is not None, battery=bool(ps) and psstats.attempt(ps.sensors_battery) is not None,
                   idle=idle_ms() is not None, locked=is_locked is not None, typing=is_locked is not None)
    return out
