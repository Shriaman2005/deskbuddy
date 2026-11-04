#!/data/data/com.termux/files/usr/bin/bash
# One-time Termux setup for the desk buddy, run inside Termux on the phone. Either:
#   curl -fsS http://<laptop>:8766/<token>/setup.sh | bash   (pairing from the dashboard: runs this with the bundle dir)
#   bash /sdcard/Download/deskbuddy-setup/setup.sh            (the old way: files copied to /sdcard by hand)
# $1 / SRC = a folder holding phone/ and authorized_keys.
SRC=${1:-/sdcard/Download/deskbuddy-setup}
[ -d "$SRC/phone" ] && [ -f "$SRC/authorized_keys" ] || { echo "[setup] $SRC needs phone/ and authorized_keys" >&2; exit 1; }
exec > >(tee "$SRC/setup.log") 2>&1
set -e
echo "[setup] started $(date)"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y -o Dpkg::Options::=--force-confnew upgrade
apt-get -y -o Dpkg::Options::=--force-confnew install python openssh termux-api procps pulseaudio

# ssh: the laptop's key only, and nothing it doesn't need. It uses a shell (deploy.sh, doctor.py) and a remote
# forward (-R 8765, the tunnel); no passwords, no agent/X11/tun, no local forwards into the phone, -R on loopback only.
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cp "$SRC/authorized_keys" ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
CONF=$PREFIX/etc/ssh/sshd_config
KEYS='PasswordAuthentication|KbdInteractiveAuthentication|ChallengeResponseAuthentication|PubkeyAuthentication|AuthenticationMethods|PermitEmptyPasswords|AllowTcpForwarding|GatewayPorts|AllowAgentForwarding|X11Forwarding|PermitTunnel|MaxAuthTries|LoginGraceTime|MaxStartups|ClientAliveInterval|ClientAliveCountMax'
sed -i -E "/^#?[[:space:]]*($KEYS)[[:space:]]/d" "$CONF"
cat >>"$CONF" <<'SSHD'
PubkeyAuthentication yes
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
AllowTcpForwarding remote
GatewayPorts no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
MaxAuthTries 3
LoginGraceTime 20
MaxStartups 4:50:10
ClientAliveInterval 15
ClientAliveCountMax 3
SSHD
sshd -t  # a broken config would lock the laptop out: stop here instead (set -e)

# buddy files + autostart (Termux:Boot if installed, otherwise whenever Termux opens) + chip-start / chip-stop / chip-restart
mkdir -p ~/deskbuddy ~/.termux/boot
cp -r "$SRC/phone/." ~/deskbuddy/
chmod +x ~/deskbuddy/services.sh ~/deskbuddy/server.py ~/deskbuddy/chip-start ~/deskbuddy/chip-stop ~/deskbuddy/chip-restart ~/deskbuddy/stt-setup.sh
ln -sf ~/deskbuddy/chip-start ~/deskbuddy/chip-stop ~/deskbuddy/chip-restart "$PREFIX/bin/"   # deploys replace the targets, so these stay current
printf '#!/data/data/com.termux/files/usr/bin/bash\nexec ~/deskbuddy/services.sh\n' >~/.termux/boot/deskbuddy
chmod +x ~/.termux/boot/deskbuddy
grep -q "deskbuddy/services.sh" ~/.bashrc 2>/dev/null || echo '~/deskbuddy/services.sh >/dev/null 2>&1' >>~/.bashrc

pkill -f deskbuddy/server.py || true
~/deskbuddy/services.sh
sleep 2
pgrep -a sshd && pgrep -af deskbuddy/server.py

# Termux:API is a separate app (F-Droid, same source as Termux): the battery reading, torch and speech go through it.
# Its first call can take a few seconds (it starts the app), so the answer is waited for, not assumed.
if timeout 25 termux-battery-status 2>/dev/null | grep -q percentage; then
  echo "[setup] Termux:API answers"
else
  echo "[setup] !! Termux:API did not answer. Install the Termux:API app from F-Droid (same source as Termux), open it once,"
  echo "[setup]    then check with: termux-battery-status   (Chip works without it but shows no battery, torch or voice)"
fi
echo
echo "[setup] Android permissions (Settings → Apps → ...), granted by you, never by this script:"
echo "[setup]   Termux → Permissions → Microphone                dictation (hold with two fingers)"
echo "[setup]   Termux → Notifications: allowed                  its notification holds the wake lock; its Exit stops Chip"
echo "[setup]   Termux → Battery: Unrestricted                   so Android doesn't suspend the link when the screen is off"
echo "[setup]   Termux:API → Modify system settings              ONLY on a phone that is Chip's own screen, for brightness control"
echo "[setup]   Termux:Boot and kiFOSSk are optional: only for an always-on phone (start at boot, kiosk). Otherwise open"
echo "[setup]   Termux to start Chip (chip-start / chip-stop), and open http://127.0.0.1:8080 in Chrome."
echo "[setup]   Offline dictation on the phone: bash ~/deskbuddy/stt-setup.sh (optional, builds whisper.cpp, ~10 minutes)"
echo
# the pairing code: type it into the laptop's dashboard (it pins only the key that matches; never type it anywhere else)
FP=$(ssh-keygen -lf "$PREFIX/etc/ssh/ssh_host_ed25519_key.pub" | cut -d' ' -f2)
CODE=${FP#SHA256:}; CODE=${CODE:0:16}
echo "[setup] this phone's ssh key: $FP"
echo
echo "    PAIRING CODE:  ${CODE:0:4} ${CODE:4:4} ${CODE:8:4} ${CODE:12:4}"
echo "    (type it on the laptop's dashboard; capitals matter)"
echo
echo "[setup] done $(date)"
touch "$SRC/setup.done"

# After the code is typed on the laptop, the laptop sends Chip's files (~/deskbuddy/.chip-hash is written last).
# Wait for that, then show one clear next step. Gives up after 15 minutes; it only prints, nothing else depends on it.
MARK="$SRC/.code-shown"; touch "$MARK"
echo "[setup] waiting for you to type the code on the laptop (this window can stay open)..."
for _ in $(seq 1 450); do
  [ "$HOME/deskbuddy/.chip-hash" -nt "$MARK" ] && break
  sleep 2
done
if [ "$HOME/deskbuddy/.chip-hash" -nt "$MARK" ]; then
  sleep 3   # let the face server finish restarting
  echo
  echo "  ╔══════════════════════════════════════════════════════════╗"
  echo "  ║   ✓  CONNECTED. Chip is installed on this phone.         ║"
  echo "  ╠══════════════════════════════════════════════════════════╣"
  echo "  ║                                                          ║"
  echo "  ║   NEXT: open Chrome on this phone and go to              ║"
  echo "  ║                                                          ║"
  echo "  ║         http://127.0.0.1:8080                            ║"
  echo "  ║                                                          ║"
  echo "  ║   (long-press the line above to copy it, then paste it   ║"
  echo "  ║    into Chrome's address bar)                            ║"
  echo "  ║                                                          ║"
  echo "  ║   Then Chrome ⋮ menu → Install app (or Add to Home       ║"
  echo "  ║   screen), so Chip opens full screen.                    ║"
  echo "  ║                                                          ║"
  echo "  ║   Keep Termux open in the background.                    ║"
  echo "  ║   Start Chip later: chip-start     Stop it: chip-stop    ║"
  echo "  ╚══════════════════════════════════════════════════════════╝"
  echo
else
  echo "[setup] Nothing arrived from the laptop. Type the code on its dashboard (Add phone), or run this again."
fi
