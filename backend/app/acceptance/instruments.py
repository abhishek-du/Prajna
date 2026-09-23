"""M3.0 acceptance: archived master -> instrument table, proven end to end.

    ARCHIVED MASTER -> SHA VERIFY -> PARSE -> SELECTION -> PROVENANCE
      -> INSTRUMENT TABLE -> REPLAY SAME MASTER -> NO CHANGES

Each link is a check. The replay is a DRY_RUN load of the same archived
payload; like every dry run it writes only its own ingest_run ledger row. The
verdict is FAIL if any link fails:
  * the archived bytes no longer hash to the named sha256;
  * the selection differs from the one recorded (rule set or member list);
  * any current instrument row differs from what the master yields, is
    missing, or is extra;
  * any row lacks provenance or points at a different payload;
  * the replay would insert rows or raises a FAIL anomaly.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestRun, Instrument, RawPayload
from app.ingest.instruments import (
    _INFINITY,
    ATTRIBUTES,
    STREAM,
    _canon,
    _norm,
    load_current_instruments,
    locate_archived,
    plan_instruments,
    selection_sha256,
)
from app.storage.payload_store import PayloadStore

PASS, FAIL = "PASS", "FAIL"


@dataclass(slots=True)
class Check:
    id: str
    link: str
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _db_rows_sha256(rows: list[Instrument]) -> str:
    doc = [[r.instrument_key, *[_canon(_norm(getattr(r, c))) for c in ATTRIBUTES]]
           for r in sorted(rows, key=lambda r: r.instrument_key)]
    return hashlib.sha256(json.dumps(doc, separators=(",", ":")).encode()).hexdigest()


def _plan_sha256_normalized(plan) -> str:
    doc = [[k, *[_canon(_norm(plan.rows[k][c])) for c in ATTRIBUTES]] for k in plan.keys]
    return hashlib.sha256(json.dumps(doc, separators=(",", ":")).encode()).hexdigest()


async def evaluate(s: AsyncSession, *, master_sha256: str, archive_root: pathlib.Path,
                   replay: bool = True) -> dict[str, Any]:
    checks: list[Check] = []
    add = lambda *a, **ev: checks.append(Check(*a, evidence=ev))  # noqa: E731

    # 1-2. archive + hash
    try:
        path = locate_archived(archive_root, master_sha256)
        data = PayloadStore.read(path, master_sha256)
        add("I1", "archived master located and sha256 verified", PASS,
            path=str(path), bytes=len(data))
    except (LookupError, ValueError) as e:
        add("I1", "archived master located and sha256 verified", FAIL, error=str(e))
        return _result(master_sha256, checks)

    # 3. parse
    plan = plan_instruments(data, master_sha256)
    fails = [a for a in plan.issues.anomalies if a.severity.value == "FAIL"]
    add("I2", "parse: every row accounted for, no FAIL issue", FAIL if fails else PASS,
        rows_in_master=plan.rows_in_master, issues=len(plan.issues.anomalies),
        fail_issues=[f"{a.kind.value}:{a.subject}" for a in fails][:20])

    # 4. selection vs what the load recorded
    runs = list((await s.execute(
        select(IngestRun).where(IngestRun.stream == STREAM, IngestRun.mode == "COMMIT",
                                IngestRun.status == "COMPLETE")
        .order_by(IngestRun.started_at))).scalars())
    recorded = {r.request_params.get("selection_sha256") for r in runs
                if r.request_params.get("master_sha256") == master_sha256}
    ok = recorded == {selection_sha256()}
    add("I3", "selection rules unchanged since the load", PASS if ok else FAIL,
        code_selection_sha256=selection_sha256(), recorded=sorted(x for x in recorded if x),
        equity=len(plan.equity_keys), indices=list(plan.index_keys))

    # 5. provenance
    rows = list((await s.execute(
        select(Instrument).where(Instrument.valid_to == _INFINITY))).scalars())
    rp = await s.get(RawPayload, master_sha256)
    by_payload = {r.payload_sha256 for r in rows}
    run_ids = {r.run_id for r in rows}
    run_ok = {r.run_id for r in runs}
    bad_prov = [r.instrument_key for r in rows
                if not (r.source and r.run_id and r.fetched_at and r.knowable_at
                        and r.knowable_at_basis) or r.knowable_at > r.fetched_at]
    ok = (rp is not None and by_payload == {master_sha256} and run_ids <= run_ok
          and not bad_prov and rp.byte_size == len(data))
    add("I4", "provenance: every row -> this payload, a COMPLETE COMMIT run", PASS if ok else FAIL,
        raw_payload_present=rp is not None, payloads_referenced=sorted(by_payload),
        runs_referenced=sorted(str(x) for x in run_ids),
        rows_missing_provenance=bad_prov[:20])

    # 6. table == plan, exactly
    keys_db = {r.instrument_key for r in rows}
    missing, extra = sorted(set(plan.keys) - keys_db), sorted(keys_db - set(plan.keys))
    db_sha, plan_sha = _db_rows_sha256(rows), _plan_sha256_normalized(plan)
    ok = not missing and not extra and db_sha == plan_sha and len(rows) == len(keys_db)
    add("I5", "instrument table == what the master yields (keys and attributes)",
        PASS if ok else FAIL, current_rows=len(rows), planned=len(plan.rows),
        missing=missing[:20], extra=extra[:20], db_attributes_sha256=db_sha,
        plan_attributes_sha256=plan_sha)

    dupes = (await s.execute(text(
        "select count(*) from (select instrument_key from instrument "
        "where valid_to = 'infinity' group by 1 having count(*) > 1) x"))).scalar()
    add("I6", "no key has two current rows", PASS if dupes == 0 else FAIL,
        keys_with_multiple_current_rows=dupes)

    # 7. replay the same archived master (DRY_RUN)
    if replay:
        rep = await load_current_instruments(s, master_sha256=master_sha256,
                                             archive_root=archive_root, commit=False,
                                             token=None, operator="acceptance")
        fail_anoms = [a for a in rep.anomalies if a["severity"] == "FAIL"]
        ok = (rep.status == "COMPLETE" and rep.would_insert == 0 and not fail_anoms
              and rep.already_current == rep.planned
              and rep.planned_rows_sha256 == plan.rows_sha256)
        add("I7", "replay of the same master changes nothing", PASS if ok else FAIL,
            run_id=str(rep.run_id), status=rep.status, would_insert=rep.would_insert,
            already_current=rep.already_current, planned=rep.planned,
            fail_anomalies=fail_anoms[:10])
    return _result(master_sha256, checks)


def _result(sha: str, checks: list[Check]) -> dict[str, Any]:
    return {"master_sha256": sha,
            "verdict": FAIL if any(c.status == FAIL for c in checks) else PASS,
            "checks": [{"id": c.id, "link": c.link, "status": c.status,
                        "evidence": c.evidence} for c in checks]}
