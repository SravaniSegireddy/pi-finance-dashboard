#!/usr/bin/env bash
# 07_wireguard.sh — OPTIONAL. Self-hosted WireGuard VPN so you can reach the
# dashboard from anywhere, with no third-party service. Run it once per device
# you want to add (phone, laptop). Re-running adds another client.
#
# MANUAL (one-time, on your router):
#   * Forward UDP 51820 to this Pi's LAN IP (hostname -I).
#   * If your home IP changes, set up Dynamic DNS so your endpoint name
#     always points home (many routers do this built-in).
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

WG_DIR=/etc/wireguard
PORT=51820
SVR_ADDR="10.6.0.1"

echo "==> Installing WireGuard + qrencode"
sudo apt install -y wireguard qrencode >/dev/null

read -r -p "Your home PUBLIC IP or DDNS hostname (e.g. myhome-finance.duckdns.org): " ENDPOINT
read -r -p "Name for this device (e.g. my-phone): " CLIENT
[ -n "$ENDPOINT" ] && [ -n "$CLIENT" ] || { echo "Endpoint and device name are required."; exit 1; }

sudo install -d -m 700 "$WG_DIR" "$WG_DIR/clients"

# --- server keys (once) ---
if ! sudo test -f "$WG_DIR/server_private.key"; then
  wg genkey | sudo tee "$WG_DIR/server_private.key" >/dev/null
  sudo chmod 600 "$WG_DIR/server_private.key"
  sudo sh -c "wg pubkey < $WG_DIR/server_private.key > $WG_DIR/server_public.key"
fi
SVR_PRIV="$(sudo cat "$WG_DIR/server_private.key")"
SVR_PUB="$(sudo cat "$WG_DIR/server_public.key")"

# --- server interface config (once) ---
if ! sudo test -f "$WG_DIR/wg0.conf"; then
  sudo tee "$WG_DIR/wg0.conf" >/dev/null <<EOF
[Interface]
Address = ${SVR_ADDR}/24
ListenPort = ${PORT}
PrivateKey = ${SVR_PRIV}
EOF
  sudo chmod 600 "$WG_DIR/wg0.conf"
fi

# --- pick the next free client IP (10.6.0.2, .3, ...) ---
LAST="$(sudo grep -oE '10\.6\.0\.[0-9]+/32' "$WG_DIR/wg0.conf" | grep -oE '[0-9]+/32' | cut -d/ -f1 | sort -n | tail -1 || true)"
NEXT=$(( ${LAST:-1} + 1 ))
CLIENT_ADDR="10.6.0.${NEXT}"

# --- client keys + peer entry ---
CPRIV="$(wg genkey)"
CPUB="$(printf '%s' "$CPRIV" | wg pubkey)"
sudo tee -a "$WG_DIR/wg0.conf" >/dev/null <<EOF

# ${CLIENT}
[Peer]
PublicKey = ${CPUB}
AllowedIPs = ${CLIENT_ADDR}/32
EOF

CLIENT_CONF="$WG_DIR/clients/${CLIENT}.conf"
sudo tee "$CLIENT_CONF" >/dev/null <<EOF
[Interface]
PrivateKey = ${CPRIV}
Address = ${CLIENT_ADDR}/32

[Peer]
PublicKey = ${SVR_PUB}
Endpoint = ${ENDPOINT}:${PORT}
AllowedIPs = ${SVR_ADDR}/32
PersistentKeepalive = 25
EOF
sudo chmod 600 "$CLIENT_CONF"

# --- (re)start the VPN ---
sudo systemctl enable wg-quick@wg0 >/dev/null 2>&1 || true
sudo systemctl restart wg-quick@wg0

echo
echo "✓ WireGuard is up. Device '${CLIENT}' has VPN address ${CLIENT_ADDR}."
echo
echo "On your PHONE: install the official WireGuard app, tap +, 'Scan from QR code',"
echo "and scan this:"
echo
sudo cat "$CLIENT_CONF" | qrencode -t ansiutf8
echo
echo "On a LAPTOP: copy the config saved at ${CLIENT_CONF} into the WireGuard app."
cat <<EOF

============================================================
  MANUAL STEPS (one-time, on your router):
    1) Forward UDP ${PORT}  ->  $(hostname -I | awk '{print $1}')  (this Pi)
    2) Dynamic DNS if your home IP isn't static, pointing
       '${ENDPOINT}' at your home.
  Then, with the VPN connected from anywhere, open:
       http://${SVR_ADDR}:8000
============================================================
EOF
