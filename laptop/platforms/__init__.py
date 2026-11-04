"""Everything OS-specific the bridge does, behind one small set of functions; the backend is picked by sys.platform:
linux.py (GNOME), windows.py and macos.py (stubs until S5/S6). base.py documents each function.

CAPS: what this laptop can do, as bools (refreshed every 30 s by caps(); /stats carries it as "caps", GET /caps too):
  stats, gpu, temps, battery          PC stats, the GPU ring, temperatures, the laptop battery
  idle, locked                        time since the last input; whether the screen is locked
  typing                              typing dictated text into the focused window
  media, nowPlaying, volume           media keys, the song playing, the volume
  notifications                       other apps' desktop notifications
  visualizer                          the audio spectrum (/viz)
  typingRate                          how long and fast you type (Chip types along)
  gaze                                the mouse pointer, for Chip's eyes (/gaze)
  wifiName                            the Wi-Fi name, for "home Wi-Fi only"
  termuxLink, skins, laptopStt        ssh, node and whisper-cli were found
CHIP_FAKE_CAPS=gpu=0,media=0 switches caps off (or on) for testing the "Linux only for now" paths on Linux.

/stats keys, from Sampler.sample() every 2 s (None where unknown):
  cpu, cores [per-core %], ram, temp, battery, charging, net_rx, net_tx (bytes/s), uptime (s),
  temps {cpu, gpu, ssd, board}, fan, gpu, ram_used_gb, ram_total_gb, swap, disk, disk_free_gb, load [1, 5, 15 min],
  wifi {iface, dbm} | None, bat {watts, cycles, health, status, minutes_left?}
and every 3 s: media {name, player, status, title, artist} | None, volume, muted, idle_ms, locked.
The bridge adds ts, typing_for, wpm, idle, settingsRev, skinsRev, attention and caps.
"""
import os
import shutil
import sys
import time

from . import paths, proc  # noqa: F401  (platforms.paths / platforms.proc for callers)

if sys.platform.startswith("linux"):
    from . import linux as backend
elif sys.platform == "win32":
    from . import windows as backend
else:  # macOS, and anything else gets the do-nothing stubs
    from . import macos as backend

NAME = backend.NAME
CAP_KEYS = ("stats", "gpu", "temps", "battery", "idle", "locked", "typing", "media", "nowPlaying", "volume",
            "notifications", "visualizer", "typingRate", "gaze", "wifiName", "termuxLink", "skins", "laptopStt")

Sampler, KeyCounter, GazeWatch, TypingError = backend.Sampler, backend.KeyCounter, backend.GazeWatch, backend.TypingError
volume, idle_ms, locked, type_text = backend.volume, backend.idle_ms, backend.locked, backend.type_text
media_status, media_control, volume_control = backend.media_status, backend.media_control, backend.volume_control
watch_notifications, audio_monitor = backend.watch_notifications, backend.audio_monitor
gaze_call, gaze_pointer, gaze_monitors = backend.gaze_call, backend.gaze_pointer, backend.gaze_monitors
prepare_listener = backend.prepare_listener
interface, is_wireless, wifi_ssid, firewall_on = backend.interface, backend.is_wireless, backend.wifi_ssid, backend.firewall_on

_WHISPER_EXE = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
WHISPER = paths.data("stt", _WHISPER_EXE)   # Windows/macOS also take a whisper-cli found on PATH (looked up at start)
if not os.path.isfile(WHISPER) and not sys.platform.startswith("linux"):
    WHISPER = shutil.which(_WHISPER_EXE) or WHISPER


def fake_caps():
    """{cap: bool} from CHIP_FAKE_CAPS ("gpu=0,media=0"); unknown names are ignored."""
    out = {}
    for item in os.environ.get("CHIP_FAKE_CAPS", "").split(","):
        k, _, v = item.strip().partition("=")
        if k in CAP_KEYS and v in ("0", "1"):
            out[k] = v == "1"
    return out


def _detect():
    found = dict(backend.caps(), termuxLink=bool(proc.which("ssh")), skins=bool(shutil.which("node")),
                 laptopStt=os.path.isfile(WHISPER))
    return {k: bool(found.get(k)) for k in CAP_KEYS} | fake_caps()


CAPS = _detect()
_caps_at = time.monotonic()


def caps():
    """CAPS, looked at again when older than 30 s (a tool installed, whisper-cli downloaded)."""
    global _caps_at
    if time.monotonic() - _caps_at > 30:
        CAPS.update(_detect())
        _caps_at = time.monotonic()
    return dict(CAPS)


# the bridge as a service (chip.py, /bridge/*, doctor.py): base.py documents them
SERVICE, start_command = backend.SERVICE, backend.start_command
service_stop, service_start, service_restart = backend.service_stop, backend.service_start, backend.service_restart
autostart_get, autostart_set = backend.autostart_get, backend.autostart_set
