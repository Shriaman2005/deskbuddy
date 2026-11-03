"""Text cleaning shared by the typing backends (typer.py on Linux, platforms/windows.py, macos.py): never a newline or a tab."""
import unicodedata

# Typographic punctuation whisper likes, mapped so ordinary English stays plain ASCII.
ASCII = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", " ": " "}


def clean(text):
    """One line, typographic punctuation made plain. Unicode letters stay."""
    return " ".join("".join(ASCII.get(ch, ch) for ch in text).split())


def is_plain(text):
    return all(0x20 <= ord(ch) < 0x7F for ch in text)


def typable(text):
    """text as one line with no control characters (a U+0008 sent as a Unicode "key" would act as Backspace).
    For the backends that type Unicode key events (Windows, macOS)."""
    return clean("".join(ch for ch in text if ch.isspace() or unicodedata.category(ch) != "Cc"))


def utf16_units(text):
    """The UTF-16 code units of text (a character outside the BMP is two), lone surrogates dropped."""
    data = text.encode("utf-16-le", "ignore")
    return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
