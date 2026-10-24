#!/usr/bin/env bash
# One-time setup of ROSPOS on Lubuntu (any Ubuntu or Debian system).
#   Install:    sudo bash install-lubuntu.sh
#   Undo:       sudo bash install-lubuntu.sh --uninstall   (your data is not touched)
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run this with sudo:  sudo bash install-lubuntu.sh"; exit 1; }
U="${SUDO_USER:-}"
{ [ -n "$U" ] && [ "$U" != root ]; } || { echo "Run it with sudo from your normal user account, not as root."; exit 1; }
HOME_DIR="$(getent passwd "$U" | cut -d: -f6)"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE=/etc/systemd/system/pos.service
LAUNCHER=pos.desktop
# Never overwrite or uninstall another application's pos.service unit.
if [ -e "$SERVICE" ] && ! grep -qx 'Description=ROSPOS' "$SERVICE"; then
  echo "Refusing to modify $SERVICE: it does not belong to ROSPOS."
  exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
  systemctl disable --now pos 2>/dev/null || true
  rm -f "$SERVICE" "$HOME_DIR/.local/share/applications/$LAUNCHER" "$HOME_DIR/Desktop/$LAUNCHER" \
        /etc/systemd/logind.conf.d/pos.conf /etc/systemd/resolved.conf.d/pos-mdns.conf
  systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || true
  systemctl daemon-reload
  echo "Removed. Your data in $APP_DIR/data was not touched. Reboot to finish undoing sleep settings."
  exit 0
fi

if [ ! -f "$APP_DIR/server.py" ] || [ ! -f "$APP_DIR/index.html" ] || [ ! -d "$APP_DIR/js" ] || [ ! -f "$APP_DIR/poscore/__init__.py" ]; then
  echo "Run this from the folder that contains server.py, index.html, the js folder and the poscore package."
  exit 1
fi

echo "1/6 Installing packages (python, avahi, libnss-mdns)..."
export DEBIAN_FRONTEND=noninteractive
{ apt-get update && apt-get install -y python3 avahi-daemon libnss-mdns; } || { echo "Package install failed. Check the internet connection and try again."; exit 1; }

echo "2/6 Setting up the name pos.local ..."
sed -i 's/^#\?host-name=.*/host-name=pos/' /etc/avahi/avahi-daemon.conf
grep -q '^host-name=pos' /etc/avahi/avahi-daemon.conf || sed -i '/^\[server\]/a host-name=pos' /etc/avahi/avahi-daemon.conf
if ! grep -q '^hosts:.*mdns' /etc/nsswitch.conf; then
  cp /etc/nsswitch.conf /etc/nsswitch.conf.bak
  sed -i '/^hosts:/ s/ dns/ mdns4_minimal [NOTFOUND=return] dns/' /etc/nsswitch.conf
  grep -q '^hosts:.*mdns' /etc/nsswitch.conf || echo "  Could not edit /etc/nsswitch.conf automatically. See the README."
fi
if systemctl is-active --quiet systemd-resolved; then
  # avoid two programs answering .local lookups at the same time
  mkdir -p /etc/systemd/resolved.conf.d
  printf '[Resolve]\nMulticastDNS=no\n' > /etc/systemd/resolved.conf.d/pos-mdns.conf
  systemctl restart systemd-resolved
fi

echo "3/6 Creating the background service (starts at boot, restarts if it stops)..."
PY="$(command -v python3)"
cat > "$SERVICE" <<EOF
[Unit]
Description=ROSPOS
After=network-online.target
Wants=network-online.target

[Service]
User=$U
WorkingDirectory=$APP_DIR
Environment=POS_PORT=80
ExecStart="$PY" "$APP_DIR/server.py"
Restart=always
RestartSec=3
UMask=0077
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF

echo "4/6 Opening the firewall if one is running..."
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp && ufw allow 5353/udp
fi

read -rp "5/6 Stop the laptop from sleeping or suspending when the lid closes? Recommended if it is the store server. [y/N] " ANS
if [[ "${ANS:-}" =~ ^[Yy] ]]; then
  mkdir -p /etc/systemd/logind.conf.d
  printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n' > /etc/systemd/logind.conf.d/pos.conf
  systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  echo "  Done. The lid setting applies after the next reboot."
fi

echo "6/6 Starting everything and adding an 'Open ROSPOS' icon..."
make_launcher() {
  sudo -u "$U" mkdir -p "$(dirname "$1")"
  cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Name=Open ROSPOS
Comment=Open ROSPOS
Exec=xdg-open http://localhost
Icon=accessories-calculator
Terminal=false
Categories=Office;
EOF
  chmod +x "$1"
  chown "$U:$(id -gn "$U")" "$1"
}
make_launcher "$HOME_DIR/.local/share/applications/$LAUNCHER"
if [ -d "$HOME_DIR/Desktop" ]; then make_launcher "$HOME_DIR/Desktop/$LAUNCHER"; fi

systemctl daemon-reload
systemctl enable --now avahi-daemon pos
systemctl restart avahi-daemon
sleep 2

echo
if systemctl is-active --quiet pos; then echo "The POS is running."; else echo "The POS did not start. Run:  journalctl -u pos -e"; fi
echo "On this laptop:   http://localhost   (or the Open ROSPOS icon)"
echo "On tablets/PCs:   http://pos.local"
echo "If a device cannot open pos.local, use one of these instead:"
ip -4 -brief address | awk '$1!="lo" && $2=="UP" {split($3,a,"/"); print "                  http://" a[1]}'
echo
echo "Tip: in your router, reserve that address for this laptop so the number never changes."
