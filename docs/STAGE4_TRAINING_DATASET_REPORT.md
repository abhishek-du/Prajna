# Stage 4 training dataset: report

Generated 2026-10-09T00:24:07.662758+05:30 from `audit/evidence/stage4_training_dataset.json` (`ops/measure/stage4_validate.py`, read-only). **No model, signal, risk or order code exists or was built.**

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


## Datasets

| name | dataset_version | knowability | snapshots | first | last | sessions | snapshot rows | symbols | feature rows | registry | hash | runtime s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| strict | stage4-ds-v2-strict | STRICT_PIT-v2 | PRE_SESSION, PRE_OPEN | 2026-09-24 | 2026-10-08 | 10 | 20 | 3549 | 4229340 | features-v2 | dd696ca66b02 | 4295.5 |
| asif | stage4-ds-v2-asif | AS_IF_LIVE-v2 | PRE_SESSION | 2025-09-24 | 2026-10-08 | 256 | 256 | 3566 | 47274794 | features-v2 | dd696ca66b02 | 84626.1 |

Run IDs (one per worker; resumable):

- **strict**: `b9afefdc-6467-4d2b-a967-909b636ad281` COMPLETE (5 snapshots, 1022879 rows), `7e065b52-ae2b-4cc6-9bec-5f237df84390` COMPLETE (5 snapshots, 1093411 rows), `f958e6a1-09a9-445a-afc1-53d3ad07bf04` COMPLETE (5 snapshots, 1091737 rows), `49339a93-740e-421c-bfb4-47503ba6a89e` COMPLETE (5 snapshots, 1021313 rows), `acde737f-4fc8-44d3-841f-2c6a1b4e25d5` COMPLETE (0 snapshots, 0 rows)
- **asif**: `0af84b73-ec74-4ec8-abed-06f39e7841f1` COMPLETE (37 snapshots, 6828053 rows), `9c9228f5-357d-4f37-bc82-9cc87db9b1ee` COMPLETE (37 snapshots, 6843713 rows), `a6dd53c8-d792-49a9-a166-792968beea90` COMPLETE (36 snapshots, 6650134 rows), `b475de8d-d06e-43bb-bac0-2d15a2eaa1a8` COMPLETE (36 snapshots, 6653034 rows), `72c1ce57-2a98-49c2-a50e-51346deb45ef` COMPLETE (37 snapshots, 6832461 rows), `84232a56-250a-48cb-b02f-2b7b58cd265e` COMPLETE (36 snapshots, 6641724 rows), `b61e0a8c-9ef7-4588-a1a9-ea1c7ff12e85` COMPLETE (37 snapshots, 6825675 rows)

### Status counts (missingness contract)

| status | strict | asif |
|---|---|---|
| INVALID | 81941 | 40876 |
| MISSING_INPUT | 816918 | 9848792 |
| NOT_AVAILABLE_HISTORICALLY | 371576 | 18942954 |
| STALE_INPUT | 254424 | 655166 |
| VALID | 2704481 | 17787006 |

INVALID = the engine's MALFORMED_INPUT, inherited unchanged from production (the same features are MALFORMED in production `feature_value`): `pat_yoy_q` 21412, `revenue_yoy_q` 19437, `roce_pct` 18, `roe_pct` 9

## Historical windows per family

### STRICT_PIT

| group:family | earliest valid | stable (>=50% valid) | latest | sessions with values |
|---|---|---|---|---|
| event:corporate_actions | 2026-09-25 |  | 2026-10-08 | 9 |
| event:legacy_news | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| event:multi_news | 2026-09-30 | 2026-09-30 | 2026-10-08 | 6 |
| fundamental:fundamentals | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| market_context:bars | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| market_context:bars+sector | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| market_context:fii_dii | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| market_context:global | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| preopen:bars+preopen | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| preopen:preopen | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| price_technical:bars | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| volume_liquidity:bars | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |

### AS_IF_LIVE-v1

| group:family | earliest valid | stable (>=50% valid) | latest | sessions with values |
|---|---|---|---|---|
| event:corporate_actions | 2025-09-29 |  | 2026-10-08 | 253 |
| event:legacy_news | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| event:multi_news | 2026-09-30 | 2026-09-30 | 2026-10-08 | 6 |
| fundamental:fundamentals | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| market_context:bars | 2025-09-24 | 2025-09-24 | 2026-10-08 | 256 |
| market_context:bars+sector | 2026-09-25 | 2026-09-25 | 2026-10-08 | 9 |
| market_context:fii_dii | 2026-04-02 | 2026-04-02 | 2026-10-08 | 129 |
| market_context:global | 2025-09-24 | 2025-09-24 | 2026-10-08 | 256 |
| price_technical:bars | 2025-09-26 | 2025-10-27 | 2026-10-08 | 254 |
| volume_liquidity:bars | 2025-10-24 | 2025-10-24 | 2026-10-08 | 236 |

## Validation

| check | strict | asif |
|---|---|---|
| rows | 4229340 | 47274794 |
| duplicates | 0 | 0 |
| duplicate_snapshots | 0 | 0 |
| orphan_instruments | 0 | 0 |
| nan_inf_values | 0 | 0 |
| value_status_inconsistent | 0 | 0 |
| pit_violations | 0 | 0 |
| non_trading_dates | 0 | 0 |
| future_timestamps | 0 | 0 |
| registry_hash_mismatch | 0 | 0 |
| missing snapshots | 0 | 0 |
| as_of not the calendar instant | 0 | 0 |

### Labels

|  | value |
|---|---|
| version | label-v1 |
| rows | 7077591 |
| valid | 7046085 |
| sessions | 255 |
| instruments | 3567 |
| first | 2025-09-24 |
| last | 2026-10-07 |
| duplicates | 0 |
| leakage_label_start_le_as_of | 0 |
| label_snapshot_pairs_checked | 9863136 |
| non_trading_dates | 0 |

```
label-v1: the outcome of session T for a snapshot taken before T opened.

Both snapshots of T (PRE_SESSION 08:59:59, PRE_OPEN 09:08 IST) precede T's open,
so every label starts at T's open (label_start_at = T open, from the calendar)
and ends at T's close: strictly after the snapshot. A label MAY use future data -
it is the outcome; features never see it (their inputs are knowable before
as_of and exclude the session's own bar, app.features.inputs).

Prices: split/bonus-adjusted bars as known NOW (pit.bars_adjusted with as_of =
now), so a corporate action with ex-date T adjusts close(T-1) and every ratio
below is on one basis. LOW-confidence history is refused there, as in Stage 3.

  ret_cc    close(T) / close(T-1) - 1        T-1 = the previous trading session
  gap       open(T)  / close(T-1) - 1
  ret_oc    close(T) / open(T)    - 1
  high_exc  high(T)  / open(T)    - 1
  low_exc   low(T)   / open(T)    - 1
  hit_up_1, hit_up_2   1 if high(T) >= open(T) * (1 + 1% / 2%) else 0
  hit_dn_1, hit_dn_2   1 if low(T)  <= open(T) * (1 - 1% / 2%) else 0

Limitation: from daily bars the ORDER of an up and a down hit within T is unknown.
No production target is chosen here (Stage 4 target selection is research).
```

### Independent replay

- STRICT vs production `feature_value` 2026-09-29: 371256 joined rows, 346520 identical inputs, 370988 identical values, 0 production values stored as NOT_AVAILABLE_HISTORICALLY, 3392 production rows outside the replay universe.
  - `PRE_OPEN sector_rs_20 NSE_EQ|IN9175A01010` training -0.0048453492781 (VALID) vs production -0.0049195893266; same inputs: True
  - `PRE_SESSION sector_rs_20 NSE_EQ|IN9175A01010` training -0.0048453492781 (VALID) vs production -0.0049195893266; same inputs: True
  - `PRE_SESSION sector_rs_20 NSE_EQ|IN9623B01058` training -0.0832264926921 (VALID) vs production -0.0833007327406; same inputs: True
  - `PRE_OPEN sector_rs_20 NSE_EQ|IN9623B01058` training -0.0832264926921 (VALID) vs production -0.0833007327406; same inputs: True
  - `PRE_OPEN sector_rs_20 NSE_EQ|INE00GO01025` training -0.134126872334 (VALID) vs production -0.134201112383; same inputs: True
  - `PRE_SESSION sector_rs_20 NSE_EQ|INE00GO01025` training -0.134126872334 (VALID) vs production -0.134201112383; same inputs: True
  - `PRE_SESSION sector_rs_20 NSE_EQ|INE00UG01014` training -0.0818505883311 (VALID) vs production -0.0819248283796; same inputs: True
  - `PRE_OPEN sector_rs_20 NSE_EQ|INE00UG01014` training -0.0818505883311 (VALID) vs production -0.0819248283796; same inputs: True
  - `PRE_SESSION sector_rs_20 NSE_EQ|INE00WV01027` training 0.0474862556209 (VALID) vs production 0.0473097019486; same inputs: True
  - `PRE_OPEN sector_rs_20 NSE_EQ|INE00WV01027` training 0.0474862556209 (VALID) vs production 0.0473097019486; same inputs: True
  - `PRE_SESSION sector_rs_20 NSE_EQ|INE02KC01010` training -0.0326082422121 (VALID) vs production -0.0539381144926; same inputs: True
  - `PRE_OPEN sector_rs_20 NSE_EQ|INE02KC01010` training -0.0326082422121 (VALID) vs production -0.0539381144926; same inputs: True
- STRICT vs production `feature_value` 2026-10-08: 423426 joined rows, 398642 identical inputs, 423426 identical values, 0 production values stored as NOT_AVAILABLE_HISTORICALLY, 3360 production rows outside the replay universe.
- inputs_sha256 differs only for the 8 ca_days_* features: v2 hashes the corporate actions with their OBSERVED knowable_at (migration 0017), production with KN-CA; the values are identical. Value differences: only sector_rs_20 on 2026-09-29 (peer set from today's lifecycle, finding 2).
- Fresh read-only recompute (strict): 10 random snapshots x 10 random instruments, 6300 rows, **0 mismatches** (sector_rs_20 excluded (peer set); every other feature recomputed).
- Fresh read-only recompute (asif): 10 random snapshots x 10 random instruments, 6060 rows, **0 mismatches** (sector_rs_20 excluded (peer set); every other feature recomputed).
- Raw SQL (strict): 270 ret_1d / sma_20 / avg_volume_20 values, **0 mismatches**; 200 ret_cc labels, **0 mismatches** (relative 1e-9 (values are stored at 12 significant digits)).
- Raw SQL (asif): 296 ret_1d / sma_20 / avg_volume_20 values, **0 mismatches**; 200 ret_cc labels, **0 mismatches** (relative 1e-9 (values are stored at 12 significant digits)).

### Scenarios

```json
{
 "late_arriving_bars": {
  "late_bars_found": 35,
  "checked_in_strict": 18,
  "never_used_before_knowable": 18,
  "pass": true
 },
 "delayed_fundamentals_strict": [
  [
   "2026-09-24",
   "PRE_OPEN",
   "NOT_AVAILABLE_HISTORICALLY",
   "3499"
  ],
  [
   "2026-09-24",
   "PRE_SESSION",
   "NOT_AVAILABLE_HISTORICALLY",
   "3499"
  ],
  [
   "2026-09-25",
   "PRE_OPEN",
   "MISSING_INPUT",
   "414"
  ],
  [
   "2026-09-25",
   "PRE_OPEN",
   "VALID",
   "3088"
  ],
  [
   "2026-09-25",
   "PRE_SESSION",
   "MISSING_INPUT",
   "531"
  ],
  [
   "2026-09-25",
   "PRE_SESSION",
   "VALID",
   "2971"
  ]
 ],
 "delayed_fundamentals_pass": true,
 "fii_dii": [
  [
   "stage4-ds-v2-asif",
   "256",
   "129",
   "0"
  ],
  [
   "stage4-ds-v2-strict",
   "20",
   "18",
   "0"
  ]
 ],
 "missing_news_never_zero": {
  "stage4-ds-v2-asif": {
   "rows_before_collection": 5558839,
   "non_null_before_collection": 0
  },
  "stage4-ds-v2-strict": {
   "rows_before_collection": 196606,
   "non_null_before_collection": 0
  }
 },
 "legacy_news_never_zero": {
  "stage4-ds-v2-asif": {
   "rows_before_collection": 1566328,
   "non_null_before_collection": 0
  },
  "stage4-ds-v2-strict": {
   "rows_before_collection": 13996,
   "non_null_before_collection": 0
  }
 },
 "corporate_action_knowable_later": {
  "cas": 50,
  "rows_before_knowable": 0,
  "rows_equal_to_the_not_yet_knowable_ex_date": 0,
  "pass": true
 },
 "strict_corporate_action_observed": {
  "actions_stored_after_announcement": 2336,
  "rows_between_announcement_and_storage": 44,
  "rows_reflecting_the_unobserved_action": 0,
  "pass": true
 },
 "removed_from_master_present": {
  "stage4-ds-v2-asif": 19,
  "stage4-ds-v2-strict": 19
 }
}
```

## Survivorship and selection bias

| measure | value |
|---|---|
| universe_per_session | {"first": ["2025-09-24", 2939], "last": ["2026-10-08", 3545], "min": 2939, "max": 3545} |
| stocks_with_daily_bars | 3567 |
| first_bar_after_2025_09_24_new_listings | 620 |
| last_bar_before_2026_09_01_vanished | 13 |
| history_from_2020 | 1604 |
| removed_from_master | ["BGLOBAL", "BLSE", "BLUECHIP", "BUILDPRO", "CEREBRAINT", "CLCIND", "CMICABLES", "EDUCOMP", "IMPEXFERRO", "LASA", "MORARJEE", "NAGAFERT", "ORTEL", "RAJVIR", "RCDL-RE", "SELMC", "SKIL", "SPELS", "UNIVAFOODS"] |
| delisted_never_in_master | "UNKNOWN: the instrument master (Upstox) lists only currently tradable instruments; companies delisted before 2026-09-23 were never downloaded, so their bars do not exist in Prajna (survivorship bias)" |

## Storage

| table | size |
|---|---|
| training_feature_value | 26 GB |
| training_label | 2275 MB |
| training_session_done | 576 kB |
| training_dataset_run | 88 kB |

## Production untouched

```json
{
 "count": 801434,
 "md5": "b45381f3c89664cdf3dbbfa95d70b1a5",
 "baseline_count": 801434,
 "baseline_md5": "b45381f3c89664cdf3dbbfa95d70b1a5",
 "untouched_since_baseline": true,
 "note": "rows added after the baseline by the live Stage 3 cron change this; rows_before_baseline_identical checks the baseline rows themselves",
 "rows_before_baseline_identical": true
}
```

## Gates

| gate | result | evidence |
|---|---|---|
| 1 Historical coverage measured | PASS | per-feature coverage table below |
| 2 PIT-safe window established | PASS | family windows below (both policies) |
| 3 Same Stage 3 engine reused | PASS | engine.compute_snapshot unchanged; STRICT values equal production (10-08: all 423,426; 09-29: all but 40 sector_rs_20) |
| 4 Historical snapshots backfilled | PASS | strict 20/20, asif 256/256 snapshots |
| 5 Labels generated and versioned | PASS | label-v1: 7077591 rows |
| 6 No look-ahead | PASS | 0 inputs knowable at/after as_of; 0 labels starting at/before as_of |
| 7 No duplicate rows | PASS |  |
| 8 No silent missing->zero | PASS | news rows before collection are NOT_AVAILABLE_HISTORICALLY (null) |
| 9 Survivorship documented | PASS | see the survivorship section |
| 10 Independent replay | PASS | fresh recompute, raw SQL, production comparison |
| 11 Dataset metadata complete | PASS | training_dataset_run + policy params |
| 12 Live Stage 3 untouched | PASS | cron, flags, registry unchanged |
| 13 Production feature_value untouched | PASS | baseline rows fingerprint identical |
| 14 Git clean | see final block |  |
| 15 Resumable / idempotent | PASS | {"dataset": "stage4-ds-v2-strict", "rerun_snapshots_skipped": 20, "fingerprint_before": "(4229340, 'ae26653e2688f0606e4c291a832e0f4a')", "fingerprint_after": "(4229340, 'ae26653e2688f0606e4c291a832e0f4a')", "pass": true, "labels_rerun": "label build rerun is covered by the drift check (drift_vs_stored 0); a full rerun was not executed"} |

## Feature coverage: STRICT_PIT

| feature_id | family | inputs | earliest | latest | coverage % | missing+stale | not avail. hist. | invalid | PIT | class |
|---|---|---|---|---|---|---|---|---|---|---|
| ret_1d | price_technical | bars | 2026-09-25 | 2026-10-08 | 87.14 | 9062 | 0 | 0 | PASS | BACKFILLED |
| ret_5d | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.88 | 9246 | 0 | 0 | PASS | BACKFILLED |
| ret_20d | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.05 | 9832 | 0 | 0 | PASS | BACKFILLED |
| sma_20 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.12 | 9780 | 0 | 0 | PASS | BACKFILLED |
| sma_50 | price_technical | bars | 2026-09-25 | 2026-10-08 | 81.01 | 13386 | 0 | 0 | PASS | BACKFILLED |
| sma_200 | price_technical | bars | 2026-09-25 | 2026-10-08 | 71.98 | 19748 | 0 | 0 | PASS | BACKFILLED |
| close_to_sma_20 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.12 | 9780 | 0 | 0 | PASS | BACKFILLED |
| close_to_sma_50 | price_technical | bars | 2026-09-25 | 2026-10-08 | 81.01 | 13386 | 0 | 0 | PASS | BACKFILLED |
| close_to_sma_200 | price_technical | bars | 2026-09-25 | 2026-10-08 | 71.98 | 19748 | 0 | 0 | PASS | BACKFILLED |
| ema_12 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.54 | 9484 | 0 | 0 | PASS | BACKFILLED |
| ema_26 | price_technical | bars | 2026-09-25 | 2026-10-08 | 85.66 | 10110 | 0 | 0 | PASS | BACKFILLED |
| rsi_14 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.38 | 9596 | 0 | 0 | PASS | BACKFILLED |
| macd_line | price_technical | bars | 2026-09-25 | 2026-10-08 | 85.66 | 10110 | 0 | 0 | PASS | BACKFILLED |
| macd_trigger | price_technical | bars | 2026-09-25 | 2026-10-08 | 82.78 | 12134 | 0 | 0 | PASS | BACKFILLED |
| macd_histogram | price_technical | bars | 2026-09-25 | 2026-10-08 | 82.78 | 12134 | 0 | 0 | PASS | BACKFILLED |
| atr_14 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.38 | 9596 | 0 | 0 | PASS | BACKFILLED |
| atr_pct_14 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.38 | 9596 | 0 | 0 | PASS | BACKFILLED |
| volatility_20 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.05 | 9832 | 0 | 0 | PASS | BACKFILLED |
| beta_60 | price_technical | bars | 2026-09-25 | 2026-10-08 | 80.67 | 13626 | 0 | 0 | PASS | BACKFILLED |
| dist_high_20 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.12 | 9780 | 0 | 0 | PASS | BACKFILLED |
| dist_low_20 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.12 | 9780 | 0 | 0 | PASS | BACKFILLED |
| breakout_20 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.05 | 9832 | 0 | 0 | PASS | BACKFILLED |
| breakdown_20 | price_technical | bars | 2026-09-25 | 2026-10-08 | 86.05 | 9832 | 0 | 0 | PASS | BACKFILLED |
| avg_volume_20 | volume_liquidity | bars | 2026-09-25 | 2026-10-08 | 86.12 | 9780 | 0 | 0 | PASS | BACKFILLED |
| volume_spike_20 | volume_liquidity | bars | 2026-09-25 | 2026-10-08 | 85.97 | 9886 | 0 | 0 | PASS | BACKFILLED |
| turnover_20 | volume_liquidity | bars | 2026-09-25 | 2026-10-08 | 86.12 | 9780 | 0 | 0 | PASS | BACKFILLED |
| pe | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 79.64 | 7353 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| pb | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 79.98 | 7113 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| roe_pct | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 79.83 | 7199 | 6998 | 18 | PASS | PARTIAL_HISTORY |
| roce_pct | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 78.79 | 7916 | 6998 | 36 | PASS | PARTIAL_HISTORY |
| ev_ebitda | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 77.58 | 8800 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| pe_to_sector | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 67.86 | 15656 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| pb_to_sector | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 79.61 | 7371 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| revenue_yoy | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 54.97 | 24735 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| pat_yoy | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 52.71 | 26331 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| eps_yoy | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 52.8 | 26268 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| revenue_yoy_q | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 0.09 | 24451 | 6998 | 38965 | PASS | PARTIAL_HISTORY |
| pat_yoy_q | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 0.07 | 20512 | 6998 | 42922 | PASS | PARTIAL_HISTORY |
| liabilities_to_assets | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 61.19 | 20354 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_since_any | event | corporate_actions | 2026-09-25 | 2026-10-08 | 39.53 | 35620 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_since_dividend | event | corporate_actions | 2026-09-25 | 2026-10-08 | 36.63 | 37664 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_since_split | event | corporate_actions | 2026-09-25 | 2026-10-08 | 1.88 | 62158 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_since_bonus | event | corporate_actions | 2026-09-25 | 2026-10-08 | 1.71 | 62278 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_to_any | event | corporate_actions |  |  | 0.0 | 63480 | 6998 | 0 | PASS | UNAVAILABLE_HISTORICALLY |
| ca_days_to_dividend | event | corporate_actions |  |  | 0.0 | 63480 | 6998 | 0 | PASS | UNAVAILABLE_HISTORICALLY |
| ca_days_to_split | event | corporate_actions |  |  | 0.0 | 63480 | 6998 | 0 | PASS | UNAVAILABLE_HISTORICALLY |
| ca_days_to_bonus | event | corporate_actions |  |  | 0.0 | 63480 | 6998 | 0 | PASS | UNAVAILABLE_HISTORICALLY |
| news_count_24h | event | legacy_news | 2026-09-25 | 2026-10-08 | 90.07 | 0 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| news_count_7d | event | legacy_news | 2026-09-25 | 2026-10-08 | 90.07 | 0 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| news_hours_since_last | event | legacy_news | 2026-09-25 | 2026-10-08 | 4.81 | 60090 | 6998 | 0 | PASS | PARTIAL_HISTORY |
| index_ret_1d | market_context | bars | 2026-09-25 | 2026-10-08 | 90.0 | 4 | 0 | 0 | PASS | BACKFILLED |
| index_ret_5d | market_context | bars | 2026-09-25 | 2026-10-08 | 90.0 | 4 | 0 | 0 | PASS | BACKFILLED |
| index_close_to_sma_50 | market_context | bars | 2026-09-25 | 2026-10-08 | 90.0 | 4 | 0 | 0 | PASS | BACKFILLED |
| india_vix_level | market_context | bars | 2026-09-25 | 2026-10-08 | 90.0 | 2 | 0 | 0 | PASS | BACKFILLED |
| india_vix_change_5d | market_context | bars | 2026-09-25 | 2026-10-08 | 90.0 | 2 | 0 | 0 | PASS | BACKFILLED |
| fii_net_cash_1d | market_context | fii_dii | 2026-09-25 | 2026-10-08 | 90.0 | 2 | 0 | 0 | PASS | BACKFILLED |
| fii_net_cash_5d | market_context | fii_dii | 2026-09-25 | 2026-10-08 | 90.0 | 2 | 0 | 0 | PASS | BACKFILLED |
| dii_net_cash_1d | market_context | fii_dii | 2026-09-25 | 2026-10-08 | 90.0 | 2 | 0 | 0 | PASS | BACKFILLED |
| dii_net_cash_5d | market_context | fii_dii | 2026-09-25 | 2026-10-08 | 90.0 | 2 | 0 | 0 | PASS | BACKFILLED |
| global_ret_1d | market_context | global | 2026-09-25 | 2026-10-08 | 90.0 | 0 | 26 | 0 | PASS | PARTIAL_HISTORY |
| sector_rs_20 | market_context | bars+sector | 2026-09-25 | 2026-10-08 | 74.98 | 10629 | 6992 | 0 | PASS | PARTIAL_HISTORY |
| preopen_gap_pct | preopen | bars+preopen | 2026-09-25 | 2026-10-08 | 77.69 | 7861 | 0 | 0 | PASS | BACKFILLED |
| preopen_imbalance | preopen | preopen | 2026-09-25 | 2026-10-08 | 80.35 | 6926 | 0 | 0 | PASS | BACKFILLED |
| preopen_ieq | preopen | preopen | 2026-09-25 | 2026-10-08 | 87.13 | 4534 | 0 | 0 | PASS | BACKFILLED |
| preopen_ieq_to_avg_volume | preopen | bars+preopen | 2026-09-25 | 2026-10-08 | 86.05 | 4917 | 0 | 0 | PASS | BACKFILLED |
| mnews_news_count_1h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_count_4h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_count_3d | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_unique_publishers_1h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_unique_publishers_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_breaking_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_high_relevance_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_negative_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_positive_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_mixed_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_regulatory_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_corporate_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_macro_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_velocity_1h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_velocity_24h | event | multi_news | 2026-10-01 | 2026-10-08 | 50.0 | 2 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_publisher_diversity_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_story_group_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_new_story_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_updated_story_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_time_since_last_news_s | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_time_since_last_high_relevance_news_s | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_market_wide_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_macro_scope_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_geopolitical_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_commodity_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_currency_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_global_market_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_correction_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_edited_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_duplicate_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_unique_sources_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.0 | 0 | 8 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_count_1h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.17 | 0 | 28050 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_count_4h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.17 | 0 | 28050 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.17 | 0 | 28050 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_count_3d | event | multi_news | 2026-09-30 | 2026-10-08 | 60.17 | 0 | 28050 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_story_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.17 | 0 | 28050 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_correction_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 60.17 | 0 | 28050 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_time_since_last_s | event | multi_news | 2026-09-30 | 2026-10-08 | 15.0 | 31804 | 28050 | 0 | PASS | PARTIAL_HISTORY |

## Feature coverage: AS_IF_LIVE-v1

| feature_id | family | inputs | earliest | latest | coverage % | missing+stale | not avail. hist. | invalid | PIT | class |
|---|---|---|---|---|---|---|---|---|---|---|
| ret_1d | price_technical | bars | 2025-09-26 | 2026-10-08 | 94.59 | 44083 | 0 | 0 | PASS | BACKFILLED |
| ret_5d | price_technical | bars | 2025-10-03 | 2026-10-08 | 92.89 | 57916 | 0 | 0 | PASS | BACKFILLED |
| ret_20d | price_technical | bars | 2025-10-27 | 2026-10-08 | 86.59 | 109283 | 0 | 0 | PASS | BACKFILLED |
| sma_20 | price_technical | bars | 2025-10-24 | 2026-10-08 | 87.01 | 105865 | 0 | 0 | PASS | BACKFILLED |
| sma_50 | price_technical | bars | 2025-12-08 | 2026-10-08 | 74.8 | 205366 | 0 | 0 | PASS | BACKFILLED |
| sma_200 | price_technical | bars | 2026-07-20 | 2026-10-08 | 18.94 | 660550 | 0 | 0 | PASS | PARTIAL_HISTORY |
| close_to_sma_20 | price_technical | bars | 2025-10-24 | 2026-10-08 | 87.01 | 105865 | 0 | 0 | PASS | BACKFILLED |
| close_to_sma_50 | price_technical | bars | 2025-12-08 | 2026-10-08 | 74.8 | 205366 | 0 | 0 | PASS | BACKFILLED |
| close_to_sma_200 | price_technical | bars | 2026-07-20 | 2026-10-08 | 18.94 | 660550 | 0 | 0 | PASS | PARTIAL_HISTORY |
| ema_12 | price_technical | bars | 2025-10-13 | 2026-10-08 | 90.37 | 78501 | 0 | 0 | PASS | BACKFILLED |
| ema_26 | price_technical | bars | 2025-11-03 | 2026-10-08 | 84.5 | 126321 | 0 | 0 | PASS | BACKFILLED |
| rsi_14 | price_technical | bars | 2025-10-16 | 2026-10-08 | 89.09 | 88904 | 0 | 0 | PASS | BACKFILLED |
| macd_line | price_technical | bars | 2025-11-03 | 2026-10-08 | 84.5 | 126321 | 0 | 0 | PASS | BACKFILLED |
| macd_trigger | price_technical | bars | 2025-11-14 | 2026-10-08 | 81.18 | 153406 | 0 | 0 | PASS | BACKFILLED |
| macd_histogram | price_technical | bars | 2025-11-14 | 2026-10-08 | 81.18 | 153406 | 0 | 0 | PASS | BACKFILLED |
| atr_14 | price_technical | bars | 2025-10-16 | 2026-10-08 | 89.11 | 88783 | 0 | 0 | PASS | BACKFILLED |
| atr_pct_14 | price_technical | bars | 2025-10-16 | 2026-10-08 | 89.11 | 88783 | 0 | 0 | PASS | BACKFILLED |
| volatility_20 | price_technical | bars | 2025-10-27 | 2026-10-08 | 86.59 | 109283 | 0 | 0 | PASS | BACKFILLED |
| beta_60 | price_technical | bars | 2025-12-23 | 2026-10-08 | 70.48 | 240557 | 0 | 0 | PASS | BACKFILLED |
| dist_high_20 | price_technical | bars | 2025-10-24 | 2026-10-08 | 87.01 | 105865 | 0 | 0 | PASS | BACKFILLED |
| dist_low_20 | price_technical | bars | 2025-10-24 | 2026-10-08 | 87.01 | 105865 | 0 | 0 | PASS | BACKFILLED |
| breakout_20 | price_technical | bars | 2025-10-27 | 2026-10-08 | 86.59 | 109283 | 0 | 0 | PASS | BACKFILLED |
| breakdown_20 | price_technical | bars | 2025-10-27 | 2026-10-08 | 86.59 | 109283 | 0 | 0 | PASS | BACKFILLED |
| avg_volume_20 | volume_liquidity | bars | 2025-10-24 | 2026-10-08 | 87.01 | 105865 | 0 | 0 | PASS | BACKFILLED |
| volume_spike_20 | volume_liquidity | bars | 2025-10-27 | 2026-10-08 | 86.5 | 109988 | 0 | 0 | PASS | BACKFILLED |
| turnover_20 | volume_liquidity | bars | 2025-10-24 | 2026-10-08 | 87.01 | 105865 | 0 | 0 | PASS | BACKFILLED |
| pe | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 3.44 | 3768 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| pb | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 3.45 | 3648 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| roe_pct | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 3.44 | 3691 | 783164 | 9 | PASS | PARTIAL_HISTORY |
| roce_pct | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 3.4 | 4048 | 783164 | 18 | PASS | PARTIAL_HISTORY |
| ev_ebitda | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 3.35 | 4490 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| pe_to_sector | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 2.93 | 7909 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| pb_to_sector | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 3.44 | 3777 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| revenue_yoy | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 2.37 | 12446 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| pat_yoy | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 2.27 | 13241 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| eps_yoy | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 2.28 | 13209 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| revenue_yoy_q | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 0.0 | 12304 | 783164 | 19437 | PASS | PARTIAL_HISTORY |
| pat_yoy_q | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 0.0 | 10338 | 783164 | 21412 | PASS | PARTIAL_HISTORY |
| liabilities_to_assets | fundamental | fundamentals | 2026-09-25 | 2026-10-08 | 2.64 | 10258 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_since_any | event | corporate_actions | 2025-09-29 | 2026-10-08 | 16.05 | 675308 | 8820 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_since_dividend | event | corporate_actions | 2025-09-29 | 2026-10-08 | 13.59 | 695336 | 8820 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_since_split | event | corporate_actions | 2025-09-30 | 2026-10-08 | 1.21 | 796275 | 8820 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_since_bonus | event | corporate_actions | 2025-09-30 | 2026-10-08 | 1.13 | 796934 | 8820 | 0 | PASS | PARTIAL_HISTORY |
| ca_days_to_any | event | corporate_actions |  |  | 0.0 | 806117 | 8820 | 0 | PASS | UNAVAILABLE_HISTORICALLY |
| ca_days_to_dividend | event | corporate_actions |  |  | 0.0 | 806117 | 8820 | 0 | PASS | UNAVAILABLE_HISTORICALLY |
| ca_days_to_split | event | corporate_actions |  |  | 0.0 | 806117 | 8820 | 0 | PASS | UNAVAILABLE_HISTORICALLY |
| ca_days_to_bonus | event | corporate_actions |  |  | 0.0 | 806117 | 8820 | 0 | PASS | UNAVAILABLE_HISTORICALLY |
| news_count_24h | event | legacy_news | 2026-09-25 | 2026-10-08 | 3.9 | 0 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| news_count_7d | event | legacy_news | 2026-09-25 | 2026-10-08 | 3.9 | 0 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| news_hours_since_last | event | legacy_news | 2026-09-25 | 2026-10-08 | 0.21 | 30075 | 783164 | 0 | PASS | PARTIAL_HISTORY |
| index_ret_1d | market_context | bars | 2025-09-24 | 2026-10-08 | 100.0 | 0 | 0 | 0 | PASS | BACKFILLED |
| index_ret_5d | market_context | bars | 2025-09-24 | 2026-10-08 | 100.0 | 0 | 0 | 0 | PASS | BACKFILLED |
| index_close_to_sma_50 | market_context | bars | 2025-09-24 | 2026-10-08 | 100.0 | 0 | 0 | 0 | PASS | BACKFILLED |
| india_vix_level | market_context | bars | 2025-09-24 | 2026-10-08 | 100.0 | 0 | 0 | 0 | PASS | BACKFILLED |
| india_vix_change_5d | market_context | bars | 2025-09-24 | 2026-10-08 | 100.0 | 0 | 0 | 0 | PASS | BACKFILLED |
| fii_net_cash_1d | market_context | fii_dii | 2026-04-02 | 2026-10-08 | 50.39 | 0 | 127 | 0 | PASS | PARTIAL_HISTORY |
| fii_net_cash_5d | market_context | fii_dii | 2026-04-09 | 2026-10-08 | 48.83 | 4 | 127 | 0 | PASS | PARTIAL_HISTORY |
| dii_net_cash_1d | market_context | fii_dii | 2026-04-02 | 2026-10-08 | 50.39 | 0 | 127 | 0 | PASS | PARTIAL_HISTORY |
| dii_net_cash_5d | market_context | fii_dii | 2026-04-09 | 2026-10-08 | 48.83 | 4 | 127 | 0 | PASS | PARTIAL_HISTORY |
| global_ret_1d | market_context | global | 2025-09-24 | 2026-10-08 | 100.0 | 0 | 0 | 0 | PASS | BACKFILLED |
| sector_rs_20 | market_context | bars+sector | 2026-09-25 | 2026-10-08 | 3.24 | 5390 | 782423 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_count_1h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_count_4h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_count_3d | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_unique_publishers_1h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_unique_publishers_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_breaking_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_high_relevance_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_negative_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_positive_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_mixed_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_regulatory_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_corporate_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_macro_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_velocity_1h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_news_velocity_24h | event | multi_news | 2026-10-01 | 2026-10-08 | 1.95 | 1 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_publisher_diversity_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_story_group_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_new_story_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_updated_story_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_time_since_last_news_s | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_time_since_last_high_relevance_news_s | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_market_wide_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_macro_scope_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_geopolitical_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_commodity_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_currency_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_global_market_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_correction_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_edited_news_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_duplicate_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_unique_sources_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.34 | 0 | 250 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_count_1h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.6 | 0 | 792977 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_count_4h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.6 | 0 | 792977 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.6 | 0 | 792977 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_count_3d | event | multi_news | 2026-09-30 | 2026-10-08 | 2.6 | 0 | 792977 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_story_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.6 | 0 | 792977 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_correction_count_24h | event | multi_news | 2026-09-30 | 2026-10-08 | 2.6 | 0 | 792977 | 0 | PASS | PARTIAL_HISTORY |
| mnews_company_time_since_last_s | event | multi_news | 2026-09-30 | 2026-10-08 | 0.65 | 15913 | 792977 | 0 | PASS | PARTIAL_HISTORY |

