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
apt-get -y -o Dpkg::Options::=--force-confnew install python openssh termux-api procps

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

# buddy files + autostart (Termux:Boot if installed, otherwise whenever Termux opens)
mkdir -p ~/deskbuddy ~/.termux/boot
cp -r "$SRC/phone/." ~/deskbuddy/
chmod +x ~/deskbuddy/services.sh ~/deskbuddy/server.py
printf '#!/data/data/com.termux/files/usr/bin/bash\nexec ~/deskbuddy/services.sh\n' >~/.termux/boot/deskbuddy
chmod +x ~/.termux/boot/deskbuddy
grep -q "deskbuddy/services.sh" ~/.bashrc 2>/dev/null || echo '~/deskbuddy/services.sh >/dev/null 2>&1' >>~/.bashrc

pkill -f deskbuddy/server.py || true
~/deskbuddy/services.sh
sleep 2
pgrep -a sshd && pgrep -af deskbuddy/server.py
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
