#!/usr/bin/env python3
"""The dashboard's Update now for a Chip folder that came from a ZIP (updates.py): a release ZIP is checked and
unpacked over the folder, bad ZIPs are refused and leave the folder as it was. No network: CHIP_UPDATE_ZIP-style
file:// URL, temp folders only.
  python3 -I laptop/tests/test_update_zip.py"""
import io
import os
import stat
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ["CHIP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="chip-upd-cfg-")
os.environ["CHIP_DATA_DIR"] = tempfile.mkdtemp(prefix="chip-upd-data-")
import updates  # noqa: E402

failed = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"), flush=True)
    if not ok:
        failed.append(name)


def make_zip(files, top="deskbuddy-1.9.0/", links=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            info = zipfile.ZipInfo(top + name)
            info.external_attr = ((0o755 if name.endswith(".sh") else 0o644) | stat.S_IFREG) << 16
            z.writestr(info, text)
        for name in links:
            info = zipfile.ZipInfo(top + name)
            info.external_attr = (0o777 | stat.S_IFLNK) << 16
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


def two_folders():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for top in ("deskbuddy-1.9.0/", "other/"):
            for name, text in NEW.items():
                z.writestr(top + name, text)
    return buf.getvalue()


NEW = {"VERSION": "1.9.0\n", "laptop/bridge.py": "# new bridge\n", "laptop/requirements.txt": "psutil\n",
       "deploy.sh": "#!/bin/sh\n", "phone/www/new.js": "// added in 1.9.0\n"}


def old_folder():
    root = tempfile.mkdtemp(prefix="chip-upd-root-")
    for name, text in {"VERSION": "1.0.0\n", "laptop/bridge.py": "# old bridge\n", "laptop/requirements.txt": "psutil\n",
                       "deploy.sh": "#!/bin/sh\n", "laptop/gone.py": "# removed upstream\n"}.items():
        path = os.path.join(root, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    return root


def read(root, name):
    with open(os.path.join(root, *name.split("/"))) as f:
        return f.read()


# a good ZIP
root = old_folder()
n = updates.unpack_over(root, make_zip(NEW), "v1.9.0")
check("unpacks every file", n == len(NEW), n)
check("VERSION is the new one", read(root, "VERSION").strip() == "1.9.0")
check("files are replaced and added", read(root, "laptop/bridge.py") == "# new bridge\n" and
      read(root, "phone/www/new.js").startswith("// added"))
check("a file the release removed stays", os.path.exists(os.path.join(root, "laptop", "gone.py")))
check("no staging folder left", not os.path.exists(os.path.join(root, updates.STAGING)))
if os.name != "nt":
    check("deploy.sh stays executable", os.access(os.path.join(root, "deploy.sh"), os.X_OK))

# bad ZIPs: refused, folder untouched
bad = {
    "a path out of the folder": make_zip({**NEW, "../evil.py": "x"}),
    "a link": make_zip(NEW, links=("laptop/link.py",)),
    "another version than the tag": make_zip({**NEW, "VERSION": "1.8.0\n"}),
    "two folders": two_folders(),
    "no Chip folder": make_zip({"VERSION": "1.9.0\n", "README.md": "hi"}),
    "not a ZIP": b"<html>rate limited</html>",
}
for name, data in bad.items():
    root = old_folder()
    try:
        updates.unpack_over(root, data, "v1.9.0")
        check(f"refuses {name}", False, "no error")
    except updates.ZipUpdateError:
        check(f"refuses {name}", read(root, "VERSION").strip() == "1.0.0"
              and not os.path.exists(os.path.join(os.path.dirname(root), "evil.py")), "folder changed")

# the whole Update now path: Updater.apply on a ZIP folder, the ZIP from a file:// URL
root = old_folder()
zpath = os.path.join(tempfile.mkdtemp(prefix="chip-upd-zip-"), "v1.9.0.zip")
with open(zpath, "wb") as f:
    f.write(make_zip(NEW))
updates.ROOT, updates.VERSION_FILE = root, os.path.join(root, "VERSION")
updates.REQUIREMENTS = os.path.join(root, "laptop", "requirements.txt")
updates.ZIP_URL = "file://" + zpath.replace("\\", "/").replace("v1.9.0", "{tag}")
if os.name == "nt":
    updates.ZIP_URL = "file:///" + zpath.replace("\\", "/").replace("v1.9.0", "{tag}")
u = updates.Updater(lambda: {"updateCheck": True})
u.latest = {"tag": "v1.9.0"}
check("a ZIP folder is mode zip", u.state()["mode"] == "zip")
answer, code = u.apply()
check("Update now works for a ZIP folder", code == 200 and answer.get("version") == "1.9.0", (code, answer))
answer, code = u.apply()
check("then Chip is up to date", code == 409 and answer.get("error") == "no update", (code, answer))

print("PASS" if not failed else f"{len(failed)} FAILED: {failed}")
sys.exit(1 if failed else 0)
