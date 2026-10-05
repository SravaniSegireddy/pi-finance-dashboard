"""
store.py — persistence shared by the link setup and the sync job.

Why this exists: Windows Credential Manager limits each keychain entry to
~2.5 KB. Storing every card's token + account details + sync cursor in one
entry overflows that limit (the "CredWrite ... bad data" error). So:

  * keyring holds ONLY the per-card access token — the single real secret —
    as one tiny entry per item, keyed by item_id. It can never grow large.
  * Everything else (institution, issuer, account labels, Plaid sync cursor,
    and all transactions) lives in the local SQLite DB, which has no such
    limit and is not secret.

It also auto-migrates the older single-blob format if it's still present, so
cards you already linked are preserved — you won't have to redo them.

Token backend is selectable via the TOKEN_BACKEND env var:
  * "keyring" (default) — OS keychain. Use on Windows/Mac laptops.
  * "file"   — an owner-only JSON file (TOKEN_FILE, default tokens.json).
    Use on a headless Raspberry Pi, where the OS keychain isn't practical.
"""
import json
import os

KEYRING_SERVICE = "finance-dashboard"
LEGACY_USER = "plaid_items"

def _backend():
    return os.getenv("TOKEN_BACKEND", "keyring").strip().lower()


def _token_file():
    p = os.getenv("TOKEN_FILE", "").strip()
    if not p:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.json")
    return p


def _file_load():
    p = _token_file()
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _file_save(d):
    p = _token_file()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f)
    try:
        os.chmod(p, 0o600)  # owner read/write only
    except Exception:
        pass


# ---------- token storage ----------
def save_token(item_id, access_token):
    if _backend() == "file":
        d = _file_load(); d[item_id] = access_token; _file_save(d)
    else:
        import keyring
        keyring.set_password(KEYRING_SERVICE, item_id, access_token)


def get_token(item_id):
    if _backend() == "file":
        return _file_load().get(item_id)
    import keyring
    return keyring.get_password(KEYRING_SERVICE, item_id)


def delete_token(item_id):
    if _backend() == "file":
        d = _file_load(); d.pop(item_id, None); _file_save(d)
        return
    import keyring
    try:
        keyring.delete_password(KEYRING_SERVICE, item_id)
    except Exception:
        pass


# ---------- metadata storage (sqlite; unbounded, non-secret) ----------
def connect(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS items(
        item_id TEXT PRIMARY KEY,
        institution TEXT,
        issuer TEXT,
        accounts_json TEXT,
        cursor TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS txns(
        transaction_id TEXT PRIMARY KEY,
        item_id TEXT,
        account_id TEXT,
        date TEXT,
        amount REAL,
        name TEXT,
        merchant TEXT,
        pfc_primary TEXT,
        pfc_detailed TEXT
    )""")
    conn.commit()
    _migrate_legacy(conn)
    return conn


def save_item_meta(conn, item_id, institution, issuer, accounts):
    """Insert/update an item's metadata. Never touches the cursor."""
    conn.execute(
        "INSERT INTO items(item_id,institution,issuer,accounts_json) VALUES(?,?,?,?) "
        "ON CONFLICT(item_id) DO UPDATE SET "
        "institution=excluded.institution, issuer=excluded.issuer, "
        "accounts_json=excluded.accounts_json",
        (item_id, institution, issuer, json.dumps(accounts)),
    )
    conn.commit()


def load_items(conn):
    """Return {item_id: {institution, issuer, accounts, cursor, access_token}}."""
    items = {}
    for item_id, inst, issuer, acc, cursor in conn.execute(
        "SELECT item_id,institution,issuer,accounts_json,cursor FROM items"
    ):
        token = get_token(item_id)
        if not token:
            continue  # token missing → that card needs a re-link
        items[item_id] = {
            "institution": inst,
            "issuer": issuer,
            "accounts": json.loads(acc) if acc else {},
            "cursor": cursor,
            "access_token": token,
        }
    return items


def set_cursor(conn, item_id, cursor):
    conn.execute("UPDATE items SET cursor=? WHERE item_id=?", (cursor, item_id))
    conn.commit()


def list_items_brief(conn):
    return list(conn.execute("SELECT item_id,institution FROM items"))


# ---------- migration from the old single-blob format ----------
def _migrate_legacy(conn):
    if _backend() != "keyring":
        return  # legacy blob only ever existed in the OS keychain
    import keyring
    raw = keyring.get_password(KEYRING_SERVICE, LEGACY_USER)
    if not raw:
        return
    try:
        legacy = json.loads(raw)
    except Exception:
        return
    for item_id, d in legacy.items():
        tok = d.get("access_token")
        if tok:
            save_token(item_id, tok)
        conn.execute(
            "INSERT OR REPLACE INTO items(item_id,institution,issuer,accounts_json,cursor) "
            "VALUES(?,?,?,?,?)",
            (item_id, d.get("institution"), d.get("issuer"),
             json.dumps(d.get("accounts", {})), d.get("cursor")),
        )
    conn.commit()
    try:
        keyring.delete_password(KEYRING_SERVICE, LEGACY_USER)
    except Exception:
        pass
