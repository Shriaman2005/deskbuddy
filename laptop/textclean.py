"""Text cleaning shared by the typing backends (typer.py on Linux, platforms/windows.py, macos.py): never a newline or a tab."""

# Typographic punctuation whisper likes, mapped so ordinary English stays plain ASCII.
ASCII = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "\u00a0": " "}


def clean(text):
    """One line, typographic punctuation made plain. Unicode letters stay."""
    return " ".join("".join(ASCII.get(ch, ch) for ch in text).split())


def is_plain(text):
    return all(0x20 <= ord(ch) < 0x7F for ch in text)
