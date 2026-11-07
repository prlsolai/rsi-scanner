"""
Weekly RSI Scanner - Nifty 500
Run every Saturday (after weekly candle completes). Produces weekly_scanner.html

Setup:  pip install yfinance pandas requests
Run:    python weekly_rsi_scanner.py
Cron:   0 19 * * 6  python /path/weekly_rsi_scanner.py   (Saturday 7 PM)

Rules
  Signal  : Weekly RSI(14) crossed above 60 (previous week <= 60, last week > 60)
  Entry   : Weekly close of the signal week
  Stoploss: Weekly SMA(20)  -> exit if a weekly candle CLOSES below it
  Qty     : floor(RISK / (entry - SMA20))   with RISK = Rs. 500 per stock
"""
import io, json, datetime as dt
import pandas as pd, requests, yfinance as yf

RISK, RSI_LEN, SMA_LEN, LEVEL = 500, 14, 20, 60
MIN_CAPITAL = 5000   # drop stocks needing less than this capital
URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
import os
os.makedirs("docs", exist_ok=True)
OUT = "docs/index.html"


def get_symbols():
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))[["Symbol", "Company Name", "Industry"]]


def rsi(close, n=RSI_LEN):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def scan():
    meta = get_symbols()
    syms = meta["Symbol"].tolist()
    info = meta.set_index("Symbol")
    today = dt.date.today()
    rows = []
    for i in range(0, len(syms), 50):
        batch = syms[i:i + 50]
        data = yf.download([s + ".NS" for s in batch], period="3y", interval="1wk",
                           auto_adjust=True, group_by="ticker", progress=False, threads=True)
        for s in batch:
            try:
                df = data[s + ".NS"].dropna(subset=["Close"])
                # drop the running (incomplete) week
                if len(df) and today < (df.index[-1].date() + dt.timedelta(days=5)):
                    df = df.iloc[:-1]
                if len(df) < SMA_LEN + RSI_LEN + 2:
                    continue
                c = df["Close"]
                r = rsi(c)
                sma = c.rolling(SMA_LEN).mean()
                if not (r.iloc[-2] <= LEVEL < r.iloc[-1]):
                    continue
                entry, stop = float(c.iloc[-1]), float(sma.iloc[-1])
                per_share = entry - stop
                if per_share <= 0:          # already below SMA20 -> no valid stop
                    continue
                qty = int(RISK // per_share)
                if qty < 1:                 # stop too wide for Rs.500 risk
                    continue
                if qty * entry < MIN_CAPITAL:   # capital below Rs.5000
                    continue
                rows.append({
                    "symbol": s, "name": info.loc[s, "Company Name"],
                    "industry": info.loc[s, "Industry"],
                    "week": df.index[-1].strftime("%d %b %Y"),
                    "rsi": round(float(r.iloc[-1]), 1), "prev_rsi": round(float(r.iloc[-2]), 1),
                    "entry": round(entry, 2), "stop": round(stop, 2),
                    "risk_pct": round(per_share / entry * 100, 2),
                    "qty": qty, "capital": round(qty * entry),
                })
            except Exception:
                continue
    rows.sort(key=lambda x: x["risk_pct"])   # tightest stops first
    return rows


HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly RSI Scanner</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1a1d21;--mu:#6b7280;--bd:#e5e7eb;--ac:#0f766e;--rd:#b91c1c}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--tx:#e8eaed;--mu:#9aa0a6;--bd:#2a2e36;--ac:#2dd4bf;--rd:#f87171}}
*{box-sizing:border-box}body{margin:0;font:15px system-ui,sans-serif;background:var(--bg);color:var(--tx);padding:12px;max-width:640px;margin:auto}
h1{font-size:18px;margin:4px 0}.sub{color:var(--mu);font-size:13px;margin-bottom:10px}
.bar{display:flex;gap:8px;margin-bottom:10px}
input,select{flex:1;padding:9px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--tx);font-size:14px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px;margin-bottom:10px}
.card.done{opacity:.55}
.top{display:flex;justify-content:space-between;align-items:baseline}
.sym{font-weight:700;font-size:16px}.rsi{color:var(--ac);font-weight:600;font-size:13px}
.nm{color:var(--mu);font-size:12px;margin:2px 0 8px}
.g{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;font-size:13px}
.g div span{display:block;color:var(--mu);font-size:11px}
.sl{color:var(--rd)}
label{display:flex;gap:8px;align-items:center;margin-top:10px;font-size:13px;color:var(--mu)}
.empty{text-align:center;color:var(--mu);padding:30px}
</style></head><body>
<h1>Weekly RSI &gt; 60 Scanner</h1>
<div class="sub">Nifty 500 &middot; Week of __WEEK__ &middot; Generated __GEN__ &middot; Risk &#8377;__RISK__/stock</div>
<div class="bar"><input id="q" placeholder="Search symbol / industry">
<select id="s"><option value="risk_pct">Tightest stop</option><option value="rsi">RSI high</option><option value="symbol">A-Z</option></select></div>
<div id="list"></div>
<script>
const D=__DATA__;let T={};try{T=JSON.parse(localStorage.getItem("wrs_taken")||"{}")}catch(e){}
const key=d=>d.symbol+"|"+d.week,f=n=>n.toLocaleString("en-IN");
function draw(){
 const q=document.getElementById("q").value.toLowerCase(),s=document.getElementById("s").value;
 let r=D.filter(d=>(d.symbol+d.industry+d.name).toLowerCase().includes(q));
 r.sort((a,b)=>s=="symbol"?a.symbol.localeCompare(b.symbol):s=="rsi"?b.rsi-a.rsi:a.risk_pct-b.risk_pct);
 document.getElementById("list").innerHTML=r.length?r.map(d=>`
 <div class="card ${T[key(d)]?"done":""}">
  <div class="top"><span class="sym">${d.symbol}</span><span class="rsi">RSI ${d.prev_rsi} &rarr; ${d.rsi}</span></div>
  <div class="nm">${d.name} &middot; ${d.industry}</div>
  <div class="g"><div><span>Entry</span>&#8377;${f(d.entry)}</div>
  <div class="sl"><span>SL (W SMA20 close)</span>&#8377;${f(d.stop)}</div>
  <div><span>Risk/share</span>${d.risk_pct}%</div>
  <div><span>Qty</span><b>${f(d.qty)}</b></div>
  <div><span>Capital</span>&#8377;${f(d.capital)}</div>
  <div><span>Max loss</span>&#8377;__RISK__</div></div>
  <label><input type="checkbox" ${T[key(d)]?"checked":""} onchange="tg('${key(d)}',this.checked)"> Trade taken</label>
 </div>`).join(""):'<div class="empty">No stocks crossed weekly RSI 60 this week.</div>';
}
function tg(k,v){T[k]=v;try{localStorage.setItem("wrs_taken",JSON.stringify(T))}catch(e){}draw()}
document.getElementById("q").oninput=draw;document.getElementById("s").onchange=draw;draw();
</script></body></html>"""


if __name__ == "__main__":
    res = scan()
    week = res[0]["week"] if res else dt.date.today().strftime("%d %b %Y")
    html = (HTML.replace("__DATA__", json.dumps(res)).replace("__WEEK__", week)
            .replace("__GEN__", dt.datetime.now().strftime("%d %b %Y %H:%M")).replace("__RISK__", str(RISK)))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)
    # JSON for the synced dashboard (use the Import button there)
    with open("docs/weekly_scanner.json", "w", encoding="utf-8") as fh:
        json.dump({"week": week, "risk": RISK, "rows": res}, fh)
    print(f"{len(res)} stocks found -> {OUT}, docs/weekly_scanner.json")
