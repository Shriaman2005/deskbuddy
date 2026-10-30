#!/usr/bin/env bash
# Sets the laptop side up so it survives reboots: the bridge runs as a systemd user service, started at boot
# (linger) even before you log in. Safe to run again.
set -euo pipefail
here="$(dirname "$(readlink -f "$0")")"
unit="$HOME/.config/systemd/user/deskbuddy-bridge.service"
mkdir -p "$(dirname "$unit")"
cat >"$unit" <<EOF
[Unit]
Description=Desk buddy bridge (laptop stats and controls for the phone)

[Service]
ExecStart=/usr/bin/python3 -I $here/bridge.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
# Eyes follow the cursor: the GNOME Shell extension that reports the pointer position (see bridge.py Gaze)
ext="$here/gnome-extension/chip-gaze@deskbuddy"
mkdir -p "$HOME/.local/share/gnome-shell/extensions"
ln -sfn "$ext" "$HOME/.local/share/gnome-shell/extensions/chip-gaze@deskbuddy"
gnome-extensions enable chip-gaze@deskbuddy || true
echo "Eyes follow the cursor: the chip-gaze extension is linked. On Wayland GNOME loads a new extension only at login,"
echo "so log out and back in once (and run this script again after that if it says it isn't enabled yet)."

systemctl --user daemon-reload
systemctl --user enable --now deskbuddy-bridge
systemctl --user restart deskbuddy-bridge
loginctl enable-linger "$USER"
echo "Bridge installed. Check everything with: python3 -I $here/doctor.py"
