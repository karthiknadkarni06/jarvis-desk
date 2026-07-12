#!/usr/bin/env python3
"""Deep backtest v3: NIFTY + BANKNIFTY + SENSEX, 5y daily, incl. EMA5 strategies."""
import json, urllib.request, time
from datetime import datetime, timedelta, date

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126.0",
      "Accept": "application/json"}
INDICES = {"NIFTY": "NSE_INDEX%7CNifty%2050",
           "BANKNIFTY": "NSE_INDEX%7CNifty%20Bank",
           "SENSEX": "BSE_INDEX%7CSENSEX"}

def get(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode()

def upstox_daily(key, years=5):
    rows = []
    to = date.today()
    for _ in range(years):
        frm = to - timedelta(days=365)
        try:
            d = json.loads(get(f"https://api.upstox.com/v2/historical-candle/{key}/day/{to}/{frm}"))
            rows += [(c[0], float(c[4])) for c in d.get("data", {}).get("candles", [])]
        except Exception as e:
            print(key, "chunk failed:", e)
        to = frm - timedelta(days=1)
        time.sleep(1)
    rows = sorted(set(rows))
    return [c for _, c in rows]

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

def stats(tr):
    if not tr: return None
    w=[t for t in tr if t>0]; gl=abs(sum(t for t in tr if t<=0))
    return {"n":len(tr),"wr":len(w)/len(tr)*100,"pts":sum(tr),"pf":sum(w)/gl if gl>0 else 99.0}

def run_all(C):
    N=len(C)
    e5,e9,e21,e50 = ema_series(C,5), ema_series(C,9), ema_series(C,21), ema_series(C,50)
    rsi = rsi_series(C)
    R={}
    def s1():  # EMA5/21 cross up
        tr=[];pos=None
        for i in range(50,N):
            if None in (e5[i],e21[i],e5[i-1],e21[i-1]): continue
            if pos is None and e5[i]>e21[i] and e5[i-1]<=e21[i-1]: pos=C[i]
            elif pos and e5[i]<e21[i]: tr.append(C[i]-pos); pos=None
        return tr
    def s2():  # EMA5 fast momentum: close>EMA5>EMA21, hold 3d
        tr=[];i=50
        while i<N-3:
            if None not in (e5[i],e21[i]) and C[i]>e5[i]>e21[i] and C[i-1]<=e5[i-1]:
                tr.append(C[i+3]-C[i]); i+=3
            i+=1
        return tr
    def s3():  # EMA9/21 cross up
        tr=[];pos=None
        for i in range(50,N):
            if None in (e9[i],e21[i],e9[i-1],e21[i-1]): continue
            if pos is None and e9[i]>e21[i] and e9[i-1]<=e21[i-1]: pos=C[i]
            elif pos and e9[i]<e21[i]: tr.append(C[i]-pos); pos=None
        return tr
    def s4():  # +2% burst 5d hold
        tr=[];i=50
        while i<N-5:
            if e21[i] is not None and C[i]>C[i-5]*1.02 and C[i]>e21[i]:
                tr.append(C[i+5]-C[i]); i+=5
            i+=1
        return tr
    def s5():  # RSI<35 dip-buy in uptrend
        tr=[];pos=None
        for i in range(50,N):
            if rsi[i] is None or e50[i] is None: continue
            if pos is None and rsi[i]<35 and C[i]>e50[i]*0.97: pos=C[i]
            elif pos:
                if rsi[i]>55 or C[i]<pos*0.98: tr.append(C[i]-pos); pos=None
        return tr
    def s6():  # 20d breakout + trend
        tr=[];pos=None
        for i in range(50,N):
            if e21[i] is None or e50[i] is None: continue
            if pos is None and C[i]>max(C[i-20:i]) and C[i]>e50[i]: pos=C[i]
            elif pos and C[i]<e21[i]: tr.append(C[i]-pos); pos=None
        return tr
    R["EMA5/21 cross — CE"]=stats(s1())
    R["EMA5 fast momentum 3d — CE"]=stats(s2())
    R["EMA9/21 cross — CE"]=stats(s3())
    R["+2% burst 5d hold — CE"]=stats(s4())
    R["RSI<35 dip-buy uptrend — CE"]=stats(s5())
    R["20d breakout+trend — CE"]=stats(s6())
    return R, N

lines=["# 📊 Deep Backtest v3 — NIFTY · BANKNIFTY · SENSEX (5y daily)",
       f"\nRun {datetime.utcnow().strftime('%d-%b-%Y %H:%M UTC')} · data: Upstox public candles · timeframe: DAILY candles, signals at close",
       "\n_PF = profit factor. >1.3 with 20+ trades = respectable edge. Points are index points._"]
summary={}
for name,key in INDICES.items():
    C = upstox_daily(key)
    if len(C) < 300:
        lines.append(f"\n## {name}: insufficient data ({len(C)} days)"); continue
    R,N = run_all(C)
    lines += [f"\n## {name} ({N} days)", "", "| Strategy | Trades | Win% | Net pts | PF |", "|---|---|---|---|---|"]
    for k,v in sorted(R.items(), key=lambda x:-(x[1]["pf"] if x[1] else -9)):
        if v:
            lines.append(f"| {k} | {v['n']} | {v['wr']:.0f}% | {v['pts']:+.0f} | {v['pf']:.2f} |")
            summary.setdefault(k, []).append((name, v["pf"], v["n"]))
lines += ["\n## 🏆 Robustness check — strategies that worked on ALL THREE indices\n"]
for k, res in sorted(summary.items(), key=lambda x: -min(p for _,p,_ in x[1])):
    if len(res)==3:
        all_pos = all(p>1.0 for _,p,_ in res)
        badge = "✅" if all_pos else "⚠️"
        lines.append(f"- {badge} **{k}** — " + " · ".join(f"{n}: PF {p:.2f} ({t}tr)" for n,p,t in res))
with open("BACKTEST.md","w") as f: f.write("\n".join(lines))
print("done")
