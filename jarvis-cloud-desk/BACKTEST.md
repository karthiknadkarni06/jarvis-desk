# 📊 Deep Backtest v3 — NIFTY · BANKNIFTY · SENSEX (5y daily)

Run 12-Jul-2026 15:41 UTC · data: Upstox public candles · timeframe: DAILY candles, signals at close

_PF = profit factor. >1.3 with 20+ trades = respectable edge. Points are index points._

## NIFTY (1240 days)

| Strategy | Trades | Win% | Net pts | PF |
|---|---|---|---|---|
| RSI<35 dip-buy uptrend — CE | 8 | 62% | +1006 | 1.60 |
| +2% burst 5d hold — CE | 58 | 57% | +2479 | 1.36 |
| EMA5/21 cross — CE | 32 | 31% | +2479 | 1.32 |
| EMA9/21 cross — CE | 25 | 40% | +2335 | 1.32 |
| EMA5 fast momentum 3d — CE | 53 | 57% | +492 | 1.07 |
| 20d breakout+trend — CE | 30 | 30% | +35 | 1.01 |

## BANKNIFTY (1240 days)

| Strategy | Trades | Win% | Net pts | PF |
|---|---|---|---|---|
| RSI<35 dip-buy uptrend — CE | 10 | 70% | +7518 | 3.28 |
| +2% burst 5d hold — CE | 62 | 63% | +19765 | 2.43 |
| EMA5/21 cross — CE | 34 | 38% | +8634 | 1.50 |
| EMA9/21 cross — CE | 25 | 36% | +6549 | 1.42 |
| 20d breakout+trend — CE | 29 | 41% | +2302 | 1.15 |
| EMA5 fast momentum 3d — CE | 60 | 53% | -3767 | 0.82 |

## SENSEX (1240 days)

| Strategy | Trades | Win% | Net pts | PF |
|---|---|---|---|---|
| EMA5/21 cross — CE | 33 | 30% | +6518 | 1.26 |
| EMA9/21 cross — CE | 25 | 36% | +5744 | 1.24 |
| +2% burst 5d hold — CE | 60 | 55% | +2376 | 1.08 |
| 20d breakout+trend — CE | 31 | 29% | +1427 | 1.07 |
| EMA5 fast momentum 3d — CE | 59 | 53% | -1935 | 0.93 |
| RSI<35 dip-buy uptrend — CE | 11 | 45% | -1295 | 0.88 |

## 🏆 Robustness check — strategies that worked on ALL THREE indices

- ✅ **EMA5/21 cross — CE** — NIFTY: PF 1.32 (32tr) · BANKNIFTY: PF 1.50 (34tr) · SENSEX: PF 1.26 (33tr)
- ✅ **EMA9/21 cross — CE** — NIFTY: PF 1.32 (25tr) · BANKNIFTY: PF 1.42 (25tr) · SENSEX: PF 1.24 (25tr)
- ✅ **+2% burst 5d hold — CE** — NIFTY: PF 1.36 (58tr) · BANKNIFTY: PF 2.43 (62tr) · SENSEX: PF 1.08 (60tr)
- ✅ **20d breakout+trend — CE** — NIFTY: PF 1.01 (30tr) · BANKNIFTY: PF 1.15 (29tr) · SENSEX: PF 1.07 (31tr)
- ⚠️ **RSI<35 dip-buy uptrend — CE** — NIFTY: PF 1.60 (8tr) · BANKNIFTY: PF 3.28 (10tr) · SENSEX: PF 0.88 (11tr)
- ⚠️ **EMA5 fast momentum 3d — CE** — NIFTY: PF 1.07 (53tr) · BANKNIFTY: PF 0.82 (60tr) · SENSEX: PF 0.93 (59tr)