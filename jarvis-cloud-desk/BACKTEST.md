# 📊 Deep Backtest — NIFTY, 5 Years Daily

**Data:** 1241 trading days · source: Upstox public candles · run 11-Jul-2026 18:32 UTC

**Monday-readiness diagnostic (from cloud server):** Upstox intraday: OK (0 candles) · NSE: OK · Yahoo: FAIL: HTTP Error 429: Too Many Requests

_Measures directional signal edge in index points; options amplify both ways. PF = profit factor (>1.3 with 20+ trades = respectable)._

| Strategy | Trades | Win% | Net pts | Avg/trade | PF |
|---|---|---|---|---|---|
| RSI<35 dip-buy in uptrend — CE | 8 | 62% | +1006 | +126 | 1.60 |
| +2% burst continuation, 5d hold — CE | 58 | 57% | +2479 | +43 | 1.36 |
| EMA9/21 cross up — buy CE, hold trend | 25 | 40% | +2335 | +93 | 1.32 |
| 20d high breakout + uptrend — CE | 30 | 30% | +35 | +1 | 1.01 |
| 3-red-days bounce — CE | 76 | 62% | -3289 | -43 | 0.67 |
| -2% drop continuation, 5d hold — PE | 46 | 48% | -3750 | -82 | 0.59 |
| EMA9/21 cross down — buy PE, hold trend | 26 | 27% | -3986 | -153 | 0.41 |
| 20d low breakdown — PE | 32 | 16% | -7195 | -225 | 0.20 |

## 🏆 Top 5 (min 8 trades, by profit factor)

1. **RSI<35 dip-buy in uptrend — CE** — PF 1.60 · 62% wins · 8 trades · +1006 pts
2. **+2% burst continuation, 5d hold — CE** — PF 1.36 · 57% wins · 58 trades · +2479 pts
3. **EMA9/21 cross up — buy CE, hold trend** — PF 1.32 · 40% wins · 25 trades · +2335 pts
4. **20d high breakout + uptrend — CE** — PF 1.01 · 30% wins · 30 trades · +35 pts
5. **3-red-days bounce — CE** — PF 0.67 · 62% wins · 76 trades · -3289 pts