"""
insights.py — AI spending checks for the household dashboard.

Two modes (both scheduled by setup/10_insights.sh):

  --daily    Runs every morning after the sync. Looks at the last few days for
             new subscriptions, cancelled subscriptions (an expected recurring
             charge that didn't arrive), price increases, duplicate charges and
             unusual amounts. Emails ONLY if something is flagged, and never
             alerts on the same thing twice.

  --monthly  Runs on the 3rd. Always emails a summary of last month: spend by
             category vs the previous month and the 6-month average, recurring
             charges, subscription changes, and anything unusual.

Privacy: only date, merchant (scrubbed), amount, category, card letter
(Card A/B/C/D) and spend/refund are sent to the model. Account and transaction
IDs, card numbers, bank/card names, card-bill payments and transfers, and raw
locations never leave the Pi. Card letters are mapped back to real names on the
Pi, only for the email.

Usage:
  python insights.py --daily [--dry-run]
  python insights.py --monthly [--month 2026-09] [--force] [--dry-run]
  python insights.py --test-email
"""
import argparse
import json
import os
import re
import smtplib
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

from sync_and_build import DB_PATH, classify_flow, friendly_category, load_overrides  # noqa: E402

MODEL = os.getenv("INSIGHTS_MODEL", "claude-sonnet-5-5")
LOOKBACK_MONTHS = int(os.getenv("INSIGHTS_LOOKBACK_MONTHS", "6"))
DAILY_WINDOW_DAYS = int(os.getenv("INSIGHTS_DAILY_WINDOW_DAYS", "10"))   # late postings
DAILY_HISTORY_DAYS = int(os.getenv("INSIGHTS_DAILY_HISTORY_DAYS", "180"))
CANCEL_GRACE_DAYS = int(os.getenv("INSIGHTS_CANCEL_GRACE_DAYS", "7"))
STATE_FILE = os.path.join(HERE, "insights_state.json")
LOG_FILE = os.path.join(HERE, "insights.log")


# ================================================================ helpers
def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def month_shift(ym, delta):
    y, m = map(int, ym.split("-"))
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_label(ym):
    return datetime.strptime(ym, "%Y-%m").strftime("%B %Y")


def money(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    return f"-${-v:,.2f}" if v < 0 else f"${v:,.2f}"


_EMAIL = re.compile(r"\S+@\S+")
_PHONE = re.compile(r"\+?\d[\d\-\s().]{7,}\d")
_DIGITS = re.compile(r"\d{3,}")
_REFS = re.compile(r"(#|\bREF\b|\bID\b|\bCONF\b)\s*\S*", re.I)
_STATE = re.compile(r"\s+(A[KLRZ]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|"
                    r"N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])$")


def scrub(text, raw_descriptor=False):
    """Strip anything that could identify a person, account or location."""
    t = text or ""
    for rx in (_EMAIL, _PHONE, _REFS, _DIGITS):
        t = rx.sub("", t)
    t = re.sub(r"[*]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -.,")
    if _STATE.search(t):
        t = _STATE.sub("", t)
        if raw_descriptor and len(t.split()) >= 2:
            t = " ".join(t.split()[:-1])  # drop the city too
    return t.strip()[:60] or "Unknown merchant"


# ================================================================ data
def load_rows(start, end):
    """Anonymized rows with start <= date < end (ISO strings). Returns (rows, card_names)."""
    overrides = load_overrides()
    conn = sqlite3.connect(DB_PATH)
    real = {}
    for inst, issuer, acc_json in conn.execute("SELECT institution, issuer, accounts_json FROM items"):
        for acc_id in (json.loads(acc_json) if acc_json else {}):
            real[acc_id] = issuer or inst or "Card"
    raw = list(conn.execute(
        "SELECT account_id, date, amount, name, merchant, pfc_primary, pfc_detailed "
        "FROM txns WHERE date >= ? AND date < ? ORDER BY date", (start, end)))
    # card letters are assigned over ALL accounts so they're stable across runs
    all_accts = sorted({r[0] for r in conn.execute("SELECT DISTINCT account_id FROM txns")})
    conn.close()
    letters = {a: f"Card {chr(ord('A') + i)}" for i, a in enumerate(all_accts)}
    card_names = {letters[a]: real.get(a, "Card") for a in all_accts}

    rows = []
    for acc, dt, amt, name, merchant, primary, detailed in raw:
        flow = classify_flow(primary, name, merchant, amt)
        if flow == "payment":
            continue
        rows.append({
            "date": dt,
            "merchant": scrub(merchant) if merchant else scrub(name, raw_descriptor=True),
            "amount": round(float(amt), 2),
            "category": friendly_category(primary, detailed, merchant or "", name or "", overrides),
            "card": letters.get(acc, "Card ?"),
            "type": flow,
        })
    return rows, card_names


def key(r):
    return r["merchant"].lower()


# ================================================================ local detection
def recurring_profile(spend_rows):
    """Merchants charging a stable amount roughly monthly (3+ charges, 3+ months)."""
    by_m = defaultdict(list)
    for r in spend_rows:
        by_m[key(r)].append(r)
    out = {}
    for k, rs in by_m.items():
        rs = sorted(rs, key=lambda r: r["date"])
        months = {r["date"][:7] for r in rs}
        if len(rs) < 3 or len(months) < 3:
            continue
        amts = [r["amount"] for r in rs]
        med = statistics.median(amts)
        if med <= 0:
            continue
        # stable amount across all but the latest charge (latest may be a price change)
        base = amts[:-1]
        if (max(base) - min(base)) / med > 0.25:
            continue
        gaps = [(d(b["date"]) - d(a["date"])).days for a, b in zip(rs, rs[1:])]
        interval = statistics.median(gaps)
        if not 25 <= interval <= 35:
            continue
        out[k] = {"merchant": rs[-1]["merchant"], "card": rs[-1]["card"],
                  "category": rs[-1]["category"], "usual_amount": round(statistics.median(base), 2),
                  "last_date": rs[-1]["date"], "last_amount": rs[-1]["amount"],
                  "interval_days": int(interval), "charges": len(rs)}
    return out


def detect(target, history, today):
    """Flags for `target` rows (spend only) compared with `history` rows."""
    target = [r for r in target if r["type"] == "spend"]
    history = [r for r in history if r["type"] == "spend"]
    flags = []
    hist_by_m = defaultdict(list)
    for r in history:
        hist_by_m[key(r)].append(r["amount"])

    seen_new = set()
    for r in target:
        if key(r) not in hist_by_m and key(r) not in seen_new:
            seen_new.add(key(r))
            flags.append({"flag": "first_time_merchant", **r})

    recurring = recurring_profile(history + target)
    hist_recurring = recurring_profile(history)
    for r in target:
        p = hist_recurring.get(key(r))
        if p and abs(r["amount"] - p["usual_amount"]) / p["usual_amount"] > 0.10:
            flags.append({"flag": "recurring_price_change", "usual_amount": p["usual_amount"], **r})
            continue
        amts = hist_by_m.get(key(r), [])
        if len(amts) >= 3:
            med = statistics.median(amts)
            if med > 0 and r["amount"] > 3 * med and r["amount"] > 50:
                flags.append({"flag": "unusually_high_for_merchant", "usual_amount": round(med, 2), **r})

    all_hist = sorted(r["amount"] for r in history)
    if len(all_hist) >= 20:
        p98 = all_hist[int(0.98 * (len(all_hist) - 1))]
        for r in target:
            if r["amount"] > max(400, p98):
                flags.append({"flag": "large_charge", "typical_max": round(p98, 2), **r})

    by_k = defaultdict(list)
    for r in target:
        by_k[(key(r), r["amount"], r["card"])].append(d(r["date"]))
    for (m, amt, card), ds in by_k.items():
        ds.sort()
        if amt > 5 and any((b - a).days <= 2 for a, b in zip(ds, ds[1:])):
            flags.append({"flag": "possible_duplicate", "merchant": m, "amount": amt, "card": card,
                          "date": ds[-1].isoformat(), "dates": [x.isoformat() for x in ds]})

    # cancelled: was charging regularly, expected date + grace has passed, no charge
    for k, p in recurring.items():
        expected = d(p["last_date"]) + timedelta(days=p["interval_days"])
        if expected + timedelta(days=CANCEL_GRACE_DAYS) < today and \
                (today - d(p["last_date"])).days <= 2.5 * p["interval_days"]:
            flags.append({"flag": "possibly_cancelled_subscription", "merchant": p["merchant"],
                          "card": p["card"], "usual_amount": p["usual_amount"],
                          "last_charged": p["last_date"], "expected_by": expected.isoformat(),
                          "date": expected.isoformat(), "amount": p["usual_amount"]})
    cancelled = {f["merchant"].lower() for f in flags if f["flag"] == "possibly_cancelled_subscription"}
    active = {k: p for k, p in recurring.items() if k not in cancelled}
    return flags, active


def fingerprint(f):
    return "|".join(str(f.get(k, "")) for k in ("flag", "merchant", "date", "amount")).lower()


def category_table(rows, month):
    """Net spend per category: this month, previous month, average of prior months."""
    tot = defaultdict(float)
    for r in rows:
        tot[(r["date"][:7], r["category"])] += r["amount"]
    prev = month_shift(month, -1)
    prior = [month_shift(month, -i) for i in range(1, LOOKBACK_MONTHS + 1)]
    cats = sorted({c for (_, c) in tot})
    table = []
    for c in cats:
        cur, pm = tot.get((month, c), 0.0), tot.get((prev, c), 0.0)
        avg = statistics.mean(tot.get((m, c), 0.0) for m in prior)
        if cur == 0 and avg == 0:
            continue
        table.append({"category": c, "this_month": round(cur, 2), "last_month": round(pm, 2),
                      "avg_prior": round(avg, 2),
                      "vs_avg_pct": round((cur - avg) / avg * 100) if avg else None})
    table.sort(key=lambda x: -x["this_month"])
    return table


# ================================================================ Claude
RULES = """Cards are labeled Card A/B/C/D, amounts are USD, positive = spend, \
negative = refund. "local_flags" are rough statistical hints computed on the \
device; confirm or dismiss each using the transactions. Be conservative: normal \
variation in groceries, dining, gas and one-off shopping is NOT a finding, and a \
new restaurant or store in a familiar category is NOT a new kind of spending.

Worth flagging:
- new_subscription: a recurring-looking service (streaming, software, apps, \
memberships, cloud storage, a free trial converting to paid) charging for the first time
- cancelled_subscription: a regular charge that stopped arriving (confirm it \
really looked recurring)
- price_increase on an existing subscription
- duplicate_charge, unusual_charge, possible_fraud (unfamiliar merchant), \
fee (foreign transaction, late, interest), new_spending_type (a category of \
merchant never used before)

Each finding: {"type": "...", "severity": "high|medium|low", "merchant": "...", \
"date": "YYYY-MM-DD or empty", "amount": 0.0, "card": "Card X or empty", \
"explanation": "one or two plain sentences"}"""

DAILY_SYSTEM = ("You check a household's credit-card activity each morning and flag only "
                "what they would genuinely want to know today.\n\n" + RULES +
                '\n\nRespond with ONLY JSON, no code fences: {"findings": [...]}')

MONTHLY_SYSTEM = ("You write a household's monthly spending review.\n\n" + RULES +
                  "\n\nAlso write a short summary of the month and 2-4 sentences on the most "
                  "meaningful category changes in category_table (ignore tiny categories)."
                  '\n\nRespond with ONLY JSON, no code fences: {"summary": "one sentence", '
                  '"category_commentary": "2-4 sentences", "findings": [...]}')


def ask_claude(system, payload_text):
    import anthropic
    ws = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()
    # identity-linked keys not scoped to one workspace must name the workspace
    client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)
    resp = client.messages.create(model=MODEL, max_tokens=2500, system=system,
                                  messages=[{"role": "user", "content": payload_text}])
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return parse_json(text)


def parse_json(text):
    t = re.sub(r"```(?:json)?", "", text).strip()
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b == -1:
        raise ValueError(f"Model did not return JSON: {text[:200]}")
    data = json.loads(t[a:b + 1])
    data.setdefault("findings", [])
    return data


def tx_lines(rows):
    return "\n".join(["date|merchant|amount|category|card|type"] + [
        f'{r["date"]}|{r["merchant"]}|{r["amount"]}|{r["category"]}|{r["card"]}|{r["type"]}'
        for r in rows])


# ================================================================ email
def send_email(subject, text_body, html_body=None):
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    user, pw = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    to = [x.strip() for x in os.environ["ALERT_TO"].split(",") if x.strip()]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, ", ".join(to)
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(user, pw)
        s.send_message(msg)


SEV = {"high": 0, "medium": 1, "low": 2}
SEV_COLOR = {"high": "#B42318", "medium": "#B54708", "low": "#475467"}
WRAP = "font-family:-apple-system,Segoe UI,sans-serif;max-width:660px;color:#101828"
FOOT = ("<p style='color:#98A2B3;font-size:12px;margin-top:18px'>Sent by your Raspberry Pi. "
        "Only anonymized transactions were shared with the model.</p>")


def _card(f, card_names):
    c = f.get("card") or ""
    return card_names.get(c, c)


def findings_parts(findings, card_names):
    fs = sorted(findings, key=lambda f: SEV.get(f.get("severity"), 3))
    text, html = [], []
    for f in fs:
        kind = (f.get("type") or "").replace("_", " ")
        text.append(f"[{(f.get('severity') or '').upper()}] {kind} — {f.get('merchant','')} "
                    f"{money(f.get('amount'))} {f.get('date','')} {_card(f, card_names)}\n"
                    f"    {f.get('explanation','')}")
        html.append(
            f"<tr><td style='padding:8px;vertical-align:top;font-weight:600;"
            f"color:{SEV_COLOR.get(f.get('severity'), '#475467')}'>{escape((f.get('severity') or '').upper())}</td>"
            f"<td style='padding:8px'><b>{escape(f.get('merchant',''))}</b><br>"
            f"<span style='color:#667085'>{escape(kind)} · {escape(f.get('date',''))} · "
            f"{escape(_card(f, card_names))}</span><br>{escape(f.get('explanation',''))}</td>"
            f"<td style='padding:8px;text-align:right;white-space:nowrap;vertical-align:top'>"
            f"{escape(money(f.get('amount')))}</td></tr>")
    table = ("<table style='border-collapse:collapse;width:100%;border-top:1px solid #EAECF0'>"
             + "".join(html) + "</table>") if html else "<p style='color:#475467'>Nothing unusual.</p>"
    return "\n".join(text) or "Nothing unusual.", table


def render_daily(findings, card_names):
    n = len(findings)
    subject = f"Spending alert: {n} new thing{'s' if n != 1 else ''} to look at"
    t, h = findings_parts(findings, card_names)
    return subject, t, f"<div style='{WRAP}'><h2 style='margin:0 0 12px'>Spending alert</h2>{h}{FOOT}</div>"


def render_monthly(month, result, table, recurring, card_names):
    label = month_label(month)
    findings = result.get("findings", [])
    n = len(findings)
    subject = f"Monthly spending summary · {label}" + (f" · {n} to review" if n else "")
    total = sum(r["this_month"] for r in table)
    prev_total = sum(r["last_month"] for r in table)
    rec_total = sum(p["last_amount"] for p in recurring.values())

    def pct(x):
        return "—" if x is None else f"{x:+d}%"

    t = [f"{label}: {money(total)} net spend (last month {money(prev_total)}).",
         result.get("summary", ""), "", "BY CATEGORY (this month / last month / 6-mo avg / vs avg)"]
    t += [f"  {r['category']:<16} {money(r['this_month']):>11} {money(r['last_month']):>11} "
          f"{money(r['avg_prior']):>11} {pct(r['vs_avg_pct']):>6}" for r in table]
    t += ["", result.get("category_commentary", ""), "",
          f"RECURRING CHARGES: {len(recurring)} detected, about {money(rec_total)}/month", ""]
    ft, fh = findings_parts(findings, card_names)
    t += ["TO REVIEW", ft]

    rows_html = "".join(
        f"<tr><td style='padding:6px 8px'>{escape(r['category'])}</td>"
        f"<td style='padding:6px 8px;text-align:right'>{money(r['this_month'])}</td>"
        f"<td style='padding:6px 8px;text-align:right;color:#667085'>{money(r['last_month'])}</td>"
        f"<td style='padding:6px 8px;text-align:right;color:#667085'>{money(r['avg_prior'])}</td>"
        f"<td style='padding:6px 8px;text-align:right;font-weight:600;color:"
        f"{'#B42318' if (r['vs_avg_pct'] or 0) > 25 else '#027A48' if (r['vs_avg_pct'] or 0) < -25 else '#475467'}'>"
        f"{pct(r['vs_avg_pct'])}</td></tr>" for r in table)
    rec_html = "".join(
        f"<li>{escape(p['merchant'])} — {money(p['last_amount'])} "
        f"<span style='color:#667085'>({escape(_card(p, card_names))})</span></li>"
        for p in sorted(recurring.values(), key=lambda p: -p["last_amount"]))
    th = "padding:6px 8px;text-align:right;color:#667085;font-weight:500"
    html = (
        f"<div style='{WRAP}'><h2 style='margin:0 0 4px'>Monthly summary · {escape(label)}</h2>"
        f"<p style='margin:0 0 4px;font-size:18px'><b>{money(total)}</b> net spend "
        f"<span style='color:#667085'>(last month {money(prev_total)})</span></p>"
        f"<p style='color:#475467;margin:0 0 16px'>{escape(result.get('summary',''))}</p>"
        f"<h3 style='margin:18px 0 6px'>By category</h3>"
        f"<table style='border-collapse:collapse;width:100%;font-size:14px'>"
        f"<tr><th style='padding:6px 8px;text-align:left;color:#667085;font-weight:500'>Category</th>"
        f"<th style='{th}'>This month</th><th style='{th}'>Last month</th>"
        f"<th style='{th}'>6-mo avg</th><th style='{th}'>vs avg</th></tr>{rows_html}</table>"
        f"<p style='color:#344054'>{escape(result.get('category_commentary',''))}</p>"
        f"<h3 style='margin:18px 0 6px'>To review</h3>{fh}"
        f"<h3 style='margin:18px 0 6px'>Recurring charges · about {money(rec_total)}/month</h3>"
        f"<ul style='margin:0;padding-left:18px;color:#344054'>{rec_html or '<li>None detected yet</li>'}</ul>"
        f"{FOOT}</div>")
    return subject, "\n".join(t), html


# ================================================================ state
def load_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("reviewed_months", s.pop("reviewed", []))
    s.setdefault("seen", {})
    return s


def save_state(s):
    cutoff = (date.today() - timedelta(days=200)).isoformat()
    s["seen"] = {k: v for k, v in s["seen"].items() if v >= cutoff}
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=1)


def fail(context, err):
    detail = getattr(err, "body", None) or getattr(err, "message", None)
    if detail and str(detail) not in str(err):
        err = f"{err} — {detail}"
    log(f"{context} failed: {err}")
    try:
        send_email(f"Spending check: {context} could not run",
                   f"The {context} check failed on the Pi:\n\n{err}\n\nSee insights.log.")
    except Exception as e2:  # noqa: BLE001
        log(f"Also failed to send failure email: {e2}")
    return 1


# ================================================================ modes
def run_daily(today, dry_run):
    start = (today - timedelta(days=DAILY_HISTORY_DAYS)).isoformat()
    cut = (today - timedelta(days=DAILY_WINDOW_DAYS)).isoformat()
    rows, card_names = load_rows(start, (today + timedelta(days=1)).isoformat())
    history = [r for r in rows if r["date"] < cut]
    target = [r for r in rows if r["date"] >= cut]
    flags, _ = detect(target, history, today)

    state = load_state()
    new = [f for f in flags if fingerprint(f) not in state["seen"]]
    if dry_run:
        print(f"\n=== DAILY DRY RUN ({today}) — nothing is sent ===")
        print(f"{len(rows)} transactions in history, {len(target)} in the last {DAILY_WINDOW_DAYS} days")
        print(f"{len(flags)} local flags, {len(new)} not seen before:")
        print(json.dumps(new, indent=1))
        print("Card letters stay on the Pi:", card_names)
        return 0
    if not new:
        log("daily: nothing new.")
        return 0

    payload = (f"Today is {today}. Review activity since {cut}; earlier rows are history.\n\n"
               f"local_flags:\n{json.dumps(new, indent=1)}\n\ntransactions:\n{tx_lines(rows)}")
    try:
        result = ask_claude(DAILY_SYSTEM, payload)
    except Exception as e:  # noqa: BLE001
        return fail("daily", e)

    for f in new:  # reviewed = never re-sent, whether Claude kept it or not
        state["seen"][fingerprint(f)] = today.isoformat()
    findings = result["findings"]
    log(f"daily: {len(new)} new flag(s), {len(findings)} finding(s).")
    if findings:
        send_email(*render_daily(findings, card_names))
        log("daily: alert emailed.")
    save_state(state)
    return 0


def run_monthly(month, force, dry_run):
    state = load_state()
    if not dry_run and not force and month in state["reviewed_months"]:
        log(f"monthly: {month} already reviewed — use --force to redo.")
        return 0
    start = month_shift(month, -LOOKBACK_MONTHS) + "-01"
    end = month_shift(month, 1) + "-01"
    rows, card_names = load_rows(start, end)
    target = [r for r in rows if r["date"].startswith(month)]
    if not target:
        log(f"monthly: no transactions for {month}.")
        return 0
    history = [r for r in rows if r["date"] < month + "-01"]
    month_end = d(end) - timedelta(days=1)
    flags, recurring = detect(target, history, month_end)
    table = category_table(rows, month)

    if dry_run:
        print(f"\n=== MONTHLY DRY RUN ({month}) — nothing is sent ===")
        print(f"{len(rows)} transactions ({len(target)} in {month}), {len(flags)} local flags")
        print("\ncategory_table:")
        for r in table:
            print(f"  {r['category']:<16} {r['this_month']:>10} {r['last_month']:>10} "
                  f"{r['avg_prior']:>10}  {r['vs_avg_pct']}")
        print("\nrecurring:", json.dumps(list(recurring.values()), indent=1))
        print("\nlocal_flags:", json.dumps(flags, indent=1))
        print("\nCard letters stay on the Pi:", card_names)
        return 0

    payload = (f"Month under review: {month}. Earlier months are baseline history.\n\n"
               f"category_table:\n{json.dumps(table, indent=1)}\n\n"
               f"recurring_charges:\n{json.dumps(list(recurring.values()), indent=1)}\n\n"
               f"local_flags:\n{json.dumps(flags, indent=1)}\n\ntransactions:\n{tx_lines(rows)}")
    try:
        result = ask_claude(MONTHLY_SYSTEM, payload)
    except Exception as e:  # noqa: BLE001
        return fail("monthly", e)

    send_email(*render_monthly(month, result, table, recurring, card_names))
    log(f"monthly: {month} summary emailed ({len(result['findings'])} finding(s)).")
    state["reviewed_months"].append(month)
    save_state(state)
    return 0


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--daily", action="store_true")
    mode.add_argument("--monthly", action="store_true")
    mode.add_argument("--test-email", action="store_true")
    ap.add_argument("--month", help="YYYY-MM for --monthly (default: last full month)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today", help=argparse.SUPPRESS)  # testing only
    args = ap.parse_args()

    today = d(args.today) if args.today else date.today()
    if args.test_email:
        send_email("Spending check · test", "If you can read this, alerts from the Pi work.")
        log("Test email sent.")
        return 0
    if args.daily:
        return run_daily(today, args.dry_run)
    month = args.month or month_shift(today.strftime("%Y-%m"), -1)
    return run_monthly(month, args.force, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
