#!/usr/bin/env python3
"""
Jarvis Cloud Desk — autonomous NIFTY option-buying paper trader.
Runs on GitHub Actions every ~20 min during market hours.
Strategy: OI-wall breakout with trend confirmation. BUY only. Paper only.

Env vars required (GitHub Secrets):
  DHAN_TOKEN      - Dhan Data API access token
  DHAN_CLIENT_ID  - Dhan client id
"""
import json, os, sys, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import urllib.request

IST = ZoneInfo("Asia/Kolkata")
API = "https://api.dhan.co/v2"
TOKEN = os.environ.get("DHAN_TOKEN", "")
CLIENT = os.environ.get("DHAN_CLIENT_ID", "")
LEDGER = "ledger.json"
LOT = 75  # NIFTY
NIFTY_ID = 13

# ── Risk framework (hard guardrails) ──
START_CAP = 100000
MAX_OUTLAY_PCT = 0.25      # premium per trade
MAX_POSITIONS = 2
MAX_TRADES_PER_DAY = 2
SL_PCT = 0.30              # -30%
TGT_PCT = 0.60             # +60%
DERISK_EQ = 80000          # halve size below this
HALT_EQ = 60000            # stop everything below this
EXPIRY_SQUAREOFF = (14, 45)  # HH, MM IST on expiry day


def api(path, payload):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode(),
        headers={"access-token": TOKEN, "client-id": CLIENT,
                 "Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def now_ist():
    return datetime.now(IST)


def market_open(t):
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return 555 <= m <= 930  # 09:15–15:30


def load_ledger():
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            return json.load(f)
    return {"capital": START_CAP, "open": [], "trades": [], "peak": START_CAP,
            "maxDD": 0.0, "halted": False, "last_run": None, "note": "initialized"}


def save_ledger(L):
    L["last_run"] = now_ist().strftime("%d-%b-%Y %H:%M IST")
    with open(LEDGER, "w") as f:
        json.dump(L, f, indent=1)


def equity(L):
    return L["capital"] + sum(p["mark"] * LOT * p["lots"] for p in L["open"])


def log(L, msg):
    print(msg)
    L["note"] = msg


def ema(vals, n):
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def get_spot_vix():
    d = api("/marketfeed/quote", {"IDX_I": [NIFTY_ID, 21]})
    data = d.get("data", {}).get("IDX_I", {})
    spot = data.get(str(NIFTY_ID), {}).get("last_price")
    vix = data.get("21", {}).get("last_price")
    return spot, vix


def get_chain():
    exp = api("/optionchain/expirylist", {"UnderlyingScrip": NIFTY_ID, "UnderlyingSeg": "IDX_I"})
    expiries = exp.get("data", [])
    if not expiries:
        raise RuntimeError("no expiries returned")
    expiry = expiries[0]
    time.sleep(3)  # option chain rate limit: 1 per 3s
    ch = api("/optionchain", {"UnderlyingScrip": NIFTY_ID, "UnderlyingSeg": "IDX_I", "Expiry": expiry})
    oc = ch.get("data", {}).get("oc", {})
    chain = {}
    for k, v in oc.items():
        strike = float(k)
        ce, pe = v.get("ce", {}), v.get("pe", {})
        chain[strike] = {
            "ce_oi": ce.get("oi", 0), "ce_ltp": ce.get("last_price", 0),
            "pe_oi": pe.get("oi", 0), "pe_ltp": pe.get("last_price", 0)}
    return expiry, chain


def get_ema21():
    to = now_ist().date() + timedelta(days=1)
    frm = to - timedelta(days=130)
    d = api("/charts/historical", {"securityId": str(NIFTY_ID), "exchangeSegment": "IDX_I",
                                   "instrument": "INDEX", "expiryCode": 0,
                                   "fromDate": str(frm), "toDate": str(to)})
    closes = d.get("close") or d.get("data", {}).get("close") or []
    return ema(closes[-80:], 21) if len(closes) >= 25 else None


def walls(chain, spot):
    ce_band = {s: v["ce_oi"] for s, v in chain.items() if spot <= s <= spot + 600 and v["ce_oi"] > 0}
    pe_band = {s: v["pe_oi"] for s, v in chain.items() if spot - 600 <= s <= spot and v["pe_oi"] > 0}
    ce_wall = max(ce_band, key=ce_band.get) if ce_band else None
    pe_wall = max(pe_band, key=pe_band.get) if pe_band else None
    return ce_wall, pe_wall


def atm_strike(chain, spot):
    return min(chain, key=lambda s: abs(s - spot))


def mark_positions(L, chain):
    for p in L["open"]:
        row = chain.get(float(p["strike"]))
        if row:
            m = row["ce_ltp"] if p["side"] == "CE" else row["pe_ltp"]
            if m and m > 0:
                p["mark"] = m


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
        log(L, f"skip entry {side} {strike}: premium {prem} too large for sizing")
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

    if not TOKEN or not CLIENT:
        log(L, "ERROR: DHAN_TOKEN / DHAN_CLIENT_ID secrets not set")
        save_ledger(L); return
    if L["halted"]:
        log(L, "desk halted (drawdown) — no action"); save_ledger(L); return
    if not market_open(t):
        log(L, "market closed — no action"); save_ledger(L); return

    try:
        spot, vix = get_spot_vix()
        expiry, chain = get_chain()
        if not spot or not chain:
            raise RuntimeError("empty spot/chain")
    except Exception as e:
        log(L, f"data fetch failed: {e} — holding safely")
        save_ledger(L); return

    mark_positions(L, chain)

    # ── manage exits ──
    is_expiry_day = str(t.date()) == expiry
    squareoff = is_expiry_day and (t.hour, t.minute) >= EXPIRY_SQUAREOFF
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

    # ── entries ──
    if len(L["open"]) < MAX_POSITIONS and trades_today(L) < MAX_TRADES_PER_DAY \
       and not (is_expiry_day and t.hour >= 13):  # no fresh theta bombs on expiry afternoon
        try:
            e21 = get_ema21()
        except Exception:
            e21 = None
        ce_wall, pe_wall = walls(chain, spot)
        atm = atm_strike(chain, spot)
        entered = False

        if ce_wall and spot > ce_wall - 50 and (e21 is None or spot > e21):
            prem = chain[atm]["ce_ltp"]
            if prem > 0:
                open_position(L, "CE", atm, prem,
                              f"spot {spot} pressing CE wall {ce_wall}, trend ok (EMA21 {round(e21,1) if e21 else 'n/a'})",
                              expiry)
                entered = True
        elif pe_wall and spot < pe_wall - 20 and (e21 is None or spot < e21):
            prem = chain[atm]["pe_ltp"]
            if prem > 0:
                open_position(L, "PE", atm, prem,
                              f"spot {spot} broke PE wall {pe_wall}, trend down (EMA21 {round(e21,1) if e21 else 'n/a'})",
                              expiry)
                entered = True

        if not entered and not L["open"]:
            log(L, f"HOLD — spot {spot} inside walls (PE {pe_wall} / CE {ce_wall}), VIX {vix}")

    save_ledger(L)


if __name__ == "__main__":
    main()
