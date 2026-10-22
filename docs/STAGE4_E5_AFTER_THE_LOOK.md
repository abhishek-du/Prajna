# Stage 4 E5: after the look, and the E5.1 retraining policy (2026-10-22; prerequisites built, refit inactive until ACCEPTED)

This plan is fixed **before** any forward-test result exists. It is written while forward day 1 of 40 is done and nothing about performance is known. That way the outcome cannot shape what happens after it. Each step below needs the user's approval when its time comes.

## 1. Operations up to the look (built 2026-10-22)

- **Daily heartbeat.** After each prediction, `model_predict.sh` sends one Telegram line of counts only: day N/40, rows, picks, missing days and outcomes ready. It sends an ISSUE alert instead when a forward day is missing or a closed session has no outcomes yet.
- **Outcome readiness.** `models status` reports, per closed session, whether at least 90 % of the predicted names have a canonical daily bar. It shows counts only, never a price or a return.
- **The look waits** until 40 sessions are predicted and closed **and** every one of them has its outcomes. It is never computed on incomplete outcomes. A session without usable PRE_SESSION values is listed in `not_evaluable_sessions`, never dropped silently.
- **End-to-end test.** `tests/models/test_e5_look.py` runs the look on synthetic forward sessions in the test database. It checks the 39/40 refusal, the outcome wait, A1–A4, the ledger, the refusal of a second look and the not-evaluable listing.

## 2. The look (session 40 closed, about mid-December 2026)

1. `prajna models status` must show 40/40 predicted, 0 missing and outcomes ready 40/40.
2. Run `prajna models report --look`, once. It writes the ledger and `forward_look_<sha>.json`.
3. Report the verdict as it is, together with the secondary metrics. Nothing is re-run, re-cut or re-chosen.

## 3. If NOT_ACCEPTED

- E5 is not used. Stage 5 keeps its current paper strategies.
- E5 stays frozen and readable, as the evidence.
- The next candidate is **E6**: a new pre-registration, with its own recipe, gates and forward test. Candidate inputs, none of them in E5:
  - features-v5 results calendar, analyst counts and company sentiment;
  - news AI enrichment, after a `news-ai-v2` prompt with a closed `event_type` list.
- E6 is trained only once those inputs have at least 120 sessions of history, and it is never selected on E5's forward window.

## 4. If ACCEPTED: Stage 5 use and E5.1 (retraining)

Stage 5 may use E5's picks in **paper** trading. A model left unretrained decays, so production use needs **E5.1**: the same recipe, refitted on a schedule. E5.1 is a policy, not a new search.

| Item | E5.1 rule |
|---|---|
| Recipe | `e5-recipe-v2` unchanged: members, hyperparameters, stacking (inner validation on the last 20 training sessions), universe, hybrid selection, K = 10 |
| Window | the latest 120 labelled sessions, as at E5's freeze |
| Cadence | every 20 trading sessions (the walk-forward's roll), after the close, effective from the next session |
| Data | the same kind of rows E5 was trained on: AS_IF_LIVE features plus `label-v2`, extended session by session (see prerequisites) |
| Freeze | each refit is a `model_version` row with its own sha, artefact sha256, code sha, training window and its predecessor's sha (lineage). The tree must be clean |
| Swap | the new model predicts from the next session's 09:06 run. Each session's predictions name exactly one model |
| Refusal (keep the previous model, alert) | the refit fails; fewer than 400 universe names; any member fails to fit; every stacking weight is 0; the PIT, determinism or fingerprint checks fail |
| Not allowed | tuning hyperparameters, changing K or the thresholds, choosing the window by recent results |

**Monitoring (Stage 8, paper):**
- The realised s_d (picks − MIS cost − matched controls) is tracked over a rolling 40 sessions.
- **Stop rule:** if the rolling 40-session mean s_d is below 0 and its sign-flip CI (0.975) lies wholly below 0, paper use stops and an alert is sent. Restarting is a new decision.
- Feature drift of the 24 core features against the training window is checked weekly and reported. It is not a stop rule.

### Prerequisites for E5.1 (BUILT 2026-10-22; the refit stays inactive until ACCEPTED)

| # | Prerequisite | Built |
|---|---|---|
| 1 | Daily labels | `ops/runbooks/e51_data.sh daily` labels the closed sessions after the last labelled one, up to yesterday. `label-v2` was caught up for 2026-10-09..10-21 (246,150 rows, drift 0) |
| 2 | Daily training rows | The same runbook then builds `stage4-ds-v4b-asif` (AS_IF_LIVE, PRE_SESSION, features-v5) up to the last labelled session, then the samples. A session is never sampled before its labels: samples are append-only, so it would otherwise stay NO_LABEL for good. Backfill 2026-05-01..10-21 started 2026-10-22 17:57 IST (3 builders) |
| 3 | Migration 0026 | `model_version.purpose` adds PRODUCTION; `previous_sha256` (FK) is required for PRODUCTION (CHECK). Applied to production 2026-10-22 18:3x IST after a verified backup (`prajna_20261022T1752_pre_0026_e51.dump`, sha256 `506aae18…`, in /windows/prajna_archive) |
| 4 | Refit and tests | `prajna models refit [--commit]` applies every refusal rule above and stores the refit as PRODUCTION with its predecessor. `prajna models production-model --date D` names the model for session D: the latest of the lineage created before D, refused if another lineage model already predicted D. `tests/models/test_e51.py` |

**Found while building (2026-10-22):** the parallel input readers of `compute_snapshot` (PREOPEN-TAIL) did not take the caller's search_path. A training replay sets `train_asif2` on its own transaction only, so the readers read the public views. The first `stage4-ds-v4-asif` snapshot (2026-10-21) had 11,840 of 245,255 rows different from a sequential recompute.
- Fixed: the readers set the caller's search_path and check it.
- Verified: 4 readers equal a sequential recompute for all 245,255 rows; v4b 2026-10-21 differs in 0.
- `stage4-ds-v4-asif` is frozen and its run SUPERSEDED; the rows are kept.
- Production Stage 3 reads the public views and was not affected: 0 of 506,856 differ.

**Scheduled:** the daily data job runs at 10:05 Mon–Fri (installed 2026-10-22), after the 07:00 bars and the Stage 3 runs. The refit itself gets no cron until E5 is ACCEPTED.

## 5. What stays fixed in every branch

- **Paper only.** No order is placed, modified or cancelled until the user explicitly authorises live trading.
- **No interim look at E5.** No historical replay inside a research TEST window.
