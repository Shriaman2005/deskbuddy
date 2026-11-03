"""Hold-to-talk dictation for the desk buddy (runs in Termux on the phone).

Records the phone mic through PulseAudio's Android (OpenSL ES) source only while you hold
Chip's face, then turns the audio into text with the engine chosen on the dashboard: whisper.cpp on the phone
(offline, nothing leaves it except the final text, which the page sends to the laptop to be typed), or the
laptop's whisper.cpp / a cloud API, for which the clip goes through the ssh tunnel to the bridge's /transcribe.
There is no fallback: if the chosen engine fails the result is {"error": <code>} and the audio goes nowhere else.
Error codes (the same as the bridge's, laptop/stt.py): silence, too_short, no_words, key_missing, key_rejected,
quota, offline, timeout, lang_unsupported, provider_error, locked.
"""
import array
import glob
import json
import math
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

STT = os.path.expanduser("~/stt")
WHISPER = os.path.join(STT, "whisper-cli")
# 8-bit models: the chip has no fp16 maths, so these are ~1.5x faster than the originals.
# For a 4 s sentence: base ~6 s (better Hinglish), tiny ~3 s.
MODELS = {False: os.path.join(STT, "models", "ggml-base-q8_0.bin"),
          True: os.path.join(STT, "models", "ggml-tiny-q8_0.bin")}
RATE = 16000
MAX_SECONDS = 60
# Nudges Whisper towards romanised Hinglish mixed with English, the way you'd type it.
def start_pulseaudio():
    """PulseAudio for the mic and the alert sound (alert.py). It runs with no default config, so it only has
    the socket for parec/pacat/pactl; the Android input and output are loaded only while in use."""
    # `pulseaudio --check` can't read other processes' /proc entries, so ask the socket instead. After a reboot the
    # old pid file is left behind and PulseAudio then assumes it is still running and refuses to start.
    if subprocess.run(["pactl", "info"], capture_output=True, timeout=10).returncode != 0:
        for pid_file in glob.glob(os.path.expanduser("~/.config/pulse/*-runtime/pid")):
            os.remove(pid_file)
        subprocess.run(["pulseaudio", "--start", "-n", "--load=module-native-protocol-unix",
                        "--exit-idle-time=-1"], timeout=15)


ENGINES = ("phone", "laptop", "cloud")
LANG_RE = re.compile(r"auto|hinglish|[a-z]{2,3}")  # "auto", "hinglish" or a Whisper language code
PROMPT = "Haan, main kal office aaunga. Meeting is at 5 PM, okay? Thik hai, send kar do."
LAPTOP = "http://127.0.0.1:8765"  # the laptop bridge, through the ssh tunnel
BRIDGE_WAIT = 70  # s: laptop whisper may take up to 60 s, a cloud request 20


class Dictation:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"          # idle | listening | thinking
        self.proc = None
        self.module = ""
        self.buf = bytearray()
        self.level = 0.0
        self.peak = 0.0
        self.started = 0.0

    # ------------------------------------------------------------ mic
    def _open_mic(self):
        start_pulseaudio()
        # a take that died without cancel (page closed, ssh dropped) leaves its source loaded and the mic held
        for line in subprocess.run(["pactl", "list", "short", "modules"], capture_output=True, text=True,
                                   timeout=10).stdout.splitlines():
            f = line.split("\t")
            if len(f) > 1 and f[1] == "module-sles-source":
                subprocess.run(["pactl", "unload-module", f[0]], timeout=10)
        # the mic source is loaded per take and unloaded afterwards, so the mic is really off in between
        self.module = subprocess.run(["pactl", "load-module", "module-sles-source"],
                                     capture_output=True, text=True, timeout=10).stdout.strip()

    def _close_mic(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.module:
            subprocess.run(["pactl", "unload-module", self.module], timeout=10)
            self.module = ""

    def _read(self, proc):
        while proc.poll() is None:
            chunk = proc.stdout.read(1600)  # 50 ms of 16 kHz mono s16le
            if not chunk:
                break
            if time.time() - self.started < MAX_SECONDS:
                self.buf += chunk
            samples = array.array("h", chunk)
            rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples))) / 32768
            self.level = min(1.0, rms * 10)
            self.peak = max(self.peak, self.level)

    # ------------------------------------------------------------ API
    def start(self):
        with self.lock:
            if self.state == "listening" or (self.state == "thinking" and time.time() - self.started > 200):
                self._close_mic()  # a new hold means the old take is dead (page closed mid-take, lost cancel)
                self.state = "idle"
            if self.state != "idle":
                return {"error": "busy"}
            try:
                self._open_mic()
            except (OSError, subprocess.SubprocessError):
                self._close_mic()
                raise
            self.buf, self.level, self.peak, self.started = bytearray(), 0.0, 0.0, time.time()
            self.proc = subprocess.Popen(["parec", "--format=s16le", f"--rate={RATE}", "--channels=1", "--raw",
                                          "--latency-msec=50"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
            self.state = "listening"
            return {"ok": True}

    def cancel(self):
        with self.lock:
            self._close_mic()
            self.state = "idle"
            return {"ok": True}

    def stop(self, fast=False, engine="phone", lang="hinglish"):
        with self.lock:
            if self.state != "listening":
                return {"error": "not listening"}
            self._close_mic()
            audio, peak = bytes(self.buf), self.peak
            self.state = "thinking"
        try:
            if engine not in ENGINES or not LANG_RE.fullmatch(lang):
                return {"error": "lang_unsupported" if engine in ENGINES else "provider_error"}
            seconds = len(audio) / 2 / RATE
            if seconds < 0.5:
                return {"error": "too_short"}
            if peak < 0.04:  # silence: Whisper would make something up
                return {"error": "silence"}
            path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "deskbuddy-dictation.wav")
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(audio)
            try:
                return self.transcribe(path, fast, engine, lang)
            finally:
                os.remove(path)
        finally:
            self.state = "idle"

    def transcribe(self, path, fast, engine, lang):
        t0 = time.time()
        if engine == "phone":
            try:
                out = self._on_phone(path, fast, lang)
            except subprocess.TimeoutExpired:
                return {"error": "timeout"}
            except (OSError, subprocess.SubprocessError):
                return {"error": "provider_error"}
        else:
            out = self._on_bridge(path, fast, engine, lang)
            if isinstance(out, dict):  # {"error": code, "message": ...}
                return out
        text = " ".join(re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", out).split())  # drop [BLANK_AUDIO], (music) and the like
        if not text:
            return {"error": "no_words"}
        return {"text": text, "engine": engine, "lang": lang, "ms": int((time.time() - t0) * 1000)}

    @staticmethod
    def _on_phone(path, fast, lang):
        with wave.open(path) as w:
            seconds = w.getnframes() / w.getframerate()
        # -ac shrinks Whisper's fixed 30 s window to the clip's length, which is most of the speed-up
        audio_ctx = min(1500, int(seconds * 50) + 128)
        # the Hinglish prompt is only sent for "hinglish" (English with romanised Hindi)
        lang_args = ["-l", "en", "--prompt", PROMPT] if lang == "hinglish" else ["-l", lang]
        # -bs 1 -bo 1: greedy decoding, much faster than the default beam search for the same text
        return subprocess.run([WHISPER, "-m", MODELS[fast], "-f", path, "-t", "4", "-nt", "-np",
                               "-bs", "1", "-bo", "1", "-ac", str(audio_ctx), *lang_args],
                              capture_output=True, text=True, timeout=180, check=True).stdout

    @staticmethod
    def _on_bridge(path, fast, engine, lang):
        """The bridge's text, or {"error": code} (also when the tunnel is down: "offline"). Never falls back."""
        query = urllib.parse.urlencode({"engine": engine, "lang": lang, "fast": int(fast)})
        with open(path, "rb") as f:
            req = urllib.request.Request(f"{LAPTOP}/transcribe?{query}", data=f.read(), method="POST",
                                         headers={"Content-Type": "audio/wav"})
        try:
            with urllib.request.urlopen(req, timeout=BRIDGE_WAIT) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:  # the bridge answered with an error code
            try:
                data = json.load(e)
            except (OSError, ValueError):
                return {"error": "provider_error"}
            return {"error": str(data.get("error") or "provider_error"), "message": str(data.get("message") or "")}
        except (socket.timeout, TimeoutError):
            return {"error": "timeout"}
        except urllib.error.URLError as e:  # tunnel down or bridge not running
            return {"error": "timeout" if isinstance(e.reason, (socket.timeout, TimeoutError)) else "offline"}
        except (OSError, ValueError):
            return {"error": "offline"}
        if not isinstance(data, dict) or not data.get("ok") or not isinstance(data.get("text"), str):
            return {"error": "provider_error"}
        return data["text"]

    def status(self):
        listening = self.state == "listening"
        return {"state": self.state, "level": round(self.level, 2) if listening else 0,
                "elapsed": round(time.time() - self.started, 1) if listening else 0}
