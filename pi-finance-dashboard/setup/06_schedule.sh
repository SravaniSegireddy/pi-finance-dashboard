#!/usr/bin/env bash
# 06_schedule.sh — daily automatic sync at 6am via cron (idempotent).
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"
LINE="0 6 * * * cd $PROJECT_DIR && $PY sync_and_build.py >> $PROJECT_DIR/sync.log 2>&1"

CUR="$(crontab -l 2>/dev/null || true)"
if printf '%s\n' "$CUR" | grep -Fq "sync_and_build.py"; then
  echo "Cron entry already present:"
else
  { [ -n "$CUR" ] && printf '%s\n' "$CUR"; printf '%s\n' "$LINE"; } | crontab -
  echo "✓ Added daily 6am sync."
fi
crontab -l | grep -F sync_and_build.py
echo
echo "Core setup is done. Optional remote access:  bash setup/07_wireguard.sh"
echo "Verify anytime with:  bash setup/98_check.sh"
