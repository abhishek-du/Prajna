"""Stage 2 acceptance gate: criteria A-P from the REAL database (+ test suite).

Read-only against the data. Statuses: PASS / FAIL / PENDING (the evidence can
only exist after an event that has not happened yet, e.g. an incremental
Stage 1 update). Overall PASS needs every criterion PASS.
"""

from __future__ import annotations

import datetime as _dt
import json
import random
import subprocess
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import CANON_SOURCE, pit
from app.canon.process import STREAM
from app.canon.quality import run_gates
from app.canon.time import LookAheadViolation
from app.canon.universe import RULES_SHA256
from app.core.clock import now

PASS, FAIL, PENDING = "PASS", "FAIL", "PENDING"
EXPECTED_CONSTRAINTS = (
    "ck_canon_instrument_nse_only", "ck_canon_instrument_sector_time",
    "ck_canon_coverage_state", "ck_canon_coverage_timeframe", "ck_canon_coverage_range",
    "ck_canon_coverage_data", "canon_instrument_pkey", "canon_coverage_pkey",
    "canon_instrument_instrument_key_key", "ck_ohlcv_sane", "ck_ohlcv_knowable")
TESTS = {
    "E": ["TestPointInTime", "test_knowable_is_strictly_before"],
    "K": ["test_idempotent_three_runs",
          "test_stage1_ingest_is_processed_and_served_point_in_time"],
    "L": ["test_crash_rolls_back_and_the_rerun_resumes"],
    "M": ["test_incremental_update_touches_only_the_new_pair"],
    "N": ["test_db_constraints"],
}


async def _one(s, sql, **kw):
    return (await s.execute(text(sql), kw)).one()


async def _all(s, sql, **kw):
    return list((await s.execute(text(sql), kw)).all())


def run_tests() -> dict[str, Any]:
    """The full suite (Stage 1 + Stage 2): P, and test evidence for E/K/L/M/N."""
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:randomly"],
                       capture_output=True, text=True, timeout=3600)
    tail = [ln for ln in p.stdout.splitlines() if " passed" in ln or " failed" in ln]
    return {"exit": p.returncode, "summary": tail[-1] if tail else p.stdout[-300:]}


async def _pit_probes(s: AsyncSession, n: int = 40) -> dict[str, Any]:
    """Random real (instrument, as_of) pairs: every row returned is knowable
    strictly before as_of, and the first row knowable AT as_of is excluded."""
    rnd = random.Random(20260924)  # noqa: S311 (sampling)
    keys = [k for (k,) in await _all(s, """select instrument_key from canon_instrument
                                            where included order by 1""")]
    checked = rows = boundary_excluded = 0
    for key in rnd.sample(keys, min(n, len(keys))):
        ks = await _all(s, """select knowable_at from canon_market_bar where instrument_key=:k
                              and timeframe='1d' order by knowable_at""", k=key)
        if not ks:
            continue
        k = ks[rnd.randrange(len(ks))][0]
        at_k = await pit.bars(s, key, "1d", k)              # asserts every row itself
        after = await pit.bars(s, key, "1d", k + _dt.timedelta(microseconds=1))
        checked += 1
        rows += len(after)
        # AT k: nothing knowable at or after k; 1 us later: the rows knowable at k
        # appear, and every returned row is strictly earlier than as_of
        if all(r["knowable_at"] < k for r in at_k) and after and \
                all(r["knowable_at"] <= k for r in after) and len(after) > len(at_k):
            boundary_excluded += 1
    return {"instruments_probed": checked, "rows_returned_after_boundary": rows,
            "boundary_behaviour_correct": boundary_excluded}


async def evaluate(s: AsyncSession, tests: dict | None = None) -> dict[str, Any]:
    out: list[dict] = []

    def add(cid, question, status, evidence, notes=""):
        out.append({"id": cid, "question": question, "status": status, "evidence": evidence,
                    "notes": notes})

    runs = await _all(s, """select run_id, status, started_at, finished_at, rows_written,
            request_params->'outcome' o from ingest_run where source=:src and stream=:st
            and mode='COMMIT' order by started_at""", src=CANON_SOURCE, st=STREAM)
    done = [r for r in runs if r.status == "COMPLETE"]
    last = done[-1] if done else None
    inst = await _one(s, """select (select count(*) from instrument where valid_to='infinity'),
            (select count(*) from canon_instrument), (select count(*) from canon_instrument
            where included)""")
    cov = await _one(s, """select count(distinct (instrument_id, timeframe)), count(*)
                           from canon_coverage""")
    q = await run_gates(s)
    gate = {g["gate"]: g for g in q["gates"]}

    # A
    a_ok = bool(last) and inst[0] == inst[1] and cov[0] == inst[2] * 4
    add("A", "Can Stage 2 process Stage 1 data?", PASS if a_ok else FAIL,
        {"latest_commit_run": str(last.run_id) if last else None,
         "mode": last.o.get("mode") if last else None,
         "seconds": last.o.get("seconds") if last else None,
         "instruments_current/decided/included": list(inst), "coverage_pairs": cov[0],
         "coverage_ranges": cov[1]})
    # B
    b_gates = ("duplicate_bars", "invalid_timeframe", "null_required_bar_fields",
               "coverage_contradicts_bars", "non_session_bars_exposed")
    add("B", "Is data normalized consistently?",
        PASS if all(gate[g]["status"] == PASS for g in b_gates) else FAIL,
        {g: gate[g]["count"] for g in b_gates})
    # C
    c_gates = ("bar_knowable_before_event_end", "daily_bar_fetched_same_session")
    ev = await _one(s, """select
        count(*) filter (where b.timeframe = '1d'
            and (b.bar_start_utc at time zone 'Asia/Kolkata')::time <> '00:00'),
        count(*) filter (where b.timeframe = '1d' and t.open_ist is not null and
            (b.event_start <> (b.market_date + t.open_ist) at time zone 'Asia/Kolkata'
             or b.event_end <> (b.market_date + t.close_ist) at time zone 'Asia/Kolkata')),
        count(*) filter (where b.timeframe <> '1d' and t.open_ist is not null and
            (b.event_start < (b.market_date + t.open_ist) at time zone 'Asia/Kolkata'
             or b.event_end > (b.market_date + t.close_ist) at time zone 'Asia/Kolkata')),
        count(*) filter (where b.market_date <>
            (b.bar_start_utc at time zone 'Asia/Kolkata')::date)
        from canon_market_bar b join trading_session t on t.session_date = b.market_date""")
    add("C", "Are timestamps correct?",
        PASS if all(gate[g]["status"] == PASS for g in c_gates) and ev == (0, 0, 0, 0)
        else FAIL,
        {**{g: gate[g]["count"] for g in c_gates}, "daily_label_not_0000_ist": ev[0],
         "daily_event_not_session_hours": ev[1], "intraday_outside_session": ev[2],
         "market_date_not_label_date": ev[3]},
        "D4: daily label 00:00 IST; event = the session's own hours (Muhurat sessions "
        "included); knowable after it")
    # D
    dk = await _one(s, """select count(*) from canon_market_bar c join ohlcv_bar b
            on b.instrument_id=c.instrument_id and b.timeframe=c.timeframe
            and b.bar_start_utc=c.bar_start_utc and b.session_date=c.market_date
            where b.knowable_at <> c.knowable_at or b.fetched_at <> c.fetched_at
               or b.payload_sha256 <> c.payload_sha256""")
    add("D", "Is knowable_at preserved?",
        PASS if dk[0] == 0 and gate["knowable_after_fetched"]["status"] == PASS else FAIL,
        {"canonical_vs_stage1_mismatches": dk[0],
         "knowable_after_fetched": gate["knowable_after_fetched"]["count"]})
    # E
    probes = {}
    try:
        probes = await _pit_probes(s)
        e_real = probes["instruments_probed"] > 0 and \
            probes["boundary_behaviour_correct"] == probes["instruments_probed"]
    except LookAheadViolation as e:
        e_real, probes = False, {"violation": str(e)}
    e_ok = e_real and (tests is None or tests.get("exit") == 0)
    add("E", "Is future leakage impossible?", PASS if e_ok else FAIL,
        {"real_db_probes": probes, "tests": TESTS["E"]},
        "every read requires as_of; rows with knowable_at >= as_of are never returned")
    # F
    fx = await _one(s, """select
        count(*) filter (where included and segment not in ('NSE_EQ','NSE_INDEX')),
        count(*) filter (where not included and segment='NSE_EQ'
            and instrument_type in ('EQ','BE','SM','BZ','ST','IV')
            and isin ~ '^IN[A-Z0-9]{9}[0-9]$'),
        count(*) filter (where segment like 'GLOBAL%' and included),
        count(*) filter (where rules_sha256 <> :h), count(*) filter (where filter_reason = '')
        from canon_instrument""", h=RULES_SHA256)
    add("F", "Is NSE filtering correct?", PASS if fx == (0, 0, 0, 0, 0) else FAIL,
        {"non_nse_included": fx[0], "eligible_equity_excluded": fx[1], "global_included": fx[2],
         "stale_rules": fx[3], "missing_reason": fx[4], "rules_sha256": RULES_SHA256})
    # G
    gx = await _one(s, """select count(*) from canon_instrument ci join instrument i
            using (instrument_id) where i.valid_to='infinity' and (i.instrument_key <>
            ci.instrument_key or i.isin is distinct from ci.isin or i.trading_symbol <>
            ci.trading_symbol or i.segment <> ci.segment)""")
    add("G", "Is instrument mapping correct?",
        PASS if gx[0] == 0 and gate["orphan_instruments"]["status"] == PASS
        and gate["missing_identifiers"]["status"] == PASS else FAIL,
        {"mapping_mismatches": gx[0], "orphans": gate["orphan_instruments"]["count"],
         "missing_identifiers": gate["missing_identifiers"]["count"]})
    # H
    hx = await _one(s, """select count(*) filter (where sector is not null),
        count(*) filter (where sector is not null and (f.id is null or
            f.knowable_at <> ci.sector_knowable_at or f.payload->>'sector' <> ci.sector))
        from canon_instrument ci
        left join fundamental_snapshot f on f.id = ci.sector_snapshot_id""")
    add("H", "Is data enrichment traceable?", PASS if hx[1] == 0 else FAIL,
        {"instruments_with_sector": hx[0], "sector_not_traceable_to_snapshot": hx[1]},
        "sector coverage grows with the Stage 1 fundamentals sweep; PIT sector via pit.sector()")
    # I
    st = dict(await _all(s, "select state, sum(sessions) from canon_coverage group by 1"))
    add("I", "Is missing data represented correctly?",
        PASS if st.get("MISSING", 0) == 0 and set(st) <= {
            "DATA", "EMPTY", "QUARANTINED", "VENDOR_ERROR", "PENDING_BACKFILL"} else FAIL,
        {"sessions_by_state": {k: int(v) for k, v in st.items()},
         "out_of_scope": "5m via pit.coverage/pit.bars (OutOfScope)"},
        "nothing is filled: no zero, no forward fill, no interpolation")
    # J
    qd = await _one(s, """select count(*) from ingest_anomaly a join ingest_run r using (run_id)
        join canon_instrument ci on ci.instrument_key = a.detail->>'instrument_key' and ci.included
        where a.kind='QUARANTINED' and r.mode='COMMIT' and r.status='COMPLETE'""")
    qc = st.get("QUARANTINED", 0)
    j_ok = gate["invalid_ohlc"]["status"] == PASS and gate["negative_volume"]["status"] == PASS
    add("J", "Is bad data quarantined?", PASS if j_ok else FAIL,
        {"stage1_quarantined_bars_nse": qd[0], "coverage_quarantined_sessions": int(qc),
         "invalid_ohlc_visible": gate["invalid_ohlc"]["count"],
         "non_session_placeholder_bars_excluded": q["informational"][
             "bars_excluded_non_session (canon_excluded_bar)"]})
    # K
    noop = [r for r in done if (r.o or {}).get("mode") == "NOOP" and r.rows_written == 0]
    add("K", "Is processing idempotent?",
        PASS if noop and (tests is None or tests.get("exit") == 0) else FAIL,
        {"real_noop_reruns": [str(r.run_id) for r in noop[-3:]], "tests": TESTS["K"]})
    # L
    add("L", "Can processing resume after failure?",
        PASS if tests is None or tests.get("exit") == 0 else FAIL,
        {"tests": TESTS["L"], "failed_canon_runs": sum(r.status == "FAILED" for r in runs),
         "note": "rows and checkpoint commit in one transaction"})
    # M
    inc = [r for r in done if (r.o or {}).get("mode") == "INCREMENTAL"]
    add("M", "Can Stage 2 process incremental Stage 1 updates?",
        PASS if inc else PENDING,
        {"real_incremental_runs": [str(r.run_id) for r in inc[-3:]], "tests": TESTS["M"]},
        "real evidence needs a Stage 1 run finishing after a Stage 2 checkpoint")
    # N
    cons = {r[0] for r in await _all(s, "select conname from pg_constraint")}
    missing = [c for c in EXPECTED_CONSTRAINTS if c not in cons]
    add("N", "Are database constraints enforced?",
        PASS if not missing and (tests is None or tests.get("exit") == 0) else FAIL,
        {"missing_constraints": missing, "tests": TESTS["N"]})
    # O
    try:
        key = "NSE_EQ|INE002A01018"
        ctx = await pit.context(s, key, now())
        o_ok = bool(ctx["daily_bars"])
        o_ev = {"probe": key, "daily_bars": len(ctx["daily_bars"]),
                "corporate_actions": len(ctx["corporate_actions"]), "news": len(ctx["news"]),
                "fundamentals": len(ctx["fundamentals"]), "sector": ctx["sector"]}
    except Exception as e:                      # the probe itself must not fail
        o_ok, o_ev = False, {"error": repr(e)[:300]}
    add("O", "Can Stage 3 consume the canonical data safely?", PASS if o_ok else FAIL,
        {**o_ev, "api": "app.canon.pit: bars, corporate_actions, news, fundamentals, sector, "
                        "preopen, macro, global_bars, coverage, context"})
    # P
    add("P", "Are all existing Stage 1 tests still passing?",
        PASS if tests and tests.get("exit") == 0 else (PENDING if tests is None else FAIL),
        tests or {"note": "run with --run-tests"})

    overall = "PASS" if all(c["status"] == PASS for c in out) else "NOT PASSED"
    return {"generated_at": now().isoformat(), "overall": overall, "criteria": out,
            "quality": q}


def to_markdown(rep: dict, dependency: dict) -> str:
    L = ["# Stage 2 acceptance", "",
         f"**Generated:** {rep['generated_at']} by `prajna acceptance stage2` (read-only; "
         "regenerate, do not edit).", "",
         f"## Overall: **{rep['overall']}**", "",
         "Stage 3 stays locked until this is PASS.", "",
         "| # | Question | Status | Evidence | Notes |", "|---|---|---|---|---|"]
    for c in rep["criteria"]:
        ev = json.dumps(c["evidence"], default=str).replace("|", "\\|")[:700]
        L.append(f"| {c['id']} | {c['question']} | **{c['status']}** | {ev} | {c['notes']} |")
    L += ["", "## Quality gates", "", "| gate | status | count |", "|---|---|---|"]
    L += [f"| {g['gate']} | {g['status']} | {g['count']} |" for g in rep["quality"]["gates"]]
    L += ["", f"Informational: `{json.dumps(rep['quality']['informational'])}`", "",
          "## Dependence on Stage 1 (not yet complete)", ""]
    L += [f"- {k}: {v}" for k, v in dependency.items()]
    L += ["", "## Known limitations", "",
          "- Market data is not copied. The canonical layer is views over the "
          "validated Stage 1 tables, plus two derived tables.",
          "- Coverage is a meta view of what Stage 1 holds **now**. It is not "
          "point-in-time data.",
          "- A news-instrument association is knowable only when the vendor link was "
          "fetched (the Stage 1 contract), so historical news associations become "
          "visible from their fetch time.",
          "- The daily convention is D4 (session_date label; knowable after the "
          "session). There is no 09:15 timestamp for daily bars.",
          "- Upstox is the only vendor: there is no NSE HTTP connector, because NSE "
          "data arrives via Upstox."]
    return "\n".join(L) + "\n"
