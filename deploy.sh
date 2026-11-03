#!/usr/bin/env bash
# Copies phone/ to the phone's Termux over the pinned ssh and restarts Chip's server there (laptop/deploy.py).
exec python3 -I -X utf8 "$(dirname "$(readlink -f "$0")")/laptop/deploy.py" "$@"
