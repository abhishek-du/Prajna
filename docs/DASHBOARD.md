# Prajna research dashboard (built 2026-10-22, user request)

**Open:** http://127.0.0.1:8600. It is bound to localhost only.
- Start or stop with `backend/ops/runbooks/dashboard.sh start|stop|status`.
- Cron starts it at boot and checks every 10 min that it is still running.

**What it is:** a read-only view of the Prajna database.
- It lives in `backend/app/dashboard/`, never in `frontend/` or `backend/app/api/`.
- It makes no database write; every transaction is set read only. The only write is the on-disk cache of AI notes.
- **Paper research only, not investment advice.** No order is ever placed.

| Tab | Contents |
|---|---|
| Market | Nifty 50 / Bank / VIX; regime (regime-v1); breadth; top gainers and losers; AI-tagged hot topics; stocks in the news; sector heat map; latest news |
| Movers | Best and worst returns by cap bucket (large / mid / small) and period (session / 5 d / 20 d); "steadier" (large/mid, uptrend, lowest 20-day volatility: lower volatility, not safe); research bullish / bearish |
| Sectors | Every sector's median move. Click a sector for its stocks |
| News | 6 h – 7 d. Topics, most mentioned stocks, each item with its description and its AI enrichment (summary, impact, direction) |
| Stock | Candles 1D (split/bonus adjusted, all history) / 1H / 15M / 5M with SMA 20/50 and pattern markers; candle-by-candle analysis; research signal with every reason; typical ranges; E5 today; AI note (on request); forensic flags; valuation vs sector; shareholding; results; corporate actions; 30 days of news |
| Model | E5's ranking for today only. Its past picks and their returns stay hidden until the single look after session 40 (pre-registration) |

## Rules (fixed, shown on the page)

- **Research signal `dash-signal-v1`** (`app/dashboard/analysis.py`):
  - price vs its 20/50/200-day averages: ±1 each;
  - RSI bands: ±1, and −0.5 when overbought;
  - MACD histogram sign: ±0.5;
  - 3-day company news tone: ±1;
  - E5: +1 if picked, else P(up) ±0.5, and expected return ±0.5.
  - The label is BULLISH at ≥ +3, BEARISH at ≤ −3, otherwise NEUTRAL.
- **Ranges, never targets:** E5's q10–q90 for the next session, and ±ATR×√5 for about a week.
- **Candle patterns:** fixed geometric rules (doji, hammer / hanging man, shooting star / inverted hammer, engulfing, gaps, inside bar, marubozu, volume spike).
- **Cap buckets:** the SEBI/AMFI rank rule by market cap (1–100 large, 101–250 mid, the rest small). Market cap = last close × shares, where shares = FY profit after tax / FY basic EPS (`app/fundamentals/ratios.py`). A stock without that data is UNCLASSIFIED.
- **Forensic flags** from the vendor fundamentals: P/E vs sector, ROE, liabilities/assets, profit growth, EPS vs a year ago, promoter holding change, pledges. This is not an audit.
- **AI:**
  - News enrichment comes from the 30-minute job.
  - The stock note is generated on request: one Bedrock call per stock per day, cached in `backend/var/dashboard/ai/`.
  - The model gets only the page's facts and is told not to predict prices or advise. An answer with advice or a price target is rejected.

## Live quotes (2026-10-22, user: "sab live hona chaiye")

`app/dashboard/live.py` runs a poller inside the dashboard process. It reads Upstox `/v2/market-quote/quotes` for every active NSE instrument (3,569; 500 keys a request).
- **Cadence:** every 30 s from 09:00 to 15:45 IST on a trading day, every 20 min otherwise. The day's close shows as soon as the session ends.
- **What uses it:** prices, changes, breadth, indices, movers and sectors; the stock page's price box (O/H/L, previous close, volume, circuit limits; refreshed every 30 s); and today's provisional candle.
- **Display only.** Quotes stay in memory. They are never written to the database and are never an input of a feature or a model, which stay point in time.
- **Read-only market data.** No order API is ever called.
- **Token:** the dashboard uses the cached Upstox token and never logs in. Without a valid token it shows "Live quotes unavailable" and falls back to stored bars.
- **Rate limit:** its own limiter (4/s, 120/min, 1500/30 min), well inside Upstox's per-API limits.
- **Switch off:** `PRAJNA_DASHBOARD_LIVE=0`.

## Live indicators and the trade plan (2026-10-22)

**Indicators** (`app/dashboard/indicators.py`) are recomputed after every quote cycle (30 s in market hours). They use the same functions as Stage 3 (`app.features.compute.price`) on the stored daily bars up to the last session plus today's bar from the live quote. Indicators: returns, SMA 20/50/200 distance, RSI 14, MACD histogram, ATR %, 20-day volatility and the 52-week range.
- The research signal, the trend, the market tables, the stock page and the trade plan all use them.
- They are display only: never stored, never a model input.
- The history is the stored daily bars, not the per-stock CA-adjusted read Stage 3 uses, so a stock with a recent split or bonus can differ a little.

**Trade plan `dash-plan-v1`** (`analysis.trade_plan`). The action comes from the signal (BULLISH → BUY, NEUTRAL → HOLD / WAIT, BEARISH → SELL / AVOID).

| Action | Levels |
|---|---|
| BUY | entry zone = [max(price − 0.5 ATR, SMA 20), price]; stop = 20-day low − 0.25 ATR, or entry − 1.5 ATR when that low is nearer than 1 ATR or farther than 3 ATR; R = entry − stop; T1 = entry + 1.5 R, T2 = entry + 3 R |
| HOLD / WAIT | buy only above the 20-day high (else price + 0.5 ATR), with the same stop / T1 / T2 rule from that trigger; holding stop = max(20-day low, price − 2 ATR) |
| SELL / AVOID | exit zone up to the 20-day average (or price + 0.5 ATR); downside levels price − 1.5 ATR and − 3 ATR; stop for the view = price + 1.5 ATR |

- Every plan lists "when to buy", "when to sell / exit" and how each level was computed.
- The levels are drawn on the chart.
- Candle analysis adds a plain-language reading of the last 5 candles' patterns.
- **These are fixed technical rules on an unvalidated model:** not validated, not investment advice, paper research only.

## Data freshness

- Market figures come from the latest Stage 3 PRE_SESSION snapshot and the last daily bars (07:00 job).
- **Price and change:** the latest stored bar. Today's 1m bars are stored by the 16:05 job, so after that, price = today's last 1m close and change = vs the last daily close; before it, the last daily close.
- **Chart:** the 1D chart adds a provisional candle for today, built from those 1m bars, until the official daily bar arrives with the next morning's job.
- **Found on 2026-10-22:** the stock header showed the last *daily* close (2026-10-21) after the session had closed. CUBEXTUB showed 220.90; it closed at 216.49.
- The pages refresh every 60–120 s, and the market view is cached for 2 min. It is not tick by tick.

## Notes

- The chart library (TradingView Lightweight Charts 4.1.3, Apache-2.0) is served from `static/`. This network re-signs TLS, so loading it from a CDN fails.
- Tests: `tests/unit/test_dashboard_analysis.py` covers the patterns, the signal, ranges, forensic, cap buckets and the AI-note validation.
