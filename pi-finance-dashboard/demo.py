"""demo.py — build docs/demo.html from FAKE transactions, so anyone can see the
dashboard without a Plaid account:   python demo.py"""
import os
import random
from datetime import date, timedelta

from dashboard import build_dashboard

random.seed(7)
CARDS = [("Card A", "Bank One"), ("Card B", "Bank Two"), ("Card C", "Bank Three")]
SPEND = [("Grocery Mart", "Groceries", 40, 160, 6), ("Corner Cafe", "Dining", 6, 18, 8),
         ("Pizza Place", "Dining", 20, 60, 3), ("Fuel Stop", "Transportation", 35, 70, 3),
         ("Power & Light Co", "Utilities", 80, 140, 1), ("Mobile Carrier", "Utilities", 65, 65, 1),
         ("StreamFlix", "Entertainment", 15.49, 15.49, 1), ("Home Store", "Home", 25, 220, 1),
         ("Online Shop", "Shopping", 12, 150, 4), ("City Pharmacy", "Health", 8, 45, 1)]

rows, start = [], date.today().replace(day=1) - timedelta(days=330)
for m in range(12):
    month = (start + timedelta(days=31 * m)).replace(day=1)
    for merchant, cat, lo, hi, n in SPEND:
        for _ in range(n):
            label, issuer = random.choice(CARDS)
            d = month + timedelta(days=random.randint(0, 27))
            rows.append({"date": d.isoformat(), "amount": round(random.uniform(lo, hi), 2),
                         "name": merchant, "merchant": merchant, "category": cat,
                         "account": label, "issuer": issuer, "flow": "spend"})
    if m % 3 == 0:
        rows.append({"date": (month + timedelta(days=12)).isoformat(), "amount": -round(random.uniform(15, 80), 2),
                     "name": "Online Shop", "merchant": "Online Shop", "category": "Shopping",
                     "account": "Card B", "issuer": "Bank Two", "flow": "refund"})
    for label, issuer in CARDS:
        rows.append({"date": (month + timedelta(days=20)).isoformat(), "amount": -round(random.uniform(400, 1200), 2),
                     "name": "Payment - thank you", "merchant": "Payment", "category": "Payment",
                     "account": label, "issuer": issuer, "flow": "payment"})

os.makedirs("docs", exist_ok=True)
out = build_dashboard(rows, "docs/demo.html",
                      meta={"title": "Household Spend (demo)", "subtitle": "Sample data — not real transactions"})
print("Wrote", out)
