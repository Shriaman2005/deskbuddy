"""The one way Chip starts other programs: no console window on Windows, UTF-8 text, a timeout on every run;
on Windows the long-running helpers end when Chip ends."""
import ctypes
import os
import shutil
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


def which(name):
    """Full path of a program on PATH, or None. On Windows also Windows' own OpenSSH folder (System32\\OpenSSH),
    which isn't always on PATH for programs started at login."""
    found = shutil.which(name)
    if found or os.name != "nt":
        return found
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "OpenSSH", name + ".exe")
    return path if os.path.isfile(path) else None


def popen(cmd, text=True, detached=False, **kw):
    """subprocess.Popen for long-running helpers (ssh, busctl monitor, parec); text=False for raw bytes.
    detached=True: a program that outlives this one (install.py starting supervise.py); on Windows it gets no
    console and is not part of this one's process group."""
    flags = dict(_FLAGS)
    if detached and os.name == "nt":
        flags["creationflags"] |= subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    if detached and os.name == "nt":  # also leave the caller's job (OpenSSH kills its session's job when ssh ends)
        try:
            return subprocess.Popen(cmd, **(_TEXT if text else {}),
                                    **dict(flags, creationflags=flags["creationflags"] | 0x01000000), **kw)
        except PermissionError:  # the job doesn't allow breakaway: stay in it
            pass
    child = subprocess.Popen(cmd, **(_TEXT if text else {}), **flags, **kw)
    if os.name == "nt" and not detached:
        _end_with_us(child)
    return child


# ---- Windows: helpers end when Chip ends. Windows doesn't kill a program's children when it exits, so a helper left
# running by a crashed or restarted bridge lives on: an orphaned tunnel ssh keeps the phone's forwarded port, and
# every new tunnel is refused until it dies. So every helper popen() starts (not the detached ones, which must
# outlive us) goes into one job object that Windows closes, killing what is in it, when this process ends.

class _JobBasicLimits(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]


class _JobLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (144 bytes on 64-bit)
    _fields_ = [("Basic", _JobBasicLimits), ("IoCounters", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


_job = None


def _end_with_us(child):
    global _job
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes, k.CreateJobObjectW.restype = [ctypes.c_void_p, ctypes.c_wchar_p], ctypes.c_void_p
        k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        if _job is None:
            job, limits = k.CreateJobObjectW(None, None), _JobLimits()
            limits.Basic.LimitFlags = 0x2000 | 0x800  # KILL_ON_JOB_CLOSE | BREAKAWAY_OK (detached starts may leave)
            if not job or not k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                return  # 9 = JobObjectExtendedLimitInformation
            _job = job  # never closed: it closes when this process ends, and takes the helpers with it
        k.AssignProcessToJobObject(_job, int(child._handle))
    except (OSError, AttributeError, ValueError):
        pass  # as before: the helper just isn't tied to us
