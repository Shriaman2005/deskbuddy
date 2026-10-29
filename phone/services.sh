#!/data/data/com.termux/files/usr/bin/bash
# Starts the desk buddy's background services and the supervisor that keeps them running.
# Called by Termux:Boot at startup and by every new Termux session (~/.bashrc).
termux-wake-lock
bash ~/deskbuddy/supervisor.sh once >>~/deskbuddy/supervisor.log 2>&1
if ! pgrep -f "[d]eskbuddy/supervisor.sh" >/dev/null; then
  nohup bash ~/deskbuddy/supervisor.sh >>~/deskbuddy/supervisor.log 2>&1 &
fi
