"""
plaid_link_setup.py — friendly one-time card linking.

Run it on the Pi; reach it from a laptop browser through an SSH tunnel. As you
log in to each bank, this terminal prints a running tally, and the browser
shows a live list. When you're finished, click "I'm done" in the browser and
the server stops on its own — no Ctrl+C needed.

Your bank passwords are entered only on the bank's own page inside Plaid Link;
this script never sees them. Only the resulting access token is saved (to
tokens.json when TOKEN_BACKEND=file).
"""
import os
import threading
import webbrowser

from dotenv import load_dotenv
from flask import Flask, request, jsonify

from plaid.api import plaid_api
from plaid import Configuration, ApiClient, Environment
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.accounts_get_request import AccountsGetRequest

import store

load_dotenv()

PORT = 4700
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", "./spend_store.sqlite3").strip().strip('"').strip("'")
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(HERE, DB_PATH)

ENV_MAP = {"production": Environment.Production, "sandbox": Environment.Sandbox}

ISSUER_FROM_NAME = [
    ("american express", "Amex"), ("amex", "Amex"),
    ("capital one", "Capital One"), ("chase", "Chase"), ("wells fargo", "Wells Fargo"),
]


def issuer_label(name):
    low = (name or "").lower()
    for needle, label in ISSUER_FROM_NAME:
        if needle in low:
            return label
    return name or "Other"


def plaid_client():
    cfg = Configuration(
        host=ENV_MAP.get(os.getenv("PLAID_ENV", "production"), Environment.Production),
        api_key={"clientId": os.environ["PLAID_CLIENT_ID"], "secret": os.environ["PLAID_SECRET"]},
    )
    return plaid_api.PlaidApi(ApiClient(cfg))


client = plaid_client()
app = Flask(__name__)

PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Link your cards</title>
<style>
 body{font:16px -apple-system,Segoe UI,system-ui,sans-serif;max-width:600px;margin:44px auto;
   padding:0 20px;color:#10171D;background:#FAFBFC}
 h1{font-size:24px;margin:0 0 4px} .sub{color:#61707A;margin:0 0 22px}
 .card{background:#fff;border:1px solid #E6EBEF;border-radius:14px;padding:24px;
   box-shadow:0 10px 30px -20px rgba(0,0,0,.3)}
 button{font:16px inherit;border:0;border-radius:10px;padding:13px 20px;cursor:pointer}
 .primary{background:#0E7C66;color:#fff} .done{background:#10171D;color:#fff;margin-left:8px}
 button:disabled{opacity:.5;cursor:default}
 .status{margin:18px 0 0;font-size:15px;min-height:22px} .ok{color:#0E7C66;font-weight:600}
 ul{list-style:none;padding:0;margin:16px 0 0}
 li{padding:11px 13px;border:1px solid #E6EBEF;border-radius:10px;margin-bottom:8px;
   display:flex;align-items:center;gap:10px}
 li .dot{width:9px;height:9px;border-radius:50%;background:#0E7C66}
 .count{font-weight:600} .hint{color:#8A97A0;font-size:13.5px;margin-top:18px;line-height:1.5}
</style>
<div class=card>
  <h1>Link your cards</h1>
  <p class=sub>Add each bank below. The list grows as you go.</p>
  <div>
    <button class=primary id=add>＋ Add a bank</button>
    <button class=done id=done>✓ I'm done</button>
  </div>
  <div class=status id=status></div>
  <div id=wrap style=display:none>
    <p style="margin:20px 0 0"><span class=count id=count>0</span> linked so far:</p>
    <ul id=list></ul>
  </div>
  <p class=hint>When you've added all your cards, click <b>I'm done</b>. Then return
  to your terminal — it continues on its own, no Ctrl+C needed.</p>
</div>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
async function refresh(){
  const j = await (await fetch('/items')).json();
  document.getElementById('count').textContent = j.length;
  const wrap=document.getElementById('wrap'), list=document.getElementById('list');
  if(j.length){ wrap.style.display='block';
    list.innerHTML = j.map(x=>'<li><span class=dot></span>'+x.institution+'</li>').join(''); }
}
document.getElementById('add').onclick = async () => {
  const s=document.getElementById('status'); s.textContent='Opening secure bank login…';
  const {link_token} = await (await fetch('/create_link_token',{method:'POST'})).json();
  Plaid.create({ token: link_token,
    onSuccess: async (pt) => {
      s.textContent='Saving…';
      const j = await (await fetch('/exchange',{method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({public_token:pt})})).json();
      s.innerHTML = j.ok ? '<span class=ok>✓ Linked '+j.institution+'</span> — add another, or click “I’m done”.'
                         : '⚠ '+(j.error||'something went wrong');
      refresh();
    },
    onExit: (err) => { s.textContent = 'Cancelled — nothing saved. You can try that bank again.'; }
  }).open();
};
document.getElementById('done').onclick = async () => {
  await fetch('/done',{method:'POST'});
  document.body.innerHTML =
    '<div style="max-width:600px;margin:90px auto;text-align:center;'+
    'font:19px -apple-system,Segoe UI,sans-serif;color:#10171D">'+
    '✓ All set — close this tab and go back to your terminal.</div>';
};
refresh();
</script>
"""


@app.route("/")
def home():
    return PAGE


@app.route("/items")
def items():
    conn = store.connect(DB_PATH)
    out = [{"institution": inst} for _, inst in store.list_items_brief(conn)]
    conn.close()
    return jsonify(out)


@app.route("/create_link_token", methods=["POST"])
def create_link_token():
    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id="household-1"),
        client_name="Household Spend Dashboard",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    )
    redirect_uri = os.getenv("PLAID_REDIRECT_URI", "").strip()
    if redirect_uri:
        req.redirect_uri = redirect_uri
    return jsonify({"link_token": client.link_token_create(req).link_token})


@app.route("/exchange", methods=["POST"])
def exchange():
    try:
        public_token = request.json["public_token"]
        ex = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token))
        access_token, item_id = ex.access_token, ex.item_id

        item = client.item_get(ItemGetRequest(access_token=access_token))
        inst_id = item.item.institution_id
        inst_name = "Unknown"
        if inst_id:
            inst = client.institutions_get_by_id(
                InstitutionsGetByIdRequest(institution_id=inst_id, country_codes=[CountryCode("US")]))
            inst_name = inst.institution.name

        accts = client.accounts_get(AccountsGetRequest(access_token=access_token))
        accounts = {a.account_id: {"name": a.name, "mask": a.mask or ""} for a in accts.accounts}

        store.save_token(item_id, access_token)
        conn = store.connect(DB_PATH)
        store.save_item_meta(conn, item_id, inst_name, issuer_label(inst_name), accounts)
        n = len(store.list_items_brief(conn))
        conn.close()
        print(f"  \u2713 Linked {inst_name}   (total linked: {n})", flush=True)
        return jsonify({"ok": True, "institution": inst_name})
    except Exception as e:  # noqa: BLE001
        print(f"  ! Link failed: {e}", flush=True)
        return jsonify({"ok": False, "error": str(e)})


@app.route("/done", methods=["POST"])
def done():
    conn = store.connect(DB_PATH)
    banks = [inst for _, inst in store.list_items_brief(conn)]
    conn.close()
    print("\n" + "=" * 52, flush=True)
    if banks:
        print(f"  Finished. {len(banks)} bank(s) linked: " + ", ".join(banks), flush=True)
    else:
        print("  Finished, but no banks were linked.", flush=True)
    print("  You can close the browser tab. Continuing setup...", flush=True)
    print("=" * 52 + "\n", flush=True)
    # let the HTTP response flush, then exit the process cleanly
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return jsonify({"ok": True, "banks": banks})


def _open():
    try:
        if webbrowser.open(f"http://127.0.0.1:{PORT}"):
            return
    except Exception:
        pass
    print("  (no local browser here — reach it via the SSH tunnel below)", flush=True)


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  LINK YOUR CARDS")
    print("=" * 60)
    print(f"  This server is running on the Pi (port {PORT}).")
    print("  From your laptop, open a second terminal and run:\n")
    print(f"      ssh -L {PORT}:localhost:{PORT} {os.getenv('USER','pi')}@<pi-ip>\n")
    print(f"  Then open  http://localhost:{PORT}  in that laptop's browser.")
    print("  Add each bank; you'll see it appear here and in the browser.")
    print("  Click \"I'm done\" in the browser when finished — it stops on its own.")
    print("=" * 60 + "\n")
    threading.Timer(1.0, _open).start()
    try:
        app.run(port=PORT, debug=False)
    except KeyboardInterrupt:
        print("\nStopped.")
