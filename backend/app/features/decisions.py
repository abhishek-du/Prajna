"""Stage 3 decision register. A PENDING decision blocks production execution."""

from __future__ import annotations

DECISIONS: dict[str, dict[str, str]] = {
    "FEATURE-SCOPE": {
        "status": "APPROVED",
        "decision": "Stage 3 = Feature Engineering per the user's diagram (six groups: price & "
                    "technical, volume & liquidity, fundamental, event, market context, pre-open). "
                    "Models, signals, risk and execution are Stages 4-7 and out of scope",
        "ref": "user diagram (first prompts) + Stage 2 prompt pipeline; plan 2026-09-28"},
    "FEATURE-PARAMS": {
        "status": "PENDING",
        "decision": "Indicator parameters the diagram does not specify use conventional values, "
                    "recorded as PROPOSED in the registry (SMA 20/50/200, EMA 12/26, RSI 14, MACD "
                    "12/26/9, ATR 14, 20-session realised volatility, 60-session beta vs NIFTY 50, "
                    "20-session range/breakout, 20-session average volume/turnover, "
                    "NIFTY/BANKNIFTY close vs SMA 50, VIX 5-session change, FII/DII 5-session "
                    "flow). Production execution stays blocked until the user approves or changes "
                    "them",
        "ref": "user 2026-09-28 ('Conventional, pending approval')"},
    "FEATURE-SNAPSHOTS": {
        "status": "APPROVED",
        "decision": "Two snapshots per trading session: PRE_SESSION as_of pre-open start - 1 s "
                    "(08:59:59 IST on a normal session) and PRE_OPEN as_of pre-open start + 8 min "
                    "(09:08:00 IST), which adds the pre-open book. Strict knowable_at < as_of",
        "ref": "user 2026-09-28 ('Two snapshots')"},
    "FEATURE-NO-SOURCE": {
        "status": "APPROVED",
        "decision": "Diagram features without a data source in Prajna are registered UNSUPPORTED "
                    "with the missing source named; nothing is computed or approximated for them",
        "ref": "user 2026-09-28 ('Register UNSUPPORTED')"},
}
