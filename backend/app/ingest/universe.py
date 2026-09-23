"""Instrument master -> pre-open universe, through the standard run lifecycle.

    master bytes
      -> PayloadStore.put()        archived BEFORE parsing (even on dry-run)
      -> parse_master()            pure; unusable rows named, not dropped
      -> select_preopen()          eligibility by segment + series, never ISIN
      -> plan_subscription()       sort, then cap (cap UNVERIFIED, B5)
      -> checks                    cap exclusions, coverage vs last universe
      -> instrument_universe_membership, one transaction

Reproducibility: every membership row carries the master's payload_sha256 and
the run records rules_sha256 and the cap, so "which universe, from which file,
under which rules" is answerable from the database alone, and re-selecting
from the archived payload yields the identical member list (and hash).

Two universes are written for a session:
  preopen               every eligible instrument, rank = sorted position
  preopen.cap_excluded  the eligible instruments the cap left out, by name
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.knowable import for_snapshot_download
from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.contracts.universe import (
    CAP_EXCLUDED_SUFFIX,
    PREOPEN_RULES_VERSION,
    PREOPEN_UNIVERSE,
    RULE_SELECTED,
    keys_sha256,
    plan_subscription,
    rules_fingerprint,
    rules_sha256,
    select_preopen,
)
from app.core.clock import to_utc
from app.core.errors import IngestCheckFailed
from app.db.models import InstrumentUniverseMembership as Member
from app.db.models import RawPayload
from app.ingest.checks import check_coverage, check_provenance_complete, check_universe_cap
from app.ingest.runner import IngestRunner
from app.parsers.upstox_instrument_master import GZIP_MAGIC, MasterDecodeError, parse_master
from app.sources.upstox_instruments import MASTER_URL
from app.storage.payload_store import PayloadStore

SOURCE = Source.UPSTOX_ASSETS.value
_CHUNK = 1000


@dataclass(slots=True)
class UniverseReport:
    run_id: uuid.UUID | None = None
    status: str = ""
    committed: bool = False
    universe: str = PREOPEN_UNIVERSE
    session_date: str = ""
    master_sha256: str = ""
    master_bytes: int = 0
    master_fetched_at: str = ""
    archive_path: str = ""
    rows_in_master: int = 0
    rules_version: str = PREOPEN_RULES_VERSION
    rules_sha256: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    rejected_rows: dict[str, int] = field(default_factory=dict)
    members: int = 0
    members_sha256: str = ""
    cap: int | None = None
    subscribed: int = 0
    subscribed_sha256: str = ""
    cap_excluded: list[str] = field(default_factory=list)
    subscribed_keys: list[str] = field(default_factory=list)
    already_recorded: bool = False
    rows_written: int = 0
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__ if k != "subscribed_keys"}


async def load_archived_master(session: AsyncSession, payload_sha256: str):
    """(bytes, fetched_at, http_status) of a master already in raw_payload,
    verified against its hash. The route to re-selecting exactly."""
    rp = await session.get(RawPayload, payload_sha256)
    if rp is None:
        raise LookupError(f"no raw_payload {payload_sha256}")
    if rp.source != SOURCE:
        raise LookupError(f"raw_payload {payload_sha256} is {rp.source}, not {SOURCE}")
    return PayloadStore.read(rp.storage_uri, payload_sha256), rp.fetched_at, rp.http_status


async def _baseline(session: AsyncSession, universe: str, day: _dt.date) -> int | None:
    prev = (await session.execute(
        select(func.max(Member.session_date))
        .where(Member.universe == universe, Member.session_date < day)
    )).scalar()
    if prev is None:
        return None
    return (await session.execute(
        select(func.count()).where(Member.universe == universe, Member.session_date == prev)
    )).scalar()


async def _existing(session: AsyncSession, universe: str, day: _dt.date) -> list[str]:
    return list((await session.execute(
        select(Member.instrument_key)
        .where(Member.universe == universe, Member.session_date == day)
        .order_by(Member.instrument_key)
    )).scalars())


async def select_universe(
    session: AsyncSession,
    data: bytes,
    *,
    fetched_at: _dt.datetime,
    session_date: _dt.date,
    cap: int | None,
    commit: bool,
    token: str | None,
    store: PayloadStore,
    source_uri: str = MASTER_URL,
    http_status: int | None = None,
    universe: str = PREOPEN_UNIVERSE,
    operator: str = "cli",
    coverage_min_ratio: float = 0.80,
) -> UniverseReport:
    fetched_at = to_utc(fetched_at)
    report = UniverseReport(committed=commit, universe=universe, cap=cap,
                            session_date=session_date.isoformat(), rules_sha256=rules_sha256())
    stream = f"universe.{universe}"
    runner = IngestRunner(
        session, source=SOURCE, stream=stream, vendor_endpoint=source_uri,
        request_params={"universe": universe, "session_date": session_date.isoformat(),
                        "cap": cap, "cap_verified": False, "rules": rules_fingerprint(),
                        "rules_sha256": report.rules_sha256},
        operator=operator, logical_date=session_date,
    )
    ctx = await runner.open(commit=commit, token=token)
    report.run_id = ctx.run_id
    checks = ctx.checks

    try:
        # 1. archive before anything reads the bytes
        gz = data[:2] == GZIP_MAGIC
        stored = store.put(data, source=SOURCE, fetched_at=fetched_at,
                           content_type="application/gzip" if gz else "application/json",
                           ext="json.gz" if gz else "json")
        report.master_sha256, report.master_bytes = stored.sha256, stored.byte_size
        report.archive_path, report.master_fetched_at = str(stored.path), fetched_at.isoformat()
        if commit:
            await runner.record_payload(stored, http_status=http_status)

        # 2. parse
        try:
            parsed = parse_master(data)
        except MasterDecodeError as e:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "instrument_master",
                       error=str(e)[:300], payload_sha256=stored.sha256)
            raise IngestCheckFailed(str(e)) from None
        report.rows_in_master = parsed.row_count
        report.rejected_rows = {r: len(ix) for r, ix in parsed.rejected.items()}
        for i in parsed.issues:
            checks.add(i.severity, i.kind, i.subject, **i.detail)

        # 3. eligibility, then subscription
        sel = select_preopen(parsed.instruments)
        report.counts = sel.counts()
        report.members, report.members_sha256 = len(sel.members), sel.members_sha256
        subscribed = check_universe_cap(checks, requested=list(sel.members), cap=cap,
                                        stream=stream)
        plan = plan_subscription(sel.members, cap)
        assert list(plan.subscribed) == subscribed
        report.subscribed, report.subscribed_sha256 = len(subscribed), plan.keys_sha256
        report.cap_excluded, report.subscribed_keys = list(plan.excluded), subscribed
        if not sel.members:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.COVERAGE_DROP, stream,
                       reason="no eligible instruments in the master", counts=report.counts)

        # 4. coverage against the last recorded universe
        check_coverage(checks, observed=len(sel.members),
                       baseline=await _baseline(session, universe, session_date),
                       stream=stream, min_ratio=coverage_min_ratio)

        # 5. one selection per session: identical is a no-op, different is a FAIL
        prior = await _existing(session, universe, session_date)
        prior_cap = await _existing(session, universe + CAP_EXCLUDED_SUFFIX, session_date)
        if prior:
            if prior == list(sel.members) and prior_cap == list(plan.excluded):
                report.already_recorded = True
            else:
                gained = sorted(set(sel.members) - set(prior))
                lost = sorted(set(prior) - set(sel.members))
                checks.add(AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, stream,
                           reason="a different universe is already recorded for this session",
                           session_date=session_date.isoformat(),
                           recorded_sha256=keys_sha256(prior), new_sha256=sel.members_sha256,
                           gained=gained[:200], lost=lost[:200],
                           cap_excluded_changed=prior_cap != list(plan.excluded))

        # 6. rows
        k = for_snapshot_download(fetched_at)
        prov = {"source": SOURCE, "run_id": ctx.run_id, "payload_sha256": stored.sha256,
                "fetched_at": fetched_at, "knowable_at": k.at,
                "knowable_at_verified": k.verified, "knowable_at_basis": k.basis}
        rank = {key: i for i, key in enumerate(sel.members)}
        rows = [{"universe": universe, "session_date": session_date, "instrument_key": key,
                 "rank": rank[key], "reason": f"{RULE_SELECTED} series={sel.series_of[key]}",
                 **prov} for key in sel.members]
        rows += [{"universe": universe + CAP_EXCLUDED_SUFFIX, "session_date": session_date,
                  "instrument_key": key, "rank": rank[key],
                  "reason": f"cap={cap} (UNVERIFIED, B5); sorted position {rank[key]}",
                  **prov} for key in plan.excluded]
        check_provenance_complete(checks, rows=rows, stream=stream)
        checks.raise_if_failed()

        if commit and not report.already_recorded:
            for i in range(0, len(rows), _CHUNK):
                await session.execute(pg_insert(Member).values(rows[i : i + _CHUNK]))
            report.rows_written = len(rows)
    except IngestCheckFailed as e:
        report.error = str(e)
        report.anomalies = [_anomaly(a) for a in checks.anomalies]
        await runner.fail(str(e))
        report.status, report.rows_written = RunStatus.FAILED.value, 0
        return report
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}")
        raise

    report.anomalies = [_anomaly(a) for a in checks.anomalies]
    await runner.finalize(rows_written=report.rows_written)
    report.status = RunStatus.COMPLETE.value
    return report


def _anomaly(a) -> dict[str, Any]:
    return {"severity": a.severity.value, "kind": a.kind.value, "subject": a.subject,
            "detail": a.detail}
