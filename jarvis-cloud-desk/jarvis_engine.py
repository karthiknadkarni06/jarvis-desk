#!/usr/bin/env python3
"""
Jarvis Cloud Desk v2 — TOKEN-FREE autonomous NIFTY option-buying paper trader.
Data: Yahoo Finance (spot, daily candles, India VIX) + NSE public option chain.
No credentials, no secrets, no renewals. Paper only — never places real orders.
Runs on GitHub Actions every ~5 min during market hours.
"""
import json, os, time, urllib.request, urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
LEDGER = "ledger.json"
LOT = 75  # NIFTY lot size

# ── Risk framework (hard guardrails) ──
START_CAP = 100000
MAX_OUTLAY_PCT = 0.25
MAX_POSITIONS = 2
MAX_TRADES_PER_DAY = 2
SL_PCT = 0.30
TGT_PCT = 0.60
DERISK_EQ = 80000
HALT_EQ = 60000

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def http_get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(), r.headers


def yahoo_chart(symbol, rng="6mo", interval="1d"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range={rng}&interval={interval}")
    body, _ = http_get(url)
    res = json.loads(body)["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    spot = res["meta"].get("regularMarketPrice") or (closes[-1] if closes else None)
    return spot, closes


def nse_chain():
    """NSE public option chain with cookie priming. Returns (expiry, {strike:{...}})."""
    base_headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
    }
    last_err = None
    for attempt in range(3):
        try:
            # prime session cookies
            _, h = http_get("https://www.nseindia.com/option-chain", base_headers)
            cookies = []
            for k, v in h.items():
                if k.lower() == "set-cookie":
                    cookies.append(v.split(";")[0])
            hdrs = dict(base_headers)
            if cookies:
                hdrs["Cookie"] = "; ".join(cookies)
            body, _ = http_get(
                "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY", hdrs)
            data = json.loads(body)["records"]
            expiry = data["expiryDates"][0]
            chain = {}
            for row in data["data"]:
                if row.get("expiryDate") != expiry:
                    continue
                s = float(row["strikePrice"])
                ce, pe = row.get("CE") or {}, row.get("PE") or {}
                chain[s] = {"ce_oi": ce.get("openInterest", 0),
                            "ce_ltp": ce.get("lastPrice", 0),
                            "pe_oi": pe.get("openInterest", 0),
                            "pe_ltp": pe.get("lastPrice", 0)}
            if chain:
                return expiry, chain
            last_err = "empty chain"
        except Exception as e:
            last_err = str(e)
        time.sleep(4)
    raise RuntimeError(f"NSE chain unavailable: {last_err}")


def ema(vals, n):
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def now_ist():
    return datetime.now(IST)


def market_open(t):
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return 555 <= m <= 930


def load_ledger():
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            return json.load(f)
    return {"capital": START_CAP, "open": [], "trades": [], "peak": START_CAP,
            "maxDD": 0.0, "halted": False, "last_run": None, "note": "initialized"}




def write_report(L):
    """Human-readable dashboard as REPORT.md — the page Karthik bookmarks."""
    eq = equity(L)
    open_pl = sum((p["mark"] - p["entry"]) * LOT * p["lots"] for p in L["open"])
    closed = [t for t in L["trades"] if not t.get("open")]
    wins = [t for t in closed if t["pnl"] > 0]
    wr = f"{round(100*len(wins)/len(closed))}%" if closed else "—"
    pnl = eq - START_CAP
    arrow = "🟢" if pnl >= 0 else "🔴"
    lines = [
        "# 🤖 Jarvis Paper Trading — Live Dashboard",
        "",
        f"**Updated:** {L['last_run'] or now_ist().strftime('%d-%b-%Y %H:%M IST')}",
        "",
        f"| Money now | Profit/Loss | Goal (₹10 Lakh) | Trades | Win rate | Worst dip |",
        f"|---|---|---|---|---|---|",
        f"| **₹{round(eq):,}** | {arrow} ₹{round(pnl):,} | {eq/1000000*100:.1f}% | {len(closed)} | {wr} | {L['maxDD']:.1f}% |",
        "",
        f"**What Jarvis is thinking right now:** {L['note']}",
        "",
        "## Open trades",
    ]
    if L["open"]:
        lines += ["| Trade | Lots | Bought at | Now at | Profit/Loss |", "|---|---|---|---|---|"]
        for p in L["open"]:
            pl = (p["mark"] - p["entry"]) * LOT * p["lots"]
            e = "🟢" if pl >= 0 else "🔴"
            lines.append(f"| NIFTY {p['strike']} {p['side']} | {p['lots']} | ₹{p['entry']} | ₹{p['mark']} | {e} ₹{round(pl):,} |")
    else:
        lines.append("_None right now — waiting for a good opportunity (this is normal and safe)._")
    lines += ["", "## Trade history (latest first)"]
    if L["trades"]:
        lines += ["| When | Trade | Bought | Sold | Profit/Loss | Why |", "|---|---|---|---|---|---|"]
        for t in reversed(L["trades"][-20:]):
            ex = f"₹{t['exit']}" if not t.get("open") else "OPEN"
            pl = f"₹{t['pnl']:,}" if not t.get("open") else "—"
            lines.append(f"| {t['time']} | {t['und']} {t['strike']} {t['side']} ×{t['lots']} | ₹{t['entry']} | {ex} | {pl} | {t['reason'][:80]} |")
    else:
        lines.append("_No trades yet. Trading starts automatically when markets open (Mon–Fri, 9:15 AM)._")
    lines += ["", "---", "_Paper trading only — practice money, no real orders ever. Refresh this page anytime to see the latest._"]
    with open("REPORT.md", "w") as f:
        f.write("\n".join(lines))

def save_ledger(L):
    L["last_run"] = now_ist().strftime("%d-%b-%Y %H:%M IST")
    with open(LEDGER, "w") as f:
        json.dump(L, f, indent=1)
    try:
        write_report(L)
    except Exception as e:
        print("report write failed:", e)


def equity(L):
    return L["capital"] + sum(p["mark"] * LOT * p["lots"] for p in L["open"])


def log(L, msg):
    print(msg)
    L["note"] = msg


def close_position(L, p, price, why):
    proceeds = price * LOT * p["lots"]
    L["capital"] += proceeds
    pnl = proceeds - p["entry"] * LOT * p["lots"]
    for t in L["trades"]:
        if t.get("open") and t["strike"] == p["strike"] and t["side"] == p["side"]:
            t.update({"exit": price, "pnl": round(pnl), "open": False,
                      "reason": t["reason"] + " → " + why})
            break
    L["open"].remove(p)
    log(L, f"EXIT {p['side']} {p['strike']} @ {price} ({why}) pnl {round(pnl)}")


def open_position(L, side, strike, prem, why, expiry):
    eq = equity(L)
    cap_pct = MAX_OUTLAY_PCT / 2 if eq < DERISK_EQ else MAX_OUTLAY_PCT
    lots = int((eq * cap_pct) // (prem * LOT))
    if lots < 1:
        log(L, f"skip {side} {strike}: premium {prem} too large for sizing")
        return
    cost = prem * LOT * lots
    if cost > L["capital"]:
        log(L, "skip entry: insufficient cash")
        return
    L["capital"] -= cost
    t = now_ist().strftime("%d-%b %H:%M")
    L["open"].append({"side": side, "strike": strike, "entry": prem, "mark": prem,
                      "lots": lots, "sl": round(prem * (1 - SL_PCT), 1),
                      "tgt": round(prem * (1 + TGT_PCT), 1), "time": t, "expiry": expiry})
    L["trades"].append({"time": t, "und": "NIFTY", "side": side, "strike": strike,
                        "lots": lots, "entry": prem, "exit": None, "pnl": 0,
                        "open": True, "strategy": "OI-breakout", "reason": why})
    log(L, f"ENTER {side} {strike} x{lots} @ {prem} — {why}")


def trades_today(L):
    today = now_ist().strftime("%d-%b")
    return sum(1 for t in L["trades"] if t["time"].startswith(today))


def main():
    L = load_ledger()
    t = now_ist()

    if L["halted"]:
        log(L, "desk halted (drawdown) — no action"); save_ledger(L); return
    if not market_open(t):
        log(L, "market closed — no action"); save_ledger(L); return

    # ── data: spot + trend (Yahoo, very reliable) ──
    try:
        spot, closes = yahoo_chart("%5ENSEI")
        e21 = ema(closes[-80:], 21)
        e50 = ema(closes[-120:], 50)
        try:
            vix, _ = yahoo_chart("%5EINDIAVIX", rng="5d")
        except Exception:
            vix = None
        if not spot:
            raise RuntimeError("no spot")
    except Exception as e:
        log(L, f"price data unavailable ({e}) — holding safely")
        save_ledger(L); return

    # ── data: option chain (NSE public; can be flaky from cloud IPs) ──
    chain, expiry, chain_ok = {}, None, True
    try:
        expiry, chain = nse_chain()
        # normalize NSE expiry ('10-Jul-2026') to date for squareoff check
        exp_date = datetime.strptime(expiry, "%d-%b-%Y").date()
    except Exception as e:
        chain_ok = False
        log(L, f"chain unavailable ({e}) — managing with price data only")

    # ── mark & manage open positions ──
    if chain_ok:
        for p in L["open"]:
            row = chain.get(float(p["strike"]))
            if row:
                m = row["ce_ltp"] if p["side"] == "CE" else row["pe_ltp"]
                if m and m > 0:
                    p["mark"] = m
        squareoff = (str(t.date()) == str(exp_date)) and (t.hour, t.minute) >= (14, 45)
        for p in list(L["open"]):
            if p["mark"] <= p["sl"]:
                close_position(L, p, p["mark"], "SL hit")
            elif p["mark"] >= p["tgt"]:
                close_position(L, p, p["mark"], "target hit")
            elif squareoff:
                close_position(L, p, p["mark"], "expiry squareoff")

    # ── drawdown accounting ──
    eq = equity(L)
    L["peak"] = max(L["peak"], eq)
    L["maxDD"] = max(L["maxDD"], round((L["peak"] - eq) / L["peak"] * 100, 1))
    if eq < HALT_EQ:
        L["halted"] = True
        log(L, f"DESK HALTED at equity {round(eq)}")
        save_ledger(L); return

    # ── entries (need the chain; skip cleanly if unavailable) ──
    if chain_ok and len(L["open"]) < MAX_POSITIONS and trades_today(L) < MAX_TRADES_PER_DAY:
        is_expiry_day = str(t.date()) == str(exp_date)
        if not (is_expiry_day and t.hour >= 13):
            ce_band = {s: v["ce_oi"] for s, v in chain.items()
                       if spot <= s <= spot + 600 and v["ce_oi"] > 0}
            pe_band = {s: v["pe_oi"] for s, v in chain.items()
                       if spot - 600 <= s <= spot and v["pe_oi"] > 0}
            ce_wall = max(ce_band, key=ce_band.get) if ce_band else None
            pe_wall = max(pe_band, key=pe_band.get) if pe_band else None
            atm = min(chain, key=lambda s: abs(s - spot))
            entered = False

            if ce_wall and spot > ce_wall - 50 and (e21 is None or spot > e21):
                prem = chain[atm]["ce_ltp"]
                if prem > 0:
                    open_position(L, "CE", atm, prem,
                                  f"spot {round(spot,1)} pressing CE wall {ce_wall}, "
                                  f"trend up (EMA21 {round(e21,1) if e21 else 'n/a'})", expiry)
                    entered = True
            elif pe_wall and spot < pe_wall - 20 and (e21 is None or spot < e21):
                prem = chain[atm]["pe_ltp"]
                if prem > 0:
                    open_position(L, "PE", atm, prem,
                                  f"spot {round(spot,1)} broke PE wall {pe_wall}, "
                                  f"trend down (EMA21 {round(e21,1) if e21 else 'n/a'})", expiry)
                    entered = True

            if not entered and not L["open"]:
                log(L, f"HOLD — spot {round(spot,1)} inside walls (PE {pe_wall} / CE {ce_wall}), "
                       f"EMA21 {round(e21,1) if e21 else 'n/a'}, VIX {round(vix,1) if vix else 'n/a'}")

    save_ledger(L)


if __name__ == "__main__":
    main()
