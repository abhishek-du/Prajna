"""Stage 3 acceptance gate: criteria A-O from the REAL database (+ test suite),
and the readiness LEVELS, each stated separately:

  IMPLEMENTED          the code, schema and registry exist
  TESTED               K: the full test suite passes
  DRY-RUN READY        A-L PASS: correct, point-in-time and locked, computed on real data
  PRODUCTION READY     + M (Stage 1 COMPLETE, Stage 2 PASS) and N (decisions approved)
  PRODUCTION UNLOCKED  + PRAJNA_STAGE3_ENABLED and the kill switch released
  BACKFILL EXECUTED    a committed Stage 3 BACKFILL run exists (reported; decision
                       BACKFILL-DEFER keeps it out of the COMPLETE rule)

Stage 3 is COMPLETE only at PRODUCTION UNLOCKED with production evidence (O).
Compiling code or passing tests never makes it COMPLETE.

Read-only: dry-run computations run inside a transaction that is rolled back,
and nothing here takes a lock, a token or writes a feature value.
"""

from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import json
import pathlib
import subprocess
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.core.clock import now
from app.core.config import get_settings
from app.features import engine as E
from app.features import inputs as I
from app.features import locks
from app.features import registry as R
from app.features import snapshots as SN
from app.features.compute import REASONS
from app.features.decisions import DECISIONS

PASS, FAIL, PENDING, BLOCKED, NOT_RUN = "PASS", "FAIL", "PENDING", "BLOCKED", "NOT_RUN"
FEATURES_DIR = pathlib.Path(__file__).resolve().parents[1] / "features"
FORBIDDEN_IMPORTS = ("app.vendor", "httpx", "requests", "aiohttp", "websockets", "socket")
SAMPLE = 20
LEVELS = ("IMPLEMENTED", "TESTED", "DRY-RUN READY", "PRODUCTION READY", "PRODUCTION UNLOCKED",
          "BACKFILL EXECUTED")


def run_tests() -> dict[str, Any]:
    """The full suite (Stage 1 + 2 + 3), test database only."""
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:randomly"],
                       capture_output=True, text=True, timeout=3600)
    tail = [ln for ln in p.stdout.splitlines() if " passed" in ln or " failed" in ln]
    return {"exit": p.returncode, "summary": tail[-1] if tail else p.stdout[-300:]}


def _c(cid: str, question: str, status: str, evidence: Any, notes: str = "") -> dict:
    return {"id": cid, "question": question, "status": status, "evidence": evidence,
            "notes": notes}


def _imports() -> list[tuple[str, str]]:
    out = []
    for p in sorted(FEATURES_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.Import):
                out += [(p.name, a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                out.append((p.name, node.module))
    return out


async def _sample(s: AsyncSession, day: _dt.date, n: int) -> list[str]:
    """n canonical stocks chosen by a hash of the session date (a new sample each
    session, reproducible for that session), plus up to 3 with a corporate action
    that went ex in the 120 days up to it (the price-basis path)."""
    salt = hashlib.sha256(str(day).encode()).hexdigest()[:8]
    keys = list((await s.execute(text("""select instrument_key from canon_instrument
        where included and lifecycle_status = 'ACTIVE' and segment = 'NSE_EQ'
        order by md5(instrument_key || :salt) limit :n"""), {"salt": salt, "n": n})).scalars())
    # the most recent actions: their bars are the likeliest to still need adjusting
    ca = list((await s.execute(text("""select instrument_key from (
        select f.instrument_key, max(f.ex_date) as ex from ca_factor f
        join canon_instrument ci on ci.instrument_key = f.instrument_key and ci.included
        where f.status = 'EXACT' and f.ex_date between :a and :b group by 1) x
        order by ex desc, instrument_key limit 3"""),
        {"a": day - _dt.timedelta(days=120), "b": day})).scalars())
    return list(dict.fromkeys(keys + ca))


async def _latest_session(s: AsyncSession) -> _dt.date:
    """The latest trading session whose PRE_OPEN instant has passed."""
    at = now()
    for d in (await s.execute(text("""select session_date from trading_session
        where is_trading_day and session_date <= :d order by 1 desc limit 10"""),
        {"d": at.date()})).scalars():
        try:
            if (await SN.resolve(s, d, "PRE_OPEN")).as_of < at:
                return d
        except SN.NoSnapshot:
            if (await SN.resolve(s, d, "PRE_SESSION")).as_of < at:
                return d
    raise RuntimeError("no trading session with a passed snapshot in the calendar")


async def evaluate(s: AsyncSession, tests: dict | None) -> dict[str, Any]:
    out: list[dict] = []
    st = get_settings()
    reg = R.summary()

    # A. registry covers the diagram
    bad = [d["item"] for d in R.DIAGRAM
           if (R.diagram_status(d) in ("UNSUPPORTED", "UNKNOWN") and not d.get("reason"))
           or (R.diagram_status(d) == "PARTIAL" and not d.get("partial"))]
    unknown_ids = [f for d in R.DIAGRAM for f in d["features"] if f not in R.BY_ID]
    groups = {d["group"] for d in R.DIAGRAM}
    out.append(_c("A", "Every item of the Stage 3 diagram is registered (IMPLEMENTED / PARTIAL / "
                  "UNSUPPORTED / UNKNOWN, with the reason)",
                  PASS if not bad and not unknown_ids and len(groups) == 6 else FAIL,
                  {**reg, "unexplained": bad, "unknown_feature_ids": unknown_ids}))

    day = await _latest_session(s)
    keys = await _sample(s, day, SAMPLE)
    snaps = {}
    for k in SN.SNAPSHOTS:
        try:
            snaps[k] = await SN.resolve(s, day, k)
        except SN.NoSnapshot:
            pass

    # L. dry-run on real data (read-only) - computed first, reused below
    runs: dict[str, E.SnapshotResult] = {}
    errors: dict[str, str] = {}
    for k, sn in snaps.items():
        try:
            runs[k] = await E.compute_snapshot(s, sn, keys)
        except Exception as e:                           # recorded, never hidden
            errors[k] = f"{type(e).__name__}: {e}"[:300]
    await s.rollback()

    # B. determinism: a recompute is identical
    probe = keys[:5]
    det = {}
    for k, sn in snaps.items():
        a = await E.compute_snapshot(s, sn, probe, with_context=False, with_sector=False)
        b = await E.compute_snapshot(s, sn, probe, with_context=False, with_sector=False)
        det[k] = [(r.instrument_key, r.feature_id, r.value, r.reason, r.inputs_sha256)
                  for r in a.rows] == [(r.instrument_key, r.feature_id, r.value, r.reason,
                                        r.inputs_sha256) for r in b.rows]
    await s.rollback()
    out.append(_c("B", "Determinism: recomputing a snapshot gives identical values, reasons "
                  "and input hashes", PASS if det and all(det.values()) else FAIL,
                  {"instruments": probe, "identical": det}))

    # C. point in time: every input (dry-run + stored) knowable strictly before as_of
    viol = sum(1 for res in runs.values() for r in res.rows
               if r.input_max_knowable_at is not None
               and r.input_max_knowable_at >= res.snapshot.as_of)
    stored_viol = (await s.execute(text("""select count(*) from feature_value
        where input_max_knowable_at >= as_of"""))).scalar()
    out.append(_c("C", "Point in time: every input of every value was knowable strictly before "
                  "the snapshot instant", PASS if runs and viol == 0 and stored_viol == 0
                  else FAIL, {"dry_run_rows": sum(len(r.rows) for r in runs.values()),
                              "violations": viol, "stored_violations": stored_viol,
                              "db_check": "ck_feature_pit"}))

    # D. look-ahead probe on real data: a PAST session, with later data present
    past = (await s.execute(text("""select session_date from trading_session
        where is_trading_day and session_date < :d order by 1 desc offset 4 limit 1"""),
        {"d": day})).scalar()
    psnap = await SN.resolve(s, past, "PRE_SESSION")
    later = 0
    used_after = 0
    for k in probe:
        inp = await I.instrument_inputs(s, k, psnap)
        used_after += sum(1 for b in inp.daily if b.day >= past)
        later += sum(1 for r in await pit.bars(s, k, "1d", now()) if r["market_date"] >= past)
    await s.rollback()
    out.append(_c("D", "Look-ahead probe: a past snapshot uses no bar of its own session or "
                  "later although such bars now exist", PASS if later > 0 and used_after == 0
                  else (PENDING if later == 0 else FAIL),
                  {"session": str(past), "as_of": psnap.as_of.isoformat(),
                   "bars_now_in_db_at_or_after_session": later, "used": used_after},
                  "plus tests: TestPointInTime (injected facts at as_of change nothing)"))

    # E. corporate actions / price basis
    adj = refused = 0
    for k in keys:
        a = await pit.bars_adjusted(s, k, "1d", snaps.get("PRE_SESSION", psnap).as_of,
                                    start=day - _dt.timedelta(days=I.DAILY_LOOKBACK_DAYS))
        adj += sum(1 for r in a["rows"] if r["adjustment_status"] == "ADJUSTED")
        refused += sum(a["refused"].values())
    await s.rollback()
    ref_runs = {k: dict(r.refused_bars) for k, r in runs.items()}
    out.append(_c("E", "Corporate actions and price basis: bars come from pit.bars_adjusted "
                  "(factors knowable at as_of); LOW-confidence and RECONSTRUCTED bars are "
                  "refused and never used",
                  PASS if runs and adj > 0 else (PENDING if runs else FAIL),
                  {"adjusted_bars_in_sample": adj, "refused_bars_in_sample": refused,
                   "refused_by_snapshot": ref_runs,
                   "rule": "PASS needs >= 1 bar adjusted by a knowable action in the sample"},
                  "plus tests: TestPriceBasis (bonus adjusted; action not yet knowable not "
                  "applied; LOW refused)"))

    # F. missing data carries a reason
    rows = [x for res in runs.values() for x in res.rows]
    bad_rows = [r for r in rows if (r.value is None) == (r.reason is None)
                or (r.reason is not None and r.reason not in REASONS)]
    out.append(_c("F", "Missing data is a null with a reason; nothing is filled",
                  PASS if rows and not bad_rows else FAIL,
                  {k: r.stats()["nulls_by_reason"] for k, r in runs.items()}
                  | {"contract_violations": len(bad_rows)}))

    # G. idempotency
    dup = (await s.execute(text("""select count(*) from (select 1 from feature_value
        group by instrument_key, session_date, snapshot, feature_id, feature_version
        having count(*) > 1) x"""))).scalar()
    test_ok = tests is not None and tests.get("exit") == 0
    out.append(_c("G", "Idempotency: a rerun inserts nothing; a disagreeing recompute fails the "
                  "run instead of overwriting", PASS if dup == 0 and test_ok
                  else (NOT_RUN if tests is None else FAIL),
                  {"duplicate_keys_stored": dup, "constraint": "uq_feature_value",
                   "tests": "TestRun (idempotent, determinism mismatch, restart)"}))

    # H / I. execution locks
    run_lock = await locks.check(s, mode="RUN", token=None)
    bf_lock = await locks.check(s, mode="BACKFILL", token=None)
    await s.rollback()
    eng = pathlib.Path(E.__file__).read_text()
    h_ok = (not run_lock.ok and "await locks.require(" in eng
            and "write_token" in run_lock.summary()["failing"])
    out.append(_c("H", "Execution lock: a production write is refused unless every condition "
                  "holds (checked in the engine itself, audited)", PASS if h_ok and
                  (tests is None or test_ok) else FAIL,
                  {"run_lock_now": run_lock.conditions},
                  "tests: TestLocks (each condition alone refuses; defaults refuse)"))
    bf = next((c for c in bf_lock.conditions if c["name"] == "backfill_enabled"), None)
    i_ok = bf is not None and bf["ok"] == bool(st.PRAJNA_STAGE3_BACKFILL_ENABLED)
    out.append(_c("I", "Backfill lock: a feature backfill additionally needs "
                  "PRAJNA_STAGE3_BACKFILL_ENABLED; Stage 3 never starts the Stage 1 backfill",
                  PASS if i_ok else FAIL, {"backfill_enabled": bf,
                                           "backfill_lock_now": bf_lock.summary()}))

    # J. no vendor / fetch path
    imps = _imports()
    bad_imp = [(f, m) for f, m in imps if any(m == x or m.startswith(x + ".")
                                              for x in FORBIDDEN_IMPORTS)]
    ingest = sorted({m for _, m in imps if m.startswith("app.ingest")})
    out.append(_c("J", "No vendor call: app.features imports no vendor, network or fetch module",
                  PASS if not bad_imp and set(ingest) <= {"app.ingest.runner"} else FAIL,
                  {"forbidden": bad_imp, "from_app_ingest": ingest}))

    # K. tests
    out.append(_c("K", "The full test suite passes (Stage 1 + 2 + 3)",
                  NOT_RUN if tests is None else (PASS if test_ok else FAIL), tests or {},
                  "run with --run-tests"))

    # L. dry run
    out.append(_c("L", "Dry-run on real data: a sample of instruments at both snapshots of the "
                  "latest session computes", PASS if runs and not errors
                  and all(r.stats()["values"] > 0 for r in runs.values()) else FAIL,
                  {"session": str(day), "instruments": keys, "errors": errors,
                   **{k: {**r.stats(), "as_of": r.snapshot.as_of.isoformat()}
                      for k, r in runs.items()}}))

    # M. prerequisites
    ok1, d1 = await locks.stage1_status(s)
    await s.rollback()
    ok2, d2 = locks.stage2_status()
    out.append(_c("M", "Prerequisites: Stage 1 COMPLETE (evaluated now) and Stage 2 PASS",
                  PASS if ok1 and ok2 else BLOCKED, {"stage1": d1, "stage2": d2}))

    # N. decisions
    pend = {k: v["decision"] for k, v in DECISIONS.items() if v["status"] != "APPROVED"}
    out.append(_c("N", "Every Stage 3 decision is approved", PASS if not pend else PENDING,
                  {"pending": pend, "all": {k: v["status"] for k, v in DECISIONS.items()}}))

    # O. production evidence
    prod = (await s.execute(text("""select count(*) filter (where status = 'COMPLETE'),
        count(*) filter (where status = 'COMPLETE' and request_params->>'mode' = 'BACKFILL'),
        count(*) filter (where status = 'FAILED')
        from ingest_run where source = 'PRAJNA_STAGE3' and mode = 'COMMIT'"""))).one()
    stored = (await s.execute(text("select count(*), max(session_date) from feature_value"))).one()
    out.append(_c("O", "Production evidence: at least one committed snapshot of features",
                  PASS if prod[0] > 0 and stored[0] > 0 else PENDING,
                  {"complete_runs": prod[0], "backfill_runs": prod[1], "failed_runs": prod[2],
                   "stored_values": stored[0], "latest_session": stored[1]},
                  "stays PENDING while production execution is locked"))

    st_ = {c["id"]: c["status"] for c in out}
    dry = all(st_[x] == PASS for x in "ABCDEFGHIJKL")
    ready = dry and st_["M"] == PASS and st_["N"] == PASS
    unlocked = ready and st.PRAJNA_STAGE3_ENABLED and not locks.kill_switch_engaged()
    levels = [
        {"level": "IMPLEMENTED", "reached": True,
         "detail": f"{reg['implemented']} features, {reg['diagram_items']} diagram items"},
        {"level": "TESTED", "reached": st_["K"] == PASS, "detail": f"K {st_['K']}"},
        {"level": "DRY-RUN READY", "reached": dry,
         "detail": ", ".join(f"{x} {st_[x]}" for x in "ABCDEFGHIJKL"
                             if st_[x] != PASS) or "A-L PASS"},
        {"level": "PRODUCTION READY", "reached": ready, "detail": f"M {st_['M']}, N {st_['N']}"},
        {"level": "PRODUCTION UNLOCKED", "reached": unlocked,
         "detail": f"PRAJNA_STAGE3_ENABLED={st.PRAJNA_STAGE3_ENABLED}, kill switch "
                   f"{'engaged' if locks.kill_switch_engaged() else 'off'}"},
        {"level": "BACKFILL EXECUTED", "reached": prod[1] > 0,
         "detail": f"{prod[1]} committed backfill runs (feature backfill deferred)"},
    ]
    complete = unlocked and st_["O"] == PASS
    top = [lv["level"] for lv in levels if lv["reached"] and lv["level"] != "BACKFILL EXECUTED"]
    return {
        "generated_at": now().isoformat(), "criteria": out, "levels": levels,
        "overall": "COMPLETE" if complete else f"NOT COMPLETE ({top[-1]})",
        "failing": [c["id"] for c in out if c["status"] == FAIL],
        "blocked": [c["id"] for c in out if c["status"] in (BLOCKED, PENDING, NOT_RUN)],
        "registry_sha256": R.REGISTRY_SHA256,
    }


def to_markdown(rep: dict) -> str:
    L = ["# Stage 3 acceptance (feature engineering)", "",
         f"**Generated:** {rep['generated_at']} by `prajna acceptance stage3` (read-only; "
         "regenerate, do not edit).", "",
         f"## Overall: **{rep['overall']}**", "",
         "Stage 3 is COMPLETE only when production execution is unlocked AND there is "
         "production evidence (O). Passing tests or a dry-run never makes it COMPLETE.", "",
         "## Levels", "", "| Level | Reached | Detail |", "|---|---|---|"]
    L += [f"| {lv['level']} | **{'YES' if lv['reached'] else 'no'}** | {lv['detail']} |"
          for lv in rep["levels"]]
    L += ["", "## Criteria", "", "| # | Question | Status | Evidence | Notes |",
          "|---|---|---|---|---|"]
    for c in rep["criteria"]:
        ev = json.dumps(c["evidence"], default=str).replace("|", "\\|")[:900]
        L.append(f"| {c['id']} | {c['question']} | **{c['status']}** | {ev} | {c['notes']} |")
    L += ["", f"Registry: `{rep['registry_sha256']}`", "",
          "## What unlocks production", "",
          "1. Stage 1 COMPLETE, evaluated fresh at execution time (criterion M).",
          "2. Stage 2 report PASS, at most 7 days old, with its tests (M).",
          "3. The user approves decision FEATURE-PARAMS: the PROPOSED indicator windows "
          "(N; see `prajna stage3 registry`).",
          "4. `PRAJNA_STAGE3_ENABLED=true`, the kill switch released, and a write token. "
          "A feature backfill additionally needs `PRAJNA_STAGE3_BACKFILL_ENABLED=true`.",
          "", "Until then `prajna stage3 run --commit` and `prajna stage3 backfill --commit` "
          "are refused, and the refusal is recorded in `stage3_event`."]
    return "\n".join(L) + "\n"
