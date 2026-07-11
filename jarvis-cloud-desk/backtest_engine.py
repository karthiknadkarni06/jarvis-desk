#!/usr/bin/env python3
"""One-off deep backtest: 5 years of NIFTY daily data, 8 buying strategies.
Writes BACKTEST.md. Directional edge measured in index points (option P&L would
amplify both wins and losses; this measures whether the SIGNAL itself has edge)."""
import json, urllib.request
from datetime import datetime

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126.0"}

def yahoo(rng="5y", interval="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range={rng}&interval={interval}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        res = json.loads(r.read().decode())["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = [(o,h,l,c) for o,h,l,c in zip(q["open"],q["high"],q["low"],q["close"]) if c is not None and o is not None]
    return rows

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
    if len(trades)==0: return None
    wins=[t for t in trades if t>0]; losses=[t for t in trades if t<=0]
    gw, gl = sum(wins), abs(sum(losses))
    return {"n":len(trades), "wr":len(wins)/len(trades)*100, "pts":sum(trades),
            "avg":sum(trades)/len(trades), "pf": gw/gl if gl>0 else 99.0}

rows = yahoo()
O=[r[0] for r in rows]; H=[r[1] for r in rows]; L=[r[2] for r in rows]; C=[r[3] for r in rows]
N=len(C)
e9, e21, e50 = ema_series(C,9), ema_series(C,21), ema_series(C,50)
rsi = rsi_series(C)
R = {}

# 1. EMA9/21 cross long (CE)
tr=[];pos=None
for i in range(50,N):
    if None in (e9[i],e21[i],e9[i-1],e21[i-1]): continue
    if pos is None and e9[i]>e21[i] and e9[i-1]<=e21[i-1]: pos=C[i]
    elif pos and e9[i]<e21[i]: tr.append(C[i]-pos); pos=None
R["EMA9/21 cross — buy CE"]=stats(tr)

# 2. EMA9/21 cross short (PE)
tr=[];pos=None
for i in range(50,N):
    if None in (e9[i],e21[i],e9[i-1],e21[i-1]): continue
    if pos is None and e9[i]<e21[i] and e9[i-1]>=e21[i-1]: pos=C[i]
    elif pos and e9[i]>e21[i]: tr.append(pos-C[i]); pos=None
R["EMA9/21 cross — buy PE"]=stats(tr)

# 3. 20-day breakout long with EMA50 trend filter, exit below EMA21
tr=[];pos=None
for i in range(50,N):
    if e21[i] is None or e50[i] is None: continue
    hh=max(C[i-20:i])
    if pos is None and C[i]>hh and C[i]>e50[i]: pos=C[i]
    elif pos and C[i]<e21[i]: tr.append(C[i]-pos); pos=None
R["20d breakout + trend filter — CE"]=stats(tr)

# 4. 20-day breakdown short, exit above EMA21
tr=[];pos=None
for i in range(50,N):
    if e21[i] is None: continue
    ll=min(C[i-20:i])
    if pos is None and C[i]<ll: pos=C[i]
    elif pos and C[i]>e21[i]: tr.append(pos-C[i]); pos=None
R["20d breakdown — PE"]=stats(tr)

# 5. 3 red days bounce (CE), exit first green or 5 days
tr=[];pos=None;age=0
for i in range(3,N):
    if pos is None and C[i]<C[i-1]<C[i-2]<C[i-3]: pos=C[i]; age=0
    elif pos is not None:
        age+=1
        if C[i]>C[i-1] or age>=5: tr.append(C[i]-pos); pos=None
R["3-red-days bounce — CE"]=stats(tr)

# 6. RSI<35 bounce with EMA50 uptrend filter, exit RSI>55 or -2%
tr=[];pos=None
for i in range(50,N):
    if rsi[i] is None or e50[i] is None: continue
    if pos is None and rsi[i]<35 and C[i]>e50[i]*0.97: pos=C[i]
    elif pos:
        if rsi[i]>55 or C[i]<pos*0.98: tr.append(C[i]-pos); pos=None
R["RSI<35 dip-buy in uptrend — CE"]=stats(tr)

# 7. Momentum burst: +2% in 5 days & above EMA21 -> hold 5 days
tr=[];i=50
while i<N-5:
    if e21[i] is not None and C[i]>C[i-5]*1.02 and C[i]>e21[i]:
        tr.append(C[i+5]-C[i]); i+=5
    i+=1
R["5d momentum +2% burst, hold 5d — CE"]=stats(tr)

# 8. Down momentum: -2% in 5 days & below EMA21 -> hold 5 days (PE)
tr=[];i=50
while i<N-5:
    if e21[i] is not None and C[i]<C[i-5]*0.98 and C[i]<e21[i]:
        tr.append(C[i]-C[i+5]); i+=5
    i+=1
R["5d down-momentum -2%, hold 5d — PE"]=stats(tr)

ranked = sorted([(k,v) for k,v in R.items() if v and v["n"]>=8], key=lambda x:-x[1]["pf"])
lines = ["# 📊 Deep Backtest — NIFTY, 5 Years Daily Data",
         f"\n**Data:** {N} trading days, ^NSEI via Yahoo · run {datetime.utcnow().strftime('%d-%b-%Y %H:%M UTC')}",
         "\n_Measures the directional signal edge in index points. Option buying amplifies these both ways; a signal with no index-level edge cannot be saved by options._",
         "\n## All strategies tested\n",
         "| Strategy | Trades | Win% | Net points | Avg/trade | Profit factor |", "|---|---|---|---|---|---|"]
for k,v in sorted(R.items(), key=lambda x:-(x[1]["pf"] if x[1] else -9)):
    if v:
        lines.append(f"| {k} | {v['n']} | {v['wr']:.0f}% | {v['pts']:+.0f} | {v['avg']:+.0f} | {v['pf']:.2f} |")
lines += ["\n## 🏆 Top strategies (min 8 trades, ranked by profit factor)\n"]
for i,(k,v) in enumerate(ranked[:5],1):
    lines.append(f"{i}. **{k}** — PF {v['pf']:.2f}, {v['wr']:.0f}% wins over {v['n']} trades, {v['pts']:+.0f} pts")
lines += ["\n_Profit factor >1.3 with 20+ trades = worth respecting. Anything with <10 trades = suggestive only._"]
with open("BACKTEST.md","w") as f: f.write("\n".join(lines))
print("\n".join(lines[-12:]))
