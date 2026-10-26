"""The frozen numbers of P1 (docs/STAGE4_P1_SHADOW_PREREGISTRATION.md §1). Every value is
from docs/VARSITY_PLAYBOOK.md / docs/STAGE4_AI_AGENT_DESIGN.md / app/paper/risk.py, or is
marked PRAJNA_DEFAULT. A change after the freeze is a new POLICY_VERSION with a fresh
forward window (never an edit of these values)."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

POLICY_VERSION = "p1-shadow-v1"
REGIME_VERSION = "regime-v0"
S1, S2 = "orb_breadth_v1", "vwap_revert_v1"
STRATEGIES = (S1, S2)

# Set at the freeze commit (the first trading session after it). None: commits refused.
FORWARD_FROM: _dt.date | None = None

BOOK = {
    "equity_inr": 1_000_000.0,      # reduced total equity, core only (no locked profit in shadow)
    "risk_pct": 0.01,               # Playbook §3 / Design L0
    "open_risk_cap": 0.03,          # Playbook law 1 / Design L0
    "max_open": 3,                  # 3 % / 1 %
    "sector_cap": 3,                # Design L0 / risk.py
    "max_positions": 10,            # Design L0 / risk.py
    "daily_loss_halt": 0.03,        # risk.py daily_loss_halt
    "dd_half": 0.05,                # PRAJNA_DEFAULT (Design L0 "X %")
    "dd_halt": 0.10,                # risk.py max_drawdown_halt
    "notional_cap_inr": 1_000_000.0,  # per position (leverage <= 1:10 never reached)
    "participation": 0.01,          # of the 20-session median daily volume
    "rrr_min": 2.0,                 # USER 2026-10-26 (1:2; Playbook law 3 minimum is 1.5)
    "halt_after_first_stop": True,  # USER 2026-10-26: no new entry after the first stop-out
    "half_spread_bps": 5.0,         # app.paper.sim
    "slippage_bps": (0.0, 5.0, 10.0, 20.0),   # primary 0; sensitivity (law 6)
    "checklist_min": 4,             # Playbook §4
}

REGIME = {
    "adx_n": 14, "adx_trend": 25.0, "adx_range": 20.0,           # Playbook §5 / Design L1
    "ema_trend": 50, "sma_breadth": 50,                           # Playbook §5 row 1
    "breadth_up": 0.60, "breadth_down": 0.40,                     # Playbook §5 rows 1-2
    "vix_pct_n": 252, "vix_pct_shock": 0.90, "vix_jump": 0.20,    # PRAJNA_DEFAULT
    "sigma_n": 20, "sigma_shock": 2.0,                            # Playbook §5 row 4 (2 sigma)
    "ad_collapse": 0.20,                                          # PRAJNA_DEFAULT
    "results_share_event": 0.05,
    "nh_nl_n": 20,
    "checkpoints_ist": ("09:30", "10:30", "12:00", "13:30"),      # Design L2
    "day_trend_from_open": 0.006, "day_trend_breadth": 0.65,      # PRAJNA_DEFAULT (tag only)
    "day_range_from_open": 0.003,
    # risk multiplier per state (recorded; applied from P3)
    "mult": {"SHOCK": 0.25, "SHOCK_REVERSION": 0.0, "EVENT_WAIT": 0.5, "TREND_UP": 1.0,
             "TREND_DOWN": 0.5, "RANGE": 0.5, "MIXED": 0.0},
    "holiday_thin_mult": 0.5,
}

STRAT = {
    S1: {"or_end": "09:30", "signal_from": "09:45", "signal_to": "11:00",
         "vol_ratio_min": 1.0, "vol_sessions": 10,                # Playbook §4 point 3
         "breadth_long": 0.60, "breadth_short": 0.40,
         "atr_n": 14, "stop_atr_min": 1.0,                        # Playbook law 4
         "structure_max_pct": 0.04,                               # Playbook §4 point 2
         "ind_adx_min": 25.0, "ind_rsi_long": (50.0, 80.0), "ind_rsi_short": (20.0, 50.0),
         "ema_stock": 50, "exit_eod": "15:15",
         "ma_fast": 9, "ma_slow": 21,                             # USER: MA alignment (15m)
         "macd": (12, 26, 9),                                     # USER: MACD > trigger (p5)
         "candle_body_min": 0.5, "candle_close_pos": 0.75,        # USER: strong candle (M2)
         "max_atr_pct_1d": 0.03},                                 # USER: volatility cap
    S2: {"signal_from": "10:00", "signal_to": "14:00",
         "bb_n": 20, "bb_k": 2.0, "rsi_n": 14, "rsi_low": 30.0, "rsi_high": 70.0,
         "rsi_full_low": 25.0, "rsi_full_high": 75.0,
         "max_move_prev_close": 0.03,                             # PRAJNA_DEFAULT no-news proxy
         "stock_adx_max": 20.0, "vol_ratio_min": 1.0, "vol_sessions": 10,
         "atr_n": 14, "stop_atr": 1.0, "time_stop_bars15": 4,     # PRAJNA_DEFAULT 1 h
         "exit_eod": "15:15",
         "macd": (12, 26, 9),                                     # USER: histogram turning (p5)
         "wick_body_min": 2.0},                                   # USER: hammer / star (M2)
}

UNIVERSE = {"fo_only": True}       # USER 2026-10-26: stocks with NSE futures (Upstox master)

# Varsity M2 support/resistance zones on daily bars <= T - 1 (pivots, clustered)
SR = {"lookback_sessions": 120,     # Playbook §4 point 2: 3-6 months for short-term trades
      "pivot_half_width": 2,        # a pivot high/low is the extreme of a 5-session window
      "cluster_tol": 0.01,          # PRAJNA_DEFAULT: touches within 1 % are one zone
      "min_touches": 3,             # Playbook §4 point 2
      "min_span_sessions": 10,      # Playbook §4 point 2: touches >= 2 weeks apart
      "near_pct": 0.015}            # PRAJNA_DEFAULT: S2 needs a zone within 1.5 % of the close

DATA = {"min_1m_bars": 370, "min_universe_share_1m": 0.90, "history_15m_sessions": 10,
        "ca_window_sessions": 11}


def spec() -> dict[str, Any]:
    return {"policy_version": POLICY_VERSION, "regime_version": REGIME_VERSION,
            "strategies": list(STRATEGIES), "book": BOOK, "regime": REGIME, "strat": STRAT,
            "universe": UNIVERSE, "sr": SR, "data": DATA}


def spec_sha256() -> str:
    return hashlib.sha256(json.dumps(spec(), sort_keys=True, default=str).encode()).hexdigest()
