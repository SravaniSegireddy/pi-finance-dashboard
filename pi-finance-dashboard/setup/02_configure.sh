#!/usr/bin/env bash
# 02_configure.sh — collect your Plaid keys + dashboard login, write .env,
# and create the nginx password file (only the hash is stored, never the
# plaintext password).
#
# MANUAL: have your Plaid client_id and Production secret ready
#         (dashboard.plaid.com -> Developers -> Keys).
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
ENVF="$PROJECT_DIR/.env"

if [ -f "$ENVF" ]; then
  read -r -p ".env already exists. Overwrite it? [y/N] " a
  [[ "${a:-N}" =~ ^[Yy]$ ]] || { echo "Keeping existing .env. Done."; exit 0; }
fi

echo
echo "Plaid credentials (from dashboard.plaid.com -> Developers -> Keys):"
read -r -p "  PLAID_CLIENT_ID: " CID
read -r -s -p "  PLAID_SECRET (hidden): " CSEC; echo
echo
echo "Dashboard login (you'll type these in the browser to view the page):"
read -r -p "  username [family]: " DUSER; DUSER="${DUSER:-family}"
read -r -s -p "  password (hidden): " DPASS; echo

cat > "$ENVF" <<EOF
PLAID_CLIENT_ID=$CID
PLAID_SECRET=$CSEC
PLAID_ENV=production

# headless Pi: tokens live in an owner-only file, not a keychain
TOKEN_BACKEND=file
TOKEN_FILE=./tokens.json

# nginx serves the dashboard from here
DASHBOARD_OUT=/var/www/finance/dashboard.html

DASH_USER=$DUSER
EOF
chmod 600 "$ENVF"
echo "✓ Wrote $ENVF (chmod 600)."

# nginx password file — store only the apr1 hash
HASH="$(printf '%s' "$DPASS" | openssl passwd -apr1 -stdin)"
echo "$DUSER:$HASH" | sudo tee /etc/nginx/.htpasswd-finance >/dev/null
sudo chown root:www-data /etc/nginx/.htpasswd-finance 2>/dev/null || true
sudo chmod 640 /etc/nginx/.htpasswd-finance
echo "✓ Wrote /etc/nginx/.htpasswd-finance (password hash only)."
echo
echo "Next:  bash setup/03_webserver.sh"
