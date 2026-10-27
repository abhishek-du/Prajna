"""Research Desk versions and thresholds. A change here is a new DESK_VERSION (the forward
record in Strategy Lab is per version)."""

from __future__ import annotations

DESK_VERSION = "desk-v1"
PROMPT_VERSION = "desk-prompt-v1"
MODEL_ID = "amazon.nova-pro-v1:0"
MAX_TOKENS = 1400
CONCURRENCY = 2                    # Bedrock throttled a 4-concurrent run (2026-10-22)
ATTEMPTS = 2                       # one retry on an invalid answer

UNIVERSE_TOP = 500                 # by 60-session median turnover, STOCK class, price >= 50
MIN_PRICE = 50.0
NEWS_WINDOW_H = 72
MAX_NEWS = 12
EVENT_WINDOW_D = 10                # results / corporate actions within +- 10 days

# rule judge (dash-plan-v2)
CIRCUIT_NEAR = 0.01                # within 1 % of a circuit limit: cannot be filled reliably
EXTENDED_ATR = 3.0                 # more than 3 ATR above the 20-day average: chasing
MIN_TURNOVER_INR = 5e7             # Rs 5 crore median daily turnover
NEWS_MOVE = 0.03                   # a >= 3 % day with linked news is a news move
ROUND_TRIP_COST = 0.0018           # MIS charges at Rs 1 L (app/paper/sim) ~0.18 %
HALF_SPREAD = 0.0005               # 5 bps a side (app/shadow/spec BOOK)

# validator
STOP_MIN_ATR, STOP_MAX_ATR = 0.3, 5.0

# watchlist
ADD_SCORE = 70
REMOVE_SCORE = 50
STALE_SESSIONS = 5
BUY_DECISIONS = ("STRONG_BUY", "BUY")
DECISIONS = ("STRONG_BUY", "BUY", "WATCH", "AVOID", "SELL")
HORIZONS = ("INTRADAY", "SWING_1_5D")
POVS = ("technical", "catalyst", "fundamental", "market", "execution", "risk")

DISCLAIMER = ("Research Desk: an LLM-led research suggestion from stored Upstox data, the "
              "news Prajna collects and fixed rules. Unvalidated (forward record in Strategy "
              "Lab), not investment advice; paper only, no order is ever placed.")
