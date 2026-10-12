"""Read-only consistency checks of the derived Stage 4 tables against their sources
(builder v3). Every check returns a count of violating rows; 0 is the only pass.

label-v2 (training_label)
  ambiguous_flag      AMBIGUOUS_ORDER_n is set exactly when hit_up_n and hit_dn_n are 1
  extreme_flag        EXTREME_UNEXPLAINED is set exactly when |ret_cc| or |gap| > 0.25
                      and no CA_EX_T flag explains it
  reason_status       a reason exactly when the status is MISSING_INPUT
  flags_per_session   every label row of one (session, instrument) carries the same flags
training_sample
  no_label            NO_LABEL exactly when the session has no label row
  core_valid          core_valid equals the VALID core features in training_feature_value
  feature_eligible    feature_eligible exactly when core_valid = core_total
  masks_from_flags    the EXTREME / AMBIGUOUS masks equal those label flags
  eligible_has_label  an eligible sample has at least one VALID label
  snapshot_allowed    a target/stop (label-tsl-*) sample is a PRE_SESSION sample
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.training import samples as SM

_LABEL_CHECKS = {
    "ambiguous_flag": """
        with p as (select session_date, instrument_key, flags,
              max(value) filter (where label_id = 'hit_up_1') u1,
              max(value) filter (where label_id = 'hit_dn_1') d1,
              max(value) filter (where label_id = 'hit_up_2') u2,
              max(value) filter (where label_id = 'hit_dn_2') d2
            from training_label where label_version = :lv group by 1, 2, 3)
        select count(*) from p where
          ((coalesce(u1 = 1 and d1 = 1, false)) <> ('AMBIGUOUS_ORDER_1' = any(flags)))
          or ((coalesce(u2 = 1 and d2 = 1, false)) <> ('AMBIGUOUS_ORDER_2' = any(flags)))""",
    "extreme_flag": """
        with p as (select session_date, instrument_key, flags,
              max(abs(value)) filter (where label_id in ('ret_cc', 'gap')) m
            from training_label where label_version = :lv group by 1, 2, 3)
        select count(*) from p where
          (coalesce(m > 0.25, false) and not exists (select 1 from unnest(flags) f
                                                     where f like 'CA_EX_T:%%'))
          <> ('EXTREME_UNEXPLAINED' = any(flags))""",
    "reason_status": """select count(*) from training_label where label_version = :lv
        and (reason is not null) <> (status = 'MISSING_INPUT')""",
    "flags_per_session": """select count(*) from (select session_date, instrument_key
        from training_label where label_version = :lv group by 1, 2
        having count(distinct flags) > 1) x""",
}

_SAMPLE_CHECKS = {
    "no_label": """select count(*) from training_sample sm where sm.dataset_version = :v
        and sm.label_version = :lv and ('NO_LABEL' = any(sm.exclusion_reasons)) <> not exists (
          select 1 from training_label l where l.label_version = sm.label_version
            and l.session_date = sm.session_date and l.instrument_key = sm.instrument_key)""",
    "core_valid": """select count(*) from training_sample sm where sm.dataset_version = :v
        and sm.label_version = :lv and sm.core_valid <> (select count(*)
          from training_feature_value f where f.dataset_version = sm.dataset_version
            and f.session_date = sm.session_date and f.snapshot = sm.snapshot
            and f.instrument_key = sm.instrument_key and f.feature_id = any(:core)
            and f.status = 'VALID')""",
    "feature_eligible": """select count(*) from training_sample where dataset_version = :v
        and label_version = :lv and feature_eligible <> (core_valid = core_total
          and cardinality(core_not_valid) = 0)""",
    "masks_from_flags": """select count(*) from training_sample where dataset_version = :v
        and label_version = :lv and array(select m from unnest(masks) m where m <> 'CA_WINDOW'
          order by 1) <> array(select f from unnest(label_flags) f where f in
          ('EXTREME_UNEXPLAINED', 'AMBIGUOUS_ORDER_1', 'AMBIGUOUS_ORDER_2') order by 1)""",
    "eligible_has_label": """select count(*) from training_sample where dataset_version = :v
        and label_version = :lv and eligible and cardinality(labels_valid) = 0""",
    "snapshot_allowed": """select count(*) from training_sample where dataset_version = :v
        and label_version = :lv and label_version like 'label-tsl-%%'
        and snapshot <> 'PRE_SESSION'""",
}


async def label_checks(s: AsyncSession, label_version: str) -> dict[str, Any]:
    out = {k: (await s.execute(text(q), {"lv": label_version})).scalar()
           for k, q in _LABEL_CHECKS.items()}
    return {"label_version": label_version, "violations": out,
            "pass": all(v == 0 for v in out.values())}


async def sample_checks(s: AsyncSession, dataset: str, label_version: str) -> dict[str, Any]:
    out = {k: (await s.execute(text(q), {"v": dataset, "lv": label_version,
                                         "core": list(SM.CORE_INSTRUMENT)})).scalar()
           for k, q in _SAMPLE_CHECKS.items()}
    return {"dataset_version": dataset, "label_version": label_version, "violations": out,
            "pass": all(v == 0 for v in out.values())}


# ── label-tsl-long-v1 (one-session long target/stop, gross only) ─────────────────────
_TSL_CHECKS = {
    "outcome_codes": """select count(*) from training_label where label_version = :lv
        and label_id = 'tsl_l_k1p5_outcome' and status = 'VALID' and value not in (-1, 0, 1)""",
    "triplet_status": """select count(*) from (select session_date, instrument_key
        from training_label where label_version = :lv group by 1, 2
        having count(*) <> 3 or count(distinct status) > 1 or count(distinct reason) > 1) x""",
    "geometry": """with p as (select session_date, instrument_key,
              max(value) filter (where label_id = 'tsl_l_k1p5_outcome') o,
              max(value) filter (where label_id = 'tsl_l_k1p5_gross_ret') g,
              max(value) filter (where label_id = 'tsl_l_k1p5_r_multiple') r
            from training_label where label_version = :lv and status = 'VALID' group by 1, 2)
        select count(*) from p where not (
          (o = 1 and g > 0 and r >= 2 - 1e-9) or (o = -1 and g < 0 and abs(r + 1) < 1e-9)
          or (o = 0 and r > -1))""",
    "resolution_flag": """select count(*) from training_label where label_version = :lv
        and status = 'VALID' and not ('RESOLUTION_DAILY' = any(flags)
          or 'RESOLUTION_1M' = any(flags))""",
    "reason_status": """select count(*) from training_label where label_version = :lv
        and (reason is not null) <> (status = 'MISSING_INPUT')""",
    "ambiguous_reason": """select count(*) from training_label where label_version = :lv
        and (reason = 'AMBIGUOUS_ORDER') <> exists (select 1 from unnest(flags) f
          where f in ('RESOLUTION_NO_1M', 'RESOLUTION_1M_SAME_MINUTE',
                      'RESOLUTION_1M_INCONSISTENT'))""",
}


async def tsl_checks(s: AsyncSession, label_version: str) -> dict[str, Any]:
    out = {k: (await s.execute(text(q), {"lv": label_version})).scalar()
           for k, q in _TSL_CHECKS.items()}
    return {"label_version": label_version, "violations": out,
            "pass": all(v == 0 for v in out.values())}


async def checks_for(s: AsyncSession, label_version: str) -> dict[str, Any]:
    """The integrity checks that belong to a label version."""
    if label_version.startswith("label-tsl-"):
        return await tsl_checks(s, label_version)
    return await label_checks(s, label_version)
