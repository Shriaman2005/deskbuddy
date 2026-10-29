"""Getting your attention from the phone: blinking the torch and playing an alert sound (runs in Termux).

The torch is the camera LED, switched with Termux:API's termux-torch (~0.2 s per switch). The sounds are
made here (no sound files) and played through PulseAudio's Android output, which is loaded only while one
plays. stop() ends both at once: the page calls it when you tap Chip or come back to the laptop.
"""
import math
import struct
import subprocess
import threading
import time

from dictation import start_pulseaudio

RATE = 16000
stop_event = threading.Event()
torch_lock = threading.Lock()
sound_lock = threading.Lock()
flashlight = False  # switched on from the drawer; a blink ends back in this state


def note(freq, ms, decay=4.0, harmonics=(1.0,)):
    """A struck tone: quick fade-in, then it rings out (decay = how fast)."""
    n, total = int(RATE * ms / 1000), sum(harmonics)
    return [math.exp(-decay * i / n) * min(1.0, i / 80) *
            sum(a * math.sin(2 * math.pi * freq * (k + 1) * i / RATE) for k, a in enumerate(harmonics)) / total
            for i in range(n)]


def rest(ms):
    return [0.0] * int(RATE * ms / 1000)


# One cycle of each sound; it repeats for as long as the dashboard says.
STYLES = {
    "chime": lambda: note(1319, 160) + note(1568, 160) + note(2093, 420) + rest(400),
    "beep": lambda: (note(880, 120, decay=0.5) + rest(90)) * 2 + rest(560),
    "alarm": lambda: (note(988, 110, 0.3, (1, .3, .15)) + note(1319, 110, 0.3, (1, .3, .15))) * 3 + rest(260),
    "ping": lambda: note(1760, 600, decay=5) + rest(500),
}
_cycles = {}


def cycle(style):
    if style not in _cycles:
        samples = STYLES[style]()
        _cycles[style] = struct.pack(f"<{len(samples)}h", *(int(26000 * max(-1.0, min(1.0, v))) for v in samples))
    return _cycles[style]


def torch(on):
    subprocess.run(["termux-torch", "on" if on else "off"], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def set_flashlight(on):
    global flashlight
    flashlight = on
    if torch_lock.acquire(blocking=False):  # otherwise the blink in progress ends in this state
        try:
            torch(on)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            torch_lock.release()


def blink(seconds):
    if not torch_lock.acquire(blocking=False):
        return  # already blinking
    try:
        end = time.time() + seconds
        while time.time() < end and not stop_event.is_set():
            torch(True)
            stop_event.wait(0.25)
            torch(False)
            stop_event.wait(0.3)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        try:
            torch(flashlight)  # never leave it on by accident
        except (OSError, subprocess.SubprocessError):
            pass
        torch_lock.release()


def play(style, seconds, volume):
    if not sound_lock.acquire(blocking=False):
        return  # already playing
    module = ""
    try:
        start_pulseaudio()
        module = subprocess.run(["pactl", "load-module", "module-sles-sink"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        pcm = cycle(style)
        repeats = max(1, round(seconds / (len(pcm) / 2 / RATE)))
        proc = subprocess.Popen(["pacat", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                                 f"--volume={int(65536 * volume / 100)}"],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def feed():
            try:
                for _ in range(repeats):
                    proc.stdin.write(pcm)
                proc.stdin.close()  # pacat plays what's buffered, then exits
            except (BrokenPipeError, ValueError):
                pass
        threading.Thread(target=feed, daemon=True).start()
        while proc.poll() is None:
            if stop_event.wait(0.1):
                proc.terminate()
                proc.wait()
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        if module:
            subprocess.run(["pactl", "unload-module", module], timeout=10)
        sound_lock.release()


def start(torch_seconds=0, sound_seconds=0, style="chime", volume=80):
    stop_event.clear()
    if torch_seconds:
        threading.Thread(target=blink, args=(torch_seconds,), daemon=True).start()
    if sound_seconds:
        threading.Thread(target=play, args=(style, sound_seconds, volume), daemon=True).start()


def stop():
    stop_event.set()
