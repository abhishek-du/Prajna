"""Stage 1 final acceptance gate: criteria A-Y computed from the REAL database.

READ-ONLY. Every status is derived from rows, runs, archives and the decision
register below; nothing is asserted from memory. Statuses:

  PASS                  the criterion holds on the current data
  FAIL                  it does not (data missing, incomplete, or wrong)
  BLOCKED               it cannot pass until a named human decision is taken
  OUT_OF_SCOPE          excluded by an APPROVED decision (the register names it)
  DEFERRED              postponed by an APPROVED decision (e.g. BACKFILL-DEFER)
  WAITING_FOR_EVIDENCE  the evidence can only come from a future session/refresh

Overall = COMPLETE only if every criterion is PASS, approved OUT_OF_SCOPE or
approved DEFERRED (WAITING_FOR_EVIDENCE, FAIL and BLOCKED are never settled).
LIVE_READY = nothing FAIL or BLOCKED.

DECISION REGISTER. A decision is APPROVED only with a dated reference to the
user's approval; everything else is PENDING and blocks what depends on it.
"""

from __future__ import annotations

import datetime as _dt
import glob
import json
import pathlib
import random
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts import timing as T
from app.core.clock import IST, now
from app.core.config import BACKEND_ROOT

# Every file the gate reads is anchored to the backend directory, never to the
# process's working directory: run from the repository root, the relative
# "var/..." paths found no pre-open report, close log or B1/B2 file and the gate
# reported NOT COMPLETE (BUG-STAGE1-CLI-CWD-RELATIVE-PATHS, 2026-09-28).
ACCEPTANCE_DIR = pathlib.Path("var/acceptance")
DAILY_LOG_DIR = pathlib.Path("var/logs/daily")


def anchored(path: str | pathlib.Path) -> pathlib.Path:
    """A relative path is relative to the backend directory (BACKEND_ROOT)."""
    p = pathlib.Path(path)
    return p if p.is_absolute() else BACKEND_ROOT / p


def shown(path: pathlib.Path) -> str:
    """The path as evidence has always shown it: relative to the backend directory."""
    try:
        return str(path.relative_to(BACKEND_ROOT))
    except ValueError:
        return str(path)


def preopen_report() -> tuple[str, dict[str, Any]]:
    """Criterion K's file evidence: the latest pre-open acceptance report."""
    reps = sorted(glob.glob(str(anchored(ACCEPTANCE_DIR) / "preopen_*.json")))
    if not reps:
        return FAIL, {}
    rep = json.loads(pathlib.Path(reps[-1]).read_text())
    ev = {"report": shown(pathlib.Path(reps[-1])), "verdict": rep["verdict"],
          "real_market_data": rep["real_market_data"],
          "non_pass": {c["id"]: c["status"] for c in rep["checks"] if c["status"] != "PASS"},
          "B7": rep["B7"]["status"], "B8": rep["B8"]["status"]}
    return (PASS if rep["verdict"] == "PASS" and rep["real_market_data"] else FAIL), ev


def rerun_checks() -> list[str]:
    """Criterion R's file evidence: every CLOSE_RERUN_CHECK line of the close logs."""
    out = []
    for f in sorted(anchored(DAILY_LOG_DIR).glob("close_then_backfill_*.log")):
        for line in f.read_text(errors="replace").splitlines():
            if "CLOSE_RERUN_CHECK" in line and "inserted=" in line:
                out.append(line.split("] ", 1)[-1])
    return out


def load_b1b2() -> dict[str, Any]:
    """Criterion X's timing evidence (ops/measure/analyze_timing.py output)."""
    bp = anchored(ACCEPTANCE_DIR / "b1b2.json")
    return json.loads(bp.read_text()) if bp.exists() else {}

PASS, FAIL, BLOCKED, OUT = "PASS", "FAIL", "BLOCKED", "OUT_OF_SCOPE"
# hardening: evidence that can only come from future sessions/refreshes, and
# criteria deferred by an explicit scope decision; neither is ever PASS
WAITING, DEFERRED = "WAITING_FOR_EVIDENCE", "DEFERRED"

DECISIONS: dict[str, dict[str, str]] = {
    "D1": {"status": "APPROVED", "decision": "1D from 2020-01-01; 1h and 15m from 2022-01; "
           "1m for the last 6 months", "ref": "M4.5 plan approved 2026-09-23 (M4_DECISIONS)"},
    "D2": {"status": "APPROVED", "decision": "vendor-fetched 15m/1h (and 1m)",
           "ref": "M4.5 plan approved 2026-09-23"},
    "D2-5m": {"status": "APPROVED", "decision": "5m is EXCLUDED from Stage 1 (it is exactly "
              "the aggregation of 1m, measured 428/428); later-stage scope",
              "ref": "user 2026-09-24 (D2-5m = B)"},
    "D3": {"status": "IN_FORCE", "decision": "the first observation of a bar is immutable; a "
           "later different vendor value is classified (contracts.revision) and, when "
           "explained (CA_ADJUSTMENT / ROUNDING / SETTLEMENT / GLOBAL_REVISION), recorded in "
           "ohlcv_observation; an UNEXPLAINED change still FAILS",
           "ref": "M1/M4 contracts; refined by PRICE-BASIS (hardening phase 6, 2026-09-25)"},
    "D5": {"status": "APPROVED", "decision": "all-day LTP/depth persistence stays in Stage 7; "
           "recorder capability kept; pre-open persisted", "ref": "user 2026-09-24 (D5 confirmed)"},
    "S1": {"status": "IN_FORCE", "decision": "universe = NSE_EQ series EQ/BE/SM/BZ/ST/IV "
           "(REIT RR, D1/E1/IT/SZ/W1 excluded)", "ref": "M1; not changed"},
    "S2": {"status": "APPROVED", "decision": "FII/DII, corporate actions, news, fundamentals, "
           "global (where Upstox has it) are in Stage 1",
           "ref": "user 2026-09-23 (FII/DII) and Stage-1 completion mission 2026-09-24"},
    "P1": {"status": "APPROVED", "decision": "keep vendor currentTs as WebSocket knowable_at "
           "(M0 contract); consumers use fetched_at for local receipt ordering",
           "ref": "user 2026-09-24 (P1 = A)"},
    "SURV": {"status": "APPROVED", "decision": "survivorship-biased equity history accepted "
             "and documented: Upstox publishes no delisted/historical master (the "
             "'suspended' file answers 403)", "ref": "M4.5 plan approved 2026-09-23"},
    "Q1": {"status": "APPROVED", "decision": "an invalid vendor bar (negative volume; OHLC "
           "outside [low, high]; non-positive price) is QUARANTINED: never stored, raw kept, "
           "one anomaly per bar; the rest of the window is stored",
           "ref": "user 2026-09-24 (Q1 = A)"},
    "C6": {"status": "APPROVED", "decision": "pre-open completeness counts instruments with "
           "pre-open activity (an IEP at any point) as the denominator; instruments that "
           "never had an IEP are recorded as 'no pre-open activity', never fabricated",
           "ref": "user 2026-09-24 (C6 accepted)"},
    "KN-CA": {"status": "APPROVED", "decision": "corporate actions: knowable_at = end of the "
              "announcement date in IST (23:59:59.999, unverified), never later than fetched_at",
              "ref": "user 2026-09-24 (KN-CA = B)"},
    "CAL-FIX": {"status": "APPROVED", "decision": "delete the 1,096 calendar rows 2020-2022 "
                "written by the superseded timings rule and re-ingest with the NIFTY-50 rule",
                "ref": "user 2026-09-24"},
    "PRICE-BASIS": {"status": "APPROVED", "decision": "Option B: raw observed prices are the "
                    "canonical basis (ohlcv_payload_basis); our own corporate-action factors "
                    "(ca_factor) derive PIT-adjusted views; vendor-adjusted history is never "
                    "passed off as raw", "ref": "user 2026-09-25 (hardening decisions 2-4)"},
    "SECCLASS": {"status": "APPROVED", "decision": "sector coverage (D) is measured over "
                 "STOCK instruments only (instrument_security_class, >= 2 agreeing signals)",
                 "ref": "user 2026-09-25 (hardening decision 1)"},
    "LIFECYCLE": {"status": "APPROVED", "decision": "completeness gates use the ACTIVE "
                  "universe (daily master refresh; REMOVED_FROM_MASTER / INELIGIBLE / "
                  "VENDOR_REJECTED kept, not counted)", "ref": "user 2026-09-25 (decision 7)"},
    "GLOBAL-FINALITY": {"status": "APPROVED", "decision": "global bars are exposed only once "
                        "final (confirmed re-observation or history); revisions and "
                        "placeholders withheld; Q per-instrument contract",
                        "ref": "user 2026-09-25 (decisions 6-8)"},
    "BACKFILL-DEFER": {"status": "APPROVED", "decision": "the historical intraday backfill "
                       "(1m 6 months, 15m/1h from 2022; ~293k requests) is DEFERRED for "
                       "Stage 1 (live readiness); capability kept, cron entries disabled; it "
                       "belongs to Stage 3 preparation",
                       "ref": "user 2026-09-25 (hardening decision 1 / directive 10)"},
    "TIMING-B2": {"status": "APPROVED", "decision": "B2 REVISED. Original: '1m bars never "
                  "change once listed'. Finding 2026-09-25: 90/1,125 NSE_INDEX|Nifty 50 1m bars "
                  "revised, latest 95.6 s after the bar end (RELIANCE, HDFCBANK: none); 15m <= "
                  "110.9 s, 1h <= 111.0 s; 5m (out of scope) 145.9 s. New: a candle is "
                  "timing-final from bar_end + completion_margin(timeframe) (1m/15m/1h 120 s; "
                  "an engineering threshold chosen from observation, configurable, monitored, "
                  "NOT a vendor SLA). A revision at/after the margin is a LATE_REVISION: "
                  "recorded, X BLOCKED, explicit contract review; the margin is never enlarged "
                  "silently. Timing finality never changes knowable_at (the fetch time)",
                  "ref": "user 2026-09-25 (master directive: B2/X contract change)"},
    "D-NEW-LISTING-GRACE": {"status": "APPROVED", "decision": "A NEW listing (first seen "
                            "within 7 days) in REVIEW only because the vendor has no "
                            "financials yet (ISIN says company, no other signal contradicts) "
                            "is in the same 7-day grace as an UNCLASSIFIED new listing; any "
                            "other REVIEW still fails D, and so does this one after 7 days",
                            "ref": "user 2026-10-08 ('Yes, extend the grace')"},
    "TIMING-REVIEW": {"status": "APPROVED", "decision": "Contract review after B2 was "
                      "CONTRADICTED: 23 late revisions, all NSE_INDEX|Nifty 50, on 4 of 9 "
                      "sessions (2026-09-29..10-07), up to 200.4 s (1m) / 146.1 s (15m, 1h) "
                      "after the bar end vs the 120 s margin; RELIANCE / HDFCBANK none. "
                      "Margin 1m/15m/1h 120 s -> 300 s (1.5x the observed maximum), effective "
                      "2026-10-08 18:30 IST; a fetch is judged by the margin in force at its "
                      "time; still an engineering threshold, monitored - a revision after "
                      "300 s blocks X again. knowable_at stays the fetch time",
                      "ref": "user 2026-10-08 ('Margin 300 s')"},
    "LOGIN": {"status": "APPROVED", "decision": "one automated Upstox TOTP login per day by the "
              "ops runbooks, until revoked", "ref": "user 2026-09-24"},
}

PROV_TABLES = ("ohlcv_bar", "macro_observation", "news_article", "news_instrument",
               "corporate_action", "fundamental_snapshot", "instrument", "trading_session",
               "preopen_tick", "preopen_session_status",
               "instrument_universe_membership")
# preopen_book rows inherit provenance from their preopen_tick (tick_id): checked
# as orphans instead.


@dataclass(slots=True)
class Criterion:
    id: str
    name: str
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)
    db_state: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    decisions: list[str] = field(default_factory=list)


async def review_in_new_listing_grace(s: AsyncSession, grace: _dt.date) -> int:
    """ACTIVE NSE_EQ instruments in REVIEW that are NEW listings (first seen on or after
    `grace`) whose ONLY disagreement is that the vendor has no financials yet: the ISIN
    says company and no other signal contradicts it (decision D-NEW-LISTING-GRACE)."""
    return (await s.execute(text("""select count(*) from instrument i
        join instrument_security_class c using (instrument_id)
        where i.valid_to = 'infinity' and i.lifecycle_status = 'ACTIVE'
          and i.segment = 'NSE_EQ' and c.status = 'REVIEW' and i.first_seen >= :grace
          and c.signals -> 'financials' ->> 'vote' = 'NO_FINANCIALS'
          and c.signals -> 'isin' ->> 'vote' = 'COMPANY'
          and coalesce(c.signals -> 'series' ->> 'vote', 'COMPANY') = 'COMPANY'
          and coalesce(c.signals -> 'suffix' ->> 'vote', 'COMPANY') = 'COMPANY'
          and coalesce(c.signals -> 'name' ->> 'vote', 'COMPANY') = 'COMPANY'"""),
        {"grace": grace})).scalar()


async def _one(s: AsyncSession, sql: str, **kw) -> Any:
    return (await s.execute(text(sql), kw)).one()


async def _all(s: AsyncSession, sql: str, **kw) -> list:
    return list((await s.execute(text(sql), kw)).all())


def _blocked_or(status: str, *deps: str) -> tuple[str, list[str]]:
    pending = [d for d in deps if DECISIONS[d]["status"] == "PENDING"]
    return (BLOCKED if pending and status != PASS else status), pending


async def _latest_session(s) -> _dt.date:
    today = now().astimezone(IST).date()
    return (await _one(s, "select max(session_date) from trading_session where "
                          "is_trading_day and session_date < :t", t=today))[0]


async def _candle_depth(s, tf: str, since: _dt.date, last: _dt.date) -> dict[str, Any]:
    """Per NSE instrument: does its checkpoint cover [since, last - 1 session]?"""
    rows = await _all(s, """
        select i.instrument_key,
               w.last_logical_date as through,
               (r.request_params->'outcome'->'checkpoint'->>'covered_from')::date as cfrom
        from instrument i
        left join ingest_watermark w on w.source='UPSTOX_REST_V3'
             and w.stream = 'ohlcv.' || :tf || '.' || i.instrument_key
        left join ingest_run r on r.run_id = w.last_run_id
        where i.valid_to = 'infinity' and i.segment in ('NSE_EQ','NSE_INDEX')
          and i.lifecycle_status = 'ACTIVE'""", tf=tf)
    bars = dict(await _all(s, """select instrument_key, count(*) from ohlcv_bar
                                 where timeframe=:tf group by 1""", tf=tf))
    lag = _dt.timedelta(days=3)
    covered = [k for k, t, c in rows if t and c and c <= since and t >= last - lag]
    none = [k for k, t, c in rows if t is None]
    return {"instruments": len(rows), "covered_to_depth": len(covered),
            "without_checkpoint": len(none), "bars": sum(bars.values()),
            "instruments_with_bars": len(bars), "required_from": str(since),
            "required_through": str(last), "sample_missing": sorted(none)[:5]}


def x_decision(violations: dict[str, int], timing: dict[str, dict]) -> tuple[str, list[str]]:
    """Criterion X: any look-ahead violation FAILs; a CONTRADICTED B1/B2 is BLOCKED
    (it cannot verify by waiting: it needs a decision); PASS needs B1 and the
    revised B2 VERIFIED; otherwise WAITING. Only B1 and B2 decide: B2_original is
    the contract superseded by decision TIMING-B2, kept in the evidence for the
    record and never re-evaluated."""
    contradicted = [k for k in ("B1", "B2") if timing[k]["status"] == "CONTRADICTED"]
    if any(violations.values()):
        return FAIL, contradicted
    if contradicted:
        return BLOCKED, contradicted
    return (PASS if all(timing[k]["status"] == "VERIFIED" for k in ("B1", "B2"))
            else WAITING), contradicted


async def evaluate(s: AsyncSession) -> dict[str, Any]:
    today = now().astimezone(IST).date()
    last = await _latest_session(s)
    out: list[Criterion] = []

    # A. isolation
    db = (await _one(s, "select current_database()"))[0]
    out.append(Criterion("A", "Database isolation", PASS if db == "prajna" else FAIL,
                         {"current_database": db, "v1_database": "autotrade_pro (never used)"}))

    # B. provenance, per table
    prov: dict[str, Any] = {}
    bad_total = 0
    for t in PROV_TABLES:
        # table names come from the PROV_TABLES constant, never from input
        r = await _one(s, f"""
            select count(*),
              count(*) filter (where r.run_id is null or r.status <> 'COMPLETE'
                               or r.mode <> 'COMMIT'),
              count(*) filter (where p.payload_sha256 is null),
              count(*) filter (where x.knowable_at_basis is null or x.knowable_at_basis = '')
            from {t} x left join ingest_run r on r.run_id = x.run_id
            left join raw_payload p on p.payload_sha256 = x.payload_sha256""")
        prov[t] = {"rows": r[0], "bad_run": r[1], "no_payload": r[2], "no_basis": r[3]}
        bad_total += r[1] + r[2] + r[3]
    orphans = (await _one(s, """select count(*) from preopen_book b where not exists
                                (select 1 from preopen_tick t where t.tick_id = b.tick_id)"""))[0]
    prov["preopen_book"] = {"orphans": orphans}
    bad_total += orphans
    out.append(Criterion("B", "Provenance", PASS if bad_total == 0 else FAIL,
                         {"violations": bad_total}, prov))

    # C. point-in-time: knowable_at <= fetched_at everywhere
    pit = {t: (await _one(s, f"select count(*) from {t} "
                             "where knowable_at > fetched_at"))[0]
           for t in PROV_TABLES}
    out.append(Criterion("C", "Point-in-time safety (knowable_at <= fetched_at)",
                         PASS if not any(pit.values()) else FAIL, {"violations": pit}))

    # D. instrument master + sector coverage of STOCKS (hardening phase 3).
    # Old rule: sector >= 90 % of ALL current NSE_EQ (fund units and rights
    # entitlements, which have no sector by nature, were in the denominator).
    # New rule: sector >= 90 % of ACTIVE NSE_EQ instruments classified STOCK
    # (instrument_security_class, >= 2 agreeing signals); REVIEW must be 0 and
    # UNCLASSIFIED only within a 7-day grace for new listings.
    inst = await _one(s, """select
        count(*) filter (where segment='NSE_EQ'), count(*) filter (where segment='NSE_INDEX'),
        count(*) filter (where segment like 'GLOBAL%'),
        count(*) filter (where segment='NSE_EQ' and (isin is null or trading_symbol is null))
        from instrument where valid_to='infinity' and lifecycle_status='ACTIVE'""")
    cls = await _all(s, """select coalesce(c.security_class, '-'), coalesce(c.subclass, '-'),
            coalesce(c.status, 'MISSING'), count(*),
            count(*) filter (where c.status = 'UNCLASSIFIED' and i.first_seen < :grace),
            count(*) filter (where c.security_class = 'STOCK' and p.sector is not null)
        from instrument i
        left join instrument_security_class c using (instrument_id)
        left join lateral (select nullif(f.payload->>'sector', '') sector
            from fundamental_snapshot f where f.instrument_key = i.instrument_key
              and f.statement_type = 'profile' order by f.knowable_at desc limit 1) p on true
        where i.valid_to = 'infinity' and i.lifecycle_status = 'ACTIVE' and i.segment = 'NSE_EQ'
        group by 1, 2, 3 order by 1, 2, 3""", grace=today - _dt.timedelta(days=7))
    breakdown = {f"{c}/{sub}/{st}": n for c, sub, st, n, _, _ in cls}
    stocks = sum(n for c, _, st, n, _, _ in cls if c == "STOCK" and st == "CLASSIFIED")
    with_sector = sum(ws for *_, ws in cls)
    review_total = sum(n for _, _, st, n, _, _ in cls if st == "REVIEW")
    # decision D-NEW-LISTING-GRACE: such a listing is in the 7-day grace like an
    # UNCLASSIFIED one; every other REVIEW still fails D, and so does this one after 7 days
    review_graced = await review_in_new_listing_grace(s, today - _dt.timedelta(days=7))
    review = review_total - review_graced
    unclassified_old = sum(old for *_, old, _ in cls)
    missing = sum(n for _, _, st, n, _, _ in cls if st == "MISSING")
    coverage = with_sector / stocks if stocks else 0.0
    d_ok = inst[0] > 3000 and inst[1] == 3 and inst[3] == 0 and stocks > 0 \
        and coverage >= 0.9 and review == 0 and unclassified_old == 0 and missing == 0
    out.append(Criterion("D", "Instrument master", PASS if d_ok else FAIL,
        {"sector_source": "fundamental_snapshot(profile).payload.sector",
         "classification": "instrument_security_class (prajna classify securities)",
         "listing_status": "instrument.lifecycle_status (daily master refresh, phase 2)"},
        {"active_nse_eq": inst[0], "nse_index": inst[1], "global": inst[2],
         "nse_eq_missing_isin_or_symbol": inst[3], "eligible_stock_count": stocks,
         "sector_present_count": with_sector, "sector_missing_count": stocks - with_sector,
         "coverage_percentage": round(100 * coverage, 2), "review": review,
         "review_new_listing_no_financials_in_grace": review_graced,
         "unclassified_beyond_grace": unclassified_old, "unclassified_missing_row": missing,
         "breakdown": breakdown},
        "new rule: sector >= 90 % of ACTIVE STOCK instruments (old: of all NSE_EQ); "
        "REVIEW = 0; UNCLASSIFIED only within 7 days of first_seen"))

    # E. calendar coverage 2020-01-01 .. last session + 30 days
    cal = await _one(s, """select count(*), min(session_date), max(session_date),
        count(*) filter (where is_trading_day) from trading_session""")
    span = (cal[2] - cal[1]).days + 1 if cal[1] else 0
    # Cross-source check: a past session exists iff NIFTY 50 has a daily bar.
    xs = await _one(s, """select
        count(*) filter (where t.is_trading_day and b.session_date is null),
        count(*) filter (where not t.is_trading_day and b.session_date is not null)
        from trading_session t left join ohlcv_bar b on b.session_date = t.session_date
          and b.instrument_key = 'NSE_INDEX|Nifty 50' and b.timeframe = '1d'
        where t.session_date < :last and t.session_date >= (select min(session_date)
          from ohlcv_bar where instrument_key='NSE_INDEX|Nifty 50' and timeframe='1d')""",
                    last=last)
    e_ok = cal[1] is not None and cal[1] <= _dt.date(2020, 1, 1) and cal[0] == span \
        and cal[2] >= today + _dt.timedelta(days=30) and xs[0] == 0 and xs[1] == 0
    out.append(Criterion("E", "Trading calendar", PASS if e_ok else FAIL,
                         {"trading_day_without_nifty_bar": xs[0],
                          "non_trading_day_with_nifty_bar": xs[1]},
                         {"rows": cal[0], "from": str(cal[1]), "to": str(cal[2]),
                          "contiguous": cal[0] == span, "trading_days": cal[3]},
                         "required: every date 2020-01-01 .. today+30, and agreement with "
                         "the NIFTY 50 daily bars for past dates"))

    # F-J. candle depth per timeframe (D1)
    six_months = today - _dt.timedelta(days=183)
    depth = {"1d": _dt.date(2020, 1, 1), "1m": six_months, "15m": _dt.date(2022, 1, 3),
             "1h": _dt.date(2022, 1, 3)}
    dd = {tf: await _candle_depth(s, tf, since, last) for tf, since in depth.items()}
    failed_1d = await _all(s, """select r.request_params->>'instrument_key', a.detail->>'reason',
            a.subject from ingest_watermark w right join (
              select distinct on (stream) stream, run_id, status, request_params from ingest_run
              where stream like 'ohlcv.1d.NSE_%' and mode='COMMIT' order by stream, started_at desc
            ) r on r.stream = w.stream
            join ingest_anomaly a on a.run_id = r.run_id and a.severity='FAIL'
            join instrument i on i.instrument_key = r.request_params->>'instrument_key'
             and i.valid_to = 'infinity' and i.lifecycle_status = 'ACTIVE'
            where r.status = 'FAILED'""")
    q1 = dict(await _all(s, """select a.detail->>'timeframe', count(*) from ingest_anomaly a
        join ingest_run r using (run_id) where a.kind = 'QUARANTINED' and r.mode = 'COMMIT'
        and r.status = 'COMPLETE' group by 1"""))
    f_status = PASS if dd["1d"]["covered_to_depth"] >= dd["1d"]["instruments"] \
        and not failed_1d else FAIL
    out.append(Criterion("F", "1D candles (from 2020-01-01)", f_status,
                         {"failed_streams": [list(x) for x in failed_1d][:10],
                          "quarantined_bars_Q1": q1.get("1d", 0)}, dd["1d"],
                         "instruments listed after 2020 are covered from their first bar; "
                         "value-insane vendor bars are quarantined (Q1), never stored"))
    for cid, tf, name in (("G", "1m", "1m candles (last 6 months)"),
                          ("I", "15m", "15m candles (from 2022-01)"),
                          ("J", "1h", "1h candles (from 2022-01)")):
        # historical DEPTH only (checkpoints reaching 2022 / 6 months); live
        # same-day completeness is criterion R. Deferred by decision BACKFILL-DEFER.
        depth_ok = dd[tf]["covered_to_depth"] >= dd[tf]["instruments"]
        st = PASS if depth_ok else (
            DEFERRED if DECISIONS["BACKFILL-DEFER"]["status"] == "APPROVED" else FAIL)
        out.append(Criterion(cid, name, st, {"quarantined_bars_Q1": q1.get(tf, 0),
                                             "measures": "historical depth only"}, dd[tf],
                             "historical backfill (D1); DEFERRED_FOR_STAGE_1 by decision "
                             "BACKFILL-DEFER (live same-day completeness: R)",
                             [] if depth_ok else ["BACKFILL-DEFER"]))
    five = (await _one(s, "select count(*) from ohlcv_bar where timeframe='5m'"))[0]
    h_status = OUT if DECISIONS["D2-5m"]["status"] == "APPROVED" else BLOCKED
    out.append(Criterion("H", "5m candles", h_status, {"decision": DECISIONS["D2-5m"]},
                         {"bars": five}, "excluded from Stage 1 by decision D2-5m",
                         [] if h_status == OUT else ["D2-5m"]))

    # K. pre-open
    k_status, k_ev = preopen_report()
    pre = await _one(s, """select count(*), count(distinct session_date), min(session_date),
                                  max(session_date) from preopen_tick""")
    missed = (await _one(s, """select count(*) from trading_session t where t.is_trading_day
        and t.session_date between :a and :b and not exists (
          select 1 from preopen_tick p where p.session_date = t.session_date)""",
                         a=pre[2] or today, b=pre[3] or today))[0]
    daily_pre = pre[1] >= 2 and missed == 0
    k_status, k_dep = _blocked_or(k_status if daily_pre else FAIL, "C6")
    out.append(Criterion("K", "Pre-open", k_status, k_ev,
                         {"ticks": pre[0], "sessions_captured": pre[1],
                          "trading_sessions_missed_since_first": missed},
                         "required: a PASS verdict (C6 is the only WARN, explained) and "
                         "recurring daily capture (>= 2 sessions, none missed)", k_dep))

    # L. live WebSocket
    ticks = (await _one(s, "select count(*) from tick_archive"))[0]
    l_status = OUT if DECISIONS["D5"]["status"] == "APPROVED" else BLOCKED
    l_dep = [] if l_status == OUT else ["D5"]
    out.append(Criterion("L", "Live WebSocket data (all-day persistence)", l_status,
                         {"recorder": "live-validated 2026-09-23/24: 2 connections, 3,527 keys, "
                                      "5-level depth; archived; pre-open persisted"},
                         {"tick_archive_rows": ticks},
                         "all-day persistence is Stage 7 per M0 unless D5 says otherwise",
                         l_dep))

    # M-O. corporate actions, news, fundamentals
    nse_isins = (await _one(s, "select count(distinct isin) from instrument where "
                               "valid_to='infinity' and segment='NSE_EQ' "
                               "and lifecycle_status='ACTIVE'"))[0]

    async def swept(stream: str, key: str) -> int:
        return (await _one(s, f"""select count(distinct x) from (
            select jsonb_array_elements_text(request_params->'{key}') x from ingest_run
            where stream=:st and mode='COMMIT' and status='COMPLETE'
              and not request_params ? 'superseded') y""",
                           st=stream))[0]
    ca = await _one(s, "select count(*), count(distinct isin), min(announcement_date), "
                       "max(announcement_date) from corporate_action")
    ca_swept = await swept("corporate_action.isin", "isins")
    m_ok = ca_swept >= nse_isins and ca[0] > 0
    out.append(Criterion("M", "Corporate actions", PASS if m_ok else FAIL,
                         {"isins_swept": ca_swept, "nse_isins": nse_isins},
                         {"events": ca[0], "isins_with_events": ca[1],
                          "announcement_range": [str(ca[2]), str(ca[3])]},
                         "vendor depth ~1 year; announcement is a date (knowable_at = fetched_at)"))
    nw = await _one(s, "select count(*), min(published_at), max(published_at), "
                       "(select count(*) from news_instrument), "
                       "(select max(finished_at) from ingest_run "
                       "where stream='news.instrument_keys' "
                       "and mode='COMMIT' and status='COMPLETE') from news_article")
    fresh = nw[4] is not None and now() - nw[4] < _dt.timedelta(hours=36)
    out.append(Criterion("N", "News", PASS if nw[0] and fresh else FAIL,
                         {"last_complete_sweep": str(nw[4])},
                         {"articles": nw[0], "links": nw[3],
                          "published_range": [str(nw[1]), str(nw[2])]},
                         "vendor keeps 7 days: must be swept at least daily"))
    fu = await _one(s, "select count(*), count(distinct instrument_key), "
                       "count(distinct statement_type) from fundamental_snapshot")
    fu_swept = await swept("fundamentals.isin", "isins")
    out.append(Criterion("O", "Fundamentals", PASS if fu_swept >= nse_isins and fu[0] else FAIL,
                         {"isins_swept": fu_swept, "nse_isins": nse_isins},
                         {"snapshots": fu[0], "instruments": fu[1], "statement_types": fu[2]}))

    # P. FII/DII
    fd = await _all(s, """select stream, last_logical_date from ingest_watermark
                          where stream like 'macro.%'""")
    prev = (await _one(s, "select max(session_date) from trading_session where is_trading_day "
                          "and session_date < :d", d=last))[0]
    p_ok = len(fd) == 6 and all(d and d >= prev for _, d in fd)
    out.append(Criterion("P", "FII/DII", PASS if p_ok else FAIL,
                         {"required_through": f">= {prev} (one session publication lag)"},
                         {"streams": {k: str(v) for k, v in fd},
                          "rows": (await _one(s, "select count(*) from macro_observation"))[0]}))

    # Q. global / macro under the finality contract (hardening phase 5).
    # Old rule: every global instrument has a bar dated >= the previous NSE
    # session - wrong both ways (foreign holidays failed it; placeholder and
    # later-revised bars passed it). New rule, per instrument, from its own
    # measured contract (global_instrument_contract):
    #   fetched   a COMPLETE fetch of the instrument finished within 36 h
    #   final     its latest CONFIRMED label is at most gap_days_p99 + 3 days
    #             old (+3: first observation D+1, re-observation >= 6 h later)
    #   clean     no REVISED / PLACEHOLDER label is exposed in canon_global_bar
    #   measured  a contract row exists
    # WAITING_FOR_EVIDENCE: fetched and clean, but the newest labels still wait
    # for their confirming re-observation (the next scheduled refresh).
    gq = await _all(s, """
        select i.instrument_key,
               c.gap_days_p99, c.weekend_label_share,
               (select max(r.finished_at) from ingest_run r
                 where r.stream = 'ohlcv.1d.' || i.instrument_key and r.status = 'COMPLETE'
                   and r.mode = 'COMMIT') as last_fetch,
               (select max(g.label_date) from canon_global_bar g
                 where g.instrument_key = i.instrument_key) as last_final,
               (select max(f.session_date) from global_bar_finality f
                 where f.instrument_key = i.instrument_key
                   and f.finality = 'UNCONFIRMED') as pending,
               (select count(*) from global_bar_finality f
                 where f.instrument_key = i.instrument_key
                   and f.finality in ('REVISED', 'PLACEHOLDER')) as withheld,
               (select count(*) from canon_global_vendor_absent v
                 where v.instrument_key = i.instrument_key) as vendor_absent
        from instrument i
        left join global_instrument_contract c on c.instrument_key = i.instrument_key
        where i.valid_to = 'infinity' and i.segment in ('GLOBAL_INDEX', 'GLOBAL_INDICATOR')
        order by 1""")
    per: dict[str, Any] = {}
    fails, waits = [], []
    at = now()
    for k, p99, wshare, last_fetch, last_final, pending, withheld, absent in gq:
        # exposed bars whose finality is REVISED / PLACEHOLDER (must be 0). Each view
        # is evaluated once per instrument (materialized): joining the two views
        # directly re-evaluated the finality view per row (> 120 s per instrument
        # once the observation history grew; the gate stalled on 2026-09-28)
        leaked = (await _one(s, """
            with f as materialized (
                   select instrument_id, bar_start_utc from global_bar_finality
                   where instrument_key = :k and finality in ('REVISED', 'PLACEHOLDER')),
                 g as materialized (
                   select instrument_id, bar_start_utc from canon_global_bar
                   where instrument_key = :k)
            select count(*) from g join f using (instrument_id, bar_start_utc)""", k=k))[0]
        fetched = last_fetch is not None and at - last_fetch <= _dt.timedelta(hours=36)
        limit = (p99 or 4) + 3
        age = (today - last_final).days if last_final else None
        final = age is not None and age <= limit
        st = PASS if (p99 is not None and fetched and final and not leaked) else FAIL
        if st == FAIL and p99 is not None and fetched and not leaked and pending:
            st = WAITING
        per[k] = {"status": st, "measured": p99 is not None, "fetched_within_36h": fetched,
                  "last_final_label": str(last_final), "final_age_days": age,
                  "limit_days": limit, "pending_unconfirmed": str(pending),
                  "withheld_revised_or_placeholder": withheld, "leaked": leaked,
                  "vendor_absent_days": absent, "weekend_label_share": str(wshare)}
        (fails if st == FAIL else waits if st == WAITING else []).append(k)
    q_status = FAIL if fails or len(per) != 13 else (WAITING if waits else PASS)
    out.append(Criterion("Q", "Global / macro", q_status,
                         {"contract": "per-instrument finality (migration 0010, "
                                      "global_instrument_contract)",
                          "failing": fails, "waiting_for_confirmation": waits,
                          "bond_yields": "VENDOR_UNAVAILABLE (no Upstox instrument)"},
                         {"per_instrument": per},
                         "new rule: fresh COMPLETE fetch + a CONFIRMED label within the "
                         "instrument's own p99 gap + 3 days + nothing revised/placeholder "
                         "exposed (old: a bar on the previous NSE session)"))

    # R. daily incremental (live): for the last trading session, every ACTIVE
    # NSE instrument had a COMPLETE intraday run for 1m, 15m and 1h (the close),
    # and the same-day rerun check inserted nothing (idempotency, CLOSE_RERUN_CHECK
    # in the close log). No rerun evidence yet -> WAITING_FOR_EVIDENCE.
    active = (await _one(s, "select count(*) from instrument where valid_to='infinity' and "
                            "segment in ('NSE_EQ','NSE_INDEX') and lifecycle_status='ACTIVE'"))[0]
    live = {}
    for tf in ("1m", "15m", "1h"):
        rows = await _all(s, """select (r.started_at at time zone 'Asia/Kolkata')::date d,
            count(distinct r.request_params->>'instrument_key') from ingest_run r
            where r.stream like 'ohlcv.' || :tf || '.NSE_%' and r.mode='COMMIT'
              and r.status='COMPLETE' and r.request_params->>'endpoint' = 'intraday'
            group by 1 order by 1 desc limit 5""", tf=tf)
        live[tf] = {str(d): n for d, n in rows}
    sessions = sorted({d for v in live.values() for d in v}, reverse=True)
    full = [d for d in sessions if all(live[tf].get(d, 0) >= 0.99 * active
                                       for tf in ("1m", "15m", "1h"))]
    reruns = rerun_checks()
    idem = [r for r in reruns if "idempotent=True" in r]
    r_status = FAIL if not full else (PASS if idem and not [r for r in reruns
                                                           if "idempotent=False" in r]
                                      else WAITING)
    out.append(Criterion("R", "Daily incremental ingestion", r_status,
                         {"sessions_complete_all_intraday_tfs": full,
                          "rerun_checks": reruns[-3:],
                          "runbook": "ops/runbooks/close_then_backfill.sh --no-backfill"},
                         {"active_instruments": active, "complete_runs_by_session": live},
                         "new rule: 1m + 15m + 1h complete for >= 99 % of ACTIVE instruments "
                         "on a session AND a same-day rerun inserting nothing (old: 1m only)"))

    # S. historical backfill = F, G, I, J
    parts = {c.id: c.status for c in out if c.id in ("F", "G", "I", "J")}
    s_status = PASS if all(v == PASS for v in parts.values()) else (
        DEFERRED if parts.get("F") == PASS and all(v in (PASS, DEFERRED) for v in parts.values())
        else FAIL)
    out.append(Criterion("S", "Historical backfill to the approved depth", s_status,
                         {"from": parts}, notes="intraday depth DEFERRED_FOR_STAGE_1 "
                         "(BACKFILL-DEFER); 1D depth (F) is required and measured",
                         decisions=["BACKFILL-DEFER"] if s_status == DEFERRED else []))

    # T. replay: random COMMIT runs per family, archive -> parser -> DB
    rp = await replay_sample(s)
    arch = await verify_archive(s)
    t_ok = rp["runs"] > 0 and rp["mismatches"] == 0 and all(
        v["runs"] for v in rp["by_family"].values() if v["available"]) \
        and arch["mismatched"] == 0 and arch["missing"] == 0
    out.append(Criterion("T", "Replay (archive -> parser -> DB) + raw archive hashes",
                         PASS if t_ok else FAIL, {"replay": rp, "archive": arch}))

    # U. idempotency: natural keys unique
    dup = {
        "macro": (await _one(s, "select count(*) from (select 1 from macro_observation group "
                                "by series_code, observation_date, source "
                                "having count(*)>1) x"))[0],
        "news": (await _one(s, "select count(*) from (select 1 from news_article group by "
                               "headline_sha256, published_at, source having count(*)>1) x"))[0],
        "corporate_action": (await _one(s, "select count(*) from (select 1 from corporate_action "
                                           "group by isin, content_sha256, source "
                                           "having count(*)>1) x"))[0],
        "fundamentals_repeated_snapshot": (await _one(s, """select count(*) from (
            select payload, lag(payload) over (partition by instrument_key, statement_type,
              source order by knowable_at) prev from fundamental_snapshot) x
            where payload = prev"""))[0],
        "news_links": (await _one(s, "select count(*) from (select 1 from news_instrument "
                                     "group by news_id, instrument_key, source "
                                     "having count(*)>1) x"))[0],
    }
    out.append(Criterion("U", "Idempotency (no duplicate observations)",
                         PASS if not any(dup.values()) else FAIL, {"duplicates": dup},
                         {}, "ohlcv_bar is keyed by its primary key; reruns inserted 0 "
                             "(validation doc §6, §13, §14)"))

    # V. crash recovery: nothing left RUNNING, no rows from non-COMPLETE runs (B)
    running = (await _one(s, "select count(*) from ingest_run where status='RUNNING' "
                             "and started_at < now() - interval '6 hours'"))[0]
    out.append(Criterion("V", "Crash recovery", PASS if running == 0 and bad_total == 0 else FAIL,
                         {"stale_running_runs": running,
                          "tests": "test_interrupted_insert_rolls_back_and_resume_completes, "
                                   "rate-limit abort tests (candles, news, corporate actions, "
                                   "fundamentals, FII/DII)"}))

    # W. coverage: every NSE instrument has a 1D stream outcome
    unatt = dd["1d"]["without_checkpoint"] - len({x[0] for x in failed_1d})
    out.append(Criterion("W", "Coverage reconciliation", PASS if unatt <= 0 else FAIL,
                         {"1d_without_outcome": max(unatt, 0), "1d_failed": len(failed_1d)},
                         notes="EMPTY windows are recorded outcomes (new listings)"))

    # X. no look-ahead (data-time rules)
    la = {
        "daily_nse_fetched_same_day": (await _one(s, """select count(*) from ohlcv_bar b
            join instrument i on i.instrument_id=b.instrument_id where b.timeframe='1d'
            and i.segment not like 'GLOBAL%'
            and (b.fetched_at at time zone 'Asia/Kolkata')::date <= b.session_date"""))[0],
        "intraday_before_end_plus_margin": (await _one(s, """select count(*) from ohlcv_bar
            where timeframe in ('1m','5m','15m','1h') and bar_start_utc + case timeframe
            when '1m' then interval '1 minute' when '5m' then interval '5 minutes'
            when '15m' then interval '15 minutes' else interval '1 hour' end
            + make_interval(secs => case when timeframe in ('1m','15m','1h') then
                case when fetched_at < cast(:eff as timestamptz) then cast(:prev as float8)
                else cast(:cur as float8) end else cast(:oos as float8) end)
            > fetched_at""", eff=T.MARGIN_EFFECTIVE_FROM, prev=T.PREVIOUS_MARGIN_S,
            cur=T.COMPLETION_MARGIN_S["1m"], oos=T.OUT_OF_SCOPE_MARGIN_S["5m"]))[0],
        "fii_dii_same_day": (await _one(s, """select count(*) from macro_observation
            where observation_date >= (fetched_at at time zone 'Asia/Kolkata')::date"""))[0],
        "news_published_after_knowable": (await _one(s, """select count(*) from news_article
            where knowable_at < published_at"""))[0],
        "corporate_announced_after_fetch": (await _one(s, """select count(*) from corporate_action
            where announcement_date > (fetched_at at time zone 'Asia/Kolkata')::date"""))[0],
    }
    # B1/B2 (timing contracts): measured by ops/measure/analyze_timing.py from the
    # archived poller responses; VERIFIED needs >= 3 agreeing sessions.
    b1b2 = load_b1b2()
    timing = {k: {"status": b1b2.get(k, {}).get("status", "UNMEASURED"),
                  "sessions_observed": b1b2.get(k, {}).get("sessions_observed", []),
                  "sessions_agreeing": b1b2.get(k, {}).get("sessions_agreeing", []),
                  "sessions_disagreeing": b1b2.get(k, {}).get("sessions_disagreeing", {})}
              for k in ("B1", "B2")}
    if "per_timeframe" in b1b2.get("B2", {}):          # revised B2 (decision TIMING-B2)
        timing["B2"]["contract"] = b1b2["B2"]["contract"]
        timing["B2"]["late_revisions"] = len(b1b2["B2"].get("late_revisions", []))
        timing["B2"]["headroom"] = {
            tf: {"margin_s": v["margin_s"], "observed_max_s": v["revision_latency_s"]["max"],
                 "headroom_s": v["headroom_s"], "bars_sampled": v["bars_sampled"]}
            for tf, v in b1b2["B2"]["per_timeframe"].items() if v["in_scope"]}
        timing["B2"]["evidence_sufficiency"] = b1b2["B2"].get("evidence_sufficiency")
        timing["B2_original"] = {"status": b1b2.get("B2_original", {}).get("status"),
                                 "superseded_by": "TIMING-B2"}
    x_status, contradicted = x_decision(la, timing)
    out.append(Criterion("X", "No look-ahead (incl. B1/B2 verified over >= 3 sessions)",
                         x_status, {"violations": la, "timing": timing},
                         notes="0 violations required (FAIL otherwise); B1 and the revised "
                               "B2 (TIMING-B2: timing-final at bar_end + margin) need >= 3 "
                               "agreeing sessions (WAITING_FOR_EVIDENCE until then); any late "
                               "revision (after the margin) or B1 contradiction: BLOCKED for "
                               "contract review; knowable_at stays the fetch time regardless",
                         decisions=["TIMING-REVIEW"] if contradicted else []))

    # Y. survivorship
    y_status = PASS if DECISIONS["SURV"]["status"] == "APPROVED" else BLOCKED
    out.append(Criterion("Y", "Survivorship policy", y_status,
                         {"policy": DECISIONS["SURV"]["decision"],
                          "ref": DECISIONS["SURV"]["ref"]}))

    order = {c.id: c for c in out}
    crit = [order[k] for k in sorted(order)]
    # COMPLETE: every criterion PASS, approved OUT_OF_SCOPE, or approved DEFERRED.
    # LIVE_READY: nothing FAIL or BLOCKED (WAITING_FOR_EVIDENCE items listed).
    settled = (PASS, OUT, DEFERRED)
    overall = "COMPLETE" if all(c.status in settled for c in crit) else "NOT COMPLETE"
    live_ready = "PASS" if not [c for c in crit if c.status in (FAIL, BLOCKED)] else "NOT PASS"
    return {"generated_at": now().isoformat(), "overall": overall, "live_readiness": live_ready,
            "waiting_for_evidence": [c.id for c in crit if c.status == WAITING],
            "deferred": [c.id for c in crit if c.status == DEFERRED],
            "failing": [c.id for c in crit if c.status in (FAIL, BLOCKED)],
            "last_session": str(last),
            "criteria": [{
                "id": c.id, "name": c.name, "status": c.status, "evidence": c.evidence,
                "db_state": c.db_state, "notes": c.notes, "decisions": c.decisions}
                for c in crit],
            "decisions": DECISIONS}


async def replay_sample(s: AsyncSession, per_family: int = 25, seed: int | None = None) -> dict:
    """Re-read archived payloads of random COMMIT runs, re-parse them with the
    run's own fetched_at, and compare with the rows the run wrote."""
    from app.contracts.candles import Window
    from app.parsers import upstox_institutional as PI
    from app.parsers import upstox_news as PN
    from app.parsers.upstox_candles import Endpoint, parse_candles
    from app.storage.payload_store import PayloadStore

    rnd = random.Random(seed)
    fam: dict[str, dict] = {}
    mismatches = 0

    async def runs(pattern: str) -> list:
        rows = await _all(s, """select run_id, request_params from ingest_run where stream like :p
            and mode='COMMIT' and status='COMPLETE' and rows_written > 0""", p=pattern)
        return rnd.sample(rows, min(per_family, len(rows)))

    async def payload(sha: str) -> tuple[bytes, int]:
        r = await _one(s, "select storage_uri, http_status from raw_payload where "
                          "payload_sha256=:h", h=sha)
        return PayloadStore.read(anchored(r[0]), sha), r[1]

    # candles
    n = rows_cmp = 0
    for run_id, rp in await runs("ohlcv.%"):
        sha = rp["outcome"]["payload_sha256"]
        data, status = await payload(sha)
        db = {r[0]: r for r in await _all(s, """select bar_start_utc, open, high, low, close,
              volume, open_interest, knowable_at, fetched_at from ohlcv_bar where run_id=:r""",
                                          r=run_id)}
        fetched = next(iter(db.values()))[8]
        w = rp.get("window")
        pc = parse_candles(data, http_status=status, endpoint=Endpoint(rp["endpoint"]),
                           instrument_key=rp["instrument_key"], timeframe=rp["timeframe"],
                           fetched_at=fetched, payload_sha256=sha,
                           window=None if w is None else Window(_dt.date.fromisoformat(w[0]),
                                                                _dt.date.fromisoformat(w[1])))
        parsed = {r.bar_start_utc: r for r in pc.complete}
        n += 1
        for k, row in db.items():
            rows_cmp += 1
            p = parsed.get(k)
            if p is None or (p.open, p.high, p.low, p.close, p.volume, p.open_interest,
                             p.knowable.at) != tuple(row[1:8]):
                mismatches += 1
    fam["candles"] = {"runs": n, "rows": rows_cmp, "available": True}

    # FII/DII
    n = rows_cmp = 0
    for run_id, rp in await runs("macro.%"):
        data, status = await payload(rp["outcome"]["payload_sha256"])
        db = {(r[0], r[1]): r for r in await _all(s, """select series_code, observation_date,
              value, knowable_at, fetched_at from macro_observation where run_id=:r""", r=run_id)}
        fetched = next(iter(db.values()))[4]
        pi = PI.parse_institutional(data, http_status=status, side=rp["side"], interval="1D",
                                    data_types=(rp["data_type"],), fetched_at=fetched)
        parsed = {(o.series_code, o.observation_date): o for o in pi.rows}
        n += 1
        for k, row in db.items():
            rows_cmp += 1
            o = parsed.get(k)
            if o is None or (o.value, o.knowable.at) != (row[2], row[3]):
                mismatches += 1
    fam["fii_dii"] = {"runs": n, "rows": rows_cmp, "available": True}

    # news
    n = rows_cmp = 0
    for run_id, rp in await runs("news.%"):
        db = await _all(s, """select headline_sha256, published_at, url, body, payload_sha256,
                              fetched_at, knowable_at from news_article where run_id=:r""",
                        r=run_id)
        n += 1
        for hs, pub, url, body, sha, fetched, kn in db:
            data, status = await payload(sha)
            pn = PN.parse_news(data, http_status=status,
                               requested_keys=rp["instrument_keys"], fetched_at=fetched)
            a = pn.articles.get((hs, pub))
            rows_cmp += 1
            if a is None or (a.url, a.body, a.knowable.at) != (url, body, kn):
                mismatches += 1
    fam["news"] = {"runs": n, "rows": rows_cmp, "available": True}

    # corporate actions: payloads of sampled runs re-parsed; each stored event
    # must be re-derived identically (content, dates, knowable_at)
    from app.parsers import upstox_corporate_actions as PC
    n = rows_cmp = 0
    for run_id, _rp in await runs("corporate_action.%"):
        db = await _all(s, """select isin, content_sha256, announcement_date, ex_date,
                              knowable_at, payload_sha256, fetched_at from corporate_action
                              where run_id=:r""", r=run_id)
        n += 1
        for isin, h, ann, ex, kn, sha, fetched in db:
            data, status = await payload(sha)
            ev = {e.content_sha256: e for e in PC.parse_corporate_actions(
                data, http_status=status, isin=isin, fetched_at=fetched).events}.get(h)
            rows_cmp += 1
            if ev is None or (ev.announcement_date, ev.ex_date, ev.knowable.at) != (ann, ex, kn):
                mismatches += 1
    fam["corporate_actions"] = {"runs": n, "rows": rows_cmp, "available": n > 0}

    # fundamentals: the stored payload equals the archived response's data
    n = rows_cmp = 0
    for run_id, _rp in await runs("fundamentals.%"):
        db = await _all(s, """select payload, payload_sha256 from fundamental_snapshot
                              where run_id=:r""", r=run_id)
        n += 1
        for pl, sha in db:
            data, _ = await payload(sha)
            rows_cmp += 1
            if json.loads(data).get("data") != pl:
                mismatches += 1
    fam["fundamentals"] = {"runs": n, "rows": rows_cmp, "available": n > 0}

    total = sum(v["runs"] for v in fam.values())
    return {"runs": total, "mismatches": mismatches, "by_family": fam, "per_family": per_family}


# Rules changed by the Stage 1 hardening (2026-09-25): criterion -> (old, new).
RULE_CHANGES: dict[str, tuple[str, str]] = {
    "D": ("sector >= 90 % of ALL current NSE_EQ (fund units / entitlements in the "
          "denominator)", "sector >= 90 % of ACTIVE instruments classified STOCK; REVIEW = 0; "
          "UNCLASSIFIED only within 7 days (2026-10-08: also a new listing in REVIEW only "
          "for missing vendor financials, decision D-NEW-LISTING-GRACE)"),
    "F": ("every current instrument's 1D checkpoint; any failed 1D stream fails",
          "ACTIVE instruments only; corporate-action-explained revisions are recorded, not "
          "failures (UNEXPLAINED still fails)"),
    "G": ("1m checkpoint reaches 6 months for every instrument", "historical depth only; "
          "DEFERRED_FOR_STAGE_1 (BACKFILL-DEFER); live 1m is part of R"),
    "I": ("15m checkpoint reaches 2022 for every instrument", "historical depth only; DEFERRED "
          "(BACKFILL-DEFER); live 15m is part of R"),
    "J": ("1h checkpoint reaches 2022 for every instrument", "historical depth only; DEFERRED "
          "(BACKFILL-DEFER); live 1h is part of R"),
    "Q": ("every global instrument has a bar dated >= the previous NSE session",
          "per-instrument finality contract: fresh COMPLETE fetch, a CONFIRMED label within "
          "its own p99 gap + 3 d, no revised/placeholder label exposed"),
    "R": ("a session with >= 3,000 complete 1m close runs", "1m + 15m + 1h complete for >= 99 % "
          "of ACTIVE instruments AND a same-day rerun inserting nothing"),
    "S": ("F, G, I, J all PASS", "F PASS required; G/I/J depth DEFERRED (BACKFILL-DEFER)"),
    "W": ("1D coverage of every current instrument", "unchanged rule, ACTIVE universe"),
    "X": ("0 violations AND B1/B2 verified, else FAIL", "0 violations required (else FAIL); "
          "B1 and B2 as revised by TIMING-B2 (timing-final at bar_end + per-timeframe "
          "margin, 120 s; engineering threshold, monitored) need >= 3 agreeing sessions "
          "(WAITING_FOR_EVIDENCE until then, never PASS); a late revision or a B1 "
          "contradiction makes X BLOCKED; original B2 ('1m never changes') is recorded as "
          "CONTRADICTED 2026-09-25 (90/1,125 Nifty 50 1m bars, max 95.6 s)"),
}


def to_markdown(rep: dict) -> str:
    lines = [
        "# Stage 1 final acceptance",
        "",
        f"**Generated:** {rep['generated_at']} by `prajna acceptance stage1` (read-only, "
        "computed from the prajna database; regenerate, do not edit).",
        "",
        f"## Overall: **{rep['overall']}** - live readiness: **{rep.get('live_readiness')}**",
        "",
        f"- Waiting for evidence: {', '.join(rep.get('waiting_for_evidence') or []) or 'none'}",
        f"- Deferred by decision: {', '.join(rep.get('deferred') or []) or 'none'}",
        f"- Failing: {', '.join(rep.get('failing') or []) or 'none'}",
        "",
        "COMPLETE = every criterion PASS, approved OUT_OF_SCOPE or approved DEFERRED. "
        "LIVE_READY = nothing FAIL/BLOCKED. WAITING_FOR_EVIDENCE and DEFERRED are never PASS.",
        "",
        "| # | Criterion | Old rule | New rule | Status | Current result (DB state) | "
        "Evidence | Reason / decisions |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def cell(d) -> str:
        t = json.dumps(d, default=str, ensure_ascii=False) if d else ""
        return t.replace("|", "\\|")[:600]

    for c in rep["criteria"]:
        old, new = RULE_CHANGES.get(c["id"], ("", "unchanged"))
        dec = f" **Decisions:** {', '.join(c['decisions'])}" if c["decisions"] else ""
        lines.append(f"| {c['id']} | {c['name']} | {old} | {new} | **{c['status']}** | "
                     f"{cell(c['db_state'])} | {cell(c['evidence'])} | {c['notes']}{dec} |")
    lines += ["", "## Decision register", "", "| id | status | decision | reference |",
              "|---|---|---|---|"]
    for k, d in rep["decisions"].items():
        lines.append(f"| {k} | **{d['status']}** | {d['decision']} | {d['ref']} |")
    return "\n".join(lines) + "\n"


async def verify_archive(s: AsyncSession) -> dict:
    """Every raw_payload row: its archived bytes still hash to its sha256.
    File payloads are read whole; WebSocket frames (<archive>#seq=n) are
    re-read from their frame archive and each frame re-hashed."""
    import hashlib

    from app.storage.frame_archive import FrameArchiveReader
    from app.storage.payload_store import PayloadStore

    rows = await _all(s, "select payload_sha256, storage_uri from raw_payload")
    files = [(h, u) for h, u in rows if "#seq=" not in u]
    framed: dict[str, dict[int, str]] = {}
    for h, u in rows:
        if "#seq=" in u:
            path, seq = u.split("#seq=")
            framed.setdefault(path, {})[int(seq)] = h
    ok = bad = missing = 0
    for h, u in files:
        if not anchored(u).exists():
            missing += 1
            continue
        try:
            PayloadStore.read(anchored(u), h)
            ok += 1
        except ValueError:
            bad += 1
    frames_ok = 0
    for path, want in framed.items():
        if not anchored(path).exists():
            missing += len(want)
            continue
        seen = {}
        for rec in FrameArchiveReader(anchored(path)):
            if rec.seq in want:
                seen[rec.seq] = hashlib.sha256(rec.payload).hexdigest()
        for seq, h in want.items():
            if seen.get(seq) == h:
                frames_ok += 1
            elif seq not in seen:
                missing += 1
            else:
                bad += 1
    return {"file_payloads_verified": ok, "frame_payloads_verified": frames_ok,
            "frame_archives": len(framed), "mismatched": bad, "missing": missing}
