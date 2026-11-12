#!/usr/bin/env python3
"""Run a program inside chiptest's logged-on Windows desktop over ssh, and copy back a screenshot.

ssh on Windows has no desktop, so the program is started through a scheduled task that runs "only when the user is
logged on" (schtasks /it). Everything stays in chiptest's home (%USERPROFILE%\\chiptest-run) and is removed again.

  winshot.py shot out.png                   screenshot of the desktop
  winshot.py run "notepad.exe" [--shot out.png] [--wait 3]   start a program there, optionally screenshot after --wait s
  winshot.py ps "<powershell code>" [--shot out.png] [--wait 3]   same, but PowerShell code (hidden window)

Only for agreed test windows (docs/port/WINDOWS-REMOTE.md Rules); delete screenshots after reading.
Host: env CHIP_WIN_HOST (default ssh alias chip-win). Exit 77 = no usable desktop (nobody signed in / locked).
"""
import argparse, os, subprocess, sys, time

HOST = os.environ.get("CHIP_WIN_HOST", "chip-win")
DIR = "chiptest-run"          # relative to the ssh home
TASK = "ChipWinShot"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", HOST]

SHOT_PS = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save("$PSScriptRoot\shot.png", [System.Drawing.Imaging.ImageFormat]::Png)
$c = @{}; foreach ($x in 1..12) { foreach ($y in 1..8) { $c[$bmp.GetPixel([int]($b.Width*$x/13), [int]($b.Height*$y/9)).ToArgb()] = 1 } }
"$($b.Width)x$($b.Height) colours=$($c.Count)" | Set-Content "$PSScriptRoot\shot.txt"
"""


def ssh(cmd, check=True, inp=None):
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, input=inp, timeout=120)
    if check and r.returncode:
        sys.exit(f"ssh failed ({r.returncode}): {cmd}\n{r.stdout}{r.stderr}")
    return r


def put(local_text, name, encoding="UTF8"):
    # no scp/sftp dependency: write through stdin. A .cmd file needs ASCII: cmd reads UTF8's BOM as a command.
    ps = f"$d=Join-Path $env:USERPROFILE '{DIR}'; New-Item -ItemType Directory -Force $d | Out-Null; " \
         f"[Console]::In.ReadToEnd() | Set-Content -Encoding {encoding} (Join-Path $d '{name}')"
    ssh(f'powershell -NoProfile -Command "{ps}"', inp=local_text)


def run_in_desktop(command_line, wait):
    """Create the task (interactive token, only when logged on), run it, wait, delete it."""
    ssh(f"schtasks /delete /tn {TASK} /f", check=False)
    # The command goes in a .cmd file the task runs. Registered through PowerShell, not schtasks /create: a schtasks
    # task never starts on battery (it sits "Queued" on a laptop that isn't plugged in).
    put(f"@{command_line}\r\n", "job.cmd", "ascii")
    ps = (f"$a = New-ScheduledTaskAction -Execute cmd.exe -Argument ('/c \"' + (Join-Path $env:USERPROFILE '{DIR}\\job.cmd') + '\"'); "
          "$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited; "
          "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
          f"Register-ScheduledTask {TASK} -Action $a -Principal $p -Settings $s -Force | Out-Null; Start-ScheduledTask {TASK}")
    r = ssh(f'powershell -NoProfile -Command "{ps.replace(chr(34), chr(92) + chr(34))}"', check=False)
    if r.returncode:
        ssh(f"schtasks /delete /tn {TASK} /f", check=False)
        print("cannot start task (nobody logged on?):", r.stdout, r.stderr, file=sys.stderr)
        sys.exit(77)
    time.sleep(wait)


def cleanup():
    ssh(f"schtasks /delete /tn {TASK} /f", check=False)


def fetch_shot(out):
    run_in_desktop(f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%USERPROFILE%\\{DIR}\\shot.ps1"', 6)
    r = subprocess.run(SSH + [f'powershell -NoProfile -Command "[Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $env:USERPROFILE \'{DIR}\\shot.png\')))"'],
                       capture_output=True, text=True, timeout=120)
    if r.returncode or not r.stdout.strip():
        sys.exit(77)  # screenshot never appeared: no interactive desktop
    import base64
    info = ssh(f'powershell -NoProfile -Command "Get-Content (Join-Path $env:USERPROFILE \'{DIR}\\shot.txt\')"', check=False).stdout.strip()
    if info.endswith("colours=1"):
        ssh(f'powershell -NoProfile -Command "Remove-Item (Join-Path $env:USERPROFILE \'{DIR}\\shot.*\') -ErrorAction SilentlyContinue"', check=False)
        print(f"screenshot is one flat colour ({info}): chiptest is probably signed out/disconnected/locked", file=sys.stderr)
        sys.exit(77)
    with open(out, "wb") as f:
        f.write(base64.b64decode(r.stdout.strip()))
    ssh(f'powershell -NoProfile -Command "Remove-Item (Join-Path $env:USERPROFILE \'{DIR}\\shot.*\') -ErrorAction SilentlyContinue"', check=False)
    print("saved", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["shot", "run", "ps"])
    ap.add_argument("arg")
    ap.add_argument("--shot")
    ap.add_argument("--wait", type=float, default=3)
    a = ap.parse_args()
    try:
        # clear any stale screenshot so a failure can't return an old one
        ssh(f'powershell -NoProfile -Command "Remove-Item (Join-Path $env:USERPROFILE \'{DIR}\\shot.*\') -ErrorAction SilentlyContinue"', check=False)
        put(SHOT_PS, "shot.ps1")
        if a.mode == "shot":
            fetch_shot(a.arg)
            return
        if a.mode == "run":
            run_in_desktop(a.arg, a.wait)
        else:
            put(a.arg, "job.ps1")
            run_in_desktop(f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%USERPROFILE%\\{DIR}\\job.ps1"', a.wait)
        if a.shot:
            fetch_shot(a.shot)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
