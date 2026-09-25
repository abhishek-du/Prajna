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
