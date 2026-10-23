"""Results events (F2, F5b, F4) and the event-driven fundamentals refresh (F1); docs/
STAGE1_FUNDAMENTALS_RND.md, approved 2026-10-19. Writes need the write token.

  extract_events   NSE announcements -> INTIMATION / OUTCOME; results headlines of the other
                   news sources -> ESTIMATE_NEWS. Reads only rows already in news_item and
                   their entity links (no vendor call). Idempotent: a text already stored
                   under the parser version is skipped (on conflict do nothing)
  due_refreshes    OUTCOME events whose instrument has no fundamental_refresh row yet
  refresh          one Upstox fundamentals run per due ISIN (the existing ingestor, batch
                   1, so every refresh has its own run and inserted count)
  import_results_csv  F4: a user-exported NSE Financial Results CSV -> HISTORICAL_FILING

Point in time: an event is knowable when Prajna had both the news row and its instrument
link (the later of the two). event_at is the exchange's / publisher's own time and never
later than knowable_at (otherwise it is dropped and flagged).
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import json
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.core.clock import IST, now
from app.fundamentals import events as E

# a Decimal: a float 0.9 is bound as numeric 0.90000000000000002..., which excludes 0.900
LINK_MIN_CONFIDENCE = Decimal("0.9")         # NSE announcements (symbol / company name)
# the news sources' links reach 0.80 (company name) / 0.85 (alias) only (2026-10-21: the
# 0.9 threshold excluded every news headline); a headline must also name exactly one
NEWS_LINK_MIN_CONFIDENCE = Decimal("0.8")
ANNOUNCEMENT_SOURCE = "NSE_ANNOUNCEMENTS"
ANNOUNCEMENT_CATEGORIES = ("Board Meeting Intimation", *E.OUTCOME_CATEGORIES,
                           *E.OUTCOME_IF_RESULTS)
NEWS_PREFILTER = r"(estimate|expectation|street|consensus|poll|forecast)"
CSV_SOURCE = "NSE_FINANCIAL_RESULTS_CSV"

_INSERT = text("""insert into results_event (kind, instrument_key, isin, news_item_id,
    meeting_date, period_end, period_kind, verdict, flags, event_at, knowable_at, source,
    provenance, text_sha256, parser_version, created_at)
    values (:kind, :key, :isin, :nid, :md, :pe, :pk, :v, :fl, :ea, :ka, :src,
            cast(:prov as jsonb), :sha, :pv, :ca)
    on conflict on constraint uq_results_event_text do nothing""")


def _times(published: _dt.datetime | None, knowable: _dt.datetime
           ) -> tuple[_dt.datetime | None, tuple[str, ...]]:
    if published is not None and published > knowable:
        return None, ("EVENT_AT_AFTER_KNOWABLE",)
    return published, ()


async def _candidates(s: AsyncSession) -> list[Any]:
    """News rows of interest with their single best instrument link, not yet stored."""
    return (await s.execute(text("""
        with links as (
          select l.item_id, l.instrument_key, l.knowable_at, l.confidence,
                 count(*) over (partition by l.item_id) as n_links,
                 row_number() over (partition by l.item_id
                                    order by l.confidence desc, l.instrument_key) as rk
            from news_entity_link l where l.confidence >= cast(:cn as numeric))
        select n.id, n.source, n.category_raw, n.title, n.summary, n.published_at,
               greatest(n.knowable_at, k.knowable_at) as knowable_at, k.instrument_key,
               k.n_links, i.isin
          from news_item n
          join links k on k.item_id = n.id and k.rk = 1
          left join instrument i on i.instrument_key = k.instrument_key
                                and i.valid_to = 'infinity'
         where ((n.source = :ann and n.category_raw = any(cast(:cats as text[]))
                 and k.confidence >= cast(:c as numeric))
             or (n.source <> :ann and n.title ~* :pre))
           and not exists (select 1 from results_event e where e.news_item_id = n.id
                             and e.parser_version = :pv)
         order by n.id"""), {"c": LINK_MIN_CONFIDENCE, "cn": NEWS_LINK_MIN_CONFIDENCE,
                             "ann": ANNOUNCEMENT_SOURCE,
                             "cats": list(ANNOUNCEMENT_CATEGORIES), "pre": NEWS_PREFILTER,
                             "pv": E.PARSER_VERSION})).all()


def event_for(row: Any) -> E.Event | None:
    pub = (row.published_at or row.knowable_at).astimezone(IST).date()
    if row.source == ANNOUNCEMENT_SOURCE:
        return E.classify_announcement(row.category_raw, row.summary, pub)
    if row.n_links != 1:                     # a headline about several names: ambiguous
        return None
    return E.classify_news(row.title, pub)


async def extract_events(s: AsyncSession, *, commit: bool = False,
                         token: str | None = None) -> dict[str, Any]:
    fp = authorize_write(token) if commit else None
    rows = await _candidates(s)
    out: dict[str, Any] = {"commit": commit, "candidates": len(rows), "by_kind": {},
                           "no_event": 0, "flags": {}, "inserted": 0}
    params = []
    for r in rows:
        ev = event_for(r)
        if ev is None:
            out["no_event"] += 1
            continue
        ea, fl = _times(r.published_at, r.knowable_at)
        flags = [*ev.flags, *fl]
        for f in flags:
            out["flags"][f] = out["flags"].get(f, 0) + 1
        out["by_kind"][ev.kind] = out["by_kind"].get(ev.kind, 0) + 1
        params.append({"kind": ev.kind, "key": r.instrument_key, "isin": r.isin,
                       "nid": r.id, "md": ev.meeting_date, "pe": ev.period_end,
                       "pk": ev.period_kind, "v": ev.verdict, "fl": flags, "ea": ea,
                       "ka": r.knowable_at, "src": r.source,
                       "prov": json.dumps({"category": r.category_raw,
                                           "authz": fp}),
                       "sha": E.text_sha256(r.category_raw, r.title, r.summary),
                       "pv": E.PARSER_VERSION, "ca": now()})
    if commit and params:
        before = await _count(s)
        await s.execute(_INSERT, params)
        await s.commit()
        out["inserted"] = await _count(s) - before
    return out


async def _count(s: AsyncSession) -> int:
    return int((await s.execute(text("select count(*) from results_event"))).scalar())


async def due_refreshes(s: AsyncSession, *, max_age_days: int = 10) -> list[Any]:
    """OUTCOME events (knowable within max_age_days) with no refresh of their instrument
    after the event; one row per ISIN (its latest event)."""
    return (await s.execute(text("""
        select distinct on (e.isin) e.id, e.instrument_key, e.isin, e.knowable_at
          from results_event e
         where e.kind = 'OUTCOME' and e.isin is not null
           and e.knowable_at > now() - make_interval(days => :d)
           and not exists (select 1 from fundamental_refresh f
                            where f.instrument_key = e.instrument_key
                              and f.refreshed_at > e.knowable_at
                              and f.status = 'COMPLETE')
         order by e.isin, e.knowable_at desc"""), {"d": max_age_days})).all()


async def refresh(s: AsyncSession, rest, store, *, commit: bool = False,
                  token: str | None = None, max_age_days: int = 10,
                  limit: int | None = None) -> dict[str, Any]:
    from app.ingest.fundamentals import FundamentalsIngestor

    fp = authorize_write(token) if commit else None
    due = await due_refreshes(s, max_age_days=max_age_days)
    due = due[:limit] if limit else due
    out: dict[str, Any] = {"commit": commit, "due": len(due), "refreshed": 0,
                           "inserted": 0, "problems": []}
    if not commit:
        out["isins"] = [d.isin for d in due]
        return out
    ing = FundamentalsIngestor(s, rest, store, commit=True, token=token,
                               operator="fundamentals-refresh", batch=1)
    for d in due:
        rep = await ing.run([d.isin])
        r = rep.results[0]
        # every outcome event of this instrument that is now covered by this refresh
        await s.execute(text("""insert into fundamental_refresh (event_id, instrument_key,
            isin, run_id, status, snapshots_inserted, refreshed_at, authz_token_sha256)
            select e.id, e.instrument_key, :isin, :run, :st, :ins, :at, :fp
              from results_event e
             where e.kind = 'OUTCOME' and e.instrument_key = :key and e.knowable_at <= :at
               and not exists (select 1 from fundamental_refresh f
                                where f.event_id = e.id and f.instrument_key = e.instrument_key)
            on conflict on constraint uq_fundamental_refresh_event do nothing"""),
            {"isin": d.isin, "run": r.run_id, "st": r.status, "ins": r.inserted,
             "at": now(), "fp": fp, "key": d.instrument_key})
        await s.commit()
        out["refreshed"] += r.status == "COMPLETE"
        out["inserted"] += r.inserted
        if r.status != "COMPLETE":
            out["problems"].append({"isin": d.isin, "status": r.status, "error": r.error})
        if rep.stopped:
            out["stopped"] = rep.stopped
            break
    return out


# ── F4: a user-exported NSE Financial Results CSV ────────────────────────────────────
_COLS = {"symbol": ("symbol",), "company": ("company name", "company"),
         "period_end": ("period ended", "quarter end date", "to date", "period end"),
         "relating_to": ("relating to", "period"),
         # the exchange's dissemination time first: the latest of the file's times, when
         # the filing became public (the received / broadcast time is earlier)
         "broadcast": ("exchange dissemination time", "exchange disseminated time",
                       "broadcast date/time", "broadcast date", "filing date",
                       "submission date"),
         "basis": ("consolidated / standalone", "consolidated / non-consolidated"),
         "audited": ("audited / unaudited", "audited"),
         "submission": ("type of submission",)}
_TS_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%d-%m-%Y %H:%M:%S",
               "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


class CsvRefused(ValueError):
    pass


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", h.replace("﻿", "").strip().lower())


def map_columns(header: list[str]) -> dict[str, int]:
    """Our field -> column index; refuses a file without a symbol (or company name),
    period and broadcast. The Financial Results export has no symbol column: its rows are
    mapped by company name (names_from_csv)."""
    idx = {_norm(h): i for i, h in enumerate(header)}
    out = {}
    for field, names in _COLS.items():
        for n in names:
            if n in idx:
                out[field] = idx[n]
                break
    missing = [f for f in ("period_end", "broadcast") if f not in out]
    if "symbol" not in out and "company" not in out:
        missing.insert(0, "symbol")
    if missing:
        raise CsvRefused(f"columns not found: {missing}; header was {header}")
    return out


def parse_ts(v: str) -> _dt.datetime | None:
    v = (v or "").strip()
    for f in _TS_FORMATS:
        try:
            return _dt.datetime.strptime(v, f).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def parse_csv(data: bytes) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    if not rows:
        raise CsvRefused("empty file")
    cols = map_columns(rows[0])
    quarterly = "quarter end date" in {_norm(h) for h in rows[0]}
    out, bad = [], {"no_symbol": 0, "no_period": 0, "no_broadcast": 0}
    for r in rows[1:]:
        if not any(x.strip() for x in r):
            continue
        g = {f: (r[i].strip() if i < len(r) else "") for f, i in cols.items()}
        pe, ts = E.parse_period_end(g["period_end"]), parse_ts(g["broadcast"])
        if not (g.get("symbol") or g.get("company")):
            bad["no_symbol"] += 1
        elif pe is None:
            bad["no_period"] += 1
        elif ts is None:
            bad["no_broadcast"] += 1
        else:
            out.append({**g, "period_end": pe, "broadcast": ts, "quarterly": quarterly,
                        "row_sha256": hashlib.sha256("\x1f".join(r).encode()).hexdigest()})
    return out, bad


def norm_company(name: str) -> str:
    """'Tata Consultancy Services Limited' / 'TATA CONSULTANCY SERVICES LTD.' -> one key."""
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and "))
    n = re.sub(r"\s+", " ", n).strip()
    return re.sub(r"( limited| ltd)$", "", n)


def names_from_csv(data: bytes) -> dict[str, str]:
    """company -> symbol from an NSE export that has both columns (Integrated Filing); a
    name that maps to two symbols is left out rather than guessed."""
    rows, _ = parse_csv(data)
    seen: dict[str, set[str]] = {}
    for r in rows:
        if r.get("symbol") and r.get("company"):
            seen.setdefault(norm_company(r["company"]), set()).add(r["symbol"])
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


async def import_results_csv(s: AsyncSession, data: bytes, filename: str, *,
                             commit: bool = False, token: str | None = None,
                             names: dict[str, str] | None = None) -> dict[str, Any]:
    fp = authorize_write(token) if commit else None
    file_sha = hashlib.sha256(data).hexdigest()
    rows, bad = parse_csv(data)
    by_name = 0
    for r in rows:
        if not r.get("symbol"):
            r["symbol"] = (names or {}).get(norm_company(r.get("company", "")), "")
            by_name += bool(r["symbol"])
    no_name = sum(1 for r in rows if not r["symbol"])
    rows = [r for r in rows if r["symbol"]]
    syms = sorted({r["symbol"] for r in rows})
    keys = dict((await s.execute(text("""select trading_symbol, instrument_key from instrument
        where segment = 'NSE_EQ' and valid_to = 'infinity' and trading_symbol = any(:s)"""),
        {"s": syms})).all())
    isins = dict((await s.execute(text("""select instrument_key, isin from instrument
        where valid_to = 'infinity' and instrument_key = any(:k)"""),
        {"k": list(keys.values())})).all())
    loaded_at = now()
    params, unmapped = [], 0
    for r in rows:
        key = keys.get(r["symbol"])
        if key is None:
            unmapped += 1
            continue
        params.append({"kind": "HISTORICAL_FILING", "key": key, "isin": isins.get(key),
                       "nid": None, "md": None, "pe": r["period_end"],
                       "pk": E.period_kind(r.get("relating_to") or "")
                       or ("Q" if r["quarterly"] else None), "v": None, "fl": [],
                       # the exchange's own time; knowable to Prajna only when loaded
                       "ea": r["broadcast"], "ka": loaded_at, "src": CSV_SOURCE,
                       "prov": json.dumps({"file": filename, "file_sha256": file_sha,
                                           "relating_to": r.get("relating_to"),
                                           "company": r.get("company"),
                                           "basis": r.get("basis"),
                                           "audited": r.get("audited"),
                                           "submission": r.get("submission"),
                                           "authz": fp}),
                       "sha": r["row_sha256"], "pv": "nse-csv-v2", "ca": loaded_at})
    out = {"commit": commit, "file_sha256": file_sha, "rows": len(rows) + no_name,
           "bad": bad, "mapped_by_name": by_name, "no_name_match": no_name,
           "unmapped_symbols": unmapped, "events": len(params), "inserted": 0}
    if commit and params:
        before = await _count(s)
        await s.execute(_INSERT, params)
        await s.commit()
        out["inserted"] = await _count(s) - before
    return out


# ── F3 / F5a read path ───────────────────────────────────────────────────────────────
async def ratios_as_of(s: AsyncSession, instrument_key: str, as_of: _dt.datetime
                       ) -> dict[str, Any] | None:
    """The F3 ratios and F5a surprise of one instrument from what was knowable at as_of:
    snapshots with knowable_at < as_of, and the last daily close knowable before as_of."""
    from app.fundamentals import ratios as R

    snaps: dict[str, list] = {}
    for st, k, p in (await s.execute(text("""select statement_type, knowable_at, payload
            from canon_fundamental where instrument_key = :k and knowable_at < :a"""),
            {"k": instrument_key, "a": as_of})).all():
        snaps.setdefault(st, []).append((k, p))
    f = R.build(snaps)
    if f is None:
        return None
    px = (await s.execute(text("""select close, market_date from canon_market_bar
        where instrument_key = :k and timeframe = '1d' and knowable_at < :a
        order by market_date desc limit 1"""), {"k": instrument_key, "a": as_of})).first()
    out = R.ratios(f, float(px.close) if px else None)
    out["price_date"] = px.market_date if px else None
    return out


# ── criterion FUND (report; not wired into the Stage 1 gate until it PASSES) ─────────
FUND_SESSIONS, FUND_SHARE = 10, 0.95


async def fund_report(s: AsyncSession) -> dict[str, Any]:
    """FUND PASSES when, over >= 10 trading sessions of F1 operation: >= 95 % of the
    results outcomes were refreshed (COMPLETE) by the end of the next trading day, >= 95 %
    of the results intimations carry a meeting date and a period, and no fundamentals
    snapshot is knowable before it was fetched."""
    first = (await s.execute(text("select min(refreshed_at) from fundamental_refresh"))).scalar()
    sessions = int((await s.execute(text("""select count(*) from trading_session
        where is_trading_day and session_date >= (:f at time zone 'Asia/Kolkata')::date
          and session_date < (now() at time zone 'Asia/Kolkata')::date"""),
        {"f": first or now()})).scalar()) if first else 0
    lat = (await s.execute(text("""
        with ev as (
          select e.id, e.instrument_key, e.knowable_at,
                 (select min(t.session_date) from trading_session t where t.is_trading_day
                    and t.session_date > (e.knowable_at at time zone 'Asia/Kolkata')::date) nd
            from results_event e
           where e.kind = 'OUTCOME' and e.isin is not null and e.knowable_at >= :f)
        select count(*) filter (where nd < (now() at time zone 'Asia/Kolkata')::date) due,
               count(*) filter (where nd < (now() at time zone 'Asia/Kolkata')::date
                 and exists (select 1 from fundamental_refresh f where f.event_id = ev.id
                   and f.status = 'COMPLETE'
                   and (f.refreshed_at at time zone 'Asia/Kolkata')::date <= ev.nd)) on_time
          from ev"""), {"f": first or now()})).one()
    intim = (await s.execute(text("""select count(*) n,
        count(*) filter (where meeting_date is not null and period_end is not null) ok
        from results_event where kind = 'INTIMATION'"""))).one()
    viol = int((await s.execute(text("""select count(*) from fundamental_snapshot
        where knowable_at > fetched_at or knowable_at is null"""))).scalar())
    kinds = dict((await s.execute(text("""select kind, count(*) from results_event
        group by 1"""))).all())
    on_share = lat.on_time / lat.due if lat.due else None
    int_share = intim.ok / intim.n if intim.n else None
    checks = {"sessions": sessions >= FUND_SESSIONS,
              "refresh_on_time": on_share is not None and on_share >= FUND_SHARE,
              "intimation_parsed": int_share is not None and int_share >= FUND_SHARE,
              "no_snapshot_before_fetch": viol == 0}
    status = ("PASS" if all(checks.values()) else
              "FAIL" if viol or (sessions >= FUND_SESSIONS and not all(checks.values()))
              else "PENDING")
    return {"criterion": "FUND", "status": status, "checks": checks,
            "f1_first_refresh": first, "sessions_of_operation": sessions,
            "outcomes_due": lat.due, "outcomes_refreshed_on_time": lat.on_time,
            "refresh_on_time_share": on_share, "intimations": intim.n,
            "intimations_parsed": intim.ok, "intimation_parsed_share": int_share,
            "snapshots_knowable_before_fetch": viol, "events_by_kind": kinds,
            "history_f4": {"HISTORICAL_FILING": kinds.get("HISTORICAL_FILING", 0),
                           "values_before_2026_09_24": "NOT_AVAILABLE_HISTORICALLY"},
            "estimates_f5": {"F5a_seasonal_random_walk": "computed (fund-ratios-v1)",
                             "F5b_estimate_news": kinds.get("ESTIMATE_NEWS", 0),
                             "F5c_numeric_consensus": "needs a licensed vendor (user decision)"}}
