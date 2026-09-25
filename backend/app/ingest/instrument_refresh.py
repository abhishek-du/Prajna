"""Daily instrument-master refresh with a listing lifecycle (hardening phase 2).

    download (or archived) NSE.json.gz -> archive FIRST -> parse -> S1 selection
      -> diff against the current state (pure: diff_master)
      -> one transaction: new instruments, attribute versions, lifecycle
         periods, last_seen; a consistency gate; the run ledger

instrument_id is stable per instrument_key. instrument.valid_from/valid_to
(the identity) are never closed because a key left the master; the listing
state lives in instrument_lifecycle_period and is cached in
instrument.lifecycle_status:

  ACTIVE               selected by the S1 rules in this master
  INELIGIBLE           in this master, no longer selected (e.g. series change)
  REMOVED_FROM_MASTER  absent from this (fully parsed) master
  VENDOR_REJECTED      selected, but UDAPI100011 ("Invalid Instrument key")
                       on >= 2 distinct IST sessions and no COMPLETE candle run
                       since; back to ACTIVE after a later COMPLETE run
Precedence: REMOVED_FROM_MASTER > INELIGIBLE > VENDOR_REJECTED > ACTIVE.

Safety: a master that selects fewer than MIN_COVERAGE of today's listed
(ACTIVE + VENDOR_REJECTED) instruments, or lacks a required index, FAILS and
changes nothing, so a truncated download can never delist the universe.
Nothing is deleted; every change is a new version or period.
"""

from __future__ import annotations

import collections
import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import insert, literal_column, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.identity import GLOBAL_SEGMENTS
from app.contracts.knowable import for_snapshot_download
from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.clock import IST, to_utc
from app.core.errors import IngestCheckFailed
from app.db.models import Instrument, InstrumentAttributeVersion, InstrumentLifecyclePeriod
from app.ingest.instruments import ATTRIBUTES, _convert, _norm, plan_instruments
from app.ingest.runner import IngestRunner
from app.parsers.upstox_instrument_master import MasterDecodeError, parse_master
from app.sources.upstox_instruments import MASTER_URL
from app.storage.payload_store import PayloadStore

SOURCE = Source.UPSTOX_ASSETS.value
STREAM = "instrument.refresh"
MIN_COVERAGE = 0.95
REJECT_CODE = "UDAPI100011"
REJECT_SESSIONS = 2
_INFINITY = literal_column("'infinity'::date")
LISTED = ("ACTIVE", "VENDOR_REJECTED")
GZIP_MAGIC = b"\x1f\x8b"


@dataclass(slots=True)
class MasterDiff:
    new: list[str] = field(default_factory=list)
    changed: dict[str, dict[str, tuple[Any, Any]]] = field(default_factory=dict)
    seen: list[str] = field(default_factory=list)          # current keys present in master
    transitions: dict[str, tuple[str, str, str]] = field(default_factory=dict)  # key: from,to,why

    def summary(self) -> dict[str, Any]:
        by = collections.Counter(f"{a}->{b}" for a, b, _ in self.transitions.values())
        return {"new": len(self.new), "changed": len(self.changed), "seen": len(self.seen),
                "transitions": dict(by)}


def diff_master(*, selected: dict[str, dict], in_master: dict[str, dict],
                current: dict[str, dict], rejected: set[str], recovered: set[str]) -> MasterDiff:
    """Pure. selected: S1-selected key -> attributes; in_master: every current key
    still in the master -> attributes; current: key -> {attributes..., lifecycle_status};
    rejected / recovered: keys with the vendor-rejection evidence / a COMPLETE run since."""
    d = MasterDiff()
    d.new = sorted(k for k in selected if k not in current)
    for key, cur in sorted(current.items()):
        status = cur["lifecycle_status"]
        attrs = in_master.get(key)
        if attrs is None:
            target, why = "REMOVED_FROM_MASTER", "absent from the vendor master"
        else:
            d.seen.append(key)
            diff = {c: (cur[c], attrs[c]) for c in ATTRIBUTES if _norm(cur[c]) != _norm(attrs[c])}
            if diff:
                d.changed[key] = diff
            if key not in selected:
                target, why = "INELIGIBLE", "in the master, not selected by the S1 rules"
            elif key in rejected and not (status == "VENDOR_REJECTED" and key in recovered):
                target, why = "VENDOR_REJECTED", (f"{REJECT_CODE} on >= {REJECT_SESSIONS} "
                                                  "distinct sessions")
            elif status == "VENDOR_REJECTED" and key not in recovered:
                target, why = "VENDOR_REJECTED", "no COMPLETE candle run since the rejection"
            else:
                target = "ACTIVE"
                why = {"REMOVED_FROM_MASTER": "reappeared in the vendor master",
                       "INELIGIBLE": "selected again by the S1 rules",
                       "VENDOR_REJECTED": "a COMPLETE candle run after the rejection"
                       }.get(status, "listed")
        if target != status:
            d.transitions[key] = (status, target, why)
    return d


@dataclass(slots=True)
class RefreshReport:
    run_id: str | None = None
    status: str = ""
    committed: bool = False
    master_sha256: str = ""
    fetched_at: str = ""
    rows_in_master: int = 0
    selected: int = 0
    listed_before: int = 0
    diff: dict[str, Any] = field(default_factory=dict)
    new_keys: list[str] = field(default_factory=list)
    changed_keys: list[str] = field(default_factory=list)
    transitions: dict[str, list[str]] = field(default_factory=dict)
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


async def _rejections(s: AsyncSession) -> tuple[set[str], set[str]]:
    """Keys with UDAPI100011 on >= REJECT_SESSIONS distinct IST dates, and keys
    with a COMPLETE candle run after their last rejection."""
    rows = (await s.execute(text("""
        select split_part(r.stream, '.', 3) k,
               count(distinct (r.started_at at time zone 'Asia/Kolkata')::date) n,
               max(r.started_at) last_rejected
        from ingest_anomaly a join ingest_run r using (run_id)
        where r.stream like 'ohlcv.%' and a.kind = 'VENDOR_ERROR'
          and a.detail->>'codes' like '%' || :code || '%'
        group by 1"""), {"code": REJECT_CODE})).all()
    rejected = {k for k, n, _ in rows if n >= REJECT_SESSIONS}
    recovered = set()
    for k, _, last in rows:
        ok = (await s.execute(text("""select 1 from ingest_run where stream like 'ohlcv.%.' || :k
            and status = 'COMPLETE' and mode = 'COMMIT' and started_at > :t limit 1"""),
            {"k": k, "t": last})).first()
        if ok:
            recovered.add(k)
    return rejected, recovered


async def refresh_instruments(session: AsyncSession, data: bytes, *, fetched_at: _dt.datetime,
                              commit: bool, token: str | None, store: PayloadStore,
                              http_status: int | None = None, source_uri: str = MASTER_URL,
                              operator: str = "cli") -> RefreshReport:
    fetched_at = to_utc(fetched_at)
    rep = RefreshReport(committed=commit, fetched_at=fetched_at.isoformat())
    runner = IngestRunner(session, source=SOURCE, stream=STREAM, vendor_endpoint=source_uri,
                          request_params={"min_coverage": MIN_COVERAGE,
                                          "reject_rule": f"{REJECT_CODE} x{REJECT_SESSIONS}"},
                          operator=operator, logical_date=fetched_at.astimezone(IST).date())
    ctx = await runner.open(commit=commit, token=token)
    rep.run_id, checks = str(ctx.run_id), ctx.checks
    try:
        gz = data[:2] == GZIP_MAGIC
        stored = store.put(data, source=SOURCE, fetched_at=fetched_at,
                           content_type="application/gzip" if gz else "application/json",
                           ext="json.gz" if gz else "json")
        rep.master_sha256 = stored.sha256
        if commit:
            await runner.record_payload(stored, http_status=http_status)
        try:
            plan = plan_instruments(data, stored.sha256)      # both decode gzip themselves
            parsed = parse_master(data)
        except MasterDecodeError as e:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "instrument_master",
                       error=str(e)[:300])
            raise IngestCheckFailed(str(e)) from None
        checks.anomalies.extend(a for a in plan.issues.anomalies
                                if a.severity == AnomalySeverity.FAIL)
        rep.rows_in_master, rep.selected = plan.rows_in_master, len(plan.rows)
        by_key = {m.instrument_key: m for m in parsed.instruments}

        cur_rows = (await session.execute(select(Instrument).where(
            Instrument.valid_to == _INFINITY,
            Instrument.segment.not_in(sorted(GLOBAL_SEGMENTS))))).scalars().all()
        current = {r.instrument_key: {**{c: getattr(r, c) for c in ATTRIBUTES},
                                      "lifecycle_status": r.lifecycle_status,
                                      "instrument_id": r.instrument_id} for r in cur_rows}
        rep.listed_before = sum(1 for v in current.values() if v["lifecycle_status"] in LISTED)
        if rep.listed_before and rep.selected < MIN_COVERAGE * rep.listed_before:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.COVERAGE_DROP, "instrument_master",
                       reason=f"master selects {rep.selected} < {MIN_COVERAGE:.0%} of the "
                              f"{rep.listed_before} listed; refusing to change the lifecycle")
        checks.raise_if_failed()

        in_master = {}
        for key in current:
            m = by_key.get(key)
            if m is not None:
                conv = plan.rows.get(key) or _convert(m, checks)
                if conv is not None:
                    in_master[key] = conv
        rejected, recovered = await _rejections(session)
        d = diff_master(selected=plan.rows, in_master=in_master, current=current,
                        rejected=rejected, recovered=recovered)
        rep.diff, rep.new_keys, rep.changed_keys = d.summary(), d.new, sorted(d.changed)
        tr: dict[str, list[str]] = collections.defaultdict(list)
        for k, (_, b, _) in d.transitions.items():
            tr[b].append(k)
        rep.transitions = {k: sorted(v) for k, v in tr.items()}
        for kind, keys in (("new listings", d.new), ("attribute changes", sorted(d.changed))):
            if keys:
                checks.add(AnomalySeverity.WARN, AnomalyKind.LIFECYCLE, "instrument",
                           reason=f"master refresh: {kind}", count=len(keys), keys=keys[:200])
        for target, keys in rep.transitions.items():
            checks.add(AnomalySeverity.WARN, AnomalyKind.LIFECYCLE, "instrument",
                       reason=f"lifecycle -> {target}", count=len(keys), keys=keys[:200])

        if commit:
            await _apply(session, d, plan.rows, in_master, current, fetched_at, ctx.run_id,
                         stored.sha256)
            await _consistency_gate(session, checks)
        checks.raise_if_failed()
        written = len(d.new) + len(d.changed) + len(d.transitions)
        await runner.finalize(rows_written=written, outcome={
            "master_sha256": stored.sha256, **rep.diff, "transitions": rep.transitions,
            "new_keys": d.new, "changed_keys": sorted(d.changed)})
        rep.status = RunStatus.COMPLETE.value
        return rep
    except IngestCheckFailed as e:
        rep.error = str(e)[:500]
        await runner.fail(rep.error)
        rep.status = RunStatus.FAILED.value
        return rep
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise


def _prov(fetched_at, run_id, sha) -> dict[str, Any]:
    k = for_snapshot_download(fetched_at)
    return {"source": SOURCE, "run_id": run_id, "payload_sha256": sha, "fetched_at": fetched_at,
            "knowable_at": k.at, "knowable_at_verified": k.verified,
            "knowable_at_basis": k.basis}


async def _apply(s: AsyncSession, d: MasterDiff, selected, in_master, current, fetched_at,
                 run_id, sha) -> None:
    prov = _prov(fetched_at, run_id, sha)
    day = fetched_at.astimezone(IST).date()
    for key in d.new:
        attrs = selected[key]
        iid = (await s.execute(insert(Instrument).values(
            instrument_key=key, **attrs, valid_from=day, lifecycle_status="ACTIVE",
            first_seen=day, last_seen=day, **prov).returning(Instrument.instrument_id))).scalar()
        await s.execute(insert(InstrumentAttributeVersion).values(
            instrument_id=iid, **attrs, valid_from=fetched_at, **prov))
        await s.execute(insert(InstrumentLifecyclePeriod).values(
            instrument_id=iid, status="ACTIVE", valid_from=fetched_at,
            reason="new listing in the vendor master", evidence={"master_sha256": sha}, **prov))
    for key in d.changed:
        iid, attrs = current[key]["instrument_id"], in_master[key]
        await _close(s, InstrumentAttributeVersion, iid, fetched_at)
        await s.execute(insert(InstrumentAttributeVersion).values(
            instrument_id=iid, **attrs, valid_from=fetched_at, **prov))
        await s.execute(update(Instrument).where(Instrument.instrument_id == iid).values(**attrs))
    if d.seen:
        ids = [current[k]["instrument_id"] for k in d.seen]
        for i in range(0, len(ids), 1000):
            await s.execute(update(Instrument).where(
                Instrument.instrument_id.in_(ids[i:i + 1000])).values(last_seen=day))
    for key, (frm, to, why) in d.transitions.items():
        iid = current[key]["instrument_id"]
        await _close(s, InstrumentLifecyclePeriod, iid, fetched_at)
        await s.execute(insert(InstrumentLifecyclePeriod).values(
            instrument_id=iid, status=to, valid_from=fetched_at, reason=why,
            evidence={"master_sha256": sha, "from": frm}, **prov))
        await s.execute(update(Instrument).where(Instrument.instrument_id == iid)
                        .values(lifecycle_status=to))


async def _close(s: AsyncSession, model, iid: int, at: _dt.datetime) -> None:
    res = await s.execute(update(model).where(
        model.instrument_id == iid, model.valid_to == literal_column("'infinity'::timestamptz"),
        model.valid_from < at).values(valid_to=at))
    if res.rowcount != 1:
        raise IngestCheckFailed(f"{model.__tablename__}: expected one open version for "
                                f"instrument {iid} older than {at.isoformat()}, "
                                f"closed {res.rowcount}")


async def _consistency_gate(s: AsyncSession, checks) -> None:
    """instrument's cached columns == its open attribute version / lifecycle period."""
    cols = " or ".join(f"i.{c} is distinct from v.{c}" for c in ATTRIBUTES)
    bad_attr = (await s.execute(text(f"""
        select count(*) from instrument i left join instrument_attribute_version v
          on v.instrument_id = i.instrument_id and v.valid_to = 'infinity'
        where v.id is null or {cols}"""))).scalar()                     # noqa: S608
    bad_life = (await s.execute(text("""
        select count(*) from instrument i left join instrument_lifecycle_period p
          on p.instrument_id = i.instrument_id and p.valid_to = 'infinity'
        where p.id is null or p.status <> i.lifecycle_status"""))).scalar()
    if bad_attr or bad_life:
        checks.add(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "instrument",
                   reason="cached columns disagree with the open version/period",
                   attribute_mismatch=bad_attr, lifecycle_mismatch=bad_life)
