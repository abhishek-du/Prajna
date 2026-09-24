"""Upstox fundamentals -> raw archive -> parse -> fundamental_snapshot.

    for each batch of ISINs (default 10) x every Variant (12 requests per ISIN):
        IngestRunner.open                 one run per batch, BEFORE the requests
        GET, every response archived      errors too
        parse_fundamentals                pure; payload kept as sent
        snapshot -> fundamental_snapshot  append-only: a new row only when the
                                          payload differs from the LATEST stored
                                          snapshot of (instrument, statement_type)
        finalize(outcome=coverage)

COVERAGE. Not every instrument has every statement (SMEs, InvITs, new
listings). A 4xx for one (ISIN, variant) is recorded in the run's coverage and
as a WARN VENDOR_ERROR anomaly with the vendor's code; it does not fail the
other 119 requests of the batch. An empty payload is coverage EMPTY. 401/403 or
a rate limit stops everything (ABORTED); an exhausted 5xx retry or a schema
violation FAILS the batch.
"""

from __future__ import annotations

import collections
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, insert, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.clock import IST
from app.core.errors import IngestCheckFailed, RateLimited, VendorAuthError, VendorError
from app.db.models import FundamentalSnapshot, Instrument
from app.ingest.runner import IngestRunner
from app.parsers import upstox_fundamentals as P
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import UpstoxRestClient

SOURCE = Source.UPSTOX_REST_V2.value
STREAM = "fundamentals.isin"
BATCH = 10


@dataclass(slots=True)
class BatchResult:
    isins: list[str]
    status: str
    run_id: uuid.UUID | None = None
    requests: int = 0
    inserted: int = 0
    unchanged: int = 0
    coverage: dict[str, int] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class FundamentalsReport:
    committed: bool
    results: list[BatchResult] = field(default_factory=list)
    stopped: str | None = None

    def count(self, s: str) -> int:
        return sum(1 for r in self.results if r.status == s)

    def summary(self) -> dict[str, Any]:
        cov: collections.Counter = collections.Counter()
        for r in self.results:
            cov.update(r.coverage)
        return {"committed": self.committed, "batches": len(self.results),
                "isins": sum(len(r.isins) for r in self.results),
                "requests": sum(r.requests for r in self.results),
                "inserted": sum(r.inserted for r in self.results),
                "unchanged": sum(r.unchanged for r in self.results),
                "coverage": dict(cov), "stopped": self.stopped,
                **{s.lower(): self.count(s) for s in ("COMPLETE", "FAILED", "ABORTED",
                                                       "NOT_ATTEMPTED")}}


class FundamentalsIngestor:
    def __init__(self, session: AsyncSession, rest: UpstoxRestClient, store: PayloadStore, *,
                 commit: bool, token: str | None, operator: str = "cli", batch: int = BATCH,
                 variants: tuple[P.Variant, ...] = P.VARIANTS):
        self.s, self.rest, self.store = session, rest, store
        self.commit, self.token, self.operator = commit, token, operator
        self.batch, self.variants = batch, variants

    async def _keys(self, isins: list[str]) -> dict[str, str]:
        rows = (await self.s.execute(
            select(Instrument.isin, Instrument.instrument_key).where(
                Instrument.isin.in_(isins), Instrument.segment == "NSE_EQ",
                Instrument.valid_to == literal_column("'infinity'::date")))).all()
        return dict(rows)

    async def run(self, isins: list[str]) -> FundamentalsReport:
        rep = FundamentalsReport(committed=self.commit)
        uniq = sorted(set(isins))
        for i in range(0, len(uniq), self.batch):
            b = uniq[i:i + self.batch]
            if rep.stopped:
                rep.results.append(BatchResult(b, "NOT_ATTEMPTED", error=rep.stopped))
                continue
            res = await self._one(b)
            rep.results.append(res)
            if res.status == "ABORTED":
                rep.stopped = res.error
        return rep

    async def _latest(self, keys: list[str]) -> dict[tuple[str, str], Any]:
        """The latest stored payload per (instrument_key, statement_type)."""
        latest = (select(FundamentalSnapshot.instrument_key, FundamentalSnapshot.statement_type,
                         func.max(FundamentalSnapshot.knowable_at).label("k"))
                  .where(FundamentalSnapshot.instrument_key.in_(keys),
                         FundamentalSnapshot.source == SOURCE)
                  .group_by(FundamentalSnapshot.instrument_key,
                            FundamentalSnapshot.statement_type).subquery())
        rows = (await self.s.execute(
            select(FundamentalSnapshot.instrument_key, FundamentalSnapshot.statement_type,
                   FundamentalSnapshot.payload).join(
                latest, (latest.c.instrument_key == FundamentalSnapshot.instrument_key)
                & (latest.c.statement_type == FundamentalSnapshot.statement_type)
                & (latest.c.k == FundamentalSnapshot.knowable_at)))).all()
        return {(k, t): p for k, t, p in rows}

    async def _one(self, isins: list[str]) -> BatchResult:
        runner = IngestRunner(self.s, source=SOURCE, stream=STREAM,
                              vendor_endpoint="/v2/fundamentals/{id}/{endpoint}",
                              request_params={"isins": isins,
                                              "variants": [v.statement_type
                                                           for v in self.variants]},
                              operator=self.operator)
        ctx = await runner.open(commit=self.commit, token=self.token)
        res = BatchResult(isins, "RUNNING", run_id=ctx.run_id)
        checks = ctx.checks
        keys = await self._keys(isins)
        cov: collections.Counter = collections.Counter()
        rows: list[dict] = []
        try:
            for isin in isins:
                ikey = keys.get(isin)
                if ikey is None:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.COVERAGE_DROP, isin,
                               reason="no current NSE_EQ instrument for this ISIN")
                    continue
                for v in self.variants:
                    try:
                        r = await self.rest.get(v.path(isin, ikey))
                    except (RateLimited, VendorAuthError) as e:
                        await runner.fail(str(e), status=RunStatus.ABORTED)
                        res.status, res.error = "ABORTED", f"{type(e).__name__}: {e}"
                        return res
                    except VendorError as e:
                        checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, isin,
                                   statement_type=v.statement_type, error=str(e)[:300])
                        raise IngestCheckFailed(str(e)) from None
                    res.requests += 1
                    stored = self.store.put(r.data, source=SOURCE, fetched_at=r.fetched_at,
                                            ext="json")
                    if self.commit:
                        await runner.record_payload(stored, http_status=r.status,
                                                    vendor_endpoint=r.url)
                    if r.status != 200:
                        cov["VENDOR_ERROR"] += 1
                        cov[f"code:{','.join(r.error_codes) or r.status}"] += 1
                        checks.add(AnomalySeverity.WARN, AnomalyKind.VENDOR_ERROR, isin,
                                   statement_type=v.statement_type, http_status=r.status,
                                   codes=r.error_codes, payload_sha256=stored.sha256)
                        continue
                    try:
                        snap = P.parse_fundamentals(r.data, http_status=r.status, variant=v,
                                                    subject=isin, fetched_at=r.fetched_at)
                    except P.FundamentalsDecodeError as e:
                        checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, isin,
                                   statement_type=v.statement_type, error=str(e)[:300],
                                   payload_sha256=stored.sha256)
                        continue
                    for i in snap.issues:
                        checks.add(i.severity, i.kind, i.subject, **i.detail,
                                   payload_sha256=stored.sha256)
                    if snap.empty:
                        cov["EMPTY"] += 1
                        continue
                    cov["DATA"] += 1
                    rows.append({
                        "instrument_key": ikey, "isin": isin,
                        "statement_type": snap.statement_type, "period_end": snap.period_end,
                        "period_type": snap.period_type, "reported_at": None,
                        "payload": snap.payload, "source": SOURCE, "run_id": ctx.run_id,
                        "payload_sha256": stored.sha256, "fetched_at": r.fetched_at,
                        "knowable_at": snap.knowable.at,
                        "knowable_at_verified": snap.knowable.verified,
                        "knowable_at_basis": snap.knowable.basis[:200]})
            checks.raise_if_failed()
            latest = await self._latest(sorted({r["instrument_key"] for r in rows}))
            new = [r for r in rows
                   if latest.get((r["instrument_key"], r["statement_type"])) != r["payload"]]
            res.unchanged = len(rows) - len(new)
            if self.commit and new:
                await self.s.execute(insert(FundamentalSnapshot), new)
                res.inserted = len(new)
            res.coverage = dict(cov)
            last = max((r["fetched_at"] for r in rows), default=None)
            ctx.logical_date = last.astimezone(IST).date() if last else None
            await runner.finalize(rows_written=res.inserted,
                                  outcome={"requests": res.requests, "coverage": res.coverage,
                                           "inserted": res.inserted, "unchanged": res.unchanged})
            res.status = "COMPLETE"
            return res
        except IngestCheckFailed as e:
            await runner.fail(str(e), outcome={"coverage": dict(cov)})
            res.status, res.error, res.inserted = "FAILED", str(e)[:500], 0
            return res
        except BaseException as e:
            await runner.fail(f"{type(e).__name__}: {e}", outcome={"coverage": dict(cov)})
            raise
