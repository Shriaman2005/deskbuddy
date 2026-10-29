#!/data/data/com.termux/files/usr/bin/bash
# One-time Termux setup for the desk buddy. Copied to the phone by the laptop and run inside Termux:
#   bash /sdcard/Download/deskbuddy-setup/setup.sh
SRC=/sdcard/Download/deskbuddy-setup
exec > >(tee "$SRC/setup.log") 2>&1
set -e
echo "[setup] started $(date)"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y -o Dpkg::Options::=--force-confnew upgrade
apt-get -y -o Dpkg::Options::=--force-confnew install python openssh termux-api procps

# ssh: key login only, using the laptop's public key
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cp "$SRC/authorized_keys" ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
CONF=$PREFIX/etc/ssh/sshd_config
sed -i -E '/^#?(PasswordAuthentication|ClientAliveInterval|ClientAliveCountMax) /d' "$CONF"
printf 'PasswordAuthentication no\nClientAliveInterval 15\nClientAliveCountMax 3\n' >>"$CONF"  # drop dead tunnels fast

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
echo "[setup] done $(date)"
touch "$SRC/setup.done"
