"""Types text into whatever window has keyboard focus, via GNOME's remote-desktop D-Bus API.

Works on GNOME Wayland without root or extra packages (it's what GNOME Remote Desktop uses).
"""
import unicodedata

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "org.gnome.Mutter.RemoteDesktop"


# GNOME can only type characters on the keyboard layout, so map the rest to plain ASCII.
_ASCII = {"₹": "Rs ", "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "\u00a0": " "}


def _asciify(text):
    text = "".join(_ASCII.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKD", text)  # é -> e + accent, then the accent is dropped below
    return "".join(ch for ch in text if 0x20 <= ord(ch) < 0x7F)


def type_text(text, trailing_space=True):
    """Types text one key at a time. Never sends Enter: newlines and tabs become spaces."""
    text = " ".join(_asciify(text).split())
    if not text:
        return ""
    if trailing_space:
        text += " "  # so back-to-back dictations don't run together
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    path = bus.call_sync(BUS_NAME, "/org/gnome/Mutter/RemoteDesktop", BUS_NAME, "CreateSession",
                         None, GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]

    def call(method, args=None):
        bus.call_sync(BUS_NAME, path, BUS_NAME + ".Session", method, args, None, Gio.DBusCallFlags.NONE, 5000, None)

    call("Start")
    try:
        for ch in text:
            ks = ord(ch)  # ASCII keysyms equal their code points
            call("NotifyKeyboardKeysym", GLib.Variant("(ub)", (ks, True)))
            call("NotifyKeyboardKeysym", GLib.Variant("(ub)", (ks, False)))
    finally:
        call("Stop")
    return text
