"""Stage 3 feature registry: every item of the user's diagram (stage 3, six
groups), what Prajna does with it, and the exact definition of each feature.

status        IMPLEMENTED | UNSUPPORTED (no data source; source named) | UNKNOWN (no definition)
param_status  SPECIFIED (named by the diagram or fully determined by it)
              | PROPOSED (conventional, not named by the diagram; approved by the user
                2026-09-28, decision FEATURE-PARAMS)
scope         INSTRUMENT (per stock/index) | CONTEXT (market-wide; stored under the
              context instrument key, e.g. an index, a global instrument, or MARKET)
snapshots     which snapshots compute it (pre-open features: PRE_OPEN only)

Changing any definition changes REGISTRY_SHA256; stored values carry it, so
values computed under different definitions are never confused.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

VERSION = "features-v1"
BOTH = ("PRE_SESSION", "PRE_OPEN")
PRE_OPEN_ONLY = ("PRE_OPEN",)


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    id: str
    group: str
    definition: str
    status: str = "IMPLEMENTED"
    param_status: str = "SPECIFIED"
    params: dict = field(default_factory=dict)
    inputs: tuple[str, ...] = ()
    lookback_sessions: int = 0
    scope: str = "INSTRUMENT"
    snapshots: tuple[str, ...] = BOTH
    version: int = 1


def _p(id, group, definition, *, params=None, proposed=True, inputs=("daily_bars",),
       lookback=0, scope="INSTRUMENT", snapshots=BOTH, version=1):
    return FeatureSpec(id, group, definition, "IMPLEMENTED",
                       "PROPOSED" if proposed else "SPECIFIED", params or {}, tuple(inputs),
                       lookback, scope, snapshots, version)


CA_KINDS = ("any", "dividend", "split", "bonus")
PRICE, LIQ, FUND, EVENT, CTX, PRE = ("price_technical", "volume_liquidity", "fundamental",
                                     "event", "market_context", "preopen")

FEATURES: tuple[FeatureSpec, ...] = (
    # 1. price & technical
    _p("ret_1d", PRICE, "close / close 1 session earlier - 1", proposed=False, lookback=2),
    _p("ret_5d", PRICE, "close / close 5 sessions earlier - 1", proposed=False, lookback=6),
    _p("ret_20d", PRICE, "close / close 20 sessions earlier - 1", proposed=False, lookback=21),
    _p("sma_20", PRICE, "mean of the last 20 closes", params={"n": 20}, lookback=20),
    _p("sma_50", PRICE, "mean of the last 50 closes", params={"n": 50}, lookback=50),
    _p("sma_200", PRICE, "mean of the last 200 closes", params={"n": 200}, lookback=200),
    _p("close_to_sma_20", PRICE, "close / sma_20 - 1", params={"n": 20}, lookback=20),
    _p("close_to_sma_50", PRICE, "close / sma_50 - 1", params={"n": 50}, lookback=50),
    _p("close_to_sma_200", PRICE, "close / sma_200 - 1", params={"n": 200}, lookback=200),
    _p("ema_12", PRICE, "EMA alpha 2/13 seeded with SMA(12)", params={"n": 12}, lookback=12),
    _p("ema_26", PRICE, "EMA alpha 2/27 seeded with SMA(26)", params={"n": 26}, lookback=26),
    _p("rsi_14", PRICE, "Wilder RSI", params={"n": 14}, lookback=15),
    _p("macd_line", PRICE, "EMA12 - EMA26", params={"fast": 12, "slow": 26}, lookback=26),
    _p("macd_trigger", PRICE, "EMA9 of the MACD line",
       params={"fast": 12, "slow": 26, "trigger": 9}, lookback=34),
    _p("macd_histogram", PRICE, "MACD line - trigger",
       params={"fast": 12, "slow": 26, "trigger": 9}, lookback=34),
    _p("atr_14", PRICE, "Wilder average true range", params={"n": 14}, lookback=15),
    _p("atr_pct_14", PRICE, "atr_14 / close", params={"n": 14}, lookback=15),
    _p("volatility_20", PRICE, "sample stdev of 20 daily log returns * sqrt(252)",
       params={"n": 20, "annualisation": 252}, lookback=21),
    _p("beta_60", PRICE, "cov/var of 60 daily returns vs NIFTY 50 on common dates",
       params={"n": 60, "benchmark": "NSE_INDEX|Nifty 50"}, inputs=("daily_bars", "nifty_bars"),
       lookback=61),
    _p("dist_high_20", PRICE, "close / max(high, last 20) - 1", params={"n": 20}, lookback=20),
    _p("dist_low_20", PRICE, "close / min(low, last 20) - 1", params={"n": 20}, lookback=20),
    _p("breakout_20", PRICE, "1 if close > max(high of the 20 prior sessions) else 0",
       params={"n": 20}, lookback=21),
    _p("breakdown_20", PRICE, "1 if close < min(low of the 20 prior sessions) else 0",
       params={"n": 20}, lookback=21),
    # 2. volume & liquidity
    _p("avg_volume_20", LIQ, "mean volume of the last 20 sessions", params={"n": 20}, lookback=20),
    _p("volume_spike_20", LIQ, "last volume / mean volume of the 20 sessions before it",
       params={"n": 20}, lookback=21),
    _p("turnover_20", LIQ, "mean(close * volume) of the last 20 sessions, INR", params={"n": 20},
       lookback=20),
    # 3. fundamental (vendor snapshots)
    _p("pe", FUND, "company P/E (vendor key_ratios)", proposed=False, inputs=("key_ratios",)),
    _p("pb", FUND, "company P/B (vendor key_ratios)", proposed=False, inputs=("key_ratios",)),
    _p("roe_pct", FUND, "company ROE % (vendor key_ratios)", proposed=False,
       inputs=("key_ratios",)),
    _p("roce_pct", FUND, "company ROCE % (vendor key_ratios)", proposed=False,
       inputs=("key_ratios",)),
    _p("ev_ebitda", FUND, "company EV/EBITDA (vendor key_ratios)", proposed=False,
       inputs=("key_ratios",)),
    _p("pe_to_sector", FUND, "company P/E / sector P/E", proposed=False, inputs=("key_ratios",)),
    _p("pb_to_sector", FUND, "company P/B / sector P/B", proposed=False, inputs=("key_ratios",)),
    _p("revenue_yoy", FUND, "Revenue latest year / previous year - 1 (consolidated)",
       proposed=False, inputs=("income_yearly",)),
    _p("pat_yoy", FUND, "Profit After Tax latest year / previous year - 1 (consolidated)",
       proposed=False, inputs=("income_yearly",)),
    _p("eps_yoy", FUND, "EPS - Diluted latest year / previous year - 1 (consolidated)",
       proposed=False, inputs=("income_yearly",)),
    _p("revenue_yoy_q", FUND, "Revenue latest quarter / same quarter a year earlier - 1",
       proposed=False, inputs=("income_quarterly",)),
    _p("pat_yoy_q", FUND, "Profit After Tax latest quarter / same quarter a year earlier - 1",
       proposed=False, inputs=("income_quarterly",)),
    _p("liabilities_to_assets", FUND, "(Current + Non-Current Liabilities) / Total Assets, latest "
       "year (total liabilities: the vendor balance sheet has no debt line)", proposed=False,
       inputs=("balance_sheet",)),
    # 4. event (knowable before the snapshot)
    *[_p(f"ca_days_since_{k}", EVENT, f"days since the latest {k} ex-date <= session",
         proposed=False, inputs=("corporate_actions",)) for k in CA_KINDS],
    *[_p(f"ca_days_to_{k}", EVENT, f"days until the next knowable {k} ex-date > session",
         proposed=False, inputs=("corporate_actions",)) for k in CA_KINDS],
    _p("news_count_24h", EVENT, "linked news published in the 24 h before as_of", proposed=False,
       inputs=("news",)),
    _p("news_count_7d", EVENT, "linked news published in the 7 days before as_of", proposed=False,
       inputs=("news",)),
    _p("news_hours_since_last", EVENT, "hours from the latest linked publication to as_of",
       proposed=False, inputs=("news",)),
    # 5. market context
    _p("index_ret_1d", CTX, "index close / previous close - 1 (NIFTY 50, NIFTY BANK)",
       proposed=False, scope="CONTEXT", lookback=2),
    _p("index_ret_5d", CTX, "index close / close 5 sessions earlier - 1", proposed=False,
       scope="CONTEXT", lookback=6),
    _p("index_close_to_sma_50", CTX, "index close / SMA50 - 1", params={"n": 50}, scope="CONTEXT",
       lookback=50),
    _p("india_vix_level", CTX, "India VIX last close", proposed=False, scope="CONTEXT", lookback=1),
    _p("india_vix_change_5d", CTX, "India VIX close - close 5 sessions earlier (points)",
       params={"n": 5}, scope="CONTEXT", lookback=6),
    # version 2 (decision FII-DII-STALENESS): the observation must be the snapshot's
    # previous trading session, else MISSING_INPUT (v1 took the latest published day)
    _p("fii_net_cash_1d", CTX, "FII NSE cash buy - sell of the previous trading session (INR "
       "crore); MISSING_INPUT if that session is not the latest observation", proposed=False,
       inputs=("fii_dii",), scope="CONTEXT", version=2),
    _p("fii_net_cash_5d", CTX, "FII NSE cash net, sum of the last 5 observed days ending at the "
       "previous trading session; MISSING_INPUT otherwise", params={"n": 5},
       inputs=("fii_dii",), scope="CONTEXT", version=2),
    _p("dii_net_cash_1d", CTX, "DII NSE cash buy - sell of the previous trading session (INR "
       "crore); MISSING_INPUT if that session is not the latest observation", proposed=False,
       inputs=("fii_dii",), scope="CONTEXT", version=2),
    _p("dii_net_cash_5d", CTX, "DII NSE cash net, sum of the last 5 observed days ending at the "
       "previous trading session; MISSING_INPUT otherwise", params={"n": 5},
       inputs=("fii_dii",), scope="CONTEXT", version=2),
    _p("global_ret_1d", CTX, "return between the two latest CONFIRMED labels (per global "
       "instrument)", proposed=False, inputs=("global_bars",), scope="CONTEXT"),
    _p("sector_rs_20", CTX, "ret_20d - median ret_20d of the stock's point-in-time sector "
       "(>= 3 members)", params={"n": 20, "min_members": 3}, inputs=("daily_bars", "sector"),
       lookback=21),
    # 6. pre-open (PRE_OPEN snapshot only)
    _p("preopen_gap_pct", PRE, "IEP / previous close - 1 (indicative gap)", proposed=False,
       inputs=("preopen", "daily_bars"), snapshots=PRE_OPEN_ONLY, lookback=1),
    _p("preopen_imbalance", PRE, "(buy qty - sell qty) / (buy qty + sell qty)", proposed=False,
       inputs=("preopen",), snapshots=PRE_OPEN_ONLY),
    _p("preopen_ieq", PRE, "indicative equilibrium quantity", proposed=False, inputs=("preopen",),
       snapshots=PRE_OPEN_ONLY),
    _p("preopen_ieq_to_avg_volume", PRE, "ieq / avg_volume_20", params={"n": 20},
       inputs=("preopen", "daily_bars"), snapshots=PRE_OPEN_ONLY, lookback=20),
)

# Diagram items (stage 3) and what Prajna does with each. Every item appears once.
DIAGRAM: tuple[dict, ...] = (
    {"group": PRICE, "item": "Returns (1d, 5d, 20d)", "features": ["ret_1d", "ret_5d", "ret_20d"]},
    {"group": PRICE, "item": "Moving averages (SMA, EMA)",
     "features": ["sma_20", "sma_50", "sma_200", "close_to_sma_20", "close_to_sma_50",
                  "close_to_sma_200", "ema_12", "ema_26"]},
    {"group": PRICE, "item": "RSI, MACD, ATR",
     "features": ["rsi_14", "macd_line", "macd_trigger", "macd_histogram", "atr_14", "atr_pct_14"]},
    {"group": PRICE, "item": "Volume indicators", "features": ["avg_volume_20", "volume_spike_20"]},
    {"group": PRICE, "item": "Support/resistance, breakouts",
     "features": ["dist_high_20", "dist_low_20", "breakout_20", "breakdown_20"],
     "partial": "UNKNOWN: support/resistance LEVELS beyond the 20-session range have no "
                "definition in any source"},
    {"group": PRICE, "item": "Volatility, beta", "features": ["volatility_20", "beta_60"]},
    {"group": LIQ, "item": "Average volume", "features": ["avg_volume_20"]},
    {"group": LIQ, "item": "Volume spikes", "features": ["volume_spike_20"]},
    {"group": LIQ, "item": "Turnover, bid-ask spread", "features": ["turnover_20"],
     "partial": "UNSUPPORTED: bid-ask spread needs an all-day quote/tick store (Stage 1 "
                "criterion L OUT_OF_SCOPE; Stage 7)"},
    {"group": LIQ, "item": "Order book imbalance", "features": [],
     "status": "UNSUPPORTED", "reason": "all-day order book needs a live tick store (Stage 7); "
     "the pre-open book imbalance is implemented as preopen_imbalance"},
    {"group": FUND, "item": "Valuation ratios (P/E, P/B, etc.)",
     "features": ["pe", "pb", "ev_ebitda", "pe_to_sector", "pb_to_sector"]},
    {"group": FUND, "item": "Earnings growth",
     "features": ["revenue_yoy", "pat_yoy", "eps_yoy", "revenue_yoy_q", "pat_yoy_q"]},
    {"group": FUND, "item": "Balance sheet strength", "features": ["liabilities_to_assets"]},
    {"group": FUND, "item": "ROE, ROCE, debt levels",
     "features": ["roe_pct", "roce_pct", "liabilities_to_assets"],
     "partial": "debt: the vendor balance sheet has no debt line; total liabilities / assets "
                "is provided and named as such"},
    {"group": FUND, "item": "Earnings surprises", "features": [], "status": "UNSUPPORTED",
     "reason": "no consensus estimates exist in any source (Upstox provides none)"},
    {"group": EVENT, "item": "Earnings dates", "features": [], "status": "UNSUPPORTED",
     "reason": "the vendor provides no earnings calendar; the corporate-action feed has "
               "dividends, splits, bonuses and rights only"},
    {"group": EVENT, "item": "Corporate actions",
     "features": [f"ca_days_since_{k}" for k in ("any", "dividend", "split", "bonus")]
     + [f"ca_days_to_{k}" for k in ("any", "dividend", "split", "bonus")]},
    {"group": EVENT, "item": "News sentiment", "features": ["news_count_24h", "news_count_7d",
                                                            "news_hours_since_last"],
     "partial": "UNSUPPORTED: sentiment itself (no sentiment source or approved model); news "
                "volume and recency are provided and are not sentiment"},
    {"group": EVENT, "item": "Analyst upgrades/downgrades", "features": [], "status": "UNSUPPORTED",
     "reason": "no analyst-rating source (Upstox provides none)"},
    {"group": EVENT, "item": "Sector/market events", "features": [], "status": "UNKNOWN",
     "reason": "no definition of a sector/market event exists in any source"},
    {"group": CTX, "item": "NIFTY/BANKNIFTY trend",
     "features": ["index_ret_1d", "index_ret_5d", "index_close_to_sma_50"]},
    {"group": CTX, "item": "India VIX level",
     "features": ["india_vix_level", "india_vix_change_5d"]},
    {"group": CTX, "item": "FII/DII flows",
     "features": ["fii_net_cash_1d", "fii_net_cash_5d", "dii_net_cash_1d", "dii_net_cash_5d"]},
    {"group": CTX, "item": "Global market direction", "features": ["global_ret_1d"]},
    {"group": CTX, "item": "Sector relative strength", "features": ["sector_rs_20"]},
    {"group": CTX, "item": "Market regime (bull/bear/sideways)", "features": [],
     "status": "UNKNOWN",
     "reason": "no regime definition exists in any source; inventing one is a modelling decision"},
    {"group": PRE, "item": "IEP vs previous close", "features": ["preopen_gap_pct"]},
    {"group": PRE, "item": "Buy/sell imbalance", "features": ["preopen_imbalance"]},
    {"group": PRE, "item": "Indicative volume",
     "features": ["preopen_ieq", "preopen_ieq_to_avg_volume"]},
    {"group": PRE, "item": "Gap up/down %", "features": ["preopen_gap_pct"],
     "partial": "the open is not knowable before 09:15; the gap is indicated by the IEP"},
    {"group": PRE, "item": "Pre-open news/events", "features": ["news_count_24h"],
     "partial": "UNSUPPORTED: pre-open-specific events (no event source); news published before "
                "the snapshot is counted"},
)

BY_ID = {f.id: f for f in FEATURES}
CONTEXT_INDEX_KEYS = ("NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank")
VIX_KEY = "NSE_INDEX|India VIX"
MARKET_KEY = "MARKET"


def registry_document() -> dict:
    return {"version": VERSION, "features": [asdict(f) for f in FEATURES], "diagram": list(DIAGRAM)}


REGISTRY_SHA256 = hashlib.sha256(json.dumps(registry_document(), sort_keys=True,
                                            default=str).encode()).hexdigest()


def diagram_status(d: dict) -> str:
    return d.get("status") or ("PARTIAL" if d.get("partial") else "IMPLEMENTED")


def summary() -> dict:
    impl = [f for f in FEATURES if f.status == "IMPLEMENTED"]
    items = {"IMPLEMENTED": 0, "PARTIAL": 0, "UNSUPPORTED": 0, "UNKNOWN": 0}
    for d in DIAGRAM:
        items[diagram_status(d)] += 1
    return {"version": VERSION, "registry_sha256": REGISTRY_SHA256, "features": len(FEATURES),
            "implemented": len(impl),
            "proposed_parameters": sum(1 for f in impl if f.param_status == "PROPOSED"),
            "diagram_items": len(DIAGRAM), "diagram_items_by_status": items}
