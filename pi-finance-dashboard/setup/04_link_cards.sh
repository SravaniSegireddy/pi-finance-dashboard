#!/usr/bin/env bash
# 04_link_cards.sh — link your cards through the browser, via an SSH tunnel.
#
# MANUAL: this needs a one-time browser login per card. The script starts the
# link server on the Pi; you reach it from a laptop browser through a tunnel.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
[ -f .env ] || { echo "No .env yet — run setup/02_configure.sh first."; exit 1; }

PORT=4700
IP="$(hostname -I | awk '{print $1}')"

cat <<EOF

============================================================
  MANUAL STEP — link your four cards
============================================================
  Leave THIS running. Then on your laptop (Mac or Windows):

    1) Open a new terminal and start a tunnel:

         ssh -L ${PORT}:localhost:${PORT} ${USER}@${IP}

    2) In that laptop's browser, go to:

         http://localhost:${PORT}

    3) Click "Open Plaid Link", log in to each bank, and
       repeat for all four cards (refresh between each).

    4) When all four show as linked, come back here and
       press Ctrl+C to stop the server.
============================================================

EOF
echo "Starting link server now (tokens are written here on the Pi)..."
exec .venv/bin/python plaid_link_setup.py
