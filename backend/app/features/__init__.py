"""Stage 3: Feature Engineering (NSE AI Trading System diagram, stage 3).

"Convert raw data into meaningful features according to our strategy"
(overnight + pre-open). Features are computed ONLY from the Stage 2
point-in-time read API (app.canon.pit), strictly from rows knowable before the
snapshot instant. No model, signal, order or broker logic lives here (those are
Stages 4-7), and this package never calls the vendor.

Execution: dry-run by default (read-only). Writing features (a production run)
or computing them over past sessions (a feature backfill) is locked behind
app.features.locks: feature flags (default off), a kill switch, Stage 1
acceptance COMPLETE, Stage 2 acceptance PASS, the FEATURE-PARAMS decision and
a write token.
"""
