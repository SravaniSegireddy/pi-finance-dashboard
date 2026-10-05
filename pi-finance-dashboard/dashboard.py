"""
dashboard.py — turns a list of normalized transactions into a single
self-contained HTML file.

Each transaction now carries a "flow":
    "spend"   — a purchase (positive amount)
    "refund"  — money returned for a purchase (negative amount). Nets against
                spend in the main totals AND is itemized in a Refunds section.
    "payment" — paying off the card balance (negative amount). NEVER netted
                into spend; shown separately so a payoff is always visible.

If "flow" is missing it is inferred (amount < 0 -> refund, else spend) for
backward compatibility.

A transaction is a dict:
    {
      "date":     "2026-05-14",
      "amount":   42.13,          # signed: spend > 0, refund/payment < 0
      "name":     "WHOLEFDS MKT 10",
      "merchant": "Whole Foods",
      "category": "Groceries",
      "account":  "Amex Gold",
      "issuer":   "Amex",
      "flow":     "spend"
    }
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ISSUER_HUES = {
    "Amex": "#3A6EA5",
    "Capital One": "#9B3B34",
    "Chase": "#1F6FB2",
    "Wells Fargo": "#B8893A",
}
DEFAULT_HUE = "#6B7780"


def _fmt_dt(dt):
    """Format like 'Jun 24, 2026 at 9:05 PM PDT' without platform-specific
    strftime codes (%-d / %-I are invalid on Windows)."""
    if not hasattr(dt, "strftime"):
        return str(dt)
    try:
        hour12 = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        tz = dt.strftime("%Z")
        base = f"{dt.strftime('%b')} {dt.day}, {dt.year} at {hour12}:{dt.minute:02d} {ampm}"
        return base + (f" {tz}" if tz else "")
    except Exception:
        return str(dt)


def build_dashboard(transactions, out_path, generated_at=None, meta=None):
    generated_at = generated_at or datetime.now(timezone.utc).astimezone()
    meta = meta or {}

    clean = []
    for t in transactions:
        try:
            amt = float(t["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        if amt == 0:
            continue
        flow = t.get("flow")
        if flow not in ("spend", "refund", "payment"):
            flow = "refund" if amt < 0 else "spend"
        issuer = t.get("issuer") or "Other"
        clean.append({
            "date": str(t["date"])[:10],
            "amount": round(amt, 2),
            "name": str(t.get("name") or t.get("merchant") or "Transaction"),
            "merchant": str(t.get("merchant") or t.get("name") or "Transaction"),
            "category": str(t.get("category") or "Uncategorized"),
            "account": str(t.get("account") or issuer),
            "issuer": issuer,
            "flow": flow,
        })
    clean.sort(key=lambda r: r["date"], reverse=True)

    payload = {
        "transactions": clean,
        "issuerHues": ISSUER_HUES,
        "defaultHue": DEFAULT_HUE,
        "generatedAt": _fmt_dt(generated_at),
        "title": meta.get("title", "Household Spend"),
        "subtitle": meta.get("subtitle", ""),
    }

    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    doc = _TEMPLATE.replace("/*__DATA__*/", data_json)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return str(out)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Household Spend</title>
<style>
  :root{
    --bg:#FAFBFC; --surface:#FFFFFF; --ink:#10171D; --muted:#61707A;
    --faint:#8A97A0; --hair:#E6EBEF; --hair-strong:#D6DEE4;
    --accent:#0E7C66; --accent-soft:#E3F1ED; --alert:#C0492F; --alert-soft:#F7E7E2;
    --pay:#2C5A8A; --pay-soft:#E7EEF6;
    --shadow:0 1px 2px rgba(16,23,29,.04), 0 8px 24px -16px rgba(16,23,29,.22);
    --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,Roboto,Helvetica,Arial,sans-serif;
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
    font-size:15px;line-height:1.5;letter-spacing:-.005em;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1040px;margin:0 auto;padding:40px 24px 80px}
  .num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
  .eyebrow{font-family:var(--serif);font-style:italic;color:var(--accent);
    font-size:14px;letter-spacing:.01em;margin:0 0 6px}
  .muted{color:var(--muted)} .faint{color:var(--faint)}

  header{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap;margin-bottom:8px}
  h1{font-family:var(--serif);font-weight:600;font-size:30px;line-height:1.1;margin:0;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:13.5px;margin-top:4px}
  .picker{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
  .filter{display:flex;flex-direction:column;gap:5px}
  .filter label{font-size:11px;color:var(--faint);text-transform:uppercase;letter-spacing:.08em}
  select{font-family:var(--sans);font-size:14px;color:var(--ink);background:var(--surface);
    border:1px solid var(--hair-strong);border-radius:8px;padding:8px 30px 8px 12px;appearance:none;cursor:pointer;max-width:200px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6'><path d='M1 1l4 4 4-4' fill='none' stroke='%2361707A' stroke-width='1.5'/></svg>");
    background-repeat:no-repeat;background-position:right 11px center}
  select:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
  select.on{border-color:var(--accent);background-color:var(--accent-soft)}

  .filterbar{font-size:12.5px;color:var(--muted);margin:14px 0 2px;min-height:18px}
  .filterbar .chip{display:inline-flex;align-items:center;gap:6px;background:var(--accent-soft);color:var(--accent);
    border-radius:999px;padding:3px 6px 3px 11px;margin-right:8px;font-weight:550}
  .filterbar .chip button{border:0;background:transparent;color:var(--accent);cursor:pointer;font-size:14px;line-height:1;padding:0 3px;border-radius:50%}
  .filterbar .chip button:hover{background:rgba(14,124,102,.18)}
  .filterbar .clear{color:var(--faint);text-decoration:underline;cursor:pointer;background:0;border:0;font:inherit}

  .hero{background:var(--surface);border:1px solid var(--hair);border-radius:14px;box-shadow:var(--shadow);
    padding:26px 28px;margin:10px 0 16px;display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,360px);gap:28px;align-items:center}
  .hero .total-label{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint)}
  .hero .total{font-size:46px;font-weight:650;line-height:1;margin:6px 0 10px;letter-spacing:-.02em}
  .delta{display:inline-flex;align-items:center;gap:6px;font-size:13.5px;font-weight:550;padding:4px 10px;border-radius:999px}
  .delta.up{background:var(--alert-soft);color:var(--alert)}
  .delta.down{background:var(--accent-soft);color:var(--accent)}
  .delta.flat{background:#EEF2F4;color:var(--muted)}
  .breakdown{font-size:12.5px;color:var(--muted);margin-top:12px;display:flex;gap:14px;flex-wrap:wrap}
  .breakdown b{font-weight:600;color:var(--ink)}
  .breakdown .sep{color:var(--hair-strong)}
  .spark{width:100%;height:84px;display:block}
  .spark-cap{font-size:11.5px;color:var(--faint);text-align:right;margin-top:2px}

  .kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:16px}
  .kpi{background:var(--surface);border:1px solid var(--hair);border-radius:12px;padding:16px 18px}
  .kpi .k-label{font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--faint)}
  .kpi .k-val{font-size:24px;font-weight:600;margin-top:5px;letter-spacing:-.01em}
  .kpi .k-sub{font-size:12.5px;color:var(--muted);margin-top:2px}

  .panel{background:var(--surface);border:1px solid var(--hair);border-radius:12px;padding:20px 22px;margin-bottom:16px}
  .panel h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);font-weight:600;margin:0 0 16px;
    display:flex;justify-content:space-between;align-items:baseline;gap:10px}
  .panel h2 .tag{font-size:12px;letter-spacing:0;text-transform:none;font-weight:500}
  .tag.refund{color:var(--alert)} .tag.pay{color:var(--pay)}
  .cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  @media(max-width:760px){
    .hero{grid-template-columns:1fr}.kpis{grid-template-columns:1fr}.cols{grid-template-columns:1fr!important}
    h1{font-size:25px}.hero .total{font-size:38px}select{max-width:46vw}}

  .months{display:flex;align-items:flex-end;gap:6px;height:150px;padding-top:6px}
  .mbar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:6px;cursor:pointer;min-width:0}
  .mbar .bar{width:100%;max-width:34px;background:var(--hair-strong);border-radius:5px 5px 2px 2px;transition:background .15s}
  .mbar.active .bar{background:var(--accent)}
  .mbar:hover .bar{background:#9FB0B8}.mbar.active:hover .bar{background:var(--accent)}
  .mbar .mlab{font-size:10px;color:var(--faint);white-space:nowrap}

  .row{display:grid;grid-template-columns:1fr;gap:9px}
  .barrow{display:grid;grid-template-columns:118px 1fr auto;align-items:center;gap:12px}
  .barrow .rl{font-size:13px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .track{height:9px;background:#EFF3F5;border-radius:999px;overflow:hidden}
  .fill{height:100%;border-radius:999px;background:var(--accent)}
  .barrow .rv{font-size:13px;color:var(--muted);white-space:nowrap}
  .barrow .rv.neg{color:var(--alert)}
  .dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:7px;vertical-align:middle}

  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th{text-align:left;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);font-weight:600;
    padding:0 12px 10px 0;border-bottom:1px solid var(--hair)}
  th.r,td.r{text-align:right;padding-right:0}
  td{padding:11px 12px 11px 0;border-bottom:1px solid var(--hair)}
  tr:last-child td{border-bottom:none}
  .merch{font-weight:500}
  .cat-chip{font-size:11.5px;color:var(--muted);background:#F2F5F7;border-radius:6px;padding:2px 8px;white-space:nowrap}
  .amt-neg{color:var(--alert)} .amt-pay{color:var(--pay)}
  .empty{color:var(--faint);font-size:13.5px;padding:18px 0;text-align:center}
  .ct{font-size:13px} .ct td{padding:9px 10px 9px 0}
  .more{font-size:12px;color:var(--faint);margin-top:12px}

  footer{margin-top:26px;font-size:12px;color:var(--faint);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
  @media (prefers-reduced-motion: reduce){*{transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <p class="eyebrow">Statement</p>
      <h1 id="title">Household Spend</h1>
      <div class="sub" id="subtitle"></div>
    </div>
    <div class="picker">
      <div class="filter"><label for="from">From</label><select id="from" aria-label="From month"></select></div>
      <div class="filter"><label for="to">To</label><select id="to" aria-label="To month"></select></div>
      <div class="filter"><label for="card">Card</label><select id="card" aria-label="Card"></select></div>
      <div class="filter"><label for="category">Category</label><select id="category" aria-label="Category"></select></div>
    </div>
  </header>

  <div class="filterbar" id="filterbar"></div>

  <section class="hero">
    <div>
      <div class="total-label" id="total-label">Net spend</div>
      <div class="total num" id="total">$0</div>
      <span class="delta flat" id="delta">—</span>
      <div class="breakdown" id="breakdown"></div>
    </div>
    <div>
      <svg class="spark" id="spark" viewBox="0 0 360 84" preserveAspectRatio="none" aria-hidden="true"></svg>
      <div class="spark-cap" id="sparkcap"></div>
    </div>
  </section>

  <section class="kpis">
    <div class="kpi"><div class="k-label">Purchases</div><div class="k-val num" id="k-txns">0</div><div class="k-sub" id="k-txns-sub"></div></div>
    <div class="kpi"><div class="k-label">Avg / month (net)</div><div class="k-val num" id="k-avg">$0</div><div class="k-sub" id="k-avg-sub">trailing average</div></div>
    <div class="kpi"><div class="k-label" id="k-cat-label">Largest category</div><div class="k-val" id="k-cat">—</div><div class="k-sub num" id="k-cat-sub"></div></div>
  </section>

  <section class="panel">
    <h2 id="monthsTitle">Net spend by month</h2>
    <div class="months" id="months"></div>
  </section>

  <div class="cols" id="catCardRow">
    <section class="panel" id="catPanel"><h2>By category <span class="tag faint">net</span></h2><div class="row" id="byCategory"></div></section>
    <section class="panel" id="cardPanel"><h2>By card <span class="tag faint">net</span></h2><div class="row" id="byCard"></div></section>
  </div>

  <div class="cols">
    <section class="panel">
      <h2>Refunds <span class="tag refund" id="refundTag"></span></h2>
      <table class="ct"><tbody id="refundBody"></tbody></table>
    </section>
    <section class="panel">
      <h2>Payments <span class="tag pay" id="payTag"></span></h2>
      <table class="ct"><tbody id="payBody"></tbody></table>
    </section>
  </div>

  <section class="panel">
    <h2>Top merchants <span class="tag faint">net spend</span></h2>
    <table id="merchTable"><tbody></tbody></table>
  </section>

  <section class="panel">
    <h2>Purchases <span class="tag faint" id="purchCount"></span></h2>
    <table id="txnTable">
      <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Card</th><th class="r">Amount</th></tr></thead>
      <tbody></tbody>
    </table>
    <div class="more" id="purchMore"></div>
  </section>

  <footer>
    <span>Generated <span id="genAt"></span> · net = purchases − refunds · payments shown separately</span>
    <span>Spend dashboard · runs locally</span>
  </footer>
</div>

<script id="data" type="application/json">/*__DATA__*/</script>
<script>
(function(){
  "use strict";
  var DATA=JSON.parse(document.getElementById("data").textContent);
  var TX=DATA.transactions;
  var USD0=function(n){return (n<0?"-$":"$")+Math.round(Math.abs(n)).toLocaleString("en-US");};
  var USD2=function(n){return (n<0?"-$":"$")+Math.abs(n).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});};
  var esc=function(s){var d=document.createElement("div");d.textContent=s;return d.innerHTML;};
  var hueFor=function(iss){return DATA.issuerHues[iss]||DATA.defaultHue;};
  var MN=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var uniq=function(a){return a.filter(function(v,i){return a.indexOf(v)===i;});};
  var label=function(m){var p=m.split("-");return MN[+p[1]-1]+" "+p[0];};
  var labelShort=function(m){return MN[+m.split("-")[1]-1];};

  document.getElementById("title").textContent=DATA.title;
  document.getElementById("subtitle").textContent=DATA.subtitle;
  document.getElementById("genAt").textContent=DATA.generatedAt;

  if(TX.length===0){
    document.querySelector(".wrap").innerHTML='<p class="empty">No transactions yet. Run a sync once your cards are linked.</p>';return;}

  var allMonths=uniq(TX.map(function(t){return t.date.slice(0,7);})).sort();
  var allCards=uniq(TX.map(function(t){return t.account;})).sort();
  var allCats=uniq(TX.filter(function(t){return t.flow!=="payment";}).map(function(t){return t.category;})).sort();

  var fromEl=document.getElementById("from"),toEl=document.getElementById("to"),cardEl=document.getElementById("card"),catEl=document.getElementById("category");
  function opt(el,val,txt){var o=document.createElement("option");o.value=val;o.textContent=txt;el.appendChild(o);}
  allMonths.slice().reverse().forEach(function(m){opt(fromEl,m,label(m));opt(toEl,m,label(m));});
  opt(cardEl,"ALL","All cards");allCards.forEach(function(c){opt(cardEl,c,c);});
  opt(catEl,"ALL","All categories");allCats.forEach(function(c){opt(catEl,c,c);});

  // default range: trailing 12 months (or whole history if shorter)
  var toSel=allMonths[allMonths.length-1];
  var fromSel=allMonths[Math.max(0,allMonths.length-12)];
  var cardSel="ALL",catSel="ALL";
  fromEl.value=fromSel;toEl.value=toSel;cardEl.value="ALL";catEl.value="ALL";

  fromEl.addEventListener("change",function(){
    fromSel=fromEl.value;
    if(fromSel>toSel){toSel=fromSel;toEl.value=toSel;}  // keep range valid
    render();});
  toEl.addEventListener("change",function(){
    toSel=toEl.value;
    if(toSel<fromSel){fromSel=toSel;fromEl.value=fromSel;}
    render();});
  cardEl.addEventListener("change",function(){cardSel=cardEl.value;render();});
  catEl.addEventListener("change",function(){catSel=catEl.value;render();});

  function matchCardCat(t){
    if(cardSel!=="ALL"&&t.account!==cardSel)return false;
    if(catSel!=="ALL"&&t.category!==catSel)return false;
    return true;
  }

  function render(){
    var rangeNarrowed=(fromSel!==allMonths[0]||toSel!==allMonths[allMonths.length-1]);
    document.getElementById("from").classList.toggle("on",rangeNarrowed);
    document.getElementById("to").classList.toggle("on",rangeNarrowed);
    [["card",cardSel],["category",catSel]].forEach(function(p){
      document.getElementById(p[0]).classList.toggle("on",p[1]!=="ALL");});

    // active-filter chips
    var fb=document.getElementById("filterbar");fb.innerHTML="";
    var chips=[];
    if(cardSel!=="ALL")chips.push(["card",cardSel]);
    if(catSel!=="ALL")chips.push(["category",catSel]);
    if(chips.length){
      chips.forEach(function(c){
        var s=document.createElement("span");s.className="chip";
        s.innerHTML=esc(c[1])+' <button title="Clear" data-f="'+c[0]+'">×</button>';
        fb.appendChild(s);});
      var clr=document.createElement("button");clr.className="clear";clr.textContent="clear filters";
      clr.onclick=function(){cardSel="ALL";catSel="ALL";cardEl.value="ALL";catEl.value="ALL";render();};
      fb.appendChild(clr);
      fb.querySelectorAll("button[data-f]").forEach(function(b){
        b.onclick=function(){var f=b.getAttribute("data-f");
          if(f==="card"){cardSel="ALL";cardEl.value="ALL";}else{catSel="ALL";catEl.value="ALL";}render();};});
    }

    var ccTx=TX.filter(matchCardCat);
    var netByMonth={};
    ccTx.forEach(function(t){var m=t.date.slice(0,7);netByMonth[m]=(netByMonth[m]||0)+(t.flow==="payment"?0:t.amount);});
    var netOf=function(m){return netByMonth[m]||0;};

    var chartMonths=allMonths.filter(function(m){return m>=fromSel&&m<=toSel;});
    if(!chartMonths.length)chartMonths=[toSel];

    var scope=ccTx.filter(function(t){var m=t.date.slice(0,7);return m>=fromSel&&m<=toSel;});
    var spend=scope.filter(function(t){return t.flow==="spend";});
    var refunds=scope.filter(function(t){return t.flow==="refund";});
    var payments=scope.filter(function(t){return t.flow==="payment";});
    var gross=spend.reduce(function(s,t){return s+t.amount;},0);
    var refundTotal=refunds.reduce(function(s,t){return s+(-t.amount);},0);
    var payTotal=payments.reduce(function(s,t){return s+(-t.amount);},0);
    var netTotal=gross-refundTotal;

    document.getElementById("total-label").textContent=(catSel!=="ALL"?catSel+" — net":"Net spend");
    document.getElementById("total").textContent=USD0(netTotal);
    document.getElementById("breakdown").innerHTML=
      'Gross <b class="num">'+USD0(gross)+'</b>'+
      '<span class="sep">·</span>Refunds <b class="num amt-neg">'+USD0(-refundTotal)+'</b>'+
      '<span class="sep">·</span>Payments <b class="num amt-pay">'+USD0(payTotal)+'</b> paid';

    // delta vs the equally-long preceding period (e.g. last 6 mo vs prior 6 mo)
    var dEl=document.getElementById("delta");
    var len=chartMonths.length, iFrom=allMonths.indexOf(fromSel);
    var prevMonths=allMonths.slice(Math.max(0,iFrom-len),iFrom);
    var oneMonth=(len===1);
    if(prevMonths.length===len && len>0){
      var prevNet=prevMonths.reduce(function(s,m){return s+netOf(m);},0);
      if(prevNet>0){
        var pct=(netTotal-prevNet)/prevNet*100, up=pct>=0;
        dEl.className="delta "+(Math.abs(pct)<0.5?"flat":(up?"up":"down"));
        dEl.innerHTML=(Math.abs(pct)<0.5?"●":(up?"▲":"▼"))+" "+Math.abs(pct).toFixed(pct>=10?0:1)+"% vs "+
          (oneMonth?labelShort(prevMonths[0]):("prior "+len+" mo"));
      }else{dEl.className="delta flat";dEl.textContent=label(fromSel)+(len>1?" – "+label(toSel):"");}
    }else{
      dEl.className="delta flat";
      dEl.textContent=label(fromSel)+(len>1?" – "+label(toSel):"");
    }

    // sparkline over chartMonths
    var spw=360,sph=84,pad=6;
    var vals=chartMonths.map(netOf);
    var hi=Math.max.apply(null,vals),lo=Math.min(0,Math.min.apply(null,vals)),rng=(hi-lo)||1;
    var pts=chartMonths.map(function(m,k){
      var x=chartMonths.length>1?pad+k*(spw-2*pad)/(chartMonths.length-1):spw/2;
      var y=sph-pad-((netOf(m)-lo)/rng)*(sph-2*pad);return [x,y];});
    var d=pts.map(function(p,k){return (k?"L":"M")+p[0].toFixed(1)+" "+p[1].toFixed(1);}).join(" ");
    var area=d+" L"+pts[pts.length-1][0].toFixed(1)+" "+(sph-pad)+" L"+pts[0][0].toFixed(1)+" "+(sph-pad)+" Z";
    var last=pts[pts.length-1];
    document.getElementById("spark").innerHTML=
      '<path d="'+area+'" fill="rgba(14,124,102,.10)"/>'+
      '<path d="'+d+'" fill="none" stroke="#0E7C66" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'+
      '<circle cx="'+last[0].toFixed(1)+'" cy="'+last[1].toFixed(1)+'" r="3.2" fill="#0E7C66"/>';
    document.getElementById("sparkcap").textContent=
      (chartMonths.length>1?labelShort(chartMonths[0])+" – "+labelShort(chartMonths[chartMonths.length-1]):"")+" · net";

    // kpis
    document.getElementById("k-txns").textContent=spend.length.toLocaleString("en-US");
    document.getElementById("k-txns-sub").textContent=spend.length?USD2(gross/spend.length)+" avg purchase":"—";
    var avg=chartMonths.reduce(function(s,m){return s+netOf(m);},0)/(chartMonths.length||1);
    document.getElementById("k-avg").textContent=USD0(avg);
    document.getElementById("k-avg-sub").textContent="over "+chartMonths.length+(chartMonths.length===1?" month":" months");

    var catMap={};
    spend.forEach(function(t){catMap[t.category]=(catMap[t.category]||0)+t.amount;});
    refunds.forEach(function(t){catMap[t.category]=(catMap[t.category]||0)+t.amount;});
    var cats=Object.keys(catMap).map(function(c){return [c,catMap[c]];}).sort(function(a,b){return b[1]-a[1];});
    var kCatLabel=document.getElementById("k-cat-label");
    if(catSel!=="ALL"){
      kCatLabel.textContent="Selected category";
      document.getElementById("k-cat").textContent=catSel;
      document.getElementById("k-cat-sub").textContent=USD0(netTotal);
    }else if(cats.length&&cats[0][1]>0){
      kCatLabel.textContent="Largest category";
      document.getElementById("k-cat").textContent=cats[0][0];
      document.getElementById("k-cat-sub").textContent=USD0(cats[0][1])+(netTotal>0?" · "+Math.round(cats[0][1]/netTotal*100)+"%":"");
    }else{kCatLabel.textContent="Largest category";document.getElementById("k-cat").textContent="—";document.getElementById("k-cat-sub").textContent="";}

    // monthly bars
    document.getElementById("monthsTitle").textContent="Net spend by month"+(catSel!=="ALL"?" · "+catSel:"")+(cardSel!=="ALL"?" · "+cardSel:"");
    var mWrap=document.getElementById("months");mWrap.innerHTML="";
    var mMax=Math.max.apply(null,chartMonths.map(netOf));mMax=mMax>0?mMax:1;
    var step=Math.ceil(chartMonths.length/14);  // keep labels readable on long ranges
    chartMonths.forEach(function(m,mi){
      var h=Math.max(3,(netOf(m)>0?netOf(m)/mMax:0)*120);
      var show=(chartMonths.length<=14)||(mi%step===0)||(mi===chartMonths.length-1);
      var lab=show?(m.slice(5)==="01"?"’"+m.slice(2,4):labelShort(m)):"";
      var el=document.createElement("div");el.className="mbar"+((fromSel===m&&toSel===m)?" active":"");
      el.title=label(m)+" · "+USD0(netOf(m));
      el.innerHTML='<div class="bar" style="height:'+h.toFixed(0)+'px"></div><div class="mlab">'+lab+'</div>';
      el.addEventListener("click",function(){fromSel=m;toSel=m;fromEl.value=m;toEl.value=m;render();});
      mWrap.appendChild(el);});

    // category / card panels with redundancy handling
    var showCat=(catSel==="ALL"),showCard=(cardSel==="ALL");
    var row=document.getElementById("catCardRow");
    document.getElementById("catPanel").style.display=showCat?"":"none";
    document.getElementById("cardPanel").style.display=showCard?"":"none";
    if(!showCat&&!showCard){row.style.display="none";}
    else{row.style.display="grid";row.style.gridTemplateColumns=(showCat&&showCard)?"1fr 1fr":"1fr";}
    if(showCat)renderBars("byCategory",cats.slice(0,10).map(function(c){return {label:c[0],val:c[1],hue:"#0E7C66"};}),netTotal,false);
    if(showCard){
      var cardMap={};
      spend.forEach(function(t){cardMap[t.account]=cardMap[t.account]||{val:0,issuer:t.issuer};cardMap[t.account].val+=t.amount;});
      refunds.forEach(function(t){cardMap[t.account]=cardMap[t.account]||{val:0,issuer:t.issuer};cardMap[t.account].val+=t.amount;});
      var cards=Object.keys(cardMap).map(function(k){return {label:k,val:cardMap[k].val,hue:hueFor(cardMap[k].issuer)};}).sort(function(a,b){return b.val-a.val;});
      renderBars("byCard",cards,netTotal,true);
    }

    // refunds
    var rTag=document.getElementById("refundTag"),rBody=document.getElementById("refundBody");
    rTag.textContent=refunds.length?(refunds.length+(refunds.length===1?" return · ":" returns · ")+USD0(-refundTotal)):"";
    rBody.innerHTML="";
    if(!refunds.length){rBody.innerHTML='<tr><td class="empty">No refunds for this view.</td></tr>';}
    refunds.slice().sort(function(a,b){return a.date<b.date?1:-1;}).slice(0,40).forEach(function(t){
      var p=t.date.split("-");var tr=document.createElement("tr");
      tr.innerHTML='<td class="num faint">'+labelShort(t.date)+" "+(+p[2])+'</td>'+
        '<td class="merch"><span class="dot" style="background:'+hueFor(t.issuer)+'"></span>'+esc(t.merchant)+' <span class="cat-chip">'+esc(t.category)+'</span></td>'+
        '<td class="r num amt-neg">'+USD2(t.amount)+'</td>';rBody.appendChild(tr);});

    // payments
    var pTag=document.getElementById("payTag"),pBody=document.getElementById("payBody");
    pTag.textContent=payments.length?(payments.length+(payments.length===1?" payment · ":" payments · ")+USD0(payTotal)+" paid"):"";
    pBody.innerHTML="";
    if(!payments.length){pBody.innerHTML='<tr><td class="empty">'+(catSel!=="ALL"?"Payments aren\u2019t category-specific.":"No payments for this view.")+'</td></tr>';}
    payments.slice().sort(function(a,b){return a.date<b.date?1:-1;}).slice(0,40).forEach(function(t){
      var p=t.date.split("-");var tr=document.createElement("tr");
      tr.innerHTML='<td class="num faint">'+labelShort(t.date)+" "+(+p[2])+'</td>'+
        '<td class="merch"><span class="dot" style="background:'+hueFor(t.issuer)+'"></span>'+esc(t.merchant)+'</td>'+
        '<td class="r num amt-pay">'+USD2(-t.amount)+'</td>';pBody.appendChild(tr);});

    // top merchants
    var mm={};
    spend.forEach(function(t){mm[t.merchant]=mm[t.merchant]||{val:0,n:0,cat:t.category};mm[t.merchant].val+=t.amount;mm[t.merchant].n++;});
    refunds.forEach(function(t){if(mm[t.merchant])mm[t.merchant].val+=t.amount;});
    var merchants=Object.keys(mm).map(function(k){return [k,mm[k]];}).filter(function(m){return m[1].val>0;}).sort(function(a,b){return b[1].val-a[1].val;}).slice(0,10);
    var mt=document.querySelector("#merchTable tbody");mt.innerHTML="";
    if(!merchants.length){mt.innerHTML='<tr><td class="empty" colspan="3">No spend for this view.</td></tr>';}
    merchants.forEach(function(m){var tr=document.createElement("tr");
      tr.innerHTML='<td class="merch">'+esc(m[0])+'</td>'+
        '<td><span class="cat-chip">'+esc(m[1].cat)+'</span> <span class="faint num">×'+m[1].n+'</span></td>'+
        '<td class="r num">'+USD2(m[1].val)+'</td>';mt.appendChild(tr);});

    // purchases table (cap 100 with a note)
    var tb=document.querySelector("#txnTable tbody");tb.innerHTML="";
    var sorted=spend.slice().sort(function(a,b){return a.date<b.date?1:-1;});
    document.getElementById("purchCount").textContent=sorted.length?sorted.length+" total":"";
    var shown=sorted.slice(0,100);
    if(!shown.length){tb.innerHTML='<tr><td class="empty" colspan="5">No purchases for this view.</td></tr>';}
    shown.forEach(function(t){var p=t.date.split("-");var tr=document.createElement("tr");
      tr.innerHTML='<td class="num faint">'+labelShort(t.date)+" "+(+p[2])+'</td>'+
        '<td class="merch">'+esc(t.merchant)+'</td>'+
        '<td><span class="cat-chip">'+esc(t.category)+'</span></td>'+
        '<td><span class="dot" style="background:'+hueFor(t.issuer)+'"></span>'+esc(t.account)+'</td>'+
        '<td class="r num">'+USD2(t.amount)+'</td>';tb.appendChild(tr);});
    document.getElementById("purchMore").textContent=sorted.length>100?("Showing first 100 of "+sorted.length+" — narrow the range or a filter to see the rest."):"";
  }

  function renderBars(id,items,total,showDot){
    var wrap=document.getElementById(id);wrap.innerHTML="";
    if(!items.length){wrap.innerHTML='<div class="empty">No spend for this view.</div>';return;}
    var max=Math.max.apply(null,items.map(function(i){return Math.abs(i.val);}))||1;
    items.forEach(function(it){
      var pct=total>0?Math.round(it.val/total*100):0;
      var w=it.val>0?it.val/max*100:0,neg=it.val<0;
      var r=document.createElement("div");r.className="barrow";
      r.innerHTML='<div class="rl">'+(showDot?'<span class="dot" style="background:'+it.hue+'"></span>':'')+esc(it.label)+'</div>'+
        '<div class="track"><div class="fill" style="width:'+w.toFixed(1)+'%;background:'+(neg?"#C0492F":(it.hue||"#0E7C66"))+'"></div></div>'+
        '<div class="rv num'+(neg?' neg':'')+'">'+USD0(it.val)+(total>0&&!neg?' · '+pct+'%':'')+'</div>';
      wrap.appendChild(r);});
  }

  render();
})();
</script>
</body>
</html>
"""
