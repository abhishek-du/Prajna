## Summary

Stage 4 has its training data: a historical replay of the **production Stage 3 engine**, plus versioned outcome labels.

- **Nothing is trained.** No model, signal, risk or order code exists.
- **Isolation.** Every row is in `training_feature_value` / `training_label` (migration 0016, additive). The live table `feature_value`, the Stage 3 cron and the flags are untouched (`PRAJNA_STAGE3_BACKFILL_ENABLED=false`).

### Why there are two datasets (user decision, 2026-10-08)

The Phase 1 audit measured the binding constraint. Prajna's PIT contract (`contracts/knowable.for_daily_bar`) sets `knowable_at = max(close, fetched_at)`. The whole 2020–2026 daily history was downloaded on **2026-09-23**, so under that contract **no snapshot before the 2026-09-24 session has a single price input**.

Stretching history further means *assuming* when the data would have been known, which the contract forbids ("knowable_at is NEVER INVENTED"). The user therefore chose two datasets that are **never mixed**:

**STRICT_PIT-v2 (`stage4-ds-v2-strict`)**
- The production canonical layer, with one correction: corporate actions are knowable when Prajna **observed** them (schema `train_strict`, migration 0017; see finding 1). Certified point in time.
- PRE_SESSION and PRE_OPEN, 2026-09-24 → 2026-10-08 (10 sessions). It grows by two snapshots a session.

**AS_IF_LIVE-v2 (`stage4-ds-v2-asif`)**
- **Research only; every row carries ASSUMED knowability.** History downloaded in bulk is treated as if the live schedule had collected it.
- The lag is **measured on the live-collected period, never chosen**:

  | Input | Assumed knowable at | Measured basis |
  |---|---|---|
  | Daily bars, FII/DII | next trading session 08:33 IST | P99 of 30,737 live bar rows / 360 FII-DII rows |
  | Global labels: first fetch | label + 36 h 41 m (Mon–Fri), 3 d 12 h 41 m (Sat), 2 d 12 h 41 m (Sun) | max of live labels per weekday |
  | Global labels: confirmation | label + 45 h 11 m (Mon–Fri), longer at weekends | max of live labels per weekday |
  | Corporate actions | the later of announcement (KN-CA) and ex-date, + 3 d 10 h 33 m | P99 of the 11 actions first stored by the live schedule; the Upstox endpoint lists an action around its ex-date, not at announcement |

- The parameters are frozen in `training_policy_param` (append-only).
- Implementation: the `train_asif2` shadow views, read through `search_path = train_asif, public` inside the replay transaction only. A row observed live keeps its real `knowable_at` (`least()`).
- PRE_SESSION only (no pre-open history exists), 2025-09-24 → 2026-10-08.

### Why AS_IF_LIVE starts on 2025-09-24, not 2020

Every stock bar in Prajna is VENDOR_ADJUSTED. Before the corporate-action horizon (the earliest ex-date Prajna knows, **2025-09-24**), an unknown split or bonus may be baked into the price. `pit.bars_adjusted` refuses those rows as LOW confidence, in production and here alike.

So stock features accumulate history from 2025-09-24:

| Feature | Valid from about |
|---|---|
| `ret_1d` | 2 sessions in |
| 20-session features | late October 2025 |
| `sma_200` | mid-2026 |

Index bars need no adjustment and go back to 2020, so the index, VIX and global context is complete from day one.

### Families with no history

These are **NOT_AVAILABLE_HISTORICALLY**: value null, never 0.

| Family | Collected since |
|---|---|
| Fundamentals and sector profile | today's snapshot only (knowable 2026-09-24 15:51 IST) |
| Pre-open | 2026-09-24 |
| Legacy Upstox news | 2026-09-24 |
| Multi-source news v2 | 2026-09-29 17:33 |
| FII/DII | vendor history from 2026-04-01 only |

The legacy `news_count_*` features return 0 on an empty input in the engine. The contract converts them to NOT_AVAILABLE_HISTORICALLY before the feed existed, so "no coverage" never reads as "no news".

### Findings and limitations (reported, not fixed: live semantics are out of scope)

1. **Corporate actions were backdated in the canonical layer (fixed for training only).**
   - Rule KN-CA makes a corporate action knowable at the end of its announcement date. Prajna's endpoint lists actions around their ex-date, and all 2,336 stored actions were fetched more than a day after that instant (2,320 in the 2026-09-24 bulk load).
   - Dataset **v1** (built first, through the production views) therefore saw actions before Prajna had them. In the STRICT replay of 2026-09-29, for example, 8 action rows were fetched on 10-03 but announced earlier.
   - v1 is kept stored, and its 14 runs are marked **SUPERSEDED**. **v2** reads corporate actions and `ca_factor` as observed (STRICT) or at the measured live lag (AS_IF_LIVE).
   - Live Stage 3 still uses KN-CA. On the live path that is harmless, because a row cannot be used before it exists. Any production *recompute* or backfill of a past session would inherit the backdating; recommended for review.
2. **`sector_rs_20` peer set is not PIT in the production engine.** `engine._sector_rows` pre-selects sector peers from today's `canon_instrument` ACTIVE list.
   - A stock removed from the master later (for example CEREBRAINT, now REMOVED_FROM_MASTER) silently leaves historical peer sets.
   - The STRICT replay reproduces production exactly (identical `inputs_sha256`) except for the `sector_rs_20` rows whose sector contains such a peer.
   - Recommendation for a later Stage 3 change: select peers by lifecycle as of `as_of`.
3. **Revisions overwrite.** `ohlcv_bar` keeps the latest version of a bar. A bar re-fetched later (for example the 2026-10-08 06:30 refetch) is invisible to a snapshot before the refetch, even though an earlier version had been knowable. The replay then reports STALE_INPUT. That is conservative (never look-ahead) but not identical to what the live run saw.
4. **Malformed quarterly statements.** `pat_yoy_q` / `revenue_yoy_q` are MALFORMED_INPUT (INVALID) for about 65–70% of stocks, as in production `feature_value`: the vendor quarterly payload shape. They are inherited, not introduced.
5. **Survivorship.** The Upstox master lists only currently tradable instruments. Companies delisted before 2026-09-23 were never downloaded, so the AS_IF_LIVE universe is survivorship-biased. The size is measured below; it cannot be repaired from Prajna's data.
6. **Labels from daily bars.** The order of an up hit and a down hit within a session is unknown. The `hit_*` labels say only whether each threshold was reached.
7. **Replay universe.** The replay includes a canonical NSE_EQ instrument when it has a daily bar knowable in the 15 days before the session, plus the NSE indices.
   - Production also computes rows for listed instruments without a recent bar (28–32 a day: new listings and suspended names). Those rows have no price features, and no label either.
8. **Operational note.** During development, `prajna db downgrade 0015` was run without a test-database option (that command has none). Production was already at 0015, so it was a verified no-op. The test database was then migrated through an explicit `prajna_test` DSN.
