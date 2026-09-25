"""Derived price-basis records and corporate-action factors (phases 6-7).

derive_price_basis   every ohlcv_bar payload without an ohlcv_payload_basis row
                     gets one (e.g. payloads written by a process started before
                     the phase-6 code was deployed). Idempotent.
derive_ca_factors    one ca_factor row per corporate action and METHOD_VERSION:
                     the factor (contracts.ca_factor), and whether the VENDOR's
                     history as we stored it is adjusted for the event:
       vendor_applied answers ONE question: does the vendor adjust history it
       serves AFTER the ex-date? (Bars fetched before the ex-date are raw for
       the event by construction; their basis_as_of already says so.)
          APPLIED      CA_ADJUSTMENT observations prove it (CHAVDA: 740/740), or
                       history fetched after the ex-date is smooth across it
                       while F is distinguishable (TRENT, LICI, ...)
          NOT_APPLIED  history fetched after the ex-date jumps by ~F at it
                       (JAKHARIA, UEL, IDEALTECHO, DHARIWAL)
          UNKNOWN      not observed yet (our pre-ex bars predate the ex-date and
                       no revision was seen), F too close to 1 (|ln F| < 0.2),
                       or bars missing
          N/A          no factor (dividend, rights, unsupported)
          Evidence: the two bars, their ratio, their payload basis dates.
Both are ledgered (source PRAJNA_DERIVED) and authorized like any write.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.ca_factor import METHOD_VERSION, factor_for
from app.core.clock import now
from app.db.models import CaFactor
from app.ingest.runner import IngestRunner

SOURCE = "PRAJNA_DERIVED"
DISTINGUISHABLE = 0.2          # |ln F| below this: a jump cannot be told from a market move
TOLERANCE = 0.15               # |ln(observed ratio) - ln F| to call it the event's jump


def vendor_treatment(f: Decimal | None, prev_close, ex_open, prev_basis_date, ex_date,
                     adjustment_observations: int = 0) -> tuple[str, dict[str, Any]]:
    """Pure. -> (vendor_applied, evidence)."""
    if f is None:
        return "N/A", {"why": "no factor"}
    ev: dict[str, Any] = {"factor": str(f), "prev_close": str(prev_close),
                          "ex_open": str(ex_open), "prev_bar_basis_as_of": str(prev_basis_date),
                          "ca_adjustment_observations": adjustment_observations}
    if adjustment_observations:
        return "APPLIED", {**ev, "why": "later vendor observations were exactly explained by "
                                        "this factor (CA_ADJUSTMENT)"}
    if prev_close is not None and prev_basis_date is not None and prev_basis_date < ex_date:
        return "UNKNOWN", {**ev, "why": "our pre-ex bars predate the ex-date (raw by "
                                        "construction); the vendor's post-ex treatment is not "
                                        "observed yet"}
    if prev_close is None or ex_open is None:
        return "UNKNOWN", {**ev, "why": "no stored bar on one side of the ex-date"}
    ratio = float(prev_close) / float(ex_open)
    ev["ratio"] = round(ratio, 4)
    lf = math.log(float(f))
    if abs(lf) < DISTINGUISHABLE:
        return "UNKNOWN", {**ev, "why": f"factor too close to 1 (|ln F| < {DISTINGUISHABLE})"}
    lr = math.log(ratio)
    if abs(lr - lf) < TOLERANCE:
        return "NOT_APPLIED", {**ev, "why": "the stored series jumps by ~F at the ex-date"}
    if abs(lr) < TOLERANCE:
        return "APPLIED", {**ev, "why": "the stored series is smooth across the ex-date"}
    return "UNKNOWN", {**ev, "why": "the jump matches neither F nor 1"}


async def derive_price_basis(s: AsyncSession, *, commit: bool, token: str | None,
                             operator: str = "cli") -> dict[str, Any]:
    runner = IngestRunner(s, source=SOURCE, stream="derive.price_basis",
                          vendor_endpoint="derived: ohlcv_bar + ingest_run", operator=operator)
    ctx = await runner.open(commit=commit, token=token)
    try:
        missing = (await s.execute(text("""
            select count(distinct b.payload_sha256) from ohlcv_bar b
            left join ohlcv_payload_basis p on p.payload_sha256 = b.payload_sha256
            where p.payload_sha256 is null"""))).scalar()
        n = 0
        if commit and missing:
            n = (await s.execute(text("""
                insert into ohlcv_payload_basis (payload_sha256, endpoint, price_basis,
                       basis_as_of, basis_confidence, method_version, evidence)
                select distinct on (b.payload_sha256) b.payload_sha256,
                       r.request_params->>'endpoint',
                       case when i.segment like 'GLOBAL%'
                              or r.request_params->>'endpoint' = 'intraday'
                            then 'RAW_OBSERVED' else 'VENDOR_ADJUSTED' end,
                       (b.fetched_at at time zone 'Asia/Kolkata')::date, 'HIGH', 'basis-v1',
                       jsonb_build_object('derived', 'derive.price_basis')
                from ohlcv_bar b join ingest_run r using (run_id)
                join instrument i on i.instrument_id = b.instrument_id
                left join ohlcv_payload_basis p on p.payload_sha256 = b.payload_sha256
                where p.payload_sha256 is null
                order by b.payload_sha256
                on conflict do nothing"""))).rowcount
        await runner.finalize(rows_written=n, outcome={"missing": missing, "inserted": n})
        return {"run_id": str(ctx.run_id), "committed": commit, "missing": missing, "inserted": n}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise


async def derive_ca_factors(s: AsyncSession, *, commit: bool, token: str | None,
                            operator: str = "cli") -> dict[str, Any]:
    runner = IngestRunner(s, source=SOURCE, stream="derive.ca_factor",
                          vendor_endpoint="derived: corporate_action + ohlcv_bar",
                          request_params={"method_version": METHOD_VERSION}, operator=operator)
    ctx = await runner.open(commit=commit, token=token)
    try:
        cas = (await s.execute(text("""
            select c.id, c.instrument_key, c.action_type, c.ex_date, c.knowable_at,
                   c.face_value_before, c.face_value_after, c.vendor_payload
            from corporate_action c order by c.id"""))).mappings().all()
        at, out, counts = now(), [], {}
        for c in cas:
            p = c["vendor_payload"] or {}
            details = next((d.get("value") for d in p.get("event_details", [])
                            if d.get("name") == "Details"), None)
            f = factor_for(c["action_type"], ratio=p.get("ratio"),
                           fv_before=c["face_value_before"], fv_after=c["face_value_after"],
                           details=details)
            applied, evidence = "N/A", {"why": "no factor"}
            if f.status == "EXACT" and c["instrument_key"] and c["ex_date"]:
                prev = (await s.execute(text("""
                    select b.close, pb.basis_as_of from ohlcv_bar b
                    left join ohlcv_payload_basis pb using (payload_sha256)
                    where b.instrument_key = :k and b.timeframe = '1d' and b.session_date < :x
                    order by b.session_date desc limit 1"""),
                    {"k": c["instrument_key"], "x": c["ex_date"]})).first()
                nxt = (await s.execute(text("""
                    select b.open from ohlcv_bar b where b.instrument_key = :k
                      and b.timeframe = '1d' and b.session_date >= :x
                    order by b.session_date limit 1"""),
                    {"k": c["instrument_key"], "x": c["ex_date"]})).first()
                n_obs = (await s.execute(text("""
                    select count(*) from ohlcv_observation
                    where classification = 'CA_ADJUSTMENT'
                      and explained_by->'ca_ids' @> to_jsonb(cast(:i as bigint))"""),
                    {"i": c["id"]})).scalar()
                applied, evidence = vendor_treatment(
                    f.factor_price, prev[0] if prev else None, nxt[0] if nxt else None,
                    prev[1] if prev else None, c["ex_date"], adjustment_observations=n_obs)
            key = f"{c['action_type']}/{f.status}/{applied}"
            counts[key] = counts.get(key, 0) + 1
            out.append({"ca_id": c["id"], "instrument_key": c["instrument_key"],
                        "action_type": c["action_type"], "ex_date": c["ex_date"],
                        "status": f.status, "method": f.method, "factor_price": f.factor_price,
                        "factor_volume": f.factor_volume, "knowable_at": c["knowable_at"],
                        "vendor_applied": applied, "vendor_evidence": evidence,
                        "reason": f.reason[:500], "inputs": f.inputs,
                        "method_version": METHOD_VERSION, "derived_at": at,
                        "run_id": ctx.run_id})
        if commit and out:
            for i in range(0, len(out), 1000):
                stmt = pg_insert(CaFactor).values(out[i:i + 1000])
                await s.execute(stmt.on_conflict_do_update(
                    constraint="uq_ca_factor_version",
                    set_={k: stmt.excluded[k] for k in (
                        "status", "method", "factor_price", "factor_volume", "knowable_at",
                        "vendor_applied", "vendor_evidence", "reason", "inputs", "derived_at",
                        "run_id")}))
        summary = {"events": len(out), "counts": dict(sorted(counts.items()))}
        await runner.finalize(rows_written=len(out) if commit else 0, outcome=summary)
        return {"run_id": str(ctx.run_id), "committed": commit, **summary}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise
