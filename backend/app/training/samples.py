"""Research samples of a dataset version x label version (training_sample).

One row per done snapshot x NSE_EQ instrument of that snapshot's replay universe.
Nothing is filled or dropped: every reason is recorded.

  core features   the 24 per-instrument baseline features (review
                  docs/STAGE4_POST_BACKFILL_REVIEW.md section 2; the 6 market-context
                  baseline features are per snapshot and reported separately, never a
                  per-instrument exclusion): core_valid / core_not_valid; feature_eligible
                  = all 24 VALID
  labels          labels_valid (label ids with status VALID), label_flags (label-v2 flags)
  masks           evaluation masks, NOT exclusions (research reports both ways):
                  CA_WINDOW (a non-dividend corporate action with ex-date within
                  [T-1, T+5] trading sessions), EXTREME_UNEXPLAINED, AMBIGUOUS_ORDER_1/_2
  exclusions      NO_LABEL (no label row for the session), LABEL_<reason> (every label of
                  the session missing for one reason, e.g. LABEL_BAR_REFUSED),
                  CORE_FEATURE_NOT_VALID
  eligible        no exclusion (a DB CHECK)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.features.engine import batch_rows

CORE_INSTRUMENT = (
    "ret_1d", "ret_5d", "ret_20d", "sma_20", "sma_50", "close_to_sma_20", "close_to_sma_50",
    "ema_12", "ema_26", "macd_line", "macd_trigger", "macd_histogram", "rsi_14", "atr_14",
    "atr_pct_14", "volatility_20", "beta_60", "dist_high_20", "dist_low_20", "breakout_20",
    "breakdown_20", "avg_volume_20", "volume_spike_20", "turnover_20")
CORE_CONTEXT = ("index_ret_1d", "index_ret_5d", "index_close_to_sma_50", "india_vix_level",
                "india_vix_change_5d", "global_ret_1d")
CA_WINDOW = (-1, 5)            # T - ex, in trading sessions: from the day before to 5 after
COLUMNS = ("dataset_version", "label_version", "session_date", "snapshot", "as_of",
           "instrument_key", "core_valid", "core_total", "core_not_valid", "feature_eligible",
           "labels_valid", "label_flags", "masks", "exclusion_reasons", "eligible",
           "label_start_at", "build_sha256", "built_at")


def sample_row(dataset: str, label_version: str, d: _dt.date, kind: str, as_of: _dt.datetime,
               key: str, core: dict[str, str], labels: list[dict] | None,
               ca_window: bool) -> dict[str, Any]:
    """Pure: one sample from its core feature statuses and its label rows."""
    not_valid = sorted(f for f in CORE_INSTRUMENT if core.get(f) != "VALID")
    exclusions, flags, valid, start = [], [], [], None
    if not labels:
        exclusions.append("NO_LABEL")
    else:
        valid = sorted(r["label_id"] for r in labels if r["status"] == "VALID")
        flags = sorted(set(labels[0]["flags"] or []))
        start = labels[0]["label_start_at"]
        reasons = {r["reason"] for r in labels}
        if not valid and len(reasons) == 1 and None not in reasons:
            exclusions.append(f"LABEL_{reasons.pop()}")
        elif not valid:
            exclusions.append("LABEL_NONE_VALID")
    if not_valid:
        exclusions.append("CORE_FEATURE_NOT_VALID")
    masks = sorted({f for f in flags if f in ("EXTREME_UNEXPLAINED", "AMBIGUOUS_ORDER_1",
                                              "AMBIGUOUS_ORDER_2")}
                   | ({"CA_WINDOW"} if ca_window else set()))
    return {"dataset_version": dataset, "label_version": label_version, "session_date": d,
            "snapshot": kind, "as_of": as_of, "instrument_key": key,
            "core_valid": len(CORE_INSTRUMENT) - len(not_valid),
            "core_total": len(CORE_INSTRUMENT), "core_not_valid": not_valid,
            "feature_eligible": not not_valid, "labels_valid": valid, "label_flags": flags,
            "masks": masks, "exclusion_reasons": sorted(exclusions),
            "eligible": not exclusions, "label_start_at": start}


def digest(rows: list[dict]) -> str:
    keys = ("session_date", "snapshot", "instrument_key", "core_not_valid", "labels_valid",
            "label_flags", "masks", "exclusion_reasons")
    body = sorted([str(r[k]) if not isinstance(r[k], list) else r[k] for k in keys]
                  for r in rows)
    return hashlib.sha256(json.dumps(body, default=str).encode()).hexdigest()


def check_versions(dataset: str, label_version: str) -> None:
    """Samples and splits are derived only for open (non-frozen) dataset and label
    versions: a frozen version's semantics belong to its own era (builder contract)."""
    from app.training import labels as L
    from app.training import policy as P
    from app.training.replay import BuildContractError
    if dataset in P.FROZEN:
        raise BuildContractError(f"{dataset} is frozen; samples are built for open versions")
    if label_version in L.FROZEN_LABELS:
        raise BuildContractError(f"{label_version} is frozen; use label-v2")


async def build(s: AsyncSession, dataset: str, label_version: str) -> dict[str, Any]:
    """Compute every sample of (dataset, label version), then insert them in one
    transaction (append-only; a rerun inserts 0 and must reproduce the same digest)."""
    check_versions(dataset, label_version)
    await s.rollback()
    snaps = (await s.execute(text("""select session_date, snapshot, as_of
        from training_session_done where dataset_version = :v order by 1, 2"""),
        {"v": dataset})).all()
    if not snaps:
        raise ValueError(f"{dataset}: no done snapshots")
    sessions = list((await s.execute(text("""select session_date from trading_session
        where is_trading_day and session_date between :a and :b order by 1"""),
        {"a": snaps[0][0] - _dt.timedelta(days=20), "b": snaps[-1][0] + _dt.timedelta(days=20)}
        )).scalars())
    idx = {d: i for i, d in enumerate(sessions)}
    ex = {}
    for k, x in (await s.execute(text("""select instrument_key, ex_date from
            canon_corporate_action where action_type <> 'DIVIDEND' and ex_date is not null"""))
            ).all():
        if x in idx:
            ex.setdefault(k, []).append(idx[x])
    rows: list[dict] = []
    for d, kind, as_of in snaps:
        core: dict[str, dict[str, str]] = {}
        for k, f, st in (await s.execute(text("""select instrument_key, feature_id, status
                from training_feature_value where dataset_version = :v and session_date = :d
                  and snapshot = :k and scope = 'INSTRUMENT' and instrument_key like 'NSE_EQ|%%'
                  and feature_id = any(:f)"""),
                {"v": dataset, "d": d, "k": kind, "f": list(CORE_INSTRUMENT)})).all():
            core.setdefault(k, {})[f] = st
        keys = sorted(set(core) | set((await s.execute(text("""select distinct instrument_key
            from training_feature_value where dataset_version = :v and session_date = :d
              and snapshot = :k and scope = 'INSTRUMENT' and instrument_key like 'NSE_EQ|%%'"""),
            {"v": dataset, "d": d, "k": kind})).scalars()))
        labs: dict[str, list[dict]] = {}
        for r in (await s.execute(text("""select instrument_key, label_id, status, reason, flags,
                label_start_at from training_label where label_version = :lv
                and session_date = :d"""), {"lv": label_version, "d": d})).mappings().all():
            labs.setdefault(r["instrument_key"], []).append(dict(r))
        t = idx.get(d)
        for k in keys:
            # T within [ex - 1, ex + 5] trading sessions of a non-dividend action
            win = t is not None and any(CA_WINDOW[0] <= t - e <= CA_WINDOW[1]
                                        for e in ex.get(k, ()))
            rows.append(sample_row(dataset, label_version, d, kind, as_of, k, core.get(k, {}),
                                   labs.get(k), win))
    sha = digest(rows)
    at = now()
    inserted = 0
    step = batch_rows(len(COLUMNS))
    for i in range(0, len(rows), step):
        chunk = rows[i:i + step]
        binds, params = [], {}
        for j, v in enumerate(chunk):
            v.update(build_sha256=sha, built_at=at)
            binds.append("(" + ", ".join(f":{c}_{j}" for c in COLUMNS) + ")")
            params.update({f"{c}_{j}": v[c] for c in COLUMNS})
        inserted += (await s.execute(text(
            f"insert into training_sample ({', '.join(COLUMNS)}) values {', '.join(binds)} "  # noqa: S608
            "on conflict on constraint uq_training_sample do nothing"), params)).rowcount
    stored = [dict(r) for r in (await s.execute(text("""select session_date, snapshot,
        instrument_key, core_not_valid, labels_valid, label_flags, masks, exclusion_reasons
        from training_sample where dataset_version = :v and label_version = :lv"""),
        {"v": dataset, "lv": label_version})).mappings().all()]
    if len(stored) != len(rows) or digest(stored) != sha:
        await s.rollback()
        raise RuntimeError(f"{dataset}/{label_version}: stored samples differ from the "
                           f"recompute ({len(stored)} stored, {len(rows)} computed); "
                           "nothing overwritten")
    await s.commit()
    excl: dict[str, int] = {}
    for r in rows:
        for e in r["exclusion_reasons"]:
            excl[e] = excl.get(e, 0) + 1
    return {"dataset_version": dataset, "label_version": label_version, "samples": len(rows),
            "inserted": inserted, "eligible": sum(r["eligible"] for r in rows),
            "exclusions": dict(sorted(excl.items())), "build_sha256": sha}
