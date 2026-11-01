#!/usr/bin/env bash
# Copies ~/deskbuddy/phone to the phone's Termux over ssh and restarts the buddy server.
# The face on the phone notices the new version and reloads itself within a minute.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/phone"
ip=$(python3 -I -c 'import json, os; print(json.load(open(os.path.expanduser("~/.config/deskbuddy/state.json")))["ip"])')
# sshd's port on the phone: the bridge's sshPort setting (8022 unless changed on the dashboard)
port=$(python3 -I -c 'import json, os
try: print(int(json.load(open(os.path.expanduser("~/.config/deskbuddy/settings.json")))["values"].get("sshPort", 8022)))
except (OSError, ValueError, KeyError): print(8022)')
date +%s >www/version.txt
# the phone's ssh host key is pinned by the bridge (laptop/bridge.py) under an alias, so a new IP is fine
tar cz --exclude=setup.sh --exclude=__pycache__ . | ssh -p "$port" -o BatchMode=yes -o HostKeyAlias=chip-phone \
  -o UserKnownHostsFile="$HOME/.config/deskbuddy/known_hosts" -o GlobalKnownHostsFile=/dev/null \
  -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o ForwardAgent=no -o ForwardX11=no -o ClearAllForwardings=yes "$ip" \
  'tar xz -C ~/deskbuddy && { pkill -f "[d]eskbuddy/server.py"; bash ~/deskbuddy/services.sh; }'
echo "Deployed to $ip"
