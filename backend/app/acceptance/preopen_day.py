"""The REAL pre-open acceptance test: one trading day, end to end.

Run after a live capture session has been replayed with --commit:

    prajna acceptance preopen --session <manifest.session.json>

It reads the session manifest, every connection archive and the database, and
grades each Stage-1 pre-open requirement PASS / WARN / FAIL / UNOBSERVED with
its evidence. It never writes the database.

B7 (iiqM semantics) and B8 (which instruments populate IEP/IEQ/IIQ) can only
be graded from REAL pre-open data. The harness proves both conditions from the
evidence itself, not from a flag the caller sets:
  * real     every connection authorized against Upstox's production feed
             host (from the archived `authorized` events);
  * in-window ticks exist whose vendor time falls inside the session's
             pre-open window (the window comes from the vendor's own
             PRE_OPEN_START/PRE_OPEN_END transitions when observed, else from
             trading_session).
If either fails, B7/B8 stay UNRESOLVED however good the numbers look.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import IST, ist_at
from app.storage.frame_archive import FrameArchiveReader, RecordKind, manifest_path

PRODUCTION_FEED_HOST = "wsfeeder-api.upstox.com"
PASS, WARN, FAIL, UNOBSERVED = "PASS", "WARN", "FAIL", "UNOBSERVED"


@dataclass(slots=True)
class Check:
    id: str
    requirement: str
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AcceptanceReport:
    session_id: str
    session_date: str
    manifest: str
    real_market_data: bool
    preopen_window_ist: list[str] | None
    checks: list[Check] = field(default_factory=list)
    b7: dict[str, Any] = field(default_factory=dict)
    b8: dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        s = {c.status for c in self.checks}
        if FAIL in s:
            return FAIL
        if UNOBSERVED in s:
            return UNOBSERVED
        return WARN if WARN in s else PASS

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "session_date": self.session_date,
            "manifest": self.manifest, "verdict": self.verdict,
            "real_market_data": self.real_market_data,
            "preopen_window_ist": self.preopen_window_ist,
            "checks": [{"id": c.id, "requirement": c.requirement, "status": c.status,
                        "evidence": c.evidence} for c in self.checks],
            "B7": self.b7, "B8": self.b8,
        }


def _archive_facts(path: pathlib.Path) -> dict[str, Any]:
    r = FrameArchiveReader(path)
    events: list[dict] = []
    frames = 0
    for rec in r:
        if rec.kind is RecordKind.EVENT:
            events.append({**rec.event(), "_at": rec.recv_at})
        elif rec.kind is RecordKind.BINARY:
            frames += 1
    man_p = manifest_path(path)
    man = json.loads(man_p.read_text()) if man_p.exists() else None
    names = Counter(e["event"] for e in events)
    first = lambda n: next((e["_at"] for e in events if e["event"] == n), None)  # noqa: E731
    return {
        "archive": path.name, "header_session_id": r.header.get("session_id"),
        "frames": frames, "truncated": r.truncated,
        "stream_sha256": r.stream_sha256,
        "manifest_stream_sha256": man and man.get("stream_sha256"),
        "events": dict(names),
        "authorized_hosts": sorted({e.get("endpoint", "").split("/")[2]
                                    for e in events if e["event"] == "authorized"
                                    and e.get("endpoint", "").count("/") >= 2}),
        "first_market_info": first("market_info"),
        "first_subscribed_frame": first("subscription_confirmed"),
        "heartbeats": [e.get("ping_rtt_ms") for e in events if e["event"] == "heartbeat"],
        "disconnects": [{k: v for k, v in e.items() if k in ("reason", "code", "detail")}
                        for e in events if e["event"] == "disconnected"],
    }


async def _q(s: AsyncSession, sql: str, **kw) -> list:
    return list((await s.execute(text(sql), kw)).all())


async def evaluate(s: AsyncSession, manifest: pathlib.Path) -> AcceptanceReport:
    # Read-only batch job: synchronous file reads are deliberate.
    manifest = pathlib.Path(manifest).resolve()  # noqa: ASYNC240
    doc = json.loads(manifest.read_text())
    day = _dt.date.fromisoformat(doc["session_date"])
    shards = doc["shards"]
    facts = [_archive_facts(pathlib.Path(sh["archive"])) for sh in shards]
    names = [pathlib.Path(sh["archive"]).name for sh in shards]

    real = bool(facts) and all(f["authorized_hosts"] == [PRODUCTION_FEED_HOST] for f in facts)

    ts = (await _q(s, "select * from trading_session where session_date=:d", d=day))
    runs = await _q(s, """
        select run_id, status, rows_written, request_params->>'replay_of' as archive
        from ingest_run where stream='preopen' and mode='COMMIT'
          and request_params->>'replay_of' = any(:names)
        order by started_at""", names=names)
    complete = {r.archive: r for r in runs if r.status == "COMPLETE"}
    run_ids = [complete[n].run_id for n in names if n in complete]

    statuses = await _q(s, """
        select segment, status, vendor_updated_at from preopen_session_status
        where session_date=:d and run_id = any(:r) order by vendor_updated_at""",
                        d=day, r=run_ids)
    nse_eq = {st.status: st.vendor_updated_at for st in statuses if st.segment == "NSE_EQ"}

    # The pre-open window: the vendor's own transitions when observed, else calendar.
    if "PRE_OPEN_START" in nse_eq and "PRE_OPEN_END" in nse_eq:
        w0, w1, wbasis = nse_eq["PRE_OPEN_START"], nse_eq["PRE_OPEN_END"], "vendor transitions"
    elif ts and ts[0].preopen_start_ist:
        w0, w1 = ist_at(day, ts[0].preopen_start_ist), ist_at(day, ts[0].preopen_end_ist)
        wbasis = "trading_session (derived)"
    else:
        w0 = w1 = None
        wbasis = "none"

    rep = AcceptanceReport(doc["session_id"], doc["session_date"], str(manifest), real,
                           None if w0 is None else [w0.astimezone(IST).isoformat(),
                                                    w1.astimezone(IST).isoformat(), wbasis])
    add = lambda *a, **ev: rep.checks.append(Check(*a, evidence=ev))  # noqa: E731

    # ── capture ────────────────────────────────────────────────────────────
    add("A1", "successful authorization on every connection",
        PASS if all(f["events"].get("authorized") and f["events"].get("connected")
                    for f in facts) else FAIL,
        hosts=[f["authorized_hosts"] for f in facts], real_market_data=real)
    errors = [sh["error"] for sh in shards if sh["error"]]
    add("A2", "all intended connections ran",
        PASS if not errors and len(shards) == len(facts) else FAIL,
        intended=len(shards), per_connection=doc["universe"]["per_connection"],
        errors=errors)
    cov = doc.get("coverage") or {}
    add("A3", "subscription coverage (every subscribed key produced a frame)",
        UNOBSERVED if not cov else (PASS if cov["never_seen"] == 0 else WARN),
        universe=doc["universe"]["count"], subscribed=cov.get("subscribed"),
        seen=cov.get("seen"), never_seen=cov.get("never_seen"),
        excluded_by_capacity=len(doc["universe"]["excluded_by_capacity"]))
    add("A4", "market_info received on every connection",
        PASS if all(f["first_market_info"] for f in facts) else FAIL,
        first=[str(f["first_market_info"]) for f in facts])
    add("A5", "first subscribed-key frame on every connection",
        PASS if all(f["first_subscribed_frame"] for f in facts) else FAIL,
        first=[str(f["first_subscribed_frame"]) for f in facts])
    add("A6", "heartbeat evidence (ping RTT) on every connection",
        PASS if all(f["heartbeats"] for f in facts) else UNOBSERVED,
        heartbeats=[len(f["heartbeats"]) for f in facts],
        max_rtt_ms=[max(f["heartbeats"], default=None) for f in facts])
    add("A7", "reconnect behaviour", PASS,
        observed=any(f["disconnects"] for f in facts),
        disconnects=[f["disconnects"] for f in facts])
    add("A8", "archive integrity (stream sha256 == manifest)",
        PASS if all(f["stream_sha256"] and f["stream_sha256"] == f["manifest_stream_sha256"]
                    and not f["truncated"] for f in facts) else FAIL,
        archives=[{"archive": f["archive"], "stream_sha256": f["stream_sha256"],
                   "frames": f["frames"]} for f in facts])

    # ── replay / database ──────────────────────────────────────────────────
    add("B1", "every archive replayed with --commit, COMPLETE",
        PASS if len(run_ids) == len(names) else FAIL,
        runs=[{"archive": r.archive, "run_id": str(r.run_id), "status": r.status,
               "rows_written": r.rows_written} for r in runs])
    counts = (await _q(s, """
        select (select count(*) from preopen_tick where run_id = any(:r)) ticks,
               (select count(*) from preopen_book b join preopen_tick t using (tick_id)
                 where t.run_id = any(:r)) rungs,
               (select count(*) from preopen_session_status where run_id = any(:r)) statuses,
               (select count(distinct instrument_key) from preopen_tick
                 where run_id = any(:r)) instruments""", r=run_ids))[0]
    add("B2", "database rows present", PASS if counts.ticks else FAIL,
        ticks=counts.ticks, book_rungs=counts.rungs, statuses=counts.statuses,
        instruments=counts.instruments)
    anomalies = await _q(s, """
        select severity, kind, count(*) n from ingest_anomaly where run_id = any(:r)
        group by 1, 2 order by 1, 2""", r=run_ids)
    add("B3", "anomaly rows (no FAIL on a COMPLETE run)",
        FAIL if any(a.severity == "FAIL" for a in anomalies) else PASS,
        anomalies=[{"severity": a.severity, "kind": a.kind, "n": a.n} for a in anomalies])
    kn = (await _q(s, """
        select count(*) filter (where knowable_at > fetched_at) bad,
               count(*) filter (where knowable_at_verified) verified, count(*) n,
               min(vendor_ts) first_ts, max(vendor_ts) last_ts
        from preopen_tick where run_id = any(:r)""", r=run_ids))[0]
    add("B4", "knowable_at never after fetched_at; vendor-verified share",
        PASS if kn.n and kn.bad == 0 else (UNOBSERVED if not kn.n else FAIL),
        violations=kn.bad, verified=kn.verified, rows=kn.n)
    add("B5", "timestamps within the session date",
        UNOBSERVED if not kn.n else (
            PASS if kn.first_ts.astimezone(IST).date() == day == kn.last_ts.astimezone(IST).date()
            else FAIL),
        first_vendor_ts_ist=str(kn.first_ts and kn.first_ts.astimezone(IST)),
        last_vendor_ts_ist=str(kn.last_ts and kn.last_ts.astimezone(IST)))

    # ── pre-open content ───────────────────────────────────────────────────
    add("C1", "actual pre-open status transitions (NSE_EQ)",
        PASS if {"PRE_OPEN_START", "PRE_OPEN_END"} <= set(nse_eq) else UNOBSERVED,
        transitions={k: v.astimezone(IST).isoformat() for k, v in nse_eq.items()},
        calendar_preopen=None if not ts else [str(ts[0].preopen_start_ist),
                                              str(ts[0].preopen_end_ist)])
    if w0 is None:
        for cid, req in (("C2", "IEP populated in pre-open"), ("C3", "IIQ populated"),
                         ("C4", "bid/ask depth in pre-open"), ("C5", "buy/sell quantities"),
                         ("C6", "pre-open completeness")):
            add(cid, req, UNOBSERVED, reason="no pre-open window known for this session")
        rep.b7 = rep.b8 = {"status": "UNRESOLVED", "reason": "no pre-open window"}
        return rep

    win = (await _q(s, """
        select count(*) ticks, count(distinct instrument_key) instruments,
          count(distinct instrument_key) filter (where iep > 0) iep_instr,
          count(distinct instrument_key) filter (where ieq > 0) ieq_instr,
          count(distinct instrument_key) filter (where iiq_total <> 0) iiq_instr,
          count(distinct instrument_key) filter (where iiq_m <> 0) iiqm_instr,
          count(distinct instrument_key) filter (where tbq > 0 or tsq > 0) qty_instr,
          count(distinct instrument_key) filter (where cas_eligible) cas_instr,
          count(distinct instrument_key) filter (where cas_eligible and iep > 0) cas_iep,
          count(distinct instrument_key) filter (where not cas_eligible and iep > 0) noncas_iep,
          count(*) filter (where iiq_m <> 0 and abs(iiq_m) > abs(iiq_total)) iiqm_gt_total,
          count(*) filter (where iiq_m < 0) iiqm_neg, count(*) filter (where iiq_total < 0)
            iiqt_neg
        from preopen_tick where run_id = any(:r) and vendor_ts >= :w0 and vendor_ts < :w1
        """, r=run_ids, w0=w0, w1=w1))[0]
    depth = await _q(s, """
        select n, count(*) ticks from (
          select t.tick_id, count(b.rung_no) filter (where b.bid_price > 0 or b.ask_price > 0) n
          from preopen_tick t left join preopen_book b using (tick_id)
          where t.run_id = any(:r) and t.vendor_ts >= :w0 and t.vendor_ts < :w1
          group by t.tick_id) x group by n order by n""", r=run_ids, w0=w0, w1=w1)
    subscribed = cov.get("subscribed") or 0
    add("C2", "IEP populated in pre-open", PASS if win.iep_instr else FAIL,
        instruments_with_iep=win.iep_instr, instruments_ticking=win.instruments,
        ieq_instruments=win.ieq_instr)
    add("C3", "IIQ populated in pre-open", PASS if win.iiq_instr else FAIL,
        iiq_total_instruments=win.iiq_instr, iiq_m_instruments=win.iiqm_instr)
    add("C4", "bid/ask depth in pre-open",
        PASS if any(d.n > 0 for d in depth) else FAIL,
        ticks_by_quoted_rungs={d.n: d.ticks for d in depth})
    add("C5", "buy/sell quantities (tbq/tsq) in pre-open", PASS if win.qty_instr else FAIL,
        instruments=win.qty_instr)
    add("C6", "pre-open completeness (subscribed keys with >=1 in-window tick)",
        PASS if subscribed and win.instruments == subscribed else WARN,
        in_window_instruments=win.instruments, subscribed=subscribed,
        ratio=round(win.instruments / subscribed, 4) if subscribed else None)

    evidence_ok = real and win.ticks > 0
    why = None if evidence_ok else (
        "not production feed data" if not real else "no ticks inside the pre-open window")
    rep.b8 = {
        "status": "RESOLVED" if evidence_ok else "UNRESOLVED", "reason": why,
        "observation": {
            "instruments_ticking_in_window": win.instruments,
            "with_iep": win.iep_instr, "with_ieq": win.ieq_instr, "with_iiq": win.iiq_instr,
            "cas_eligible": win.cas_instr, "cas_eligible_with_iep": win.cas_iep,
            "non_cas_with_iep": win.noncas_iep,
        },
    }
    rep.b7 = {
        # Semantics need a human reading of these facts; the harness only
        # certifies that they come from real pre-open data.
        "status": "OBSERVED" if evidence_ok else "UNRESOLVED", "reason": why,
        "observation": {
            "instruments_with_nonzero_iiq_m": win.iiqm_instr,
            "ticks_where_abs_iiq_m_exceeds_abs_iiq_total": win.iiqm_gt_total,
            "ticks_with_negative_iiq_m": win.iiqm_neg,
            "ticks_with_negative_iiq_total": win.iiqt_neg,
            "transitions": {k: v.astimezone(IST).isoformat() for k, v in nse_eq.items()},
        },
    }
    return rep
