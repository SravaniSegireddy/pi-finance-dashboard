#!/usr/bin/env bash
# 05_sync_now.sh — pull transactions and build the dashboard now.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
[ -f tokens.json ] || echo "Note: no tokens.json found — if this fails, link cards first (setup/04_link_cards.sh)."

.venv/bin/python sync_and_build.py
rc=$?

IP="$(hostname -I | awk '{print $1}')"
echo
if [ $rc -eq 0 ]; then
  echo "✓ Dashboard built. Open http://${IP}:8000"
  echo "Next:  bash setup/06_schedule.sh"
elif [ $rc -eq 2 ]; then
  echo "A card needs re-linking — re-run setup/04_link_cards.sh for that bank."
fi
exit $rc
