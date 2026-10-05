#!/usr/bin/env bash
# preflight.sh — run BEFORE linking on a fresh Plaid account. Verifies your
# setup and confirms Plaid accepts your keys, WITHOUT creating any bank
# connection (creating a link token is free and does not use an Item).
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
fail=0

echo "== Preflight (creates NO bank connections) =="

# 1) venv + dependencies
if [ -x .venv/bin/python ] && .venv/bin/python -c "import plaid, flask, dotenv" 2>/dev/null; then
  echo "ok   python env + dependencies"
else
  echo "FAIL python env/deps — run setup/01_install.sh"; fail=1
fi

# 2) store.py has the lazy-backend fix
if grep -q "_backend()" store.py 2>/dev/null; then
  echo "ok   store.py backend fix present"
else
  echo "FAIL store.py missing the backend fix"; fail=1
fi

# 3) .env + required values
if [ -f .env ]; then
  grep -q '^TOKEN_BACKEND=file' .env && echo "ok   TOKEN_BACKEND=file" || { echo "FAIL add TOKEN_BACKEND=file to .env"; fail=1; }
  for k in PLAID_CLIENT_ID PLAID_SECRET; do
    v="$(grep -E "^$k=" .env | cut -d= -f2- || true)"
    if [ -z "$v" ] || printf '%s' "$v" | grep -qi 'your_'; then
      echo "FAIL $k not set in .env"; fail=1
    fi
  done
  [ "$fail" -eq 0 ] && echo "ok   Plaid keys present in .env"
else
  echo "FAIL no .env — run setup/02_configure.sh"; fail=1
fi

# 4) warn about stale data from a previous/other account
if [ -f spend_store.sqlite3 ] || [ -f tokens.json ]; then
  echo "WARN old spend_store.sqlite3 / tokens.json exist."
  echo "     For a NEW Plaid account, clear them first:  rm -f spend_store.sqlite3 tokens.json"
fi

# stop here if basics failed (don't bother calling Plaid)
if [ "$fail" -ne 0 ]; then
  echo; echo "Fix the FAIL items above, then re-run preflight."; exit 1
fi

# 5) live check — ask Plaid for a link token (free, no Item created)
echo "--   contacting Plaid to validate your keys + trial setup..."
.venv/bin/python - <<'PY'
import os, sys
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), ".env"))
from plaid.api import plaid_api
from plaid import Configuration, ApiClient, Environment
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
cfg = Configuration(host=Environment.Production,
                    api_key={"clientId": os.environ["PLAID_CLIENT_ID"],
                             "secret": os.environ["PLAID_SECRET"]})
c = plaid_api.PlaidApi(ApiClient(cfg))
try:
    c.link_token_create(LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id="preflight"),
        client_name="Household Spend Dashboard",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")], language="en"))
    print("ok   Plaid accepted your keys — a link token was created.")
except Exception as e:
    print("FAIL Plaid rejected the request. Details:")
    print("    ", getattr(e, "body", e))
    sys.exit(1)
PY
rc=$?

echo
if [ "$rc" -eq 0 ]; then
  echo "✓ All preflight checks passed. Link your cards ONCE:  bash setup/04_link_cards.sh"
else
  echo "The live check failed — usually means the keys are wrong, the Trial plan"
  echo "isn't active yet, or the Link use case isn't set in the Plaid dashboard."
  exit 1
fi
