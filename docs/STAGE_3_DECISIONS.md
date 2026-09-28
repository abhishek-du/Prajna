# Stage 3 decisions

Status on 2026-09-28. Two kinds of decision are kept apart:

- **Engine decisions** live in `backend/app/features/decisions.py`. The lock condition `decisions` requires every one of them to be APPROVED, and `prajna stage3 locks` shows it.
- **Operational decisions** decide *when* and *whether* the engine runs, not what it computes. They are gated by other controls:
  - the cron installation (a human action);
  - `PRAJNA_STAGE3_ENABLED` and `PRAJNA_STAGE3_BACKFILL_ENABLED`;
  - the write token.

  So they are recorded here, not in the engine register. Adding a PENDING entry to the register would not add safety; it would only block the lock check that already refuses every run while the flag is false.

## Engine decisions (the lock register)

| Id | Status | Decision | Reference |
|---|---|---|---|
| FEATURE-SCOPE | **APPROVED** | Stage 3 is feature engineering per the user's diagram, in six groups: price & technical, volume & liquidity, fundamental, event, market context, and pre-open. Models, signals, risk and execution belong to Stages 4–7. | user diagram; plan 2026-09-28 |
| FEATURE-PARAMS | **APPROVED** | Parameters the diagram does not name use conventional values, marked PROPOSED in the registry: SMA 20/50/200, EMA 12/26, RSI 14, MACD 12/26/9, ATR 14, 20-session volatility, 60-session beta vs NIFTY 50, and so on. A change creates a new feature version. | user 2026-09-28: "approve the proposed feature params" |
| FEATURE-SNAPSHOTS | **APPROVED** | Two snapshots per session:<br>• PRE_SESSION, as_of = pre-open start − 1 s (08:59:59 IST);<br>• PRE_OPEN, as_of = pre-open start + 8 min (09:08:00 IST).<br>Inputs must satisfy strict `knowable_at < as_of`. | user 2026-09-28: "Two snapshots" |
| FEATURE-NO-SOURCE | **APPROVED** | A diagram item with no data source in Prajna is registered UNSUPPORTED, with the missing source named. Missing data remains MISSING_INPUT; **no proxy is invented**. | user 2026-09-28: "Register UNSUPPORTED" |
| FII-DII-STALENESS | **APPROVED**, implemented (commit 580f587) | FII/DII features use the snapshot's previous trading session (from the calendar). If the latest observation knowable before as_of is not that session, the value is MISSING_INPUT; an older day is never relabelled as current. The 5-day sum must end at that session. Features `fii_net_cash_1d/5d` and `dii_net_cash_1d/5d` are version 2; 0 values were stored under version 1. | user 2026-09-28: "MISSING_INPUT if stale" |

## Operational decisions

| Id | Status | Decision | Gate |
|---|---|---|---|
| SCHEDULE | **PENDING_APPROVAL** | The proposed daily times are in [STAGE_3_PRODUCTION_SCHEDULE.md](STAGE_3_PRODUCTION_SCHEDULE.md). PRE_SESSION starts at 09:00:30. **PRE_OPEN needs a choice**: pre-open ticks reach the database only after the 09:20 replay, so start at 09:08:30 with the four `preopen_*` features MISSING_INPUT (option A), or start after the replay (option B, available after the open). | The runbook `ops/runbooks/stage3_snapshot.sh` is prepared. The cron lines in `ops/cron/prajna.cron` are commented out (`PENDING_APPROVAL:`). Nothing is installed. |
| PRODUCTION-UNLOCK | **NOT GRANTED** | The first production run (`prajna stage3 run --commit`) needs the user's explicit authorisation. | `PRAJNA_STAGE3_ENABLED=false`; no write token supplied. |
| BACKFILL | **DEFERRED** | No historical feature backfill (`prajna stage3 backfill`). The Stage 1 vendor backfill (~293k requests) stays deferred as well. | `PRAJNA_STAGE3_BACKFILL_ENABLED=false`, which is an additional lock condition for BACKFILL. |

## News (a separate track)

| Id | Status | Decision |
|---|---|---|
| FEATURE-NEWS-V2 | **PENDING** (separate track; not part of this work) | Recorded as PENDING in `backend/app/features/news_features.py`. The multi-source `mnews_*` features are **not** part of the Stage 3 registry (`features-v1`, 65 features, with exactly 3 legacy Upstox news features: `news_count_24h`, `news_count_7d` and `news_hours_since_last`). Any change needs a separate decision. |

Nothing in Stage 3 computes, stores or schedules `mnews_*`:
- they exist only as a module (`app/features/news_features.py`), exercised by `tests/news/test_news_features.py`;
- no command or job runs them;
- multi-source news production writes stay disabled (every per-source flag is false, and NEWS-COMPLIANCE is PENDING).
