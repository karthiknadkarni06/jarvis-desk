#!/usr/bin/env python3
"""
Jarvis Cloud Desk v3 — token-free autonomous option-buying paper trader.
Underlyings: NIFTY + BANKNIFTY. Strategies: OI-wall breakout + momentum scalp (experiment).
Data: Yahoo Finance + NSE public chain. Telegram alerts. Paper only, never real orders.
"""
import json, os, time, urllib.request, urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
LEDGER = "ledger.json"

UNDS = {
    "NIFTY":     {"lot": 75, "yahoo": "%5ENSEI",    "nse": "NIFTY",
                  "upstox": "NSE_INDEX%7CNifty%2050"},
    "BANKNIFTY": {"lot": 35, "yahoo": "%5ENSEBANK", "nse": "BANKNIFTY",
                  "upstox": "NSE_INDEX%7CNifty%20Bank"},
}

START_CAP = 100000
MAX_POSITIONS = 2
MAX_TRADES_PER_DAY = 3
WALL_OUTLAY = 0.25      # wall-break trades: up to 25% of equity
SCALP_OUTLAY = 0.15     # scalp experiment: up to 15%
WALL_SL, WALL_TGT = 0.30, 0.60
SCALP_SL, SCALP_TGT = 0.20, 0.30
SCALP_MAX_MIN = 60
EXP_OUTLAY = 0.10       # expiry-gamma experiment: up to 10%
EXP_SL, EXP_TGT = 0.25, 0.50
EXP_MAX_MIN = 45
DERISK_EQ, HALT_EQ = 80000, 60000

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def http_get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(), r.headers


def yahoo_chart(symbol, rng="6mo", interval="1d"):
    body, _ = http_get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                       f"?range={rng}&interval={interval}")
    res = json.loads(body)["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    spot = res["meta"].get("regularMarketPrice") or (closes[-1] if closes else None)
    return spot, closes


def upstox_daily_closes(key, days=400):
    from datetime import timedelta, date
    to = date.today()
    frm = to - timedelta(days=days)
    body, _ = http_get(f"https://api.upstox.com/v2/historical-candle/{key}/day/{to}/{frm}",
                       {"User-Agent": UA, "Accept": "application/json"})
    candles = json.loads(body).get("data", {}).get("candles", [])
    candles.sort(key=lambda c: c[0])
    return [float(c[4]) for c in candles]


def upstox_intraday_closes(key, interval="1minute"):
    body, _ = http_get(f"https://api.upstox.com/v2/historical-candle/intraday/{key}/{interval}",
                       {"User-Agent": UA, "Accept": "application/json"})
    candles = json.loads(body).get("data", {}).get("candles", [])
    candles.sort(key=lambda c: c[0])
    return [float(c[4]) for c in candles]


def get_prices(und):
    """Returns (spot, daily_closes). Upstox primary, Yahoo fallback."""
    key = UNDS[und]["upstox"]
    try:
        daily = upstox_daily_closes(key)
        if len(daily) < 60:
            raise RuntimeError("thin daily data")
        try:
            intra = upstox_intraday_closes(key, "1minute")
            spot = intra[-1] if intra else daily[-1]
        except Exception:
            spot = daily[-1]
        return spot, daily
    except Exception as e:
        print(f"upstox failed for {und} ({e}); trying yahoo")
        return yahoo_chart(UNDS[und]["yahoo"])


def nse_chain(nse_symbol):
    base = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/option-chain"}
    last_err = None
    for _ in range(3):
        try:
            _, h = http_get("https://www.nseindia.com/option-chain", base)
            cookies = [v.split(";")[0] for k, v in h.items() if k.lower() == "set-cookie"]
            hdrs = dict(base)
            if cookies:
                hdrs["Cookie"] = "; ".join(cookies)
            body, _ = http_get("https://www.nseindia.com/api/option-chain-indices"
                               f"?symbol={nse_symbol}", hdrs)
            data = json.loads(body)["records"]
            expiry = data["expiryDates"][0]
            chain = {}
            for row in data["data"]:
                if row.get("expiryDate") != expiry:
                    continue
                s = float(row["strikePrice"])
                ce, pe = row.get("CE") or {}, row.get("PE") or {}
                chain[s] = {"ce_oi": ce.get("openInterest", 0), "ce_ltp": ce.get("lastPrice", 0),
                            "pe_oi": pe.get("openInterest", 0), "pe_ltp": pe.get("lastPrice", 0)}
            if chain:
                return expiry, chain
            last_err = "empty"
        except Exception as e:
            last_err = str(e)
        time.sleep(4)
    raise RuntimeError(f"chain unavailable: {last_err}")


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
    return t.weekday() < 5 and 555 <= t.hour * 60 + t.minute <= 930


def load_ledger():
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            return json.load(f)
    return {"capital": START_CAP, "open": [], "trades": [], "peak": START_CAP,
            "maxDD": 0.0, "halted": False, "last_run": None, "note": "initialized",
            "eq_hist": []}


def equity(L):
    return L["capital"] + sum(p["mark"] * UNDS[p["und"]]["lot"] * p["lots"] for p in L["open"])


def log(L, msg):
    print(msg)
    L["note"] = msg


# ── Telegram ──
def tg_api(method, payload):
    token = os.environ.get("TG_TOKEN", "")
    if not token:
        return None
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print("telegram error:", e)


def tg_chat_id(L):
    if L.get("tg_chat"):
        return L["tg_chat"]
    r = tg_api("getUpdates", {})
    if r and r.get("result"):
        for u in reversed(r["result"]):
            chat = (u.get("message") or {}).get("chat", {})
            if chat.get("id"):
                L["tg_chat"] = chat["id"]
                return L["tg_chat"]


def tg_send(L, text):
    chat = tg_chat_id(L)
    if chat:
        tg_api("sendMessage", {"chat_id": chat, "text": text})


def tg_daily_summary(L):
    eq = equity(L)
    today = now_ist().strftime("%d-%b")
    todays = [t for t in L["trades"] if t["time"].startswith(today)]
    closed_today = [t for t in todays if not t.get("open")]
    pnl_today = sum(t["pnl"] for t in closed_today)
    e = "🟢" if pnl_today >= 0 else "🔴"
    msg = (f"📊 Market closed — today's report\n"
           f"Money now: ₹{round(eq):,}\n"
           f"Today: {e} ₹{round(pnl_today):,} ({len(todays)} trade(s))\n"
           f"Goal progress: {eq/1000000*100:.1f}% of ₹10L")
    if L["open"]:
        msg += "\nHolding overnight: " + ", ".join(
            f"{p['und']} {p['strike']} {p['side']}" for p in L["open"])
    tg_send(L, msg)


# ── Report ──
def write_report(L):
    eq = equity(L)
    closed = [t for t in L["trades"] if not t.get("open")]
    wins = [t for t in closed if t["pnl"] > 0]
    wr = f"{round(100*len(wins)/len(closed))}%" if closed else "—"
    pnl = eq - START_CAP
    arrow = "🟢" if pnl >= 0 else "🔴"
    lines = [
        "# 🤖 Jarvis Paper Trading — Live Dashboard", "",
        f"**Updated:** {L['last_run'] or ''}", "",
        "| Money now | Profit/Loss | Goal (₹10 Lakh) | Trades | Win rate | Worst dip |",
        "|---|---|---|---|---|---|",
        f"| **₹{round(eq):,}** | {arrow} ₹{round(pnl):,} | {eq/1000000*100:.1f}% | {len(closed)} | {wr} | {L['maxDD']:.1f}% |",
        "",
        f"**What Jarvis is thinking right now:** {L['note']}", "",
    ]
    hist = L.get("eq_hist", [])
    if len(hist) >= 2:
        pts = hist[-60:]
        lines += ["## Money over time (equity curve)", "", "```mermaid",
                  "xychart-beta",
                  '  title "Account value ₹"',
                  "  x-axis [" + ", ".join(f'"{p[0]}"' for p in pts) + "]",
                  f"  y-axis \"₹\" {min(v for _, v in pts)*0.99:.0f} --> {max(v for _, v in pts)*1.01:.0f}",
                  "  line [" + ", ".join(str(round(v)) for _, v in pts) + "]",
                  "```", ""]
    by_strat = {}
    for t in closed:
        s = t.get("strategy", "other")
        by_strat.setdefault(s, []).append(t)
    if by_strat:
        lines += ["## Which strategy is earning?", "",
                  "| Strategy | Trades | Wins | Total P&L |", "|---|---|---|---|"]
        for s, ts in by_strat.items():
            w = sum(1 for t in ts if t["pnl"] > 0)
            lines.append(f"| {s} | {len(ts)} | {w} | ₹{sum(t['pnl'] for t in ts):,} |")
        lines.append("")
    lines += ["## Open trades"]
    if L["open"]:
        lines += ["| Trade | Lots | Bought at | Now at | Profit/Loss | Strategy |", "|---|---|---|---|---|---|"]
        for p in L["open"]:
            pl = (p["mark"] - p["entry"]) * UNDS[p["und"]]["lot"] * p["lots"]
            e = "🟢" if pl >= 0 else "🔴"
            lines.append(f"| {p['und']} {p['strike']} {p['side']} | {p['lots']} | ₹{p['entry']} | ₹{p['mark']} | {e} ₹{round(pl):,} | {p.get('strategy','')} |")
    else:
        lines.append("_None right now — waiting for a good opportunity (this is normal and safe)._")
    lines += ["", "## Trade history (latest first)"]
    if L["trades"]:
        lines += ["| When | Trade | Bought | Sold | Profit/Loss | Why |", "|---|---|---|---|---|---|"]
        for t in reversed(L["trades"][-25:]):
            ex = f"₹{t['exit']}" if not t.get("open") else "OPEN"
            pl = f"₹{t['pnl']:,}" if not t.get("open") else "—"
            lines.append(f"| {t['time']} | {t['und']} {t['strike']} {t['side']} ×{t['lots']} | ₹{t['entry']} | {ex} | {pl} | {t['reason'][:90]} |")
    else:
        lines.append("_No trades yet. Trading starts automatically when markets open (Mon–Fri, 9:15 AM)._")
    lines += ["", "## How Jarvis decides (plain words)",
              "- **wall-break** strategy: big players park huge option bets at certain levels — these act as floor and ceiling. When price smashes through one AND the trend agrees, Jarvis buys that direction. Stop-loss −30%, target +60%.",
              "- **scalp** experiment: when price makes a sharp fast move within the day, Jarvis rides it briefly. Smaller size (15%), tight stop −20%, quick target +30%, auto-exit within 60 minutes.",
              "- **expiry-gamma** experiment: only on expiry day (9:30 AM-2:00 PM), when the index makes a sharp fast move — options are dirt cheap on expiry so small moves pay big. Tiny 10% size, stop -25%, target +50%, auto-exit in 45 minutes. Never in the final 90 minutes where time-decay eats everything.",
              "- Most of the time: **no trade**. Sitting out when there's no edge is the strategy working, not failing.",
              "- Hard safety rules: max 2 positions, max 3 trades/day, sizes halve below ₹80k, everything halts below ₹60k.",
              "", "---",
              "_Paper trading only — practice money, no real orders ever. Refresh anytime for the latest._"]
    with open("REPORT.md", "w") as f:
        f.write("\n".join(lines))


def close_position(L, p, price, why):
    lot = UNDS[p["und"]]["lot"]
    proceeds = price * lot * p["lots"]
    L["capital"] += proceeds
    pnl = proceeds - p["entry"] * lot * p["lots"]
    for t in L["trades"]:
        if t.get("open") and t["strike"] == p["strike"] and t["side"] == p["side"] and t["und"] == p["und"]:
            t.update({"exit": price, "pnl": round(pnl), "open": False,
                      "reason": t["reason"] + " → " + why})
            break
    L["open"].remove(p)
    log(L, f"EXIT {p['und']} {p['side']} {p['strike']} @ {price} ({why}) pnl {round(pnl)}")
    e = "🟢" if pnl >= 0 else "🔴"
    tg_send(L, f"{e} SOLD: {p['und']} {p['strike']} {p['side']} at ₹{price}\n"
               f"Result: ₹{round(pnl):,} ({why})\nMoney now: ₹{round(equity(L)):,}")


def open_position(L, und, side, strike, prem, why, expiry, strategy):
    eq = equity(L)
    lot = UNDS[und]["lot"]
    cap = {"scalp": SCALP_OUTLAY, "expiry-gamma": EXP_OUTLAY}.get(strategy, WALL_OUTLAY)
    if eq < DERISK_EQ:
        cap /= 2
    lots = int((eq * cap) // (prem * lot))
    if lots < 1:
        log(L, f"skip {und} {side} {strike}: premium {prem} too big for sizing")
        return
    cost = prem * lot * lots
    if cost > L["capital"]:
        return
    L["capital"] -= cost
    sl_pct, tgt_pct = {"scalp": (SCALP_SL, SCALP_TGT),
                       "expiry-gamma": (EXP_SL, EXP_TGT)}.get(strategy, (WALL_SL, WALL_TGT))
    t = now_ist().strftime("%d-%b %H:%M")
    L["open"].append({"und": und, "side": side, "strike": strike, "entry": prem, "mark": prem,
                      "lots": lots, "sl": round(prem*(1-sl_pct), 1), "tgt": round(prem*(1+tgt_pct), 1),
                      "time": t, "expiry": expiry, "strategy": strategy,
                      "ts": int(time.time())})
    L["trades"].append({"time": t, "und": und, "side": side, "strike": strike, "lots": lots,
                        "entry": prem, "exit": None, "pnl": 0, "open": True,
                        "strategy": strategy, "reason": why})
    log(L, f"ENTER {und} {side} {strike} x{lots} @ {prem} [{strategy}] — {why}")
    tg_send(L, f"🛒 BOUGHT: {und} {strike} {side} ×{lots} lot(s) at ₹{prem}\n"
               f"Strategy: {strategy}\nWhy: {why}\n"
               f"Safety stop: ₹{round(prem*(1-sl_pct),1)} | Target: ₹{round(prem*(1+tgt_pct),1)}")


def trades_today(L):
    today = now_ist().strftime("%d-%b")
    return sum(1 for t in L["trades"] if t["time"].startswith(today))


def save_ledger(L):
    L["last_run"] = now_ist().strftime("%d-%b-%Y %H:%M IST")
    eq = round(equity(L))
    hist = L.setdefault("eq_hist", [])
    stamp = now_ist().strftime("%d %H:%M")
    if not hist or hist[-1][1] != eq:
        hist.append([stamp, eq])
        del hist[:-300]
    with open(LEDGER, "w") as f:
        json.dump(L, f, indent=1)
    try:
        write_report(L)
    except Exception as e:
        print("report failed:", e)


def main():
    L = load_ledger()
    t = now_ist()

    if not L.get("tg_hello") and os.environ.get("TG_TOKEN") and tg_chat_id(L):
        tg_send(L, "🤖 Jarvis connected! I will message you here for every trade "
                   "and a daily report at market close. Paper trading only — practice money.")
        L["tg_hello"] = True

    if L["halted"]:
        log(L, "desk halted (drawdown) — no action"); save_ledger(L); return
    if not market_open(t):
        m = t.hour * 60 + t.minute
        today_s = str(t.date())
        if 930 < m <= 1025 and t.weekday() < 5 and L.get("summary_date") != today_s:
            tg_daily_summary(L)
            L["summary_date"] = today_s
        log(L, "market closed — no action"); save_ledger(L); return

    # ── data per underlying ──
    data = {}
    for und, cfg in UNDS.items():
        try:
            spot, closes = get_prices(und)
            e21 = ema(closes[-80:], 21)
            data[und] = {"spot": spot, "e21": e21}
        except Exception as e:
            print(f"{und} price data failed: {e}")
    if not data:
        log(L, "all price data unavailable — holding safely"); save_ledger(L); return

    chains = {}
    for und in list(data.keys()):
        try:
            expiry, chain = nse_chain(UNDS[und]["nse"])
            chains[und] = {"expiry": expiry, "chain": chain,
                           "exp_date": datetime.strptime(expiry, "%d-%b-%Y").date()}
            time.sleep(3)
        except Exception as e:
            print(f"{und} chain failed: {e}")

    # ── manage open positions ──
    for p in list(L["open"]):
        c = chains.get(p["und"])
        if c:
            row = c["chain"].get(float(p["strike"]))
            if row:
                m = row["ce_ltp"] if p["side"] == "CE" else row["pe_ltp"]
                if m and m > 0:
                    p["mark"] = m
        age_min = (int(time.time()) - p.get("ts", 0)) / 60
        squareoff = c and str(t.date()) == str(c["exp_date"]) and (t.hour, t.minute) >= (14, 45)
        if p["mark"] <= p["sl"]:
            close_position(L, p, p["mark"], "safety stop hit")
        elif p["mark"] >= p["tgt"]:
            close_position(L, p, p["mark"], "target hit")
        elif p.get("strategy") == "scalp" and age_min >= SCALP_MAX_MIN:
            close_position(L, p, p["mark"], "scalp time-up (60 min)")
        elif p.get("strategy") == "expiry-gamma" and age_min >= EXP_MAX_MIN:
            close_position(L, p, p["mark"], "expiry trade time-up (45 min)")
        elif squareoff:
            close_position(L, p, p["mark"], "expiry squareoff")

    eq = equity(L)
    L["peak"] = max(L["peak"], eq)
    L["maxDD"] = max(L["maxDD"], round((L["peak"] - eq) / L["peak"] * 100, 1))
    if eq < HALT_EQ:
        L["halted"] = True
        log(L, f"DESK HALTED at equity {round(eq)}")
        tg_send(L, f"⛔ Desk halted at ₹{round(eq):,} (40% drawdown rule). "
                   "We review the strategy together before it trades again.")
        save_ledger(L); return

    # ── entries ──
    can_enter = len(L["open"]) < MAX_POSITIONS and trades_today(L) < MAX_TRADES_PER_DAY
    holds = []
    if can_enter:
        for und, d in data.items():
            if len(L["open"]) >= MAX_POSITIONS:
                break
            c = chains.get(und)
            if not c:
                continue
            spot, e21 = d["spot"], d["e21"]
            chain, expiry = c["chain"], c["expiry"]
            if str(t.date()) == str(c["exp_date"]) and t.hour >= 13:
                continue
            band = 600 if und == "NIFTY" else 1400
            ce_b = {s: v["ce_oi"] for s, v in chain.items() if spot <= s <= spot+band and v["ce_oi"] > 0}
            pe_b = {s: v["pe_oi"] for s, v in chain.items() if spot-band <= s <= spot and v["pe_oi"] > 0}
            ce_w = max(ce_b, key=ce_b.get) if ce_b else None
            pe_w = max(pe_b, key=pe_b.get) if pe_b else None
            atm = min(chain, key=lambda s: abs(s - spot))
            gap = 50 if und == "NIFTY" else 100
            if ce_w and spot > ce_w - gap and (e21 is None or spot > e21):
                prem = chain[atm]["ce_ltp"]
                if prem > 0:
                    open_position(L, und, "CE", atm, prem,
                                  f"{und} at {round(spot,1)} pressing the big ceiling {ce_w}, trend up", expiry, "wall-break")
                    continue
            if pe_w and spot < pe_w - 20 and (e21 is None or spot < e21):
                prem = chain[atm]["pe_ltp"]
                if prem > 0:
                    open_position(L, und, "PE", atm, prem,
                                  f"{und} at {round(spot,1)} broke the big floor {pe_w}, trend down", expiry, "wall-break")
                    continue
            holds.append(f"{und} {round(spot,1)} between {pe_w}/{ce_w}")

        # scalp experiment — NIFTY only, max 1/day, needs intraday burst
        already_scalped = any(t2.get("strategy") == "scalp" and t2["time"].startswith(now_ist().strftime("%d-%b"))
                              for t2 in L["trades"])
        if not already_scalped and len(L["open"]) < MAX_POSITIONS and "NIFTY" in chains and trades_today(L) < MAX_TRADES_PER_DAY:
            try:
                m5 = upstox_intraday_closes(UNDS["NIFTY"]["upstox"], "1minute")
                if len(m5) >= 16:
                    mom = (m5[-1] - m5[-16]) / m5[-16] * 100
                    chain = chains["NIFTY"]["chain"]
                    atm = min(chain, key=lambda s: abs(s - m5[-1]))
                    if mom >= 0.30 and m5[-1] > m5[-2] > m5[-3]:
                        prem = chain[atm]["ce_ltp"]
                        if prem > 0:
                            open_position(L, "NIFTY", "CE", atm, prem,
                                          f"fast burst up {mom:.2f}% in 15 min — quick ride", chains["NIFTY"]["expiry"], "scalp")
                    elif mom <= -0.30 and m5[-1] < m5[-2] < m5[-3]:
                        prem = chain[atm]["pe_ltp"]
                        if prem > 0:
                            open_position(L, "NIFTY", "PE", atm, prem,
                                          f"fast drop {mom:.2f}% in 15 min — quick ride", chains["NIFTY"]["expiry"], "scalp")
            except Exception as e:
                print("scalp check failed:", e)

        # expiry-gamma experiment — only on an underlying's own expiry day
        already_exp = any(t2.get("strategy") == "expiry-gamma" and t2["time"].startswith(now_ist().strftime("%d-%b"))
                          for t2 in L["trades"])
        if not already_exp and len(L["open"]) < MAX_POSITIONS and trades_today(L) < MAX_TRADES_PER_DAY:
            m = t.hour * 60 + t.minute
            if 570 <= m <= 840:  # 09:30-14:00 only; last 90 min is pure decay poison
                for und in chains:
                    if str(t.date()) != str(chains[und]["exp_date"]):
                        continue
                    try:
                        m5 = upstox_intraday_closes(UNDS[und]["upstox"], "1minute")
                        if len(m5) < 16:
                            continue
                        mom = (m5[-1] - m5[-16]) / m5[-16] * 100
                        chain = chains[und]["chain"]
                        atm = min(chain, key=lambda s: abs(s - m5[-1]))
                        thr = 0.35
                        if mom >= thr and m5[-1] > m5[-2]:
                            prem = chain[atm]["ce_ltp"]
                            if prem > 0:
                                open_position(L, und, "CE", atm, prem,
                                              f"EXPIRY DAY spike: {und} up {mom:.2f}% fast — cheap option, big leverage, tight leash",
                                              chains[und]["expiry"], "expiry-gamma")
                                break
                        elif mom <= -thr and m5[-1] < m5[-2]:
                            prem = chain[atm]["pe_ltp"]
                            if prem > 0:
                                open_position(L, und, "PE", atm, prem,
                                              f"EXPIRY DAY drop: {und} down {mom:.2f}% fast — cheap option, big leverage, tight leash",
                                              chains[und]["expiry"], "expiry-gamma")
                                break
                    except Exception as e:
                        print("expiry-gamma check failed:", e)

    if not L["open"] and holds:
        log(L, "HOLD — " + "; ".join(holds))
    save_ledger(L)


if __name__ == "__main__":
    main()
