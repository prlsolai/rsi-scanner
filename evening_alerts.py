"""
Evening alerts for open trades (weekly RSI>60 strategy)

Setup:  pip install yfinance pandas requests
        1. Install the free 'ntfy' app on your phone, subscribe to a private topic name
        2. Set NTFY_TOPIC below (use a hard-to-guess name)
        3. In the dashboard: Journal -> "Export open trades", save open_trades.json next to this script
Cron:   30 19 * * 1-6  python /path/evening_alerts.py     (Mon-Sat, 7:30 PM)

Alerts per open trade
  EXIT  : last COMPLETED weekly close is below weekly SMA20 (your actual stoploss rule)
  WATCH : today's daily close is below the current weekly SMA20 (week not over, may recover)
  INFO  : current price vs entry / SMA20 (sent as a short daily summary)
"""
import json, datetime as dt
import pandas as pd, requests, yfinance as yf

NTFY_TOPIC = "change-this-to-your-private-topic"
TRADES = "open_trades.json"
SMA_LEN = 20


def push(title, msg, prio="default"):
    print(title, "|", msg)
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                      headers={"Title": title, "Priority": prio}, timeout=15)
    except Exception as e:
        print("push failed:", e)


def main():
    try:
        trades = json.load(open(TRADES))
    except FileNotFoundError:
        print("open_trades.json not found - export it from the dashboard")
        return
    if not trades:
        return
    today = dt.date.today()
    lines = []
    for t in trades:
        s = t["symbol"] + ".NS"
        w = yf.download(s, period="2y", interval="1wk", auto_adjust=True, progress=False)
        d = yf.download(s, period="5d", interval="1d", auto_adjust=True, progress=False)
        if isinstance(w.columns, pd.MultiIndex):
            w.columns = w.columns.get_level_values(0)
            d.columns = d.columns.get_level_values(0)
        w, d = w.dropna(subset=["Close"]), d.dropna(subset=["Close"])
        if w.empty or d.empty:
            continue
        sma_now = float(w["Close"].rolling(SMA_LEN).mean().iloc[-1])   # includes running week
        last_complete = w if today >= w.index[-1].date() + dt.timedelta(days=5) else w.iloc[:-1]
        wc = float(last_complete["Close"].iloc[-1])
        wsma = float(last_complete["Close"].rolling(SMA_LEN).mean().iloc[-1])
        px = float(d["Close"].iloc[-1])
        pl = (px - t["entry"]) * t["qty"]
        if wc < wsma:
            push(f"EXIT {t['symbol']}", f"Weekly close {wc:.2f} < SMA20 {wsma:.2f}. Exit per rule.", "high")
        elif px < sma_now:
            push(f"WATCH {t['symbol']}", f"Daily close {px:.2f} below SMA20 {sma_now:.2f}. Weekly close decides.", "high")
        lines.append(f"{t['symbol']}: {px:.2f} | SL~{sma_now:.2f} | P&L Rs.{pl:,.0f}")
    if lines:
        push("Open trades summary", "\n".join(lines))


if __name__ == "__main__":
    main()
