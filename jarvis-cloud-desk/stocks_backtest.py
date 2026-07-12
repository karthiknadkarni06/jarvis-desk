#!/usr/bin/env python3
"""Stock-level deep backtest: top liquid F&O stocks, 5y daily.
Finds best strategy per stock + volatility profile. Writes STOCKS_BACKTEST.md"""
import json, urllib.request, time, gzip, csv, io, math
from datetime import datetime, timedelta, date

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126.0",
      "Accept": "application/json"}

FNO = ["RELIANCE","HDFCBANK","ICICIBANK","SBIN","INFY","TCS","AXISBANK","KOTAKBANK","ITC","LT",
"BHARTIARTL","HINDUNILVR","BAJFINANCE","MARUTI","M&M","TATAMOTORS","TATASTEEL","SUNPHARMA","TITAN","ASIANPAINT",
"ULTRACEMCO","WIPRO","HCLTECH","TECHM","NTPC","POWERGRID","ONGC","COALINDIA","BPCL","IOC",
"ADANIENT","ADANIPORTS","JSWSTEEL","HINDALCO","VEDL","TATAPOWER","DLF","GODREJPROP","INDUSINDBK","BANKBARODA",
"PNB","CANBK","AUROPHARMA","DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","BAJAJFINSV","BAJAJ-AUTO","EICHERMOT",
"HEROMOTOCO","TVSMOTOR","ASHOKLEY","BEL","HAL","SIEMENS","ABB","HAVELLS","VOLTAS","DIXON",
"TRENT","DMART","NAUKRI","ZOMATO","PAYTM","IRCTC","INDIGO","GRASIM","SHREECEM","AMBUJACEM",
"ACC","PIDILITIND","BERGEPAINT","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","RECLTD","PFC","IRFC","RVNL",
"LUPIN","BIOCON","GLENMARK","TORNTPHARM","MFSL","SBILIFE","HDFCLIFE","ICICIGI","NMDC","SAIL"]

def get(url, timeout=40, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read() if binary else r.read().decode()

print("downloading instrument master...")
raw = get("https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz", binary=True)
text = gzip.decompress(raw).decode()
rows = list(csv.DictReader(io.StringIO(text)))
if rows:
    print("CSV columns:", list(rows[0].keys()))
    print("sample row:", {k: rows[0][k] for k in list(rows[0].keys())[:8]})
keymap = {}
for r in rows:
    seg = (r.get("exchange") or r.get("segment") or "").upper()
    itype = (r.get("instrument_type") or r.get("instrumenttype") or "").upper()
    sym = (r.get("tradingsymbol") or r.get("trading_symbol") or r.get("symbol") or "").upper()
    ikey = r.get("instrument_key") or r.get("instrumentkey") or ""
    if "EQ" in seg and itype in ("EQ", "EQUITY", "") and sym in FNO and ikey:
        keymap.setdefault(sym, ikey.replace("|", "%7C"))
print(f"mapped {len(keymap)}/{len(FNO)} symbols; missing: {sorted(set(FNO)-set(keymap))[:10]}")

def daily_closes(key, years=5):
    out = []
    to = date.today()
    for _ in range(years):
        frm = to - timedelta(days=365)
        try:
            d = json.loads(get(f"https://api.upstox.com/v2/historical-candle/{key}/day/{to}/{frm}"))
            out += [(c[0], float(c[4])) for c in d.get("data", {}).get("candles", [])]
        except Exception:
            pass
        to = frm - timedelta(days=1)
        time.sleep(0.25)
    out = sorted(set(out))
    return [c for _, c in out]

def ema_series(v, n):
    if len(v) < n: return [None]*len(v)
    k = 2/(n+1); out = [None]*(n-1) + [sum(v[:n])/n]
    for x in v[n:]: out.append(x*k + out[-1]*(1-k))
    return out

def rsi_series(v, n=14):
    out=[None]*len(v); ag=al=None
    for i in range(1,len(v)):
        d=v[i]-v[i-1]; g,l=max(d,0),max(-d,0)
        if i==n:
            gains=[max(v[j]-v[j-1],0) for j in range(1,n+1)]
            losses=[max(v[j-1]-v[j],0) for j in range(1,n+1)]
            ag,al=sum(gains)/n,sum(losses)/n
        elif i>n:
            ag=(ag*(n-1)+g)/n; al=(al*(n-1)+l)/n
        if i>=n: out[i]=100.0 if al==0 else 100-100/(1+ag/al)
    return out

def pf(tr):
    if len(tr) < 6: return None
    w=sum(t for t in tr if t>0); l=abs(sum(t for t in tr if t<=0))
    return (w/l if l>0 else 9.9), len(tr)

def best_strategy(C):
    N=len(C)
    e5,e9,e21,e50 = ema_series(C,5),ema_series(C,9),ema_series(C,21),ema_series(C,50)
    rsi = rsi_series(C)
    res={}
    tr=[];pos=None
    for i in range(50,N):
        if None in (e5[i],e21[i],e5[i-1],e21[i-1]): continue
        if pos is None and e5[i]>e21[i] and e5[i-1]<=e21[i-1]: pos=C[i]
        elif pos and e5[i]<e21[i]: tr.append((C[i]-pos)/pos*100); pos=None
    res["EMA5/21 cross"]=pf(tr)
    tr=[];pos=None
    for i in range(50,N):
        if None in (e9[i],e21[i],e9[i-1],e21[i-1]): continue
        if pos is None and e9[i]>e21[i] and e9[i-1]<=e21[i-1]: pos=C[i]
        elif pos and e9[i]<e21[i]: tr.append((C[i]-pos)/pos*100); pos=None
    res["EMA9/21 cross"]=pf(tr)
    tr=[];i=50
    while i<N-5:
        if e21[i] is not None and C[i]>C[i-5]*1.03 and C[i]>e21[i]:
            tr.append((C[i+5]-C[i])/C[i]*100); i+=5
        i+=1
    res["Momentum burst"]=pf(tr)
    tr=[];pos=None
    for i in range(50,N):
        if rsi[i] is None or e50[i] is None: continue
        if pos is None and rsi[i]<35 and C[i]>e50[i]*0.97: pos=C[i]
        elif pos:
            if rsi[i]>55 or C[i]<pos*0.98: tr.append((C[i]-pos)/pos*100); pos=None
    res["RSI dip-buy"]=pf(tr)
    valid = {k:v for k,v in res.items() if v}
    if not valid: return None, None, None
    bk = max(valid, key=lambda k: valid[k][0])
    return bk, valid[bk][0], valid[bk][1]

results = []
for sym, key in keymap.items():
    try:
        C = daily_closes(key)
        if len(C) < 400: continue
        rets = [(C[i]-C[i-1])/C[i-1] for i in range(1,len(C))]
        mu = sum(rets)/len(rets)
        vol = math.sqrt(sum((r-mu)**2 for r in rets)/len(rets)) * math.sqrt(252) * 100
        move5y = (C[-1]/C[0]-1)*100
        bk, bpf, n = best_strategy(C)
        if bk:
            results.append({"sym":sym,"vol":vol,"move":move5y,"strat":bk,"pf":bpf,"n":n})
            print(f"{sym}: {bk} PF {bpf:.2f} vol {vol:.0f}%")
    except Exception as e:
        print(sym, "failed:", e)

results.sort(key=lambda x: -x["pf"])
lines = ["# 📊 Top F&O Stocks — Best Strategy Per Stock (5y daily)",
         f"\nRun {datetime.now().strftime('%d-%b-%Y %H:%M UTC')} · {len(results)} stocks tested · 4 validated strategies each",
         "\n_'₹ back' = per ₹100 lost on bad trades, amount recovered by good trades. Vol = yearly volatility (how wildly it moves)._",
         "\n## 🏆 Top 25 stock+strategy combos\n",
         "| Stock | Best strategy | ₹ back per ₹100 | Trades | Volatility | 5y move |", "|---|---|---|---|---|---|"]
for r in results[:25]:
    lines.append(f"| {r['sym']} | {r['strat']} | ₹{r['pf']*100:.0f} | {r['n']} | {r['vol']:.0f}% | {r['move']:+.0f}% |")

wins = {}
for r in results: wins[r["strat"]] = wins.get(r["strat"],0)+1
lines += ["\n## Which strategy wins most often across all stocks?\n"]
for k,v in sorted(wins.items(), key=lambda x:-x[1]):
    lines.append(f"- **{k}**: best on {v} stocks")

hi = [r for r in results if r["vol"]>=35]; lo = [r for r in results if r["vol"]<28]
def topstrat(rs):
    w={}
    for r in rs: w[r["strat"]]=w.get(r["strat"],0)+1
    return max(w, key=w.get) if w else "n/a"
lines += [f"\n## Volatility insight\n",
          f"- **Wild movers (vol ≥35%/yr, {len(hi)} stocks):** favourite = **{topstrat(hi)}**",
          f"- **Calm stocks (vol <28%/yr, {len(lo)} stocks):** favourite = **{topstrat(lo)}**"]
with open("STOCKS_BACKTEST.md","w") as f: f.write("\n".join(lines))
print("done,", len(results), "stocks")
