"""The one way Chip starts other programs: no console window on Windows, UTF-8 text, a timeout on every run."""
import os
import subprocess
from subprocess import DEVNULL, PIPE, STDOUT, SubprocessError, TimeoutExpired  # noqa: F401  (re-exported for callers)

_FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
_TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}


def complete(cmd, timeout, input=None, text=True, check=False):
    """subprocess.run with output captured; text=False for bytes in and out. Raises like subprocess.run."""
    return subprocess.run(cmd, capture_output=True, timeout=timeout, input=input, check=check,
                          **(_TEXT if text else {}), **_FLAGS)


def run(*cmd, timeout=6, input=None):
    """The command's stdout, stripped, or "" if it is missing, fails to start or takes longer than timeout."""
    try:
        return complete(cmd, timeout, input=input).stdout.strip()
    except (OSError, TimeoutExpired):
        return ""


def popen(cmd, text=True, **kw):
    """subprocess.Popen for long-running helpers (ssh, busctl monitor, parec); text=False for raw bytes."""
    return subprocess.Popen(cmd, **(_TEXT if text else {}), **_FLAGS, **kw)
