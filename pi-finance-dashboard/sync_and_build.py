"""
sync_and_build.py  —  the monthly (or whenever) job.

  1. Reads your linked items + access tokens from the OS keychain.
  2. Calls Plaid /transactions/sync for each, pulling only what's new since last
     run (incremental, via a stored cursor). No browser, no prompts.
  3. Stores everything in a local SQLite file, applies category mapping +
     your overrides, then regenerates the self-contained dashboard.html.

Run by hand:   python sync_and_build.py
Or let launchd / Task Scheduler run it on a schedule (see SETUP.md).

Exit codes: 0 = ok. 2 = a card needs re-authentication (re-run
plaid_link_setup.py for that bank). 1 = unexpected error.
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from plaid.api import plaid_api
from plaid import Configuration, ApiClient, Environment
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.exceptions import ApiException

import store
from dashboard import build_dashboard

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))


def _clean_path(raw):
    # tolerate surrounding quotes, stray whitespace, and a leftover leading "./"
    p = (raw or "").strip().strip('"').strip("'").strip()
    return p


DB_PATH = _clean_path(os.getenv("DB_PATH", "./spend_store.sqlite3"))
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(HERE, DB_PATH)

OUT_PATH = _clean_path(os.getenv("DASHBOARD_OUT", "./dashboard.html"))
# If DASHBOARD_OUT names a folder (or lacks an .html name), write dashboard.html inside it.
if OUT_PATH.endswith(("/", "\\")) or os.path.isdir(OUT_PATH) or not OUT_PATH.lower().endswith((".html", ".htm")):
    OUT_PATH = os.path.join(OUT_PATH, "dashboard.html")
if not os.path.isabs(OUT_PATH):
    OUT_PATH = os.path.join(HERE, OUT_PATH)

OVERRIDES_PATH = os.path.join(HERE, "categories.csv")

ENV_MAP = {"production": Environment.Production, "sandbox": Environment.Sandbox}

# Plaid personal_finance_category.primary  ->  friendly bucket
PFC_PRIMARY = {
    "FOOD_AND_DRINK": "Dining",
    "GENERAL_MERCHANDISE": "Shopping",
    "TRANSPORTATION": "Transportation",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Utilities",
    "HOME_IMPROVEMENT": "Home",
    "MEDICAL": "Health",
    "PERSONAL_CARE": "Health",
    "ENTERTAINMENT": "Entertainment",
    "GENERAL_SERVICES": "Services",
    "GOVERNMENT_AND_NON_PROFIT": "Other",
    "BANK_FEES": "Fees",
    "LOAN_PAYMENTS": "Payments",
    "INCOME": "Income",
    "TRANSFER_IN": "Transfer",
    "TRANSFER_OUT": "Transfer",
}

# A transaction is a card *payment* (not spend, not a refund) if Plaid buckets it
# as a loan payment / transfer, or its text looks like a bill payment. These are
# shown separately and never netted into spend.
PAYMENT_PRIMARIES = {"LOAN_PAYMENTS", "TRANSFER_IN", "TRANSFER_OUT"}
PAYMENT_KEYWORDS = [
    "payment thank you", "online payment", "mobile payment", "autopay", "auto pay",
    "auto-pay", "bill pay", "billpay", "e-payment", "epayment", "ach pmt",
    "web pmt", "payment - thank", "pymt",
]


def classify_flow(primary, name, merchant, amount):
    """Return 'payment', 'refund', or 'spend'."""
    text = ((merchant or "") + " " + (name or "")).lower()
    if primary in PAYMENT_PRIMARIES or any(k in text for k in PAYMENT_KEYWORDS):
        return "payment"
    if amount < 0:
        return "refund"
    return "spend"


def plaid_client():
    cfg = Configuration(
        host=ENV_MAP.get(os.getenv("PLAID_ENV", "production"), Environment.Production),
        api_key={
            "clientId": os.environ["PLAID_CLIENT_ID"],
            "secret": os.environ["PLAID_SECRET"],
        },
    )
    return plaid_api.PlaidApi(ApiClient(cfg))


def load_overrides():
    rules = []
    if os.path.exists(OVERRIDES_PATH):
        with open(OVERRIDES_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(filter(lambda l: not l.startswith("#"), f)):
                if row.get("match") and row.get("category"):
                    rules.append((row["match"].strip().lower(), row["category"].strip()))
    return rules


def friendly_category(primary, detailed, merchant, name, overrides):
    text = (merchant + " " + name).lower()
    for needle, cat in overrides:
        if needle in text:
            return cat
    if detailed and "GROCERIES" in detailed:
        return "Groceries"
    return PFC_PRIMARY.get(primary, "Other")


def sync_items(client, items, conn):
    """Pull new/modified/removed transactions for every item. Returns (added, needs_auth)."""
    added = 0
    needs_auth = []
    for item_id, meta in items.items():
        cursor = meta.get("cursor")
        token = meta["access_token"]
        try:
            has_more = True
            while has_more:
                kwargs = {"access_token": token, "count": 500}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = client.transactions_sync(TransactionsSyncRequest(**kwargs))

                for t in resp.added:
                    conn.execute(
                        """INSERT OR REPLACE INTO txns VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            t.transaction_id, item_id, t.account_id,
                            str(t.date), float(t.amount),
                            t.name or "",
                            (t.merchant_name or t.name or ""),
                            getattr(t.personal_finance_category, "primary", "") if t.personal_finance_category else "",
                            getattr(t.personal_finance_category, "detailed", "") if t.personal_finance_category else "",
                        ),
                    )
                    added += 1
                for t in resp.modified:
                    conn.execute(
                        """INSERT OR REPLACE INTO txns VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            t.transaction_id, item_id, t.account_id,
                            str(t.date), float(t.amount),
                            t.name or "",
                            (t.merchant_name or t.name or ""),
                            getattr(t.personal_finance_category, "primary", "") if t.personal_finance_category else "",
                            getattr(t.personal_finance_category, "detailed", "") if t.personal_finance_category else "",
                        ),
                    )
                for r in resp.removed:
                    conn.execute("DELETE FROM txns WHERE transaction_id=?", (r.transaction_id,))

                cursor = resp.next_cursor
                has_more = resp.has_more
            store.set_cursor(conn, item_id, cursor)
            conn.commit()
            print(f"  ✓ {meta.get('institution','?')}: up to date")
        except ApiException as e:
            body = json.loads(e.body) if e.body else {}
            code = body.get("error_code", "")
            if code in ("ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION"):
                needs_auth.append(meta.get("institution", item_id))
                print(f"  ! {meta.get('institution','?')}: needs re-authentication")
            else:
                print(f"  ! {meta.get('institution','?')}: {code or e}")
    return added, needs_auth


def normalized_rows(items, conn, overrides):
    # account_id -> (label, issuer)
    acct_index = {}
    for meta in items.values():
        issuer = meta.get("issuer", "Other")
        for acc_id, a in meta.get("accounts", {}).items():
            mask = a.get("mask")
            label = a.get("name") or meta.get("institution", "Card")
            if mask:
                label = f"{label} ··{mask}"
            acct_index[acc_id] = (label, issuer)

    rows = []
    for r in conn.execute(
        "SELECT account_id,date,amount,name,merchant,pfc_primary,pfc_detailed FROM txns"
    ):
        account_id, date, amount, name, merchant, primary, detailed = r
        label, issuer = acct_index.get(account_id, ("Card", "Other"))
        flow = classify_flow(primary, name, merchant, amount)
        if flow == "payment":
            category = "Payment"
        else:
            category = friendly_category(primary, detailed, merchant or "", name or "", overrides)
        rows.append({
            "date": date,
            "amount": amount,            # signed: spend > 0, refund/payment < 0
            "name": name,
            "merchant": merchant or name,
            "category": category,
            "account": label,
            "issuer": issuer,
            "flow": flow,
        })
    return rows


def main():
    conn = store.connect(DB_PATH)
    items = store.load_items(conn)
    if not items:
        print("No linked cards found. Run:  python plaid_link_setup.py")
        return 1

    client = plaid_client()
    overrides = load_overrides()

    print("Syncing transactions…")
    added, needs_auth = sync_items(client, items, conn)
    print(f"Added/updated {added} transaction(s).")

    rows = normalized_rows(items, conn, overrides)
    out = build_dashboard(
        rows, OUT_PATH,
        generated_at=datetime.now(timezone.utc).astimezone(),
        meta={"title": "Household Spend",
              "subtitle": " · ".join(sorted({r["issuer"] for r in rows if r.get("issuer")}))},
    )
    print(f"Dashboard written → {out}")

    if needs_auth:
        print("\nThese banks need a quick re-link (run plaid_link_setup.py):")
        for n in needs_auth:
            print(f"   • {n}")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"Unexpected error: {e}")
        sys.exit(1)
