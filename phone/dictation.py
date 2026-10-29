"""Hold-to-talk dictation for the desk buddy (runs in Termux on the phone).

Records the phone mic through PulseAudio's Android (OpenSL ES) source only while you hold
Chip's face, then turns the audio into text offline with whisper.cpp, on the phone or (if chosen on the
dashboard) on the laptop. On the phone nothing leaves it except the final text, which the page sends to the
laptop to be typed. On the laptop the clip goes through the ssh tunnel to the bridge, which transcribes it
in memory and keeps nothing; if the laptop can't do it, the phone does.
"""
import array
import glob
import json
import math
import os
import re
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


PROMPT = "Haan, main kal office aaunga. Meeting is at 5 PM, okay? Thik hai, send kar do."
LAPTOP = "http://127.0.0.1:8765"  # the laptop bridge, through the ssh tunnel


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
            if self.state != "idle":
                return {"error": "busy"}
            self._open_mic()
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

    def stop(self, fast=False, laptop=False):
        with self.lock:
            if self.state != "listening":
                return {"error": "not listening"}
            self._close_mic()
            audio, peak = bytes(self.buf), self.peak
            self.state = "thinking"
        try:
            seconds = len(audio) / 2 / RATE
            if seconds < 0.5:
                return {"text": "", "error": "too short"}
            if peak < 0.04:  # silence: Whisper would make something up
                return {"text": "", "error": "silence"}
            path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "deskbuddy-dictation.wav")
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(audio)
            try:
                return self.transcribe(path, fast, laptop)
            finally:
                os.remove(path)
        finally:
            self.state = "idle"

    def transcribe(self, path, fast=False, laptop=False):
        t0 = time.time()
        out = self._on_laptop(path, fast) if laptop else None
        engine = "laptop" if out is not None else "phone"
        if out is None:
            out = self._on_phone(path, fast)
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", out)  # drop [BLANK_AUDIO], (music) and the like
        with wave.open(path) as w:
            seconds = w.getnframes() / w.getframerate()
        return {"text": " ".join(text.split()), "seconds": round(seconds, 1), "ms": int((time.time() - t0) * 1000),
                "engine": engine, "fallback": laptop and engine == "phone"}

    @staticmethod
    def _on_phone(path, fast):
        with wave.open(path) as w:
            seconds = w.getnframes() / w.getframerate()
        # -ac shrinks Whisper's fixed 30 s window to the clip's length, which is most of the speed-up
        audio_ctx = min(1500, int(seconds * 50) + 128)
        # -bs 1 -bo 1: greedy decoding, much faster than the default beam search for the same text
        return subprocess.run([WHISPER, "-m", MODELS[fast], "-f", path, "-l", "en", "-t", "4", "-nt", "-np",
                               "-bs", "1", "-bo", "1", "-ac", str(audio_ctx), "--prompt", PROMPT],
                              capture_output=True, text=True, timeout=180).stdout

    @staticmethod
    def _on_laptop(path, fast):
        """The laptop's raw transcript, or None if it couldn't do it (tunnel down, bridge busy or broken)."""
        query = urllib.parse.urlencode({"fast": int(fast), "prompt": PROMPT})
        with open(path, "rb") as f:
            req = urllib.request.Request(f"{LAPTOP}/transcribe?{query}", data=f.read(), method="POST",
                                         headers={"Content-Type": "audio/wav"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)["text"]
        except (OSError, ValueError, KeyError):  # URLError and timeouts are OSErrors
            return None

    def status(self):
        listening = self.state == "listening"
        return {"state": self.state, "level": round(self.level, 2) if listening else 0,
                "elapsed": round(time.time() - self.started, 1) if listening else 0}
