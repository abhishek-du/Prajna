"""Measured contracts of the global indices/indicators (hardening phase 5).

For each current global instrument, from its OWN stored daily series (no
foreign calendar exists at the vendor, none is assumed):

  weekday_profile          labels per ISO weekday (Mon..Sun)
  weekend_label_share      share of labels on Sat/Sun: > 2 % means the vendor
                           dates sessions on a shifted calendar (measured:
                           USDINR Mon->Sun, N225 Fri->Sat) - labels are NOT
                           trading dates for that instrument
  absent_weekdays_per_year weekdays with no label (holidays AND vendor gaps;
                           indistinguishable without a calendar)
  gap_days_p50/p99/max     calendar days between consecutive labels
  placeholder_flat_repeat  O=H=L=C = previous close with no volume
  same_open_as_previous    open equal to the previous label's open (flagged,
                           not excluded: seen on GSPC Dec-25 / Jul-4)
  revisions_observed       GLOBAL_REVISION observations so far
  confirm_hours            re-observation window for finality (CONFIRM_HOURS;
                           calibration WAITING_FOR_EVIDENCE: one revision seen)
"""

from __future__ import annotations

import collections
import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.db.models import GlobalInstrumentContract
from app.ingest.runner import IngestRunner

METHOD_VERSION = "globalcontract-v1"
CONFIRM_HOURS = 6
SHIFTED = 0.02
SINCE = _dt.date(2021, 1, 1)


def _pct(values: list[int], q: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def measure(bars: list[tuple], *, revisions: int, through: _dt.date) -> dict[str, Any]:
    """Pure. bars: (label_date, open, high, low, close, volume) sorted by label."""
    bars = [b for b in bars if b[0] >= SINCE]
    wd = collections.Counter(b[0].isoweekday() for b in bars)
    weekend = (wd[6] + wd[7]) / len(bars) if bars else 0.0
    labels = {b[0] for b in bars}
    span = [SINCE + _dt.timedelta(days=i) for i in range((through - SINCE).days + 1)]
    absent = sum(1 for d in span if d.isoweekday() < 6 and d not in labels)
    years = max((through - SINCE).days / 365.25, 1e-9)
    gaps = [(b[0] - a[0]).days for a, b in zip(bars, bars[1:], strict=False)]
    flat = same_open = 0
    for a, b in zip(bars, bars[1:], strict=False):
        if b[1] == b[2] == b[3] == b[4] == a[4] and not b[5]:
            flat += 1
        if b[1] == a[1]:
            same_open += 1
    semantics = ("labels include weekend dates: the vendor dates some sessions on a shifted "
                 "calendar, so a label is NOT the instrument's trading date"
                 if weekend > SHIFTED else
                 "labels fall on weekdays; weekday gaps are holidays or vendor gaps "
                 "(indistinguishable: the vendor has no foreign calendar)")
    return {"label_semantics": semantics,
            "weekday_profile": {str(k): wd[k] for k in range(1, 8)},
            "weekend_label_share": round(weekend, 4),
            "absent_weekdays_per_year": round(absent / years, 2),
            "gap_days_p50": _pct(gaps, 0.5), "gap_days_p99": _pct(gaps, 0.99),
            "gap_days_max": max(gaps) if gaps else 0,
            "placeholder_flat_repeat": flat, "same_open_as_previous": same_open,
            "revisions_observed": revisions, "confirm_hours": CONFIRM_HOURS,
            "completion_rule": (f"final when re-observed unchanged >= {CONFIRM_HOURS} h after "
                                "the first observation, or first observed >= 72 h after the "
                                "label; a changed re-observation marks it REVISED (never "
                                "exposed); flat repeats are placeholders (never exposed)"),
            "measured_through": through}


async def derive_global_contracts(s: AsyncSession, *, commit: bool, token: str | None,
                                  operator: str = "cli") -> dict[str, Any]:
    runner = IngestRunner(s, source="PRAJNA_DERIVED", stream="derive.global_contract",
                          vendor_endpoint="derived: ohlcv_bar + ohlcv_observation",
                          request_params={"method_version": METHOD_VERSION}, operator=operator)
    ctx = await runner.open(commit=commit, token=token)
    try:
        keys = [k for (k,) in (await s.execute(text(
            "select instrument_key from instrument where valid_to = 'infinity' and "
            "segment in ('GLOBAL_INDEX','GLOBAL_INDICATOR') order by 1"))).all()]
        at = now()
        through = at.date() - _dt.timedelta(days=1)
        out = []
        for k in keys:
            bars = (await s.execute(text("""select session_date, open, high, low, close, volume
                from ohlcv_bar where instrument_key = :k and timeframe = '1d'
                order by session_date"""), {"k": k})).all()
            rev = (await s.execute(text("""select count(*) from ohlcv_observation where
                instrument_key = :k and classification = 'GLOBAL_REVISION'"""),
                {"k": k})).scalar()
            m = measure([tuple(b) for b in bars], revisions=rev, through=through)
            out.append({"instrument_key": k, **m, "evidence": {"bars": len(bars),
                        "since": str(SINCE)}, "method_version": METHOD_VERSION,
                        "measured_at": at, "run_id": ctx.run_id})
        if commit and out:
            stmt = pg_insert(GlobalInstrumentContract).values(out)
            await s.execute(stmt.on_conflict_do_update(
                index_elements=["instrument_key"],
                set_={c: stmt.excluded[c] for c in out[0] if c != "instrument_key"}))
        summary = {k["instrument_key"]: {x: k[x] for x in (
            "weekend_label_share", "absent_weekdays_per_year", "gap_days_p99",
            "placeholder_flat_repeat", "same_open_as_previous", "revisions_observed")}
            for k in out}
        await runner.finalize(rows_written=len(out) if commit else 0,
                              outcome={"instruments": len(out)})
        return {"run_id": str(ctx.run_id), "committed": commit, "contracts": summary}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise
