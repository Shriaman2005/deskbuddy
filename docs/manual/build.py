#!/usr/bin/env python3
"""Builds chip-manual-windows|macos|linux.pdf from manual.html with headless Chrome or Chromium. The bridge serves
the one for its own OS at /manual.pdf. Run after editing manual.html: python3 -I docs/manual/build.py"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
K = '<span class="key">{}</span>'
OSES = {
    "windows": {"OS": "Windows", "PY": "py -3", "CHIP": r"laptop\chip.py", "ENTER": "Enter",
                "SETUP": r"py -3 laptop\install.py --repair",
                "OPEN": "Open the folder in File Explorer, click the address bar, type <code>cmd</code>, press "
                        + K.format("Enter") + ".",
                "PASTE": K.format("Ctrl") + " + " + K.format("V") + " or right-click",
                "EXTRA": """<div class="task"><h2>Offline dictation <small>(downloads about 300 MB once)</small></h2>"""
                         + r"""<span class="cmd">py -3 laptop\install.py --stt</span></div>"""},
    "macos": {"OS": "macOS", "PY": "python3", "CHIP": "laptop/chip.py", "ENTER": "Return",
              "SETUP": "python3 laptop/install.py --repair", "EXTRA": "",
              "OPEN": "Open Terminal, type <code>cd</code> and a space, drag the folder in, press "
                      + K.format("Return") + ".",
              "PASTE": K.format("Command") + " + " + K.format("V")},
    "linux": {"OS": "Linux", "PY": "python3", "CHIP": "laptop/chip.py", "ENTER": "Enter",
              "SETUP": "laptop/install.sh", "EXTRA": "",
              "OPEN": "Open the folder in Files, right-click an empty spot, choose <b>Open in Terminal</b>.",
              "PASTE": K.format("Ctrl") + " + " + K.format("Shift") + " + " + K.format("V")},
}

chrome = next((p for p in map(shutil.which, ("google-chrome", "chromium", "chromium-browser")) if p), None)
if not chrome:
    sys.exit("needs Google Chrome or Chromium")
with open(os.path.join(HERE, "manual.html"), encoding="utf-8") as f:
    template = f.read()
for name, words in OSES.items():
    html = template
    for k, v in words.items():
        html = html.replace("{{" + k + "}}", v)
    # written next to the template so ../../laptop/logo resolves; removed right after
    fd, src = tempfile.mkstemp(suffix=".html", dir=HERE)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    out = os.path.join(HERE, f"chip-manual-{name}.pdf")
    try:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf=" + out,
                        "file://" + src], check=True, stderr=subprocess.DEVNULL)
    finally:
        os.remove(src)
    print(out)
