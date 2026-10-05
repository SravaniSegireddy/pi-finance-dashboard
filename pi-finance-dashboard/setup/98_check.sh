#!/usr/bin/env bash
# 98_check.sh — quick health check of the whole setup.
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "==== Household Spend — status ===="

printf "%-22s" "nginx:"
systemctl is-active nginx 2>/dev/null || echo "inactive"

printf "%-22s" "dashboard.html:"
if [ -f /var/www/finance/dashboard.html ]; then
  echo "present (updated $(date -r /var/www/finance/dashboard.html '+%Y-%m-%d %H:%M'))"
else
  echo "MISSING — run setup/05_sync_now.sh"
fi

printf "%-22s" "daily cron sync:"
crontab -l 2>/dev/null | grep -Fq sync_and_build.py && echo "scheduled" || echo "not scheduled"

printf "%-22s" "tokens.json:"
[ -f tokens.json ] && echo "present" || echo "absent — link cards (setup/04)"

printf "%-22s" "linked cards:"
.venv/bin/python - <<'PY' 2>/dev/null || echo "n/a"
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), ".env"))   # explicit path: works from stdin
import store
db = os.getenv("DB_PATH", "./spend_store.sqlite3")
if not os.path.isabs(db):
    db = os.path.join(os.getcwd(), db)
conn = store.connect(db)
rows = store.list_items_brief(conn)
print(str(len(rows)) + " (" + ", ".join(i for _, i in rows) + ")" if rows else "0")
PY

printf "%-22s" "wireguard:"
systemctl is-active wg-quick@wg0 2>/dev/null || echo "not configured (optional)"

IP="$(hostname -I | awk '{print $1}')"
echo "=================================="
echo "Home URL:  http://${IP}:8000"
