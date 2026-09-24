"""Stage 1 final acceptance gate: criteria A-Y computed from the REAL database.

READ-ONLY. Every status is derived from rows, runs, archives and the decision
register below; nothing is asserted from memory. Statuses:

  PASS          the criterion holds on the current data
  FAIL          it does not (data missing, incomplete, or wrong)
  BLOCKED       it cannot pass until a named human decision is taken
  OUT_OF_SCOPE  excluded by an APPROVED decision (the register names it)

Overall = COMPLETE only if every criterion is PASS or OUT_OF_SCOPE.

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

from app.core.clock import IST, now

PASS, FAIL, BLOCKED, OUT = "PASS", "FAIL", "BLOCKED", "OUT_OF_SCOPE"

DECISIONS: dict[str, dict[str, str]] = {
    "D1": {"status": "APPROVED", "decision": "1D from 2020-01-01; 1h and 15m from 2022-01; "
           "1m for the last 6 months", "ref": "M4.5 plan approved 2026-09-23 (M4_DECISIONS)"},
    "D2": {"status": "APPROVED", "decision": "vendor-fetched 15m/1h (and 1m)",
           "ref": "M4.5 plan approved 2026-09-23"},
    "D2-5m": {"status": "PENDING", "decision": "5m: the approved plan does not fetch it "
              "(\"can be derived from 1m later\"); the Stage-1 spec lists 5m. Fetch 5m since "
              "2022 (~201k requests), fetch for the 1m depth only, or formally exclude",
              "ref": "-"},
    "D3": {"status": "IN_FORCE", "decision": "a changed value for a stored bar/observation "
           "FAILS; nothing is overwritten (versioned storage not enabled)",
           "ref": "M1/M4 contracts; not changed"},
    "D5": {"status": "PENDING", "decision": "all-day LTP/depth persistence: Stage 7 per M0 "
           "(PRAJNA_TICK_PERSISTENCE_ENABLED=false); needs explicit confirmation as a "
           "Stage-1 exclusion", "ref": "M0"},
    "S1": {"status": "IN_FORCE", "decision": "universe = NSE_EQ series EQ/BE/SM/BZ/ST/IV "
           "(REIT RR, D1/E1/IT/SZ/W1 excluded)", "ref": "M1; not changed"},
    "S2": {"status": "APPROVED", "decision": "FII/DII, corporate actions, news, fundamentals, "
           "global (where Upstox has it) are in Stage 1",
           "ref": "user 2026-09-23 (FII/DII) and Stage-1 completion mission 2026-09-24"},
    "P1": {"status": "PENDING", "decision": "WebSocket knowable_at = vendor currentTs "
           "(11-148 ms before receipt, M0 contract) vs fetched_at", "ref": "-"},
    "SURV": {"status": "APPROVED", "decision": "survivorship-biased equity history accepted "
             "and documented: Upstox publishes no delisted/historical master (the "
             "'suspended' file answers 403)", "ref": "M4.5 plan approved 2026-09-23"},
    "Q1": {"status": "PENDING", "decision": "invalid vendor bars (negative volume; OHLC "
           "outside [low, high]): quarantine the single bar and store the rest, or keep "
           "the whole-window FAIL", "ref": "-"},
    "C6": {"status": "PENDING", "decision": "pre-open completeness C6 (88.6 % ticked in "
           "window): explained (no IEP ever = no pre-open activity); accept as expected "
           "or keep as WARN", "ref": "-"},
    "KN-CA": {"status": "IN_FORCE", "decision": "corporate actions: announcement is a date "
              "only; knowable_at = fetched_at (for_announced_fact). Alternative (end of the "
              "announcement date, IST) needs approval", "ref": "M0 contract"},
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
        where i.valid_to = 'infinity' and i.segment in ('NSE_EQ','NSE_INDEX')""", tf=tf)
    bars = dict(await _all(s, """select instrument_key, count(*) from ohlcv_bar
                                 where timeframe=:tf group by 1""", tf=tf))
    lag = _dt.timedelta(days=3)
    covered = [k for k, t, c in rows if t and c and c <= since and t >= last - lag]
    none = [k for k, t, c in rows if t is None]
    return {"instruments": len(rows), "covered_to_depth": len(covered),
            "without_checkpoint": len(none), "bars": sum(bars.values()),
            "instruments_with_bars": len(bars), "required_from": str(since),
            "required_through": str(last), "sample_missing": sorted(none)[:5]}


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
            left join raw_payload p on p.payload_sha256 = x.payload_sha256""")  # noqa: S608
        prov[t] = {"rows": r[0], "bad_run": r[1], "no_payload": r[2], "no_basis": r[3]}
        bad_total += r[1] + r[2] + r[3]
    orphans = (await _one(s, """select count(*) from preopen_book b where not exists
                                (select 1 from preopen_tick t where t.tick_id = b.tick_id)"""))[0]
    prov["preopen_book"] = {"orphans": orphans}
    bad_total += orphans
    out.append(Criterion("B", "Provenance", PASS if bad_total == 0 else FAIL,
                         {"violations": bad_total}, prov))

    # C. point-in-time: knowable_at <= fetched_at everywhere
    pit = {t: (await _one(s, f"select count(*) from {t} "  # noqa: S608 (constant names)
                             "where knowable_at > fetched_at"))[0]
           for t in PROV_TABLES}
    out.append(Criterion("C", "Point-in-time safety (knowable_at <= fetched_at)",
                         PASS if not any(pit.values()) else FAIL, {"violations": pit}))

    # D. instrument master
    inst = await _one(s, """select
        count(*) filter (where segment='NSE_EQ'), count(*) filter (where segment='NSE_INDEX'),
        count(*) filter (where segment like 'GLOBAL%'),
        count(*) filter (where segment='NSE_EQ' and (isin is null or trading_symbol is null))
        from instrument where valid_to='infinity'""")
    sector = await _one(s, """select count(distinct instrument_key) from fundamental_snapshot
        where statement_type='profile' and payload ? 'sector'
          and coalesce(payload->>'sector','') <> ''""")
    d_ok = inst[0] > 3000 and inst[1] == 3 and inst[3] == 0
    d_status = PASS if d_ok and sector[0] >= 0.9 * inst[0] else FAIL
    out.append(Criterion("D", "Instrument master", d_status,
        {"sector_source": "fundamental_snapshot(profile).payload.sector",
         "listing_status": "UNAVAILABLE: Upstox 'suspended' instruments file answers 403 "
                           "AccessDenied (archived sha a824bc77...)"},
        {"nse_eq": inst[0], "nse_index": inst[1], "global": inst[2],
         "nse_eq_missing_isin_or_symbol": inst[3], "instruments_with_sector": sector[0]},
        "sector comes from fundamentals (not a master field); needs >= 90 % of NSE_EQ"))

    # E. calendar coverage 2020-01-01 .. last session + 30 days
    cal = await _one(s, """select count(*), min(session_date), max(session_date),
        count(*) filter (where is_trading_day) from trading_session""")
    span = (cal[2] - cal[1]).days + 1 if cal[1] else 0
    e_ok = cal[1] is not None and cal[1] <= _dt.date(2020, 1, 1) and cal[0] == span \
        and cal[2] >= today + _dt.timedelta(days=30)
    out.append(Criterion("E", "Trading calendar", PASS if e_ok else FAIL, {},
                         {"rows": cal[0], "from": str(cal[1]), "to": str(cal[2]),
                          "contiguous": cal[0] == span, "trading_days": cal[3]},
                         "required: every date 2020-01-01 .. today+30"))

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
            where r.status = 'FAILED'""")
    f_status = PASS if dd["1d"]["covered_to_depth"] + len({x[0] for x in failed_1d}) \
        >= dd["1d"]["instruments"] and not failed_1d else FAIL
    f_status, f_dep = _blocked_or(f_status, "Q1") if failed_1d else (f_status, [])
    out.append(Criterion("F", "1D candles (from 2020-01-01)", f_status,
                         {"failed_streams": [list(x) for x in failed_1d][:10]}, dd["1d"],
                         "instruments listed after 2020 are covered from their first bar",
                         f_dep))
    for cid, tf, name in (("G", "1m", "1m candles (last 6 months)"),
                          ("I", "15m", "15m candles (from 2022-01)"),
                          ("J", "1h", "1h candles (from 2022-01)")):
        st = PASS if dd[tf]["covered_to_depth"] >= dd[tf]["instruments"] else FAIL
        out.append(Criterion(cid, name, st, {}, dd[tf], "historical backfill (D1)"))
    five = (await _one(s, "select count(*) from ohlcv_bar where timeframe='5m'"))[0]
    h_status, h_dep = _blocked_or(FAIL, "D2-5m")
    out.append(Criterion("H", "5m candles", h_status, {}, {"bars": five},
                         "not in the approved backfill plan", h_dep))

    # K. pre-open
    reps = sorted(glob.glob(str(pathlib.Path("var/acceptance") / "preopen_*.json")))
    k_ev = {}
    k_status = FAIL
    if reps:
        rep = json.loads(pathlib.Path(reps[-1]).read_text())  # noqa: ASYNC240 (small local file)
        k_ev = {"report": reps[-1], "verdict": rep["verdict"],
                "real_market_data": rep["real_market_data"],
                "non_pass": {c["id"]: c["status"] for c in rep["checks"] if c["status"] != "PASS"},
                "B7": rep["B7"]["status"], "B8": rep["B8"]["status"]}
        k_status = PASS if rep["verdict"] == "PASS" and rep["real_market_data"] else FAIL
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
    l_status, l_dep = _blocked_or(FAIL, "D5")
    out.append(Criterion("L", "Live WebSocket data", l_status,
                         {"recorder": "live-validated 2026-09-23/24: 2 connections, 3,527 keys, "
                                      "5-level depth; archived; pre-open persisted"},
                         {"tick_archive_rows": ticks},
                         "all-day persistence is Stage 7 per M0 unless D5 says otherwise",
                         l_dep))

    # M-O. corporate actions, news, fundamentals
    nse_isins = (await _one(s, "select count(distinct isin) from instrument "
                               "where valid_to='infinity' and segment='NSE_EQ'"))[0]

    async def swept(stream: str, key: str) -> int:
        return (await _one(s, f"""select count(distinct x) from (
            select jsonb_array_elements_text(request_params->'{key}') x from ingest_run
            where stream=:st and mode='COMMIT' and status='COMPLETE') y""",  # noqa: S608
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

    # Q. global / macro
    gl = (await _one(s, """select count(*) from ohlcv_bar b join instrument i
            on i.instrument_id=b.instrument_id where i.segment like 'GLOBAL%'"""))[0]
    q_status, q_dep = _blocked_or(PASS if gl else FAIL, "Q1")
    out.append(Criterion("Q", "Global / macro", q_status,
                         {"available": "13 global instruments (S&P, Dow, USD/INR, ...) "
                                       "loaded; 1D from 2020-04-03 served",
                          "defect": "all 13 have invalid daily bars (263 total); dry run "
                                    "FAILED all windows (PARSE_REJECT)",
                          "bond_yields": "UNAVAILABLE on Upstox (not in any instrument file)"},
                         {"global_bars": gl}, "bond yields: OUT_OF_SCOPE/UNAVAILABLE", q_dep))

    # R. daily incremental: a close + morning cycle for the same session
    closes = await _all(s, """select (r.started_at at time zone 'Asia/Kolkata')::date d,
            count(distinct r.request_params->>'instrument_key') from ingest_run r
            where r.stream like 'ohlcv.1m.NSE_%' and r.mode='COMMIT' and r.status='COMPLETE'
              and r.request_params->>'endpoint' = 'intraday' group by 1 order by 1""")
    full_close = [str(d) for d, n in closes if n >= 3000]
    out.append(Criterion("R", "Daily incremental ingestion", PASS if full_close else FAIL,
                         {"sessions_with_full_close_run": full_close,
                          "runbook": "ops/runbooks/daily.sh close|morning|weekly|monthly"}))

    # S. historical backfill = F, G, I, J
    s_ok = all(c.status == PASS for c in out if c.id in ("F", "G", "I", "J"))
    out.append(Criterion("S", "Historical backfill to the approved depth",
                         PASS if s_ok else FAIL, {"from": ["F", "G", "I", "J"]}))

    # T. replay: random COMMIT runs per family, archive -> parser -> DB
    rp = await replay_sample(s)
    t_ok = rp["runs"] > 0 and rp["mismatches"] == 0 and all(
        v["runs"] for v in rp["by_family"].values() if v["available"])
    out.append(Criterion("T", "Replay (archive -> parser -> DB)", PASS if t_ok else FAIL, rp))

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
            + interval '120 seconds' > fetched_at"""))[0],
        "fii_dii_same_day": (await _one(s, """select count(*) from macro_observation
            where observation_date >= (fetched_at at time zone 'Asia/Kolkata')::date"""))[0],
        "news_published_after_knowable": (await _one(s, """select count(*) from news_article
            where knowable_at < published_at"""))[0],
        "corporate_announced_after_fetch": (await _one(s, """select count(*) from corporate_action
            where announcement_date > (fetched_at at time zone 'Asia/Kolkata')::date"""))[0],
    }
    out.append(Criterion("X", "No look-ahead", PASS if not any(la.values()) else FAIL,
                         {"violations": la}))

    # Y. survivorship
    y_status = PASS if DECISIONS["SURV"]["status"] == "APPROVED" else BLOCKED
    out.append(Criterion("Y", "Survivorship policy", y_status,
                         {"policy": DECISIONS["SURV"]["decision"],
                          "ref": DECISIONS["SURV"]["ref"]}))

    order = {c.id: c for c in out}
    crit = [order[k] for k in sorted(order)]
    overall = "COMPLETE" if all(c.status in (PASS, OUT) for c in crit) else "NOT COMPLETE"
    return {"generated_at": now().isoformat(), "overall": overall, "last_session": str(last),
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

    rnd = random.Random(seed)  # noqa: S311 (sampling, not security)
    fam: dict[str, dict] = {}
    mismatches = 0

    async def runs(pattern: str) -> list:
        rows = await _all(s, """select run_id, request_params from ingest_run where stream like :p
            and mode='COMMIT' and status='COMPLETE' and rows_written > 0""", p=pattern)
        return rnd.sample(rows, min(per_family, len(rows)))

    async def payload(sha: str) -> tuple[bytes, int]:
        r = await _one(s, "select storage_uri, http_status from raw_payload where "
                          "payload_sha256=:h", h=sha)
        return PayloadStore.read(r[0], sha), r[1]

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

    total = sum(v["runs"] for v in fam.values())
    return {"runs": total, "mismatches": mismatches, "by_family": fam, "per_family": per_family}


def to_markdown(rep: dict) -> str:
    lines = [
        "# Stage 1 final acceptance",
        "",
        f"**Generated:** {rep['generated_at']} by `prajna acceptance stage1` (read-only, "
        "computed from the prajna database; regenerate, do not edit).",
        "",
        f"## Overall: **{rep['overall']}**",
        "",
        "Stage 2 remains LOCKED unless the overall is COMPLETE." if rep["overall"] != "COMPLETE"
        else "Every criterion is PASS or an approved OUT_OF_SCOPE.",
        "",
        "| # | Criterion | Status | DB state | Evidence | Notes / decisions |",
        "|---|---|---|---|---|---|",
    ]

    def cell(d) -> str:
        t = json.dumps(d, default=str, ensure_ascii=False) if d else ""
        return t.replace("|", "\\|")[:600]

    for c in rep["criteria"]:
        blocked = f" **Blocked by:** {', '.join(c['decisions'])}" if c["decisions"] else ""
        notes = c["notes"] + blocked
        lines.append(f"| {c['id']} | {c['name']} | **{c['status']}** | {cell(c['db_state'])} | "
                     f"{cell(c['evidence'])} | {notes} |")
    lines += ["", "## Decision register", "", "| id | status | decision | reference |",
              "|---|---|---|---|"]
    for k, d in rep["decisions"].items():
        lines.append(f"| {k} | **{d['status']}** | {d['decision']} | {d['ref']} |")
    return "\n".join(lines) + "\n"
