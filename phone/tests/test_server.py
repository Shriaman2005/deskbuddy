"""PS1: the phone server answers only its own page and local programs (curl over ssh), never other web pages.

Starts phone/server.py on a free port (CHIP_PHONE_PORT) with an empty PATH, so no Termux tool, mic, torch or sound
can start even if a check let a request through. Run: python3 -I phone/tests/test_server.py
"""
import http.client
import os
import socket
import subprocess
import sys
import time

PHONE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failed = []


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port, method, path, host=None, origin=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True)
    c.putheader("Host", host or f"127.0.0.1:{port}")
    if origin:
        c.putheader("Origin", origin)
    c.endheaders()
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


def check(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f" (wanted {want})"))
    if not ok:
        failed.append(name)


def main():
    port = free_port()
    env = {"CHIP_PHONE_PORT": str(port), "PATH": "", "HOME": os.environ.get("HOME", "/nonexistent")}
    server = subprocess.Popen([sys.executable, "-E", "-s", os.path.join(PHONE, "server.py")], cwd=PHONE, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.time() + 10
        while True:
            try:
                call(port, "GET", "/api/status")
                break
            except OSError:
                if time.time() > deadline or server.poll() is not None:
                    print("server didn't start:", server.stderr.read().decode() if server.poll() is not None else "")
                    return 1
                time.sleep(0.1)
        own, other = f"http://127.0.0.1:{port}", "https://example.com"
        check("no Origin (curl): GET /api/status", call(port, "GET", "/api/status"), 200)
        check("localhost Host: GET /api/status", call(port, "GET", "/api/status", host=f"localhost:{port}"), 200)
        check("no Origin: GET / (the face page)", call(port, "GET", "/"), 200)
        check("own Origin: POST /api/alert/stop", call(port, "POST", "/api/alert/stop", origin=own), 200)
        check("localhost Origin: POST /api/alert/stop",
              call(port, "POST", "/api/alert/stop", host=f"localhost:{port}", origin=f"http://localhost:{port}"), 200)
        for path in ("/api/dictate/start", "/api/alert?torch=5", "/api/say?text=hi", "/api/torch?on=1",
                     "/api/launch?app=browser", "/api/brightness?level=10", "/api/alert/stop"):
            check(f"other Origin: POST {path}", call(port, "POST", path, origin=other), 403)
        check("Origin null: POST /api/dictate/start", call(port, "POST", "/api/dictate/start", origin="null"), 403)
        check("other Origin: GET /api/status", call(port, "GET", "/api/status", origin=other), 403)
        check("other port's Origin: POST /api/torch", call(port, "POST", "/api/torch?on=1", origin="http://127.0.0.1:1"), 403)
        for path in ("/api/status", "/api/dictate/status", "/", "/buddy.js"):
            check(f"rebinding Host: GET {path}", call(port, "GET", path, host=f"evil.example:{port}"), 403)
        check("rebinding Host: HEAD /", call(port, "HEAD", "/", host=f"evil.example:{port}"), 403)
        check("rebinding Host: POST /api/torch", call(port, "POST", "/api/torch?on=1", host=f"evil.example:{port}"), 403)
    finally:
        server.terminate()
        server.wait(5)
    print("all passed" if not failed else f"{len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
