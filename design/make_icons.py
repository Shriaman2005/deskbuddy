#!/usr/bin/env python3
"""Renders the web app icons (phone/www/icons/icon-192.png, icon-512.png) from Chip's own face in pack.json: the
real player draws a neutral face in headless Chrome, and this crops it to the face and scales it by whole numbers
(1x for 192 px, 3x for 512 px, so every sprite pixel stays a whole number of icon pixels). No new art.
Run: python3 -I design/make_icons.py   (needs google-chrome; serves phone/www on a spare local port for a moment)"""
import functools
import http.server
import os
import struct
import subprocess
import sys
import tempfile
import threading
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(ROOT, "phone", "www")
ZOOM = 2   # the face camera draws each pack pixel as 2x2 screen pixels (320x180 view of a 160x90 world)
SIZES = {192: 1, 512: 3}   # icon px -> screen-px-per-pack-pixel


def read_png(path):
    data = open(path, "rb").read()
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and ctype in (2, 6) and interlace == 0, "unexpected screenshot format"
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    bpp = 3 if ctype == 2 else 4
    raw, rows, prev = zlib.decompress(idat), [], bytearray(w * bpp)
    for y in range(h):
        f, line = raw[y * (w * bpp + 1)], bytearray(raw[y * (w * bpp + 1) + 1:(y + 1) * (w * bpp + 1)])
        for i in range(len(line)):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x * bpp:x * bpp + 3]) for x in range(w)])
        prev = line
    return rows


def write_png(path, rows):
    h, w = len(rows), len(rows[0])
    raw = b"".join(b"\0" + b"".join(bytes(p) for p in row) for row in rows)
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                           chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def screenshot(out):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=WWW))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/pack-test.html?mood=neutral&t=1&gaze=0,0"
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(["google-chrome", "--headless=new", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--user-data-dir={profile}", "--window-size=320,180", "--virtual-time-budget=3000",
                        f"--screenshot={out}", url], check=True, capture_output=True)
    server.shutdown()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        shot = os.path.join(tmp, "face.png")
        screenshot(shot)
        rows = read_png(shot)
    bg = rows[0][0]
    # back to pack pixels: each is a ZOOM x ZOOM block of one colour (a block that isn't means the camera isn't whole-number)
    world = []
    for y in range(0, len(rows), ZOOM):
        line = []
        for x in range(0, len(rows[0]), ZOOM):
            block = {rows[y + j][x + i] for j in range(ZOOM) for i in range(ZOOM)}
            if len(block) != 1:
                sys.exit(f"pack pixel at {x // ZOOM},{y // ZOOM} is not a whole ZOOM block: the camera moved")
            line.append(block.pop())
        world.append(line)
    ink = [(x, y) for y, line in enumerate(world) for x, p in enumerate(line) if p != bg]
    x0, x1 = min(x for x, _ in ink), max(x for x, _ in ink)
    y0, y1 = min(y for _, y in ink), max(y for _, y in ink)
    face = [line[x0:x1 + 1] for line in world[y0:y1 + 1]]
    out = os.path.join(WWW, "icons")
    os.makedirs(out, exist_ok=True)
    for size, k in SIZES.items():
        fw, fh = len(face[0]) * k, len(face) * k
        if fw > size * 0.8:
            sys.exit(f"face is {fw} px wide: too big for a {size} px maskable icon")
        left, top = (size - fw) // 2, (size - fh) // 2
        img = [[bg] * size for _ in range(size)]
        for y, line in enumerate(face):
            for x, p in enumerate(line):
                for j in range(k):
                    for i in range(k):
                        img[top + y * k + j][left + x * k + i] = p
        write_png(os.path.join(out, f"icon-{size}.png"), img)
        print(f"icon-{size}.png: face {len(face[0])}x{len(face)} pack px at {k}x, background #{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}")


if __name__ == "__main__":
    main()
