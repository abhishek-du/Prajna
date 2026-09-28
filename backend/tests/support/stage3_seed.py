"""A fully specified Stage 1 world for Stage 3 (feature) tests.

Calendar: weekdays 2026-06-01 .. 2026-09-30 are trading sessions (pre-open
09:00, open 09:15, close 15:30 IST) except 2026-09-26/27 (weekend) and a
SPECIAL session on 2026-09-19 (Saturday) with no pre-open window.
Frozen "now": 2026-09-24 12:00 IST. The snapshot session under test is
2026-09-24 (PRE_SESSION as_of 08:59:59 IST, PRE_OPEN as_of 09:08:00 IST).

Daily bars (each knowable at 16:00 IST on its own session; basis RAW_OBSERVED,
HIGH confidence), for every session up to and including 2026-09-23 (index i =
0, 1, 2, ... in session order):

  A    close 100 + i, open = close - 0.5, high = close + 1, low = close - 1,
       volume 1000 + 10 i                         sector "Refineries"
  B    as A but close 200 + 2 i; a 1:1 BONUS goes ex on 2026-09-10 (factor 2,
       knowable 2026-08-20): bars before the ex-date are stored UNADJUSTED at
       2x (the raw exchange price), so the adjusted series is 100 + i
                                                  sector "Refineries"
  C    close 50 + 0.5 i                           sector "Refineries"
  D    close 80 + 0.25 i; key_ratios payload MALFORMED (a string)
                                                  sector "Refineries"
  E    VENDOR_ADJUSTED payload basis: every bar older than the corporate-action
       horizon (the earliest ex-date anywhere, 2026-09-10) is LOW confidence
       and refused                                 sector "Refineries"
  NIFTY 50       close 20000 + 10 i
  NIFTY BANK     close 45000 + 20 i
  INDIA VIX      close 12 + 0.1 i

Facts for A:
  key_ratios P/E 20 (sector 25), P/B 3 (sector 2), ROE 15%, ROCE 18%, EV/EBITDA 11
  income yearly Revenue Mar 2026 120 / Mar 2025 100; PAT 12 / 10; EPS 6 / 5
  balance sheet Mar 2026: current liabilities 30, non-current 20, total assets 100
  news published 2026-09-23 20:00 IST; dividend ex 2026-10-05 announced 09-22
  pre-open tick of session 2026-09-24 at 09:05 IST: IEP 180.5, tbq 3000, tsq 1000,
  ieq 5000 (knowable at 09:05: PRE_OPEN sees it, PRE_SESSION does not)
No FII/DII or global rows: those features are MISSING_INPUT here.
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid

from sqlalchemy import text

from app.core.clock import IST
from tests.support.stage2_seed import _payload, _run

D = _dt.date
NOW = _dt.datetime(2026, 9, 24, 12, 0, tzinfo=IST)
SESSION = D(2026, 9, 24)
SPECIAL = D(2026, 9, 19)
A, B, C, DD, E = ("NSE_EQ|INE000A00001", "NSE_EQ|INE000B00001", "NSE_EQ|INE000C00001",
                  "NSE_EQ|INE000D00001", "NSE_EQ|INE000E00001")
NIFTY, BANK, VIX = "NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank", "NSE_INDEX|India VIX"
STOCKS = (A, B, C, DD, E)
BONUS_EX = D(2026, 9, 10)


def ist(y, m, d, hh=0, mm=0, ss=0):
    return _dt.datetime(y, m, d, hh, mm, ss, tzinfo=IST)


def sessions() -> list[_dt.date]:
    out, d = [], D(2026, 6, 1)
    while d <= D(2026, 9, 30):
        if d.weekday() < 5 or d == SPECIAL:
            out.append(d)
        d += _dt.timedelta(days=1)
    return out


def history() -> list[_dt.date]:
    """Sessions with a stored bar (before the snapshot session)."""
    return [d for d in sessions() if d < SESSION]


def close_of(key: str, i: int) -> float:
    return {A: 100 + i, B: 200 + 2 * i, C: 50 + 0.5 * i, DD: 80 + 0.25 * i, E: 300 + i,
            NIFTY: 20000 + 10 * i, BANK: 45000 + 20 * i, VIX: 12 + 0.1 * i}[key]


async def insert_bar(s, ids, key, day, close, *, rid, sha, knowable=None, volume=None, i=0):
    await s.execute(text("""
        insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc, source,
          instrument_key, open, high, low, close, volume, vendor_ts_raw, run_id,
          payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values (:iid, '1d', :d, :b, 'UPSTOX_REST_V3', :k, :o, :h, :l, :c, :v, 'x', :r, :sha,
                :kn, :kn, false, 't')"""),
        {"iid": ids[key], "d": day, "b": ist(day.year, day.month, day.day), "k": key,
         "o": close - 0.5, "h": close + 1, "l": close - 1, "c": close,
         "v": volume if volume is not None else 1000 + 10 * i, "r": rid, "sha": sha,
         "kn": knowable or ist(day.year, day.month, day.day, 16)})


async def insert_basis(s, sha, basis="RAW_OBSERVED"):
    await s.execute(text("""insert into ohlcv_payload_basis (payload_sha256, endpoint,
        price_basis, basis_as_of, basis_confidence, method_version) values
        (:h, 'historical', :b, '2026-09-30', 'HIGH', 'test')"""), {"h": sha, "b": basis})


async def _fund(s, key, isin, stype, payload, rid, sha, t):
    await s.execute(text("""
        insert into fundamental_snapshot (instrument_key, isin, statement_type, payload,
          source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
          knowable_at_basis) values (:k, :isin, :st, cast(:p as jsonb), 'UPSTOX_REST_V2',
          :r, :h, :t, :t, false, 'fetched')"""),
        {"k": key, "isin": isin, "st": stype, "p": json.dumps(payload), "r": rid, "h": sha,
         "t": t})


def _stmt(lines: dict[str, dict[str, float]], period: str = "yearly") -> dict:
    return {"type": "consolidated", "time_period": period, "full_statement": [
        {"particular": p, "history": [{"period": k, "value": v} for k, v in h.items()]}
        for p, h in lines.items()]}


async def seed(s) -> dict:
    ids: dict = {}
    base = await _run(s, "instrument.current", source="UPSTOX_ASSETS")
    bsha = await _payload(s, base, "UPSTOX_ASSETS")
    for key, seg, sym, isin, typ in (
            (A, "NSE_EQ", "AAA", "INE000A00001", "EQ"), (B, "NSE_EQ", "BBB", "INE000B00001", "EQ"),
            (C, "NSE_EQ", "CCC", "INE000C00001", "EQ"), (DD, "NSE_EQ", "DDD", "INE000D00001", "EQ"),
            (E, "NSE_EQ", "EEE", "INE000E00001", "EQ"),
            (NIFTY, "NSE_INDEX", "Nifty 50", None, None),
            (BANK, "NSE_INDEX", "Nifty Bank", None, None),
            (VIX, "NSE_INDEX", "India VIX", None, None)):
        ids[key] = (await s.execute(text("""
            insert into instrument (instrument_key, segment, exchange, trading_symbol, isin,
              instrument_type, valid_from, source, run_id, payload_sha256, fetched_at,
              knowable_at, knowable_at_basis)
            values (:k, :seg, 'NSE', :sym, :isin, :typ, '2026-05-01', 'UPSTOX_ASSETS', :r, :h,
                    :f, :f, 't') returning instrument_id"""),
            {"k": key, "seg": seg, "sym": sym, "isin": isin, "typ": typ, "r": base, "h": bsha,
             "f": ist(2026, 5, 1)})).scalar()

    cal = await _run(s, "calendar.nse", source="UPSTOX_REST_V2")
    csha = await _payload(s, cal, "UPSTOX_REST_V2")
    trading = set(sessions())
    d = D(2026, 6, 1)
    while d <= D(2026, 9, 30):
        t = d in trading
        special = d == SPECIAL
        await s.execute(text("""
            insert into trading_session (session_date, is_trading_day, session_type,
              preopen_start_ist, preopen_end_ist, open_ist, close_ist, source, run_id,
              payload_sha256, fetched_at, knowable_at, knowable_at_basis)
            values (:d, :t, :ty, :ps, :pe, :o, :c, 'UPSTOX_REST_V2', :r, :h, :f, :f, 't')"""),
            {"d": d, "t": t, "ty": "SPECIAL" if special else ("NORMAL" if t else "WEEKEND"),
             "ps": _dt.time(9, 0) if t and not special else None,
             "pe": _dt.time(9, 8) if t and not special else None,
             "o": _dt.time(9, 15) if t else None, "c": _dt.time(15, 30) if t else None,
             "r": cal, "h": csha, "f": ist(2026, 5, 1)})
        d += _dt.timedelta(days=1)

    # daily bars: one payload per instrument (its basis is per payload)
    bars = await _run(s, "ohlcv.1d.seed")
    for key in (*STOCKS, NIFTY, BANK, VIX):
        sha = await _payload(s, bars)
        ids[f"sha:{key}"] = sha
        for i, day in enumerate(history()):
            c = close_of(key, i)
            if key == B and day >= BONUS_EX:
                c = c / 2                              # after the 1:1 bonus the price halves
            await insert_bar(s, ids, key, day, c, rid=bars, sha=sha, i=i)
        await insert_basis(s, sha, "VENDOR_ADJUSTED" if key == E else "RAW_OBSERVED")

    facts = await _run(s, "facts", source="UPSTOX_REST_V2")
    fsha = await _payload(s, facts, "UPSTOX_REST_V2")
    # B's bonus (+ its exact factor) and A's upcoming dividend
    for key, isin, kind, ex, ann, kn in (
            (B, "INE000B00001", "BONUS", BONUS_EX, D(2026, 8, 20), ist(2026, 8, 20, 23, 59, 59)),
            (A, "INE000A00001", "DIVIDEND", D(2026, 10, 5), D(2026, 9, 22),
             ist(2026, 9, 22, 23, 59, 59))):
        ca = (await s.execute(text("""
            insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
              ex_date, announcement_date, content_sha256, vendor_payload, source, run_id,
              payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values (:isin, :k, 'X', :t, :x, :a, :c, '{}', 'UPSTOX_REST_V2', :r, :h, :kn, :kn,
                    false, 'KN-CA') returning id"""),
            {"isin": isin, "k": key, "t": kind, "x": ex, "a": ann, "c": uuid.uuid4().hex * 2,
             "r": facts, "h": fsha, "kn": kn})).scalar()
        if kind == "BONUS":
            ids["bonus_ca"] = ca
            await s.execute(text("""
                insert into ca_factor (ca_id, instrument_key, action_type, ex_date, status,
                  method, factor_price, factor_volume, knowable_at, vendor_applied, reason,
                  method_version, derived_at, run_id) values (:c, :k, 'BONUS', :x, 'EXACT',
                  'BONUS_RATIO', 2, 2, :kn, 'NOT_APPLIED', 'test', 'cafactor-v1', now(), :r)"""),
                {"c": ca, "k": key, "x": ex, "kn": kn, "r": facts})

    t_f = ist(2026, 9, 1, 12)
    for key, isin in ((A, "INE000A00001"), (B, "INE000B00001"), (C, "INE000C00001"),
                      (DD, "INE000D00001"), (E, "INE000E00001")):
        await _fund(s, key, isin, "profile", {"sector": "Refineries"}, facts, fsha, t_f)
    await _fund(s, A, "INE000A00001", "key_ratios", [
        {"name": "P/E", "company_value": "20", "sector_value": "25"},
        {"name": "P/B", "company_value": "3", "sector_value": "2"},
        {"name": "ROE", "company_value": "15%", "sector_value": "12%"},
        {"name": "ROCE", "company_value": "18%", "sector_value": "14%"},
        {"name": "EV/EBITDA", "company_value": "11", "sector_value": "12"}], facts, fsha, t_f)
    await _fund(s, DD, "INE000D00001", "key_ratios", "not a list", facts, fsha, t_f)
    await _fund(s, A, "INE000A00001", "income:consolidated:yearly", _stmt({
        "Revenue": {"Mar 2026": 120, "Mar 2025": 100},
        "Profit After Tax": {"Mar 2026": 12, "Mar 2025": 10},
        "EPS - Diluted": {"Mar 2026": 6, "Mar 2025": 5}}), facts, fsha, t_f)
    await _fund(s, A, "INE000A00001", "income:consolidated:quarterly", _stmt({
        "Revenue": {"Mar 2026": 120, "Mar 2025": 100}}, "quarterly"), facts, fsha, t_f)
    await _fund(s, A, "INE000A00001", "balance_sheet:consolidated", _stmt({
        "Current Liabilities": {"Mar 2026": 30}, "Non-Current Liabilities": {"Mar 2026": 20},
        "Total Assets": {"Mar 2026": 100}}), facts, fsha, t_f)

    nid = (await s.execute(text("""
        insert into news_article (headline, published_at, headline_sha256, vendor_payload,
          source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
          knowable_at_basis) values ('A news', :p, :hs, '{}', 'UPSTOX_REST_V2', :r, :h,
          :p, :p, true, 'published') returning id"""),
        {"p": ist(2026, 9, 23, 20), "hs": "f" * 64, "r": facts, "h": fsha})).scalar()
    await s.execute(text("""
        insert into news_instrument (news_id, instrument_key, source, run_id, payload_sha256,
          fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values (:n, :k, 'UPSTOX_REST_V2', :r, :h, :f, :f, false, 'link')"""),
        {"n": nid, "k": A, "r": facts, "h": fsha, "f": ist(2026, 9, 23, 20)})

    await s.execute(text("""
        insert into preopen_tick (session_date, instrument_key, instrument_id, frame_seq,
          vendor_ts, feed_type, request_mode, iep, ieq, tbq, tsq, iiq_total, source, run_id,
          payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values (:d, :k, :i, 1, :t, 'ff', 'full', 180.5, 5000, 3000, 1000, 0,
                'UPSTOX_WS_V3', :r, :h, :t, :t, true, 'currentTs')"""),
        {"d": SESSION, "k": A, "i": ids[A], "t": ist(2026, 9, 24, 9, 5), "r": facts, "h": fsha})
    return ids
