#!/data/data/com.termux/files/usr/bin/bash
# Keeps the desk buddy's Termux side alive: sshd (the laptop's tunnel lands here) and server.py (the face page).
# `supervisor.sh once` fixes whatever is down and exits; with no argument it repeats every 10 s.
# Started by services.sh (Termux:Boot at startup, and every new Termux session).
ensure() {
  pgrep -x sshd >/dev/null || { echo "$(date '+%F %T') sshd was down"; sshd; }
  if ! pgrep -f "[d]eskbuddy/server.py" >/dev/null; then  # [d] keeps pgrep from matching its own caller
    echo "$(date '+%F %T') server.py was down"
    nohup python ~/deskbuddy/server.py >>~/deskbuddy/server.log 2>&1 &
  fi
}
ensure
[ "$1" = once ] && exit 0
while sleep 10; do ensure; done
