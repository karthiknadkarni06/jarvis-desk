#!/usr/bin/env python3
"""Deep backtest v2: 5 years NIFTY daily. Data: Upstox public candles (Yahoo fallback).
Also runs a live-connectivity diagnostic (Upstox / Yahoo / NSE chain) for Monday-readiness."""
import json, urllib.request, time
from datetime import datetime, timedelta

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126.0",
      "Accept": "application/json"}

def get(url, headers=None, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or UA), timeout=timeout) as r:
        return r.read().decode()

def upstox_daily(instr="NSE_INDEX%7CNifty%2050", years=5):
    rows = []
    to = datetime.utcnow().date()
    for _ in range(years):
        frm = to - timedelta(days=365)
        url = f"https://api.upstox.com/v2/historical-candle/{instr}/day/{to}/{frm}"
        try:
            d = json.loads(get(url))
            for c in d.get("data", {}).get("candles", []):
                rows.append((c[0], float(c[1]), float(c[2]), float(c[3]), float(c[4])))
        except Exception as e:
            print("upstox chunk failed:", e)
        to = frm - timedelta(days=1)
        time.sleep(1)
    rows = sorted(set(rows), key=lambda x: x[0])
    return [(o,h,l,c) for _,o,h,l,c in rows]

def yahoo_daily():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5y&interval=1d"
    res = json.loads(get(url))["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    return [(o,h,l,c) for o,h,l,c in zip(q["open"],q["high"],q["low"],q["close"]) if c and o]

# ── connectivity diagnostic ──
diag = {}
try:
    d = json.loads(get("https://api.upstox.com/v2/historical-candle/intraday/NSE_INDEX%7CNifty%2050/30minute"))
    diag["upstox_intraday"] = f"OK ({len(d.get('data',{}).get('candles',[]))} candles)"
except Exception as e:
    diag["upstox_intraday"] = f"FAIL: {str(e)[:60]}"
try:
    _, h = None, None
    body = get("https://www.nseindia.com/option-chain")
    diag["nse_prime"] = "OK"
except Exception as e:
    diag["nse_prime"] = f"FAIL: {str(e)[:60]}"
try:
    get("https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d")
    diag["yahoo"] = "OK"
except Exception as e:
    diag["yahoo"] = f"FAIL: {str(e)[:60]}"

rows = upstox_daily()
src = "Upstox public candles"
if len(rows) < 500:
    try:
        rows = yahoo_daily(); src = "Yahoo Finance"
    except Exception as e:
        print("both sources failed:", e)

O=[r[0] for r in rows]; H=[r[1] for r in rows]; L=[r[2] for r in rows]; C=[r[3] for r in rows]
N=len(C)
print(f"data: {N} days from {src}; diag: {diag}")

def ema_series(vals, n):
    k = 2/(n+1); out = [None]*(n-1) + [sum(vals[:n])/n]
    for v in vals[n:]: out.append(v*k + out[-1]*(1-k))
    return out

def rsi_series(vals, n=14):
    out=[None]*len(vals); ag=al=None
    for i in range(1,len(vals)):
        d=vals[i]-vals[i-1]; g,l=max(d,0),max(-d,0)
        if i==n:
            gains=[max(vals[j]-vals[j-1],0) for j in range(1,n+1)]
            losses=[max(vals[j-1]-vals[j],0) for j in range(1,n+1)]
            ag,al=sum(gains)/n,sum(losses)/n
        elif i>n:
            ag=(ag*(n-1)+g)/n; al=(al*(n-1)+l)/n
        if i>=n:
            out[i]=100.0 if al==0 else 100-100/(1+ag/al)
    return out

def stats(trades):
    if not trades: return None
    wins=[t for t in trades if t>0]; gl=abs(sum(t for t in trades if t<=0))
    return {"n":len(trades),"wr":len(wins)/len(trades)*100,"pts":sum(trades),
            "avg":sum(trades)/len(trades),"pf": sum(wins)/gl if gl>0 else 99.0}

e9,e21,e50 = ema_series(C,9), ema_series(C,21), ema_series(C,50)
rsi = rsi_series(C)
R = {}

tr=[];pos=None
for i in range(50,N):
    if None in (e9[i],e21[i],e9[i-1],e21[i-1]): continue
    if pos is None and e9[i]>e21[i] and e9[i-1]<=e21[i-1]: pos=C[i]
    elif pos and e9[i]<e21[i]: tr.append(C[i]-pos); pos=None
R["EMA9/21 cross up — buy CE, hold trend"]=stats(tr)

tr=[];pos=None
for i in range(50,N):
    if None in (e9[i],e21[i],e9[i-1],e21[i-1]): continue
    if pos is None and e9[i]<e21[i] and e9[i-1]>=e21[i-1]: pos=C[i]
    elif pos and e9[i]>e21[i]: tr.append(pos-C[i]); pos=None
R["EMA9/21 cross down — buy PE, hold trend"]=stats(tr)

tr=[];pos=None
for i in range(50,N):
    if e21[i] is None or e50[i] is None: continue
    if pos is None and C[i]>max(C[i-20:i]) and C[i]>e50[i]: pos=C[i]
    elif pos and C[i]<e21[i]: tr.append(C[i]-pos); pos=None
R["20d high breakout + uptrend — CE"]=stats(tr)

tr=[];pos=None
for i in range(50,N):
    if e21[i] is None: continue
    if pos is None and C[i]<min(C[i-20:i]): pos=C[i]
    elif pos and C[i]>e21[i]: tr.append(pos-C[i]); pos=None
R["20d low breakdown — PE"]=stats(tr)

tr=[];pos=None;age=0
for i in range(3,N):
    if pos is None and C[i]<C[i-1]<C[i-2]<C[i-3]: pos=C[i]; age=0
    elif pos is not None:
        age+=1
        if C[i]>C[i-1] or age>=5: tr.append(C[i]-pos); pos=None
R["3-red-days bounce — CE"]=stats(tr)

tr=[];pos=None
for i in range(50,N):
    if rsi[i] is None or e50[i] is None: continue
    if pos is None and rsi[i]<35 and C[i]>e50[i]*0.97: pos=C[i]
    elif pos:
        if rsi[i]>55 or C[i]<pos*0.98: tr.append(C[i]-pos); pos=None
R["RSI<35 dip-buy in uptrend — CE"]=stats(tr)

tr=[];i=50
while i<N-5:
    if e21[i] is not None and C[i]>C[i-5]*1.02 and C[i]>e21[i]:
        tr.append(C[i+5]-C[i]); i+=5
    i+=1
R["+2% burst continuation, 5d hold — CE"]=stats(tr)

tr=[];i=50
while i<N-5:
    if e21[i] is not None and C[i]<C[i-5]*0.98 and C[i]<e21[i]:
        tr.append(C[i]-C[i+5]); i+=5
    i+=1
R["-2% drop continuation, 5d hold — PE"]=stats(tr)

ranked = sorted([(k,v) for k,v in R.items() if v and v["n"]>=8], key=lambda x:-x[1]["pf"])
lines = ["# 📊 Deep Backtest — NIFTY, 5 Years Daily",
         f"\n**Data:** {N} trading days · source: {src} · run {datetime.utcnow().strftime('%d-%b-%Y %H:%M UTC')}",
         f"\n**Monday-readiness diagnostic (from cloud server):** Upstox intraday: {diag['upstox_intraday']} · NSE: {diag['nse_prime']} · Yahoo: {diag['yahoo']}",
         "\n_Measures directional signal edge in index points; options amplify both ways. PF = profit factor (>1.3 with 20+ trades = respectable)._",
         "\n| Strategy | Trades | Win% | Net pts | Avg/trade | PF |", "|---|---|---|---|---|---|"]
for k,v in sorted(R.items(), key=lambda x:-(x[1]["pf"] if x[1] else -9)):
    if v: lines.append(f"| {k} | {v['n']} | {v['wr']:.0f}% | {v['pts']:+.0f} | {v['avg']:+.0f} | {v['pf']:.2f} |")
lines.append("\n## 🏆 Top 5 (min 8 trades, by profit factor)\n")
for i,(k,v) in enumerate(ranked[:5],1):
    lines.append(f"{i}. **{k}** — PF {v['pf']:.2f} · {v['wr']:.0f}% wins · {v['n']} trades · {v['pts']:+.0f} pts")
with open("BACKTEST.md","w") as f: f.write("\n".join(lines))
print("BACKTEST.md written")
