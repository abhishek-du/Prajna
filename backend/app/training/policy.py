"""Knowability policies of the Stage 4 training datasets (user decision 2026-10-08).

STRICT_PIT     the production canonical layer as it is: an input is knowable when
               Prajna observed it. All history was downloaded on 2026-09-23, so
               this dataset starts at the 2026-09-24 session and grows daily.
AS_IF_LIVE-v1  RESEARCH ONLY. History downloaded in bulk is treated as if the live
               schedule had collected it: knowable at the event end plus the lag
               MEASURED on the live-collected period (never a chosen number). The
               engine reads the train_asif shadow views (migration 0016). Every
               row of this dataset is ASSUMED knowability, never certified PIT.

The measured parameters are frozen at first use (training_policy_param is
append-only): a later rerun reads the same numbers, so the dataset reproduces.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now

STRICT = "STRICT_PIT-v2"
ASIF = "AS_IF_LIVE-v2"
# v1 (superseded 2026-10-08, kept stored): corporate actions were knowable from the
# announcement date (production KN-CA) - earlier than Prajna observed them
SUPERSEDED = {"stage4-ds-v1-strict": "STRICT_PIT", "stage4-ds-v1-asif": "AS_IF_LIVE-v1"}
LIVE_FROM = _dt.date(2026, 9, 24)      # the first market date collected by the live schedule
P_LIVE = 0.99                          # lag percentile of the live period (documented)


@dataclass(frozen=True, slots=True)
class Dataset:
    version: str
    policy: str
    search_path: str | None
    snapshots: tuple[str, ...]


DATASETS = {
    # train_strict: corporate actions knowable when Prajna observed them (migration 0017)
    "strict": Dataset("stage4-ds-v2-strict", STRICT, "train_strict, public",
                      ("PRE_SESSION", "PRE_OPEN")),
    # no historical pre-open data exists, so AS_IF_LIVE has PRE_SESSION only
    "asif": Dataset("stage4-ds-v2-asif", ASIF, "train_asif2, public", ("PRE_SESSION",)),
}


def _ceil_minute(seconds: float) -> int:
    return int(math.ceil(float(seconds) / 60.0) * 60)


async def measure(s: AsyncSession) -> list[dict[str, Any]]:
    """The live lags, from the live-collected period only (market date >= LIVE_FROM).

    daily_bar / fii_dii  seconds after midnight IST of the NEXT trading session at
                         which the live fetch made the row knowable (P99 of the rows
                         fetched by the end of that session; later re-fetches are
                         revisions, not the schedule)
    global               per weekday of the label: max first-fetch and max
                         confirmation lag after label midnight IST
    """
    out: list[dict[str, Any]] = []
    for fam, sql in (
        ("daily_bar", """
            select percentile_cont(:p) within group (order by extract(epoch from
                     knowable_at - (n.next_date::timestamp at time zone 'Asia/Kolkata'))),
                   count(*)
            from canon_market_bar b join train_asif.next_session n on n.session_date = b.market_date
            where b.timeframe = '1d' and b.market_date >= :f
              and b.knowable_at < ((n.next_date + 1)::timestamp at time zone 'Asia/Kolkata')"""),
        ("fii_dii", """
            with m as (select knowable_at, (select min(session_date) from trading_session t
                         where t.is_trading_day and t.session_date > observation_date) nx
                       from canon_macro_observation where observation_date >= :f
                         and split_part(series_code, '|', 1) in ('FII', 'DII'))
            select percentile_cont(:p) within group (order by extract(epoch from
                     knowable_at - (nx::timestamp at time zone 'Asia/Kolkata'))), count(*)
            from m where knowable_at < ((nx + 1)::timestamp at time zone 'Asia/Kolkata')""")):
        v, n = (await s.execute(text(sql), {"p": P_LIVE, "f": LIVE_FROM})).one()
        if v is None:
            raise RuntimeError(f"{fam}: no live-collected rows to measure the lag from")
        out.append({"family": fam, "key": "next_session_ist", "seconds": _ceil_minute(v),
                    "basis": f"P{int(P_LIVE * 100)} of {n} live rows (market date >= "
                             f"{LIVE_FROM}): knowable_at after midnight IST of the next "
                             f"trading session, rounded up to the minute"})
    # corporate actions: the Upstox endpoint lists an action around its ex-date, so the
    # live lag is measured after the later of the announcement (KN-CA) and the ex-date,
    # over actions first stored by the live schedule (after the 2026-09-24 bulk load)
    v, n = (await s.execute(text("""
        select percentile_cont(:p) within group (order by greatest(0, extract(epoch from
                 fetched_at - greatest(knowable_at, ex_date::timestamp at time zone
                 'Asia/Kolkata')))), count(*)
        from canon_corporate_action where ex_date >= :f and fetched_at >= :live"""),
        {"p": P_LIVE, "f": LIVE_FROM, "live": _dt.datetime(2026, 9, 25, tzinfo=_dt.UTC)})).one()
    if v is None:
        raise RuntimeError("corporate_action: no live-collected rows to measure the lag from")
    out.append({"family": "corporate_action", "key": "after_ex", "seconds": _ceil_minute(v),
                "basis": f"P{int(P_LIVE * 100)} of {n} actions first stored by the live "
                         f"schedule (ex-date >= {LIVE_FROM}): fetched_at after the later of "
                         "the announcement (KN-CA) and the ex-date midnight IST"})
    rows = (await s.execute(text("""
        select extract(isodow from label_date)::int,
               max(extract(epoch from first_fetched_at - (label_date::timestamp at time zone
                   'Asia/Kolkata'))),
               max(extract(epoch from knowable_at - (label_date::timestamp at time zone
                   'Asia/Kolkata'))), count(*)
        from canon_global_bar where label_date >= :f group by 1 order by 1"""),
        {"f": LIVE_FROM})).all()
    seen = {r[0]: r for r in rows}
    worst_first = max(r[1] for r in rows)
    worst_conf = max(r[2] for r in rows)
    for wd in range(1, 8):
        r = seen.get(wd)
        first, conf, n = ((float(r[1]), float(r[2]), r[3]) if r
                          else (float(worst_first), float(worst_conf), 0))
        # confirmation needs an unchanged re-observation >= confirm_hours after the first
        conf = max(conf, first + 6 * 3600)
        basis = (f"max over {n} live labels (label date >= {LIVE_FROM}, ISO weekday {wd})"
                 if n else "weekday not observed live: the worst weekday's lag")
        out.append({"family": "global", "key": f"first_wd{wd}", "seconds": _ceil_minute(first),
                    "basis": f"first fetch after label midnight IST, {basis}"})
        out.append({"family": "global", "key": f"confirm_wd{wd}",
                    "seconds": _ceil_minute(conf),
                    "basis": f"confirmed (unchanged re-observation) after label midnight "
                             f"IST, {basis}"})
    return out


async def ensure_params(s: AsyncSession) -> dict[str, dict[str, Any]]:
    """The frozen AS_IF_LIVE-v1 parameters: measured and stored on first use only."""
    have = (await s.execute(text("""select family, key, seconds, basis, measured_at
        from training_policy_param where policy = :p order by 1, 2"""), {"p": ASIF})).all()
    if not have:
        at = now()
        for m in await measure(s):
            await s.execute(text("""insert into training_policy_param
                (policy, family, key, seconds, basis, measured_at)
                values (:p, :family, :key, :seconds, :basis, :at)"""),
                {"p": ASIF, "at": at, **m})
        await s.commit()
        return await ensure_params(s)
    return {f"{r[0]}.{r[1]}": {"seconds": r[2], "basis": r[3], "measured_at": r[4].isoformat()}
            for r in have}
