"""M3.0 — current-instrument initial load from an ALREADY ARCHIVED master.

    archived master (by sha256)
      -> PayloadStore.read()       hash verified BEFORE parsing
      -> parse_master()            every row accounted for
      -> select_preopen()          the M1 eligibility rules, unchanged
         + REQUIRED_INDEX_KEYS     named indices (see below)
      -> instrument                one CURRENT row per key, one transaction

WHAT THIS IS NOT. It is a CURRENT load: one row per key, valid_from = the IST
date the master was held, valid_to = infinity. It does not reconstruct
history and does not solve survivorship. The Upstox master lists only
instruments that exist today, so an instrument delisted before 2026-09-23 has
no row at all. A historical candle that references one of these rows points
at an identity whose valid_from is later than the candle itself; the FK does
not check validity dates. Proper SCD2 maintenance (closing a version when an
attribute changes) is M3, not M3.0.

RULES (never overwrite):
  key already current, identical attributes  -> no-op
  key already current, different attributes  -> DUPLICATE_KEY FAIL, nothing written
  a current row whose key is not selected    -> WARN (never deleted)

fetched_at: the master's own raw_payload.fetched_at when one exists; the
2026-09-23 master was only ever fetched by a DRY_RUN, which records no
raw_payload row, so the archive file's mtime is used instead. mtime is written
AFTER the bytes arrived, so it can only be late: the conservative bound.
knowable_at = for_snapshot_download(fetched_at), unverified.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.identity import GLOBAL_SEGMENTS, SEGMENT_NSE_INDEX
from app.contracts.knowable import for_snapshot_download
from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.contracts.universe import MasterInstrument, rules_fingerprint, select_preopen
from app.core.clock import IST, UTC, to_utc
from app.core.errors import IngestCheckFailed
from app.db.models import Instrument, RawPayload
from app.ingest.checks import CheckResult, check_provenance_complete
from app.ingest.runner import IngestRunner
from app.parsers.upstox_instrument_master import MasterDecodeError, parse_master
from app.sources.upstox_instruments import MASTER_URL
from app.storage.payload_store import PayloadStore, StoredPayload

SOURCE = Source.UPSTOX_ASSETS.value
# The model's open-ended validity. A literal, not a Python date: date.max would
# bind as 9999-12-31, which is not 'infinity', and would match nothing.
_INFINITY = literal_column("'infinity'::date")
STREAM = "instrument.current"
LOAD_VERSION = "m3.0-current-v1"

# Named by the user on 2026-09-23 as the indices M4 depends on. A list, not a
# rule: nothing else from NSE_INDEX is loaded. Each must exist in the master
# with segment NSE_INDEX, or the load fails.
REQUIRED_INDEX_KEYS = ("NSE_INDEX|India VIX", "NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank")

# Column -> (MasterInstrument attribute, kind, limit). Kind "text" limit is
# the varchar length; "dec" limit is the numeric scale. Mirrors the model.
_COLUMNS: dict[str, tuple[str, str, int | None]] = {
    "segment": ("segment", "text", 16),
    "exchange": ("exchange", "text", 16),
    "trading_symbol": ("trading_symbol", "text", 64),
    "name": ("name", "text", None),
    "short_name": ("short_name", "text", None),
    "isin": ("isin", "text", 12),
    "instrument_type": ("instrument_type", "text", 8),
    "security_type": ("security_type", "text", 16),
    "exchange_token": ("exchange_token", "text", 24),
    "lot_size": ("lot_size", "int", None),
    "tick_size": ("tick_size", "dec", 4),
    "freeze_quantity": ("freeze_quantity", "dec", 2),
    "qty_multiplier": ("qty_multiplier", "dec", 4),
    "cas_eligible": ("cas_eligible", "bool", None),
}
REQUIRED_NOT_NULL = ("segment", "exchange", "trading_symbol")
ATTRIBUTES = tuple(_COLUMNS)


def selection_fingerprint() -> dict[str, Any]:
    return {"load": LOAD_VERSION, "equity_rules": rules_fingerprint(),
            "indices": list(REQUIRED_INDEX_KEYS)}


def selection_sha256() -> str:
    return hashlib.sha256(json.dumps(selection_fingerprint(), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def locate_archived(root: pathlib.Path, sha: str) -> pathlib.Path:
    """The archive file whose name is the content address. Exactly one."""
    hits = sorted((pathlib.Path(root) / SOURCE).rglob(f"{sha}.*"))
    hits = [h for h in hits if not h.name.endswith(".part")]
    if len(hits) != 1:
        raise LookupError(f"expected exactly one archived payload {sha} under "
                          f"{root}/{SOURCE}, found {len(hits)}")
    return hits[0]


@dataclass(slots=True)
class InstrumentPlan:
    """The rows a master yields, before touching the database. Pure."""

    master_sha256: str
    rows_in_master: int
    equity_keys: tuple[str, ...]
    index_keys: tuple[str, ...]
    rows: dict[str, dict[str, Any]]              # key -> column values (attributes only)
    issues: CheckResult = field(default_factory=CheckResult)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.rows))

    @property
    def rows_sha256(self) -> str:
        """Content address of the planned attribute set: equal iff identical."""
        doc = [[k, *[_canon(self.rows[k][c]) for c in ATTRIBUTES]] for k in self.keys]
        return hashlib.sha256(json.dumps(doc, separators=(",", ":")).encode()).hexdigest()


def _canon(v: Any) -> Any:
    return str(v) if isinstance(v, Decimal) else v


def _convert(inst: MasterInstrument, checks: CheckResult) -> dict[str, Any] | None:
    out: dict[str, Any] = {}
    ok = True
    for col, (attr, kind, limit) in _COLUMNS.items():
        v = getattr(inst, attr)
        if v is not None and kind == "text" and limit is not None and len(v) > limit:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, inst.instrument_key,
                       field=col, reason=f"longer than varchar({limit})", value=v[:100])
            ok = False
        if v is not None and kind == "dec":
            d = Decimal(repr(v))
            if d != d.quantize(Decimal(1).scaleb(-limit)):
                checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, inst.instrument_key,
                           field=col, reason=f"precision exceeds numeric scale {limit}",
                           value=repr(v))
                ok = False
            v = d
        out[col] = v
    for col in REQUIRED_NOT_NULL:
        if out[col] is None:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, inst.instrument_key,
                       field=col, reason="required attribute missing from master")
            ok = False
    return out if ok else None


def plan_instruments(data: bytes, master_sha256: str) -> InstrumentPlan:
    """bytes -> planned rows. Raises MasterDecodeError on a non-array."""
    parsed = parse_master(data)
    checks = CheckResult()
    for i in parsed.issues:
        checks.add(i.severity, i.kind, i.subject, **i.detail)
    by_key = {m.instrument_key: m for m in parsed.instruments}

    sel = select_preopen(parsed.instruments)
    idx: list[str] = []
    for k in REQUIRED_INDEX_KEYS:
        m = by_key.get(k)
        if m is None or m.segment != SEGMENT_NSE_INDEX:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.COVERAGE_DROP, k,
                       reason="required index missing from the master",
                       found_segment=None if m is None else m.segment)
            continue
        idx.append(k)

    rows: dict[str, dict[str, Any]] = {}
    for k in (*sel.members, *idx):
        conv = _convert(by_key[k], checks)
        if conv is not None:
            rows[k] = conv
    return InstrumentPlan(master_sha256, parsed.row_count, sel.members, tuple(idx), rows, checks)


@dataclass(slots=True)
class InstrumentLoadReport:
    run_id: uuid.UUID | None = None
    status: str = ""
    committed: bool = False
    master_sha256: str = ""
    archive_path: str = ""
    fetched_at: str = ""
    fetched_at_basis: str = ""
    valid_from: str = ""
    selection_sha256: str = ""
    rows_in_master: int = 0
    equity: int = 0
    indices: int = 0
    planned: int = 0
    planned_rows_sha256: str = ""
    already_current: int = 0
    would_insert: int = 0
    inserted: int = 0
    current_not_selected: int = 0
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


async def resolve_fetched_at(
    session: AsyncSession, sha: str, path: pathlib.Path
) -> tuple[_dt.datetime, str]:
    rp = await session.get(RawPayload, sha)
    if rp is not None:
        return to_utc(rp.fetched_at), "raw_payload.fetched_at"
    mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime, UTC)  # noqa: ASYNC240 (one stat)
    return mtime, "archive file mtime (no raw_payload row; written after receipt: late bound)"


async def load_current_instruments(
    session: AsyncSession,
    *,
    master_sha256: str,
    archive_root: pathlib.Path,
    commit: bool,
    token: str | None,
    operator: str = "cli",
) -> InstrumentLoadReport:
    report = InstrumentLoadReport(committed=commit, master_sha256=master_sha256,
                                  selection_sha256=selection_sha256())
    path = locate_archived(archive_root, master_sha256)
    fetched_at, basis = await resolve_fetched_at(session, master_sha256, path)
    valid_from = fetched_at.astimezone(IST).date()
    report.archive_path, report.fetched_at = str(path), fetched_at.isoformat()
    report.fetched_at_basis, report.valid_from = basis, valid_from.isoformat()

    runner = IngestRunner(
        session, source=SOURCE, stream=STREAM, vendor_endpoint=MASTER_URL,
        request_params={"master_sha256": master_sha256, "archive_path": str(path),
                        "fetched_at_basis": basis, "valid_from": valid_from.isoformat(),
                        "selection": selection_fingerprint(),
                        "selection_sha256": report.selection_sha256,
                        "scope": "CURRENT master load; not historical, not survivorship-free"},
        operator=operator, logical_date=valid_from,
    )
    ctx = await runner.open(commit=commit, token=token)
    report.run_id = ctx.run_id
    checks = ctx.checks

    try:
        # 1. hash BEFORE parse: the archived bytes must be the ones named.
        try:
            data = PayloadStore.read(path, master_sha256)
        except ValueError as e:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "archive", error=str(e))
            raise IngestCheckFailed(str(e)) from None
        if commit:
            stored = StoredPayload(master_sha256, path, len(data), "application/gzip",
                                   fetched_at, None, True)
            await runner.record_payload(stored, storage_uri=str(path),
                                        vendor_endpoint=MASTER_URL)

        # 2. parse + select
        try:
            plan = plan_instruments(data, master_sha256)
        except MasterDecodeError as e:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "instrument_master",
                       error=str(e))
            raise IngestCheckFailed(str(e)) from None
        checks.anomalies.extend(plan.issues.anomalies)
        report.rows_in_master = plan.rows_in_master
        report.equity, report.indices = len(plan.equity_keys), len(plan.index_keys)
        report.planned, report.planned_rows_sha256 = len(plan.rows), plan.rows_sha256

        # 3. compare with what is already current: identical = no-op, else FAIL
        # Global instruments come from another file (instrument.global); this
        # NSE master neither selects nor judges them.
        current = {r.instrument_key: r for r in (await session.execute(
            select(Instrument).where(Instrument.valid_to == _INFINITY,
                                     Instrument.segment.not_in(sorted(GLOBAL_SEGMENTS)))))
                   .scalars()}
        fresh = []
        for key in plan.keys:
            row = plan.rows[key]
            old = current.get(key)
            if old is None:
                fresh.append(key)
                continue
            diff = [c for c in ATTRIBUTES if _norm(getattr(old, c)) != _norm(row[c])]
            if diff:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, key,
                           reason="current instrument differs from this master; "
                                  "M3.0 never overwrites (SCD2 rollover is M3)",
                           differing={c: [str(getattr(old, c)), str(row[c])] for c in diff},
                           current_payload_sha256=old.payload_sha256)
            else:
                report.already_current += 1
        stray = sorted(set(current) - set(plan.rows))
        if stray:
            report.current_not_selected = len(stray)
            checks.add(AnomalySeverity.WARN, AnomalyKind.COVERAGE_DROP, "instrument",
                       reason="current instrument rows not in this selection (kept)",
                       count=len(stray), keys=stray[:200])

        k = for_snapshot_download(fetched_at)
        prov = {"source": SOURCE, "run_id": ctx.run_id, "payload_sha256": master_sha256,
                "fetched_at": fetched_at, "knowable_at": k.at,
                "knowable_at_verified": k.verified, "knowable_at_basis": k.basis}
        values = [{"instrument_key": key, **plan.rows[key], "valid_from": valid_from, **prov}
                  for key in fresh]
        report.would_insert = len(values)
        check_provenance_complete(checks, rows=values, stream=STREAM)
        checks.raise_if_failed()

        if commit and values:
            for i in range(0, len(values), 1000):
                await session.execute(pg_insert(Instrument).values(values[i : i + 1000]))
            report.inserted = len(values)
    except IngestCheckFailed as e:
        report.error = str(e)
        report.anomalies = [_anomaly(a) for a in checks.anomalies]
        await runner.fail(str(e))
        report.status, report.inserted = RunStatus.FAILED.value, 0
        return report
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}")
        raise

    report.anomalies = [_anomaly(a) for a in checks.anomalies]
    await runner.finalize(rows_written=report.inserted)
    report.status = RunStatus.COMPLETE.value
    return report


def _norm(v: Any) -> Any:
    if isinstance(v, Decimal):
        return v.normalize()
    return v


def _anomaly(a) -> dict[str, Any]:
    return {"severity": a.severity.value, "kind": a.kind.value, "subject": a.subject,
            "detail": a.detail}
