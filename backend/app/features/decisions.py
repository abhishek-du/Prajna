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
        "status": "APPROVED",
        "decision": "Indicator parameters the diagram does not specify use conventional values, "
                    "recorded as PROPOSED in the registry (SMA 20/50/200, EMA 12/26, RSI 14, MACD "
                    "12/26/9, ATR 14, 20-session realised volatility, 60-session beta vs NIFTY 50, "
                    "20-session range/breakout, 20-session average volume/turnover, "
                    "NIFTY/BANKNIFTY close vs SMA 50, VIX 5-session change, FII/DII 5-session "
                    "flow). Proposed 2026-09-28, approved by the user the same day; a change "
                    "is a new feature version",
        "ref": "user 2026-09-28 ('Conventional, pending approval'; then 'approve the "
               "proposed feature params')"},
    "FII-DII-STALENESS": {
        "status": "APPROVED",
        "decision": "FII/DII features use the snapshot's PREVIOUS TRADING SESSION: if the latest "
                    "observation knowable before as_of is not that session (late or missing "
                    "publication), the value is MISSING_INPUT; an older day is never relabelled "
                    "as the current one. The 5-day sum must end at the previous session. "
                    "Implemented as feature version 2 (0 stored values existed under version 1)",
        "ref": "user 2026-09-28 ('MISSING_INPUT if stale'; restated: 'If the latest FII/DII "
               "observation does not belong to the snapshot's previous trading session, return "
               "MISSING_INPUT')"},
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
    "CA-OBSERVED": {
        "status": "APPROVED",
        "decision": "Corporate actions and their factors are knowable when Prajna observed "
                    "them: greatest(announcement end of day (KN-CA), fetched_at), through the "
                    "views canon_corporate_action / canon_ca_factor (migration 0018; the KN-CA "
                    "value stays in corporate_action and canon_corporate_action_kn_ca). The "
                    "price-adjustment horizon counts only actions knowable before as_of (none: "
                    "every vendor-adjusted bar is LOW confidence). Registry features-v3: every "
                    "per-instrument feature reading corporate actions or adjusted bars gets "
                    "version + 1; stored features-v1/v2 values are never re-labelled",
        "ref": "user 2026-10-09 ('option 1 aur F3 fix dono implement karo'); review "
               "docs/STAGE4_POST_BACKFILL_REVIEW.md F1/F2"},
    "F3-PAYLOAD-BASIS": {
        "status": "APPROVED",
        "decision": "A factor the vendor applies (vendor_applied=APPLIED) counts as baked into a "
                    "stored payload only if the vendor did not later re-serve any bar OF THAT "
                    "PAYLOAD adjusted by THAT action (a CA_ADJUSTMENT observation naming it): "
                    "such a payload was fetched before the vendor applied the action, so every "
                    "bar in it is adjusted by Prajna instead. Found on BLSE (split ex "
                    "2026-10-06; its whole history fetched that morning, only the last 4 bars "
                    "re-served later). Registry "
                    "features-v4: every per-instrument feature computed from adjusted bars gets "
                    "version + 1; stored features-v1..v3 values are never re-labelled",
        "ref": "user 2026-10-09 ('option 1 aur F3 fix dono implement karo'); review "
               "docs/STAGE4_POST_BACKFILL_REVIEW.md F3"},
}
