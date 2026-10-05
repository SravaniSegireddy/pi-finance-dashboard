#!/usr/bin/env bash
# 09_duckdns.sh — self-hosted dynamic-DNS updater. Keeps a free DuckDNS name
# pointed at your current public IP, updated by THIS Pi every 5 minutes.
# Replaces the flaky router DDNS. DuckDNS only maps name->IP; it never touches
# your traffic.
#
# MANUAL FIRST: go to https://www.duckdns.org , sign in, add a subdomain, and
# copy your token. Then run this.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

command -v curl >/dev/null || sudo apt install -y curl

echo "== Self-hosted DuckDNS updater =="
read -r -p "  DuckDNS subdomain (just the name, e.g. myhome-finance): " SUB
read -r -p "  DuckDNS token: " TOKEN
[ -n "$SUB" ] && [ -n "$TOKEN" ] || { echo "Both are required."; exit 1; }

# credentials, owner-only
cat > "$PROJECT_DIR/duckdns.conf" <<EOF
DUCKDNS_SUBDOMAIN=$SUB
DUCKDNS_TOKEN=$TOKEN
EOF
chmod 600 "$PROJECT_DIR/duckdns.conf"

# the updater itself
cat > "$PROJECT_DIR/duckdns_update.sh" <<'EOF'
#!/usr/bin/env bash
# Points your DuckDNS name at whatever your current public IP is.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/duckdns.conf"
RESP="$(curl -s --max-time 20 \
  "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=" || true)"
echo "$(date '+%Y-%m-%d %H:%M:%S')  ${RESP:-no-response}" >> "$DIR/duckdns.log"
[ "$RESP" = "OK" ]
EOF
chmod +x "$PROJECT_DIR/duckdns_update.sh"

echo "==> Testing the updater once..."
if "$PROJECT_DIR/duckdns_update.sh"; then
  echo "✓ DuckDNS accepted the update (OK)."
else
  echo "✗ DuckDNS returned KO / no OK — double-check the subdomain and token, then re-run."
  exit 1
fi

# schedule every 5 minutes (idempotent)
LINE="*/5 * * * * $PROJECT_DIR/duckdns_update.sh >/dev/null 2>&1"
CUR="$(crontab -l 2>/dev/null || true)"
if printf '%s\n' "$CUR" | grep -Fq "duckdns_update.sh"; then
  echo "Cron entry already present."
else
  { [ -n "$CUR" ] && printf '%s\n' "$CUR"; printf '%s\n' "$LINE"; } | crontab -
  echo "✓ Scheduled updates every 5 minutes."
fi

FULL="${SUB}.duckdns.org"
echo "==> Checking the name resolves..."
sleep 3
if getent hosts "$FULL" >/dev/null 2>&1; then
  echo "✓ ${FULL} -> $(getent hosts "$FULL" | awk '{print $1}' | head -1)"
else
  echo "Not resolving yet (DNS can take a minute). Re-check: ping -c1 ${FULL}"
fi

echo
echo "============================================================"
echo "  Your permanent WireGuard endpoint is now:"
echo "      ${FULL}:51820"
echo "  Next: point your client configs + phones at this name."
echo "============================================================"
