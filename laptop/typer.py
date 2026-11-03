"""Types text into whatever window has keyboard focus, via GNOME's remote-desktop D-Bus API.

Works on GNOME Wayland without root or extra packages (it's what GNOME Remote Desktop uses).
- Plain ASCII is typed one key at a time (works everywhere, even where pasting is blocked).
- Anything else (Hindi, Arabic, CJK, accents, emoji) can't be typed as keys: Mutter only types keysyms on the
  current layout. So it goes on the clipboard through the same remote-desktop session and is pasted with Ctrl+V
  (Ctrl+Shift+V in terminals); the old clipboard is put back afterwards. Mutter's clipboard manager keeps the
  restored copy after the session ends (for text and images: rich formats keep their main type only).
Never sends Enter: newlines and tabs become spaces, so a paste into a terminal can't run anything.
"""
import os
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402
from textclean import clean, is_plain  # noqa: E402,F401  (typer.clean / typer.is_plain stay)

BUS_NAME = "org.gnome.Mutter.RemoteDesktop"
GAZE_BUS = ("org.deskbuddy.Gaze", "/org/deskbuddy/Gaze", "org.deskbuddy.Gaze")  # chip-gaze extension

TEXT_MIMES = ["text/plain;charset=utf-8", "UTF8_STRING", "text/plain", "STRING", "TEXT"]
SECRET_HINT = "x-kde-passwordManagerHint"  # clipboard-history tools skip entries offering this ("secret")
TERMINALS = ("terminal", "ptyxis", "console", "kgx", "kitty", "alacritty", "foot", "tilix", "terminator",
             "xterm", "urxvt", "wezterm", "konsole", "ghostty", "blackbox", "guake", "tilda")

KEY_CTRL, KEY_SHIFT, KEY_V = 0xFFE3, 0xFFE1, 0x76
OLD_CLIP_MAX = 8 << 20      # bytes of the old clipboard worth saving (all its types together)
PASTE_WAIT = 1.5            # s for the focused app to ask for the pasted text
PASTE_GRACE = 0.3           # s after its first request, for any more types it asks for


class TypingError(Exception):
    """code: 'paste_unserved' (the focused app never asked for the pasted text) or 'clipboard'."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def focused_app():
    """The focused window's app class from the chip-gaze extension, '' if unknown (extension not loaded yet)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return bus.call_sync(GAZE_BUS[0], GAZE_BUS[1], GAZE_BUS[2], "FocusedApp", None, GLib.VariantType("(s)"),
                             Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
    except GLib.Error:
        return ""


def is_terminal(app):
    app = app.lower()
    return any(t in app for t in TERMINALS) and "code" not in app  # VS Code's editor: Ctrl+Shift+V is a preview


class _Session:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.path = self.bus.call_sync(BUS_NAME, "/org/gnome/Mutter/RemoteDesktop", BUS_NAME, "CreateSession", None,
                                       GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
        self.iface = BUS_NAME + ".Session"
        self.ctx = GLib.MainContext.default()
        self.sub = None
        self.offer = {}            # mime -> bytes we serve while we own the clipboard
        self.requests = 0          # transfers served since the counter was last reset
        self.owner_mimes = []      # what the clipboard held when we enabled it (someone else's)
        self.owner_seen = False

    def call(self, method, args=None, reply=None):
        return self.bus.call_sync(BUS_NAME, self.path, self.iface, method, args, reply, Gio.DBusCallFlags.NONE,
                                  5000, None)

    def key(self, keysym, down):
        self.call("NotifyKeyboardKeysym", GLib.Variant("(ub)", (keysym, down)))

    def tap(self, keysym):
        self.key(keysym, True)
        self.key(keysym, False)

    # -- clipboard

    def _signal(self, _conn, _sender, _path, _iface, name, params):
        if name == "SelectionOwnerChanged":
            opts = params.unpack()[0]
            if not opts.get("session-is-owner") and not self.owner_seen:
                mimes = opts.get("mime-types", ())
                if isinstance(mimes, tuple) and len(mimes) == 1 and isinstance(mimes[0], list):
                    mimes = mimes[0]  # Mutter sends it as (as)
                self.owner_mimes, self.owner_seen = [m for m in mimes if isinstance(m, str)], True
        elif name == "SelectionTransfer":
            mime, serial = params.unpack()
            data = self.offer.get(mime)
            ok = False
            if data is not None:
                try:
                    res, fds = self.bus.call_with_unix_fd_list_sync(
                        BUS_NAME, self.path, self.iface, "SelectionWrite", GLib.Variant("(u)", (serial,)),
                        GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None)
                    fd = fds.get(res.unpack()[0])
                    try:
                        view = memoryview(data)
                        while view:
                            view = view[os.write(fd, view):]
                    finally:
                        os.close(fd)
                    ok = True
                except (GLib.Error, OSError):
                    pass
            try:
                self.call("SelectionWriteDone", GLib.Variant("(ub)", (serial, ok)))
            except GLib.Error:
                pass
            self.requests += 1

    def pump(self, seconds, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end and not (until and until()):
            while self.ctx.iteration(False):
                pass
            time.sleep(0.005)

    def enable_clipboard(self):
        self.sub = self.bus.signal_subscribe(BUS_NAME, self.iface, None, self.path, None,
                                             Gio.DBusSignalFlags.NONE, self._signal)
        self.call("EnableClipboard", GLib.Variant("(a{sv})", ({},)))
        self.pump(0.3, lambda: self.owner_seen)  # the current owner's types arrive as a signal

    def read_old(self):
        """The current clipboard's contents, type by type, so it can be put back."""
        saved, total = {}, 0
        for mime in self.owner_mimes:
            if mime in ("TARGETS", "MULTIPLE", "TIMESTAMP", "SAVE_TARGETS"):
                continue
            try:
                res, fds = self.bus.call_with_unix_fd_list_sync(
                    BUS_NAME, self.path, self.iface, "SelectionRead", GLib.Variant("(s)", (mime,)),
                    GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None)
                fd = fds.get(res.unpack()[0])
            except GLib.Error:
                continue
            chunks, end = [], time.monotonic() + 1.0
            try:
                os.set_blocking(fd, False)
                while time.monotonic() < end and total <= OLD_CLIP_MAX:
                    try:
                        chunk = os.read(fd, 65536)
                    except BlockingIOError:
                        self.pump(0.01)
                        continue
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
            finally:
                os.close(fd)
            if total > OLD_CLIP_MAX:
                return {}  # too big to keep: better to leave nothing than half an image
            saved[mime] = b"".join(chunks)
        return saved

    def own(self, offer):
        self.offer = offer
        self.call("SetSelection", GLib.Variant("(a{sv})", ({"mime-types": GLib.Variant("as", list(offer))},)))

    def close(self):
        try:
            self.call("Stop")
        except GLib.Error:
            pass
        if self.sub is not None:
            self.bus.signal_unsubscribe(self.sub)
        self.pump(0.05)


def _type_keys(session, text):
    for ch in text:
        session.tap(ord(ch))  # ASCII keysyms equal their code points


def _paste(session, text):
    terminal = is_terminal(focused_app())
    session.enable_clipboard()
    old = session.read_old()
    data = text.encode("utf-8")
    offer = {m: data for m in TEXT_MIMES}
    offer[SECRET_HINT] = b"secret"
    try:
        session.own(offer)
        session.pump(0.15)  # Mutter's clipboard manager copies the new text first; that's not the paste
        session.requests = 0
        held = [KEY_CTRL] + ([KEY_SHIFT] if terminal else [])
        for k in held:
            session.key(k, True)
        try:
            session.tap(KEY_V)
        finally:
            for k in reversed(held):
                session.key(k, False)
        session.pump(PASTE_WAIT, lambda: session.requests > 0)
        served = session.requests > 0
        if served:
            session.pump(PASTE_GRACE)
    finally:
        # Put the old clipboard back (or an empty one), so the dictated text doesn't stay on it.
        restore = old or {m: b"" for m in TEXT_MIMES[:2]}
        session.own(restore)
        session.pump(0.15)  # the clipboard manager takes its copy now, which outlives the session
    if not served:
        raise TypingError("paste_unserved", "the focused window didn't take the paste")


def type_text(text, trailing_space=True):
    """Types text into the focused window and returns what was typed. Never sends Enter."""
    text = clean(text)
    if not text:
        return ""
    if trailing_space:
        text += " "  # so back-to-back dictations don't run together
    session = _Session()
    session.call("Start")
    try:
        if is_plain(text):
            _type_keys(session, text)
        else:
            _paste(session, text)
    finally:
        session.close()
    return text
