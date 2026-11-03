#!/usr/bin/env python3
"""Windows only. Types through the running bridge's POST /type into a real window and reads the window's text back:
Notepad (or --app tk, a Tk text box: no clipboard needed, for runners where Notepad won't start), then checks the
text came out as dictated, one line, no Enter.
  python -I -X utf8 laptop/tests/test_typing_windows.py [--app notepad|tk]
Exit status: 0 passed, 1 failed, 77 no usable desktop here (no window could be brought to the front, or the bridge
says the screen is locked): CI turns that one into a warning instead of a failure."""
import ctypes
import http.client
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # python -I skips the script's folder
from platforms import proc  # noqa: E402
from platforms import windows  # noqa: E402

SPOKEN = "héllo wörld नमस्ते 😀 a\nb"
EXPECT = "héllo wörld नमस्ते 😀 a b"
PORT = int(os.environ.get("CHIP_PORT") or 8765)
NO_DESKTOP = 77

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32.GetForegroundWindow.restype = ctypes.c_void_p
u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
u32.FindWindowW.argtypes, u32.FindWindowW.restype = [ctypes.c_wchar_p, ctypes.c_wchar_p], ctypes.c_void_p
u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
u32.AttachThreadInput.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int]
u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
u32.OpenClipboard.argtypes = [ctypes.c_void_p]
u32.GetClipboardData.argtypes, u32.GetClipboardData.restype = [ctypes.c_uint], ctypes.c_void_p
k32.GlobalLock.argtypes, k32.GlobalLock.restype = [ctypes.c_void_p], ctypes.c_void_p
k32.GlobalUnlock.argtypes = [ctypes.c_void_p]


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("flags", ctypes.c_uint32)] + [
        (n, ctypes.c_void_p) for n in ("active", "focus", "capture", "menu", "move", "caret")] + [("rc", RECT)]


u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
u32.GetGUIThreadInfo.argtypes = [ctypes.c_uint32, ctypes.POINTER(GUITHREADINFO)]
u32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
u32.SendMessageW.restype = ctypes.c_ssize_t


def focus_info():
    """(class of the window that has the keyboard focus, its text via WM_GETTEXT) for the foreground thread."""
    fg = u32.GetForegroundWindow()
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    tid = u32.GetWindowThreadProcessId(fg, None)
    if not u32.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.focus:
        return "(no focus window)", ""
    cls = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(info.focus, cls, 256)
    buf = ctypes.create_unicode_buffer(4096)
    u32.SendMessageW(info.focus, 0x000D, 4096, ctypes.addressof(buf))  # WM_GETTEXT
    return cls.value, buf.value


def click_inside(hwnd):
    """A click in the middle of the window, so its text area has the keyboard focus."""
    r = RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    u32.SetCursorPos((r.l + r.r) // 2, (r.t + r.b) // 2)
    u32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    u32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    time.sleep(0.5)


def log(text):
    print(text, flush=True)


def bring_to_front(hwnd):
    """SetForegroundWindow is refused to background programs; attaching to the current foreground thread's input
    queue (and a harmless Alt tap) lets it through."""
    u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = u32.GetForegroundWindow()
    mine = k32.GetCurrentThreadId()
    theirs = u32.GetWindowThreadProcessId(fg, None) if fg else 0
    if theirs and theirs != mine:
        u32.AttachThreadInput(mine, theirs, True)
    u32.keybd_event(0x12, 0, 0, 0)       # Alt down/up
    u32.keybd_event(0x12, 0, 2, 0)
    ok = u32.SetForegroundWindow(hwnd)
    if theirs and theirs != mine:
        u32.AttachThreadInput(mine, theirs, False)
    time.sleep(0.5)
    return bool(ok) and u32.GetForegroundWindow() == hwnd


def chord(*vks):
    """Presses the keys together (Ctrl+A) and lets go."""
    for vk in vks:
        u32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        u32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.4)


def clipboard_text():
    for _ in range(20):
        if u32.OpenClipboard(None):
            try:
                h = u32.GetClipboardData(13)  # CF_UNICODETEXT
                if not h:
                    return ""
                p = k32.GlobalLock(h)
                try:
                    return ctypes.wstring_at(p)
                finally:
                    k32.GlobalUnlock(h)
            finally:
                u32.CloseClipboard()
        time.sleep(0.1)
    return None


def post_type(text):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    try:
        conn.request("POST", "/type", body=text.encode("utf-8"), headers={"Host": f"127.0.0.1:{PORT}"})
        r = conn.getresponse()
        return r.status, json.loads(r.read().decode("utf-8", "replace"))
    finally:
        conn.close()


def wait_window(cls, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        hwnd = u32.FindWindowW(cls, None)
        if hwnd:
            return hwnd
        time.sleep(0.5)
    return None


def run_notepad():
    proc.run("taskkill", "/F", "/IM", "notepad.exe")
    proc.popen(["notepad.exe"], text=False, detached=True, stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL)
    hwnd = wait_window("Notepad")
    if not hwnd:
        log("no Notepad window appeared in 30 s")
        return NO_DESKTOP, None
    time.sleep(2)  # the editor inside it takes a moment
    return hwnd, lambda: (chord(0x11, 0x41), chord(0x11, 0x43), clipboard_text())[2]


def run_tk():
    import tkinter
    root = tkinter.Tk()
    box = tkinter.Text(root, width=60, height=5)
    box.pack()
    root.update()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
    box.focus_force()
    root.update()

    def read():
        for _ in range(10):
            root.update()
            time.sleep(0.1)
        return box.get("1.0", "end-1c")
    return hwnd, read, root


def main():
    app = sys.argv[sys.argv.index("--app") + 1] if "--app" in sys.argv else "notepad"
    root = None
    if app == "tk":
        hwnd, read, root = run_tk()
    else:
        hwnd, read = run_notepad()
        if read is None:
            return NO_DESKTOP
    try:
        if not bring_to_front(hwnd):
            log("could not bring the window to the front: no usable desktop here")
            return NO_DESKTOP
        if app != "tk":
            click_inside(hwnd)
        log("focus before typing: %s" % (focus_info()[0],))
        status, answer = post_type(SPOKEN)
        log(f"POST /type -> {status} {json.dumps(answer, ensure_ascii=True)}")
        if status == 423:
            return NO_DESKTOP
        if status != 200 or not answer.get("ok"):
            return 1
        time.sleep(1)
        log("focus after typing: %s, its text: %r" % focus_info())
        got = read()
        log(f"window text: {got!r}")
        ok = got is not None and got.strip() == EXPECT
        log("PASS" if ok else f"FAIL: expected {EXPECT!r}")
        return 0 if ok else 1
    finally:
        if root is not None:
            root.destroy()
        else:
            proc.run("taskkill", "/F", "/IM", "notepad.exe")


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Windows only")
    sys.exit(main())
