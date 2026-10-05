#!/usr/bin/env bash
# 10_insights.sh — AI spending checks (Claude) + email.
#   Daily  (7am):  alerts only when something new is flagged
#   Monthly (3rd, 8am): summary of last month, always sent
#
# MANUAL FIRST (skip if you already did this):
#   1) Anthropic API key: console.anthropic.com -> API Keys (add a little credit).
#   2) Gmail App Password: myaccount.google.com -> Security -> 2-Step Verification
#      must be ON -> "App passwords" -> create one (16 characters).
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
ENVF="$PROJECT_DIR/.env"
[ -f "$ENVF" ] || { echo "No .env — run setup/02_configure.sh first."; exit 1; }
[ -f insights.py ] || { echo "insights.py is missing from $PROJECT_DIR"; exit 1; }

echo "==> Installing the Anthropic SDK"
.venv/bin/pip install -q anthropic
grep -q '^anthropic' requirements.txt || echo "anthropic>=0.40" >> requirements.txt

ASK=1
if grep -q '^ANTHROPIC_API_KEY=.' "$ENVF" && grep -q '^SMTP_PASS=.' "$ENVF"; then
  read -r -p "API key and email settings already saved. Keep them? [Y/n] " k
  [[ "${k:-Y}" =~ ^[Nn]$ ]] || ASK=0
fi

if [ "$ASK" -eq 1 ]; then
  echo
  read -r -s -p "Anthropic API key (hidden): " AKEY; echo
  read -r -p "Gmail address that SENDS alerts: " SUSER
  read -r -s -p "Gmail App Password (hidden, spaces OK): " SPASS; echo
  SPASS="${SPASS// /}"
  read -r -p "Send alerts TO (comma-separated) [$SUSER]: " ATO; ATO="${ATO:-$SUSER}"
  sed -i -E '/^(ANTHROPIC_API_KEY|INSIGHTS_MODEL|INSIGHTS_LOOKBACK_MONTHS|SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASS|ALERT_TO)=/d;/^# --- monthly insights ---$/d;/^# --- AI insights ---$/d' "$ENVF"
  cat >> "$ENVF" <<CONF

# --- AI insights ---
ANTHROPIC_API_KEY=$AKEY
INSIGHTS_MODEL=claude-sonnet-5-5
INSIGHTS_LOOKBACK_MONTHS=6
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=$SUSER
SMTP_PASS=$SPASS
ALERT_TO=$ATO
CONF
  chmod 600 "$ENVF"
  echo "✓ Saved settings to .env (owner-only)."
fi

echo
echo "==> Daily dry run (nothing is sent)"
.venv/bin/python insights.py --daily --dry-run || true
echo
echo "==> Monthly dry run for last month (nothing is sent)"
.venv/bin/python insights.py --monthly --dry-run || true

echo
echo "==> Sending a test email"
if .venv/bin/python insights.py --test-email; then
  echo "✓ Check your inbox for 'Spending check · test'."
else
  echo "✗ Email failed. Usually: App Password wrong, or 2-Step Verification off."
  exit 1
fi

echo
echo "==> Scheduling (replaces any older insights schedule)"
PY="$PROJECT_DIR/.venv/bin/python"
DAILY="0 7 * * * cd $PROJECT_DIR && $PY insights.py --daily >> $PROJECT_DIR/insights.log 2>&1"
MONTHLY="0 8 3 * * cd $PROJECT_DIR && $PY insights.py --monthly >> $PROJECT_DIR/insights.log 2>&1"
{ crontab -l 2>/dev/null | grep -v "insights.py" || true; echo "$DAILY"; echo "$MONTHLY"; } | crontab -
crontab -l | grep insights.py

cat <<MSG

============================================================
  Done.
  • Every day at 7am: emails you only if something new is flagged
  • 3rd of each month, 8am: emails last month's summary

  Send last month's summary now:
      .venv/bin/python insights.py --monthly --force
  Run today's check now:
      .venv/bin/python insights.py --daily
  Log: insights.log
============================================================
MSG
