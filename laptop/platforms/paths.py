"""Where Chip keeps its files, the same on every OS: settings and keys in ~/.config/deskbuddy, downloads (speech
models, whisper-cli) in ~/.local/share/deskbuddy. CHIP_CONFIG_DIR / CHIP_DATA_DIR move them (selftest, CI)."""
import os

CONFIG_DIR = os.environ.get("CHIP_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".config", "deskbuddy")
DATA_DIR = os.environ.get("CHIP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share", "deskbuddy")

LAPTOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo's laptop/ folder
REPO = os.path.dirname(LAPTOP)


def config(*parts):
    return os.path.join(CONFIG_DIR, *parts)


def data(*parts):
    return os.path.join(DATA_DIR, *parts)


def laptop(*parts):
    return os.path.join(LAPTOP, *parts)
