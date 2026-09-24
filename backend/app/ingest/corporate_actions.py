"""Upstox corporate actions -> raw archive -> parse -> corporate_action.

    for each batch of ISINs (default 50):
        IngestRunner.open                 one run per batch, BEFORE the requests
        GET /v2/fundamentals/{ISIN}/corporate-actions, every response archived
        parse_corporate_actions           pure
        events -> corporate_action        identity (isin, content_sha256, source):
                                          identical = no-op, new = insert
        finalize(outcome=...)             per-batch counts and date range

A new event whose (isin, type, ex-date) already has a DIFFERENT stored event
is inserted and flagged (WARN): it is either a second event on the same day
(measured: happens) or a vendor edit, and only a human can tell which.
The vendor serves about one year of history; depth is recorded per run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import insert, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.clock import IST
from app.core.errors import IngestCheckFailed, RateLimited, VendorAuthError, VendorError
from app.db.models import CorporateAction, Instrument
from app.ingest.runner import IngestRunner
from app.parsers import upstox_corporate_actions as P
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import UpstoxRestClient

SOURCE = Source.UPSTOX_REST_V2.value
STREAM = "corporate_action.isin"
BATCH = 50


def path(isin: str) -> str:
    return f"/v2/fundamentals/{isin}/corporate-actions"


@dataclass(slots=True)
class BatchResult:
    isins: list[str]
    status: str
    run_id: uuid.UUID | None = None
    events: int = 0
    inserted: int = 0
    already_present: int = 0
    outcome: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class ActionsReport:
    committed: bool
    results: list[BatchResult] = field(default_factory=list)
    stopped: str | None = None

    def count(self, s: str) -> int:
        return sum(1 for r in self.results if r.status == s)

    def summary(self) -> dict[str, Any]:
        return {"committed": self.committed, "batches": len(self.results),
                "isins": sum(len(r.isins) for r in self.results),
                "events_seen": sum(r.events for r in self.results),
                "inserted": sum(r.inserted for r in self.results),
                "already_present": sum(r.already_present for r in self.results),
                "stopped": self.stopped,
                **{s.lower(): self.count(s) for s in ("COMPLETE", "FAILED", "ABORTED",
                                                       "NOT_ATTEMPTED")}}


class CorporateActionIngestor:
    def __init__(self, session: AsyncSession, rest: UpstoxRestClient, store: PayloadStore, *,
                 commit: bool, token: str | None, operator: str = "cli", batch: int = BATCH):
        self.s, self.rest, self.store = session, rest, store
        self.commit, self.token, self.operator, self.batch = commit, token, operator, batch

    async def _symbols(self, isins: list[str]) -> dict[str, tuple[str, str]]:
        rows = (await self.s.execute(
            select(Instrument.isin, Instrument.instrument_key, Instrument.trading_symbol).where(
                Instrument.isin.in_(isins), Instrument.segment == "NSE_EQ",
                Instrument.valid_to == literal_column("'infinity'::date")))).all()
        return {i: (k, t) for i, k, t in rows}

    async def run(self, isins: list[str]) -> ActionsReport:
        rep = ActionsReport(committed=self.commit)
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

    async def _one(self, isins: list[str]) -> BatchResult:
        runner = IngestRunner(self.s, source=SOURCE, stream=STREAM,
                              vendor_endpoint="/v2/fundamentals/{isin}/corporate-actions",
                              request_params={"isins": isins}, operator=self.operator)
        ctx = await runner.open(commit=self.commit, token=self.token)
        res = BatchResult(isins, "RUNNING", run_id=ctx.run_id)
        checks = ctx.checks
        syms = await self._symbols(isins)
        rows: list[dict] = []
        per_isin: dict[str, int] = {}
        try:
            for isin in isins:
                try:
                    r = await self.rest.get(path(isin))
                except (RateLimited, VendorAuthError) as e:
                    await runner.fail(str(e), status=RunStatus.ABORTED)
                    res.status, res.error = "ABORTED", f"{type(e).__name__}: {e}"
                    return res
                except VendorError as e:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, isin,
                               error=str(e)[:300])
                    raise IngestCheckFailed(str(e)) from None
                stored = self.store.put(r.data, source=SOURCE, fetched_at=r.fetched_at, ext="json")
                if self.commit:
                    await runner.record_payload(stored, http_status=r.status, vendor_endpoint=r.url)
                if r.status != 200:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, isin,
                               http_status=r.status, codes=r.error_codes,
                               payload_sha256=stored.sha256)
                    continue
                try:
                    pa = P.parse_corporate_actions(r.data, http_status=r.status, isin=isin,
                                                   fetched_at=r.fetched_at)
                except P.CorporateActionDecodeError as e:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, isin,
                               error=str(e)[:300], payload_sha256=stored.sha256)
                    continue
                for i in pa.issues:
                    checks.add(i.severity, i.kind, i.subject, **i.detail,
                               payload_sha256=stored.sha256)
                per_isin[isin] = len(pa.events)
                key, sym = syms.get(isin, (None, None))
                for e in pa.events:
                    rows.append(self._row(e, key, sym, ctx.run_id, stored.sha256, r.fetched_at))
            checks.raise_if_failed()
            res.events = len(rows)
            ann = [r["announcement_date"] for r in rows if r["announcement_date"]]
            res.outcome = {"isins": len(isins),
                           "isins_with_events": sum(1 for v in per_isin.values() if v),
                           "events": len(rows),
                           "earliest_announcement": str(min(ann)) if ann else None,
                           "latest_announcement": str(max(ann)) if ann else None,
                           "by_type": {t: sum(1 for r in rows if r["action_type"] == t)
                                       for t in sorted({r["action_type"] for r in rows})}}
            res.inserted, res.already_present = await self._write(rows, checks)
            checks.raise_if_failed()
            last = max((r["fetched_at"] for r in rows), default=None)
            ctx.logical_date = last.astimezone(IST).date() if last else None
            await runner.finalize(rows_written=res.inserted, outcome=res.outcome)
            res.status = "COMPLETE"
            return res
        except IngestCheckFailed as e:
            await runner.fail(str(e), outcome=res.outcome)
            res.status, res.error, res.inserted = "FAILED", str(e)[:500], 0
            return res
        except BaseException as e:
            await runner.fail(f"{type(e).__name__}: {e}", outcome=res.outcome)
            raise

    @staticmethod
    def _row(e: P.Event, key, sym, run_id, sha, fetched) -> dict[str, Any]:
        return {"isin": e.isin, "instrument_key": key, "trading_symbol": sym,
                "action_type": e.action_type, "ex_date": e.ex_date, "record_date": e.record_date,
                "announced_at": None, "announcement_date": e.announcement_date,
                "ratio_from": e.ratio_from, "ratio_to": e.ratio_to, "amount": e.amount,
                "face_value_before": e.face_value_before, "face_value_after": e.face_value_after,
                "vendor_action_id": None, "content_sha256": e.content_sha256,
                "vendor_payload": e.vendor_payload, "source": SOURCE, "run_id": run_id,
                "payload_sha256": sha, "fetched_at": fetched, "knowable_at": e.knowable.at,
                "knowable_at_verified": e.knowable.verified,
                "knowable_at_basis": e.knowable.basis[:200]}

    async def _write(self, rows: list[dict], checks) -> tuple[int, int]:
        if not rows:
            return 0, 0
        isins = sorted({r["isin"] for r in rows})
        stored = (await self.s.execute(
            select(CorporateAction.isin, CorporateAction.content_sha256,
                   CorporateAction.action_type, CorporateAction.ex_date).where(
                CorporateAction.isin.in_(isins), CorporateAction.source == SOURCE))).all()
        have = {(i, h) for i, h, _, _ in stored}
        by_day = {(i, t, d) for i, _, t, d in stored}
        new = [r for r in rows if (r["isin"], r["content_sha256"]) not in have]
        for r in new:
            if (r["isin"], r["action_type"], r["ex_date"]) in by_day:
                checks.add(AnomalySeverity.WARN, AnomalyKind.DUPLICATE_KEY, r["isin"],
                           reason="another, different event is already stored for this "
                                  "(isin, type, ex_date): a second event or a vendor edit",
                           action_type=r["action_type"], ex_date=str(r["ex_date"]))
        if self.commit and new:
            await self.s.execute(insert(CorporateAction), new)
        return (len(new) if self.commit else 0), len(rows) - len(new)
