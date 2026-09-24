"""A small, fully specified Stage 1 world for Stage 2 tests.

Sessions 2026-09-14 .. 2026-09-23 (weekdays, trading). Frozen "now":
2026-09-24 12:00 IST. Instruments and what Stage 1 holds for them:

  RELIANCE  NSE_EQ EQ   1d: window [09-14, 09-23] COMPLETE, checkpoint covers it;
                        bars 09-14..09-18 and 09-22; 09-21 none (EMPTY);
                        09-23 bar QUARANTINED (Q1). 1h/15m/1m: nothing (PENDING)
  HDFCBANK  NSE_EQ BE   1d: the only window FAILED (VENDOR_ERROR)
  NIFTY     NSE_INDEX   1d: checkpoint [09-14, 09-23] but no window: MISSING
  REIT      NSE_EQ RR   excluded (series outside S1)
  SPX       GLOBAL      excluded from the NSE universe (macro only)
  FUT       NSE_FO      excluded

Point-in-time facts (RELIANCE):
  corporate action announced 2026-09-24 -> knowable 09-24 23:59:59.999 IST
  news published 09-22 10:00 IST, vendor link fetched 09-24 11:00 IST
  fundamentals profile: sector "Old" knowable 09-10; sector "Refineries" 09-20
  pre-open tick of session 09-23 at 09:05 IST
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid

from sqlalchemy import text

from app.core.clock import IST

D = _dt.date
NOW = _dt.datetime(2026, 9, 24, 12, 0, tzinfo=IST)
SESSIONS = [D(2026, 9, d) for d in (14, 15, 16, 17, 18, 21, 22, 23)]
R, H, N = "NSE_EQ|INE002A01018", "NSE_EQ|INE040A01034", "NSE_INDEX|Nifty 50"
REIT, SPX, FUT = "NSE_EQ|INE041025011", "GLOBAL_INDEX|^GSPC", "NSE_FO|12345"


def ist(y, m, d, hh=0, mm=0, ss=0, us=0):
    return _dt.datetime(y, m, d, hh, mm, ss, us, tzinfo=IST)


async def _run(s, stream, source="UPSTOX_REST_V3", status="COMPLETE", params=None,
               started=None, finished=None):
    rid = uuid.uuid4()
    await s.execute(text("""
        insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
          code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
          started_at, finished_at, rows_written)
        values (:r, :src, :st, 't', cast(:p as jsonb), 't', :c, ARRAY['pytest'], 'pytest',
                'COMMIT', :status, :a, :s0, :f, 0)"""),
        {"r": rid, "src": source, "st": stream, "p": json.dumps(params or {}), "c": "c" * 64,
         "status": status, "a": "a" * 64, "s0": started or NOW - _dt.timedelta(hours=2),
         "f": finished or NOW - _dt.timedelta(hours=1)})
    return rid


async def _payload(s, rid, source="UPSTOX_REST_V3", fetched=None):
    sha = uuid.uuid4().hex * 2
    await s.execute(text("""
        insert into raw_payload (payload_sha256, source, vendor_endpoint, request_params,
          byte_size, content_type, storage_uri, first_seen_run, fetched_at)
        values (:h, :src, 't', '{}', 1, 'application/json', '/dev/null', :r, :f)"""),
        {"h": sha, "src": source, "r": rid, "f": fetched or NOW - _dt.timedelta(hours=1)})
    return sha


async def seed(s) -> dict:
    ids: dict = {}
    base = await _run(s, "instrument.current", source="UPSTOX_ASSETS")
    bsha = await _payload(s, base, "UPSTOX_ASSETS")
    prov = {"src": "UPSTOX_ASSETS", "r": base, "h": bsha, "f": NOW - _dt.timedelta(days=1)}
    for key, seg, exch, sym, isin, series in (
            (R, "NSE_EQ", "NSE", "RELIANCE", "INE002A01018", "EQ"),
            (H, "NSE_EQ", "NSE", "HDFCBANK", "INE040A01034", "BE"),
            (N, "NSE_INDEX", "NSE", "Nifty 50", None, None),
            (REIT, "NSE_EQ", "NSE", "EMBASSY", "INE041025011", "RR"),
            (SPX, "GLOBAL_INDEX", "GLOBAL", "^GSPC", None, None),
            (FUT, "NSE_FO", "NSE", "NIFTYFUT", None, "FUTIDX")):
        ids[key] = (await s.execute(text("""
            insert into instrument (instrument_key, segment, exchange, trading_symbol, isin,
              instrument_type, valid_from, source, run_id, payload_sha256, fetched_at,
              knowable_at, knowable_at_basis)
            values (:k, :seg, :ex, :sym, :isin, :ser, '2026-09-01', :src, :r, :h, :f, :f, 't')
            returning instrument_id"""),
            {"k": key, "seg": seg, "ex": exch, "sym": sym, "isin": isin, "ser": series,
             **prov})).scalar()
    cal = await _run(s, "calendar.nse", source="UPSTOX_REST_V2")
    csha = await _payload(s, cal, "UPSTOX_REST_V2")
    d = D(2026, 9, 12)
    while d <= D(2026, 9, 30):
        trading = d.weekday() < 5
        await s.execute(text("""
            insert into trading_session (session_date, is_trading_day, session_type, open_ist,
              close_ist, source, run_id, payload_sha256, fetched_at, knowable_at,
              knowable_at_basis) values (:d, :t, :ty, :o, :c, 'UPSTOX_REST_V2', :r, :h,
              :f, :f, 't')"""),
            {"d": d, "t": trading, "ty": "NORMAL" if trading else "WEEKEND",
             "o": _dt.time(9, 15) if trading else None, "c": _dt.time(15, 30) if trading else None,
             "r": cal, "h": csha, "f": NOW - _dt.timedelta(days=1)})
        d += _dt.timedelta(days=1)

    # RELIANCE 1d: one COMPLETE window, bars, an EMPTY day, a quarantined day
    w = {"window": ["2026-09-14", "2026-09-23"], "endpoint": "historical",
         "instrument_key": R, "timeframe": "1d"}
    rr = await _run(s, f"ohlcv.1d.{R}", params={**w, "outcome": {
        "checkpoint": {"covered_from": "2026-09-14", "through": "2026-09-23"}}})
    rsha = await _payload(s, rr)
    fetched = ist(2026, 9, 24, 8, 0)
    for day in (14, 15, 16, 17, 18, 22):
        sd = D(2026, 9, day)
        await s.execute(text("""
            insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc, source,
              instrument_key, open, high, low, close, volume, vendor_ts_raw, run_id,
              payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values (:i, '1d', :d, :b, 'UPSTOX_REST_V3', :k, 100, 110, 95, 105, 1000, 'x', :r, :h,
                    :f, :f, false, 't')"""),
            {"i": ids[R], "d": sd, "b": ist(sd.year, sd.month, sd.day), "k": R, "r": rr,
             "h": rsha, "f": fetched})
    await s.execute(text("""
        insert into ingest_anomaly (run_id, severity, kind, subject, detail, created_at)
        values (:r, 'WARN', 'QUARANTINED', 'candle[2026-09-23]', cast(:d as jsonb), :c)"""),
        {"r": rr, "c": fetched, "d": json.dumps({"instrument_key": R, "timeframe": "1d",
         "session_date": "2026-09-23", "decision": "Q1", "reason": "negative volume -5",
         "payload_sha256": rsha})})
    await s.execute(text("""insert into ingest_watermark (source, stream, last_logical_date,
        last_run_id) values ('UPSTOX_REST_V3', :st, '2026-09-23', :r)"""),
        {"st": f"ohlcv.1d.{R}", "r": rr})
    # HDFCBANK 1d: failed window
    await _run(s, f"ohlcv.1d.{H}", status="FAILED",
               params={**w, "instrument_key": H})
    # NIFTY 1d: a checkpoint without any window behind it (inconsistent on purpose)
    nr = await _run(s, "legacy.nifty", params={"outcome": {"checkpoint": {
        "covered_from": "2026-09-14", "through": "2026-09-23"}}})
    await s.execute(text("""insert into ingest_watermark (source, stream, last_logical_date,
        last_run_id) values ('UPSTOX_REST_V3', :st, '2026-09-23', :r)"""),
        {"st": f"ohlcv.1d.{N}", "r": nr})

    # point-in-time facts for RELIANCE
    fr = await _run(s, "facts", source="UPSTOX_REST_V2")
    fsha = await _payload(s, fr, "UPSTOX_REST_V2", fetched=ist(2026, 9, 25, 10, 0))
    await s.execute(text("""
        insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
          ex_date, announcement_date, content_sha256, vendor_payload, source, run_id,
          payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values ('INE002A01018', :k, 'RELIANCE', 'DIVIDEND', '2026-10-05', '2026-09-24', :c,
                '{}', 'UPSTOX_REST_V2', :r, :h, :f, :kn, false, 'KN-CA')"""),
        {"k": R, "c": "d" * 64, "r": fr, "h": fsha, "f": ist(2026, 9, 25, 10, 0),
         "kn": ist(2026, 9, 24, 23, 59, 59, 999000)})
    nid = (await s.execute(text("""
        insert into news_article (headline, published_at, headline_sha256, vendor_payload,
          source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
          knowable_at_basis) values ('Reliance news', :p, :hs, '{}', 'UPSTOX_REST_V2', :r, :h,
          :f, :p, true, 'published') returning id"""),
        {"p": ist(2026, 9, 22, 10, 0), "hs": "e" * 64, "r": fr, "h": fsha,
         "f": ist(2026, 9, 24, 11, 0)})).scalar()
    await s.execute(text("""
        insert into news_instrument (news_id, instrument_key, source, run_id, payload_sha256,
          fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values (:n, :k, 'UPSTOX_REST_V2', :r, :h, :f, :f, false, 'link')"""),
        {"n": nid, "k": R, "r": fr, "h": fsha, "f": ist(2026, 9, 24, 11, 0)})
    for sector, t in (("Old", ist(2026, 9, 10, 12)), ("Refineries", ist(2026, 9, 20, 12))):
        await s.execute(text("""
            insert into fundamental_snapshot (instrument_key, isin, statement_type, payload,
              source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
              knowable_at_basis) values (:k, 'INE002A01018', 'profile', cast(:p as jsonb),
              'UPSTOX_REST_V2', :r, :h, :t, :t, false, 'fetched')"""),
            {"k": R, "p": json.dumps({"sector": sector}), "r": fr, "h": fsha, "t": t})
    await s.execute(text("""
        insert into preopen_tick (session_date, instrument_key, instrument_id, frame_seq,
          vendor_ts, feed_type, request_mode, iep, tbq, tsq, iiq_total, source, run_id,
          payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values ('2026-09-23', :k, :i, 1, :t, 'ff', 'full', 1250.5, 1000, 800, 200,
                'UPSTOX_WS_V3', :r, :h, :f, :t, true, 'currentTs')"""),
        {"k": R, "i": ids[R], "t": ist(2026, 9, 23, 9, 5), "f": ist(2026, 9, 23, 9, 5, 1),
         "r": fr, "h": fsha})
    return ids
