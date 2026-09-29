"""Prajna read API (/v1): documented contracts over the Stage 2 canonical layer.

READ-ONLY: every request runs in a READ ONLY transaction; there is no write
endpoint. Every data read goes through app.canon.pit (knowable_at < as_of,
re-checked row by row) or a canonical view with the same rule, so a client
cannot see a value earlier than Prajna knew it. `as_of` defaults to now: for
live use that is "everything knowable so far"; for research pass a past
instant. Nothing here computes features, signals or decisions: Stage 3
feature endpoints serve STORED values only (empty while Stage 3 production
execution is locked), and nothing is shaped for one particular frontend.

Serve (localhost by default; expose beyond it only behind an authenticating
reverse proxy):  .venv/bin/python -m app.readapi  [--host 127.0.0.1 --port 8090]
Browser clients: set PRAJNA_API_CORS_ORIGINS (comma-separated) - default none.
OpenAPI: /v1/openapi.json, docs: /v1/docs. Contract: docs/API_CONTRACT.md.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.canon.validate import CANON_TIMEFRAMES
from app.core.clock import IST, now, to_utc
from app.db.engine import get_sessionmaker
from app.readapi import schemas as S

BASE = pathlib.Path(__file__).resolve().parents[2]
API_VERSION = "v1"
MAX_LIMIT = 5000

api = FastAPI(title="Prajna read API", version="1.0.0",
              description=(__doc__ or "").split("\n\n")[1],
              openapi_url="/v1/openapi.json", docs_url="/v1/docs", redoc_url=None)
_origins = [o.strip() for o in os.environ.get("PRAJNA_API_CORS_ORIGINS", "").split(",")
            if o.strip()]
if _origins:
    api.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET"],
                       allow_headers=["*"])


async def session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction read only"))
        yield s


DB = Annotated[AsyncSession, Depends(session)]
AsOf = Annotated[_dt.datetime | None, Query(
    description="knowledge instant (ISO-8601 with offset); default now")]


def _as_of(as_of: _dt.datetime | None) -> _dt.datetime:
    if as_of is None:
        return now()
    if as_of.tzinfo is None:
        raise HTTPException(422, "as_of needs a UTC offset (e.g. 2026-09-25T10:00:00+05:30)")
    return to_utc(as_of)


def _meta(as_of: _dt.datetime, pit_: bool, *notes: str) -> S.Meta:
    return S.Meta(as_of=as_of, generated_at=now(), point_in_time=pit_, notes=list(notes))


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


INSTRUMENT_SQL = """
    select ci.instrument_key, ci.trading_symbol, ci.name, ci.isin, ci.segment, ci.exchange,
           ci.instrument_type, sc.security_class, ci.lifecycle_status, ci.lifecycle_since,
           ci.sector
    from canon_instrument ci
    left join instrument_security_class sc on sc.instrument_key = ci.instrument_key
    where ci.included"""


async def _instrument(s: AsyncSession, key: str) -> dict:
    row = (await s.execute(text(INSTRUMENT_SQL + " and ci.instrument_key = :k"),
                           {"k": key})).mappings().first()
    if row is None:
        raise HTTPException(404, f"unknown or excluded instrument {key!r}")
    return dict(row)


# ── 1. instruments ──────────────────────────────────────────────────────────
@api.get("/v1/instruments", response_model=S.Envelope[list[S.Instrument]], tags=["instruments"])
async def instruments(s: DB, segment: str | None = None, security_class: str | None = None,
                      lifecycle_status: str | None = "ACTIVE", sector: str | None = None,
                      limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 500,
                      offset: Annotated[int, Query(ge=0)] = 0):
    """The canonical NSE universe (current state). Default: ACTIVE listings;
    lifecycle_status=ANY for every status. An empty filter value means no filter."""
    where = """
        and (cast(:seg as text) is null or ci.segment = :seg)
        and (cast(:cls as text) is null or sc.security_class = :cls)
        and (cast(:life as text) is null or ci.lifecycle_status = :life)
        and (cast(:sec as text) is null or ci.sector = :sec)"""
    def opt(v: str | None) -> str | None:                    # "" and ANY: no filter
        return None if v in (None, "", "ANY") else v
    params = {"seg": opt(segment), "cls": opt(security_class), "life": opt(lifecycle_status),
              "sec": opt(sector)}
    total = (await s.execute(text(f"select count(*) from ({INSTRUMENT_SQL} {where}) x"),  # noqa: S608
                             params)).scalar()
    rows = (await s.execute(text(INSTRUMENT_SQL + where +
                                 " order by ci.trading_symbol limit :l offset :o"),
                            {**params, "l": limit, "o": offset})).mappings().all()
    meta = _meta(now(), False, "current universe; lifecycle history: /profile")
    meta.total = total
    return S.Envelope(data=[S.Instrument(**r) for r in rows], meta=meta)


# ── 2. search ───────────────────────────────────────────────────────────────
@api.get("/v1/search", response_model=S.Envelope[list[S.SearchHit]], tags=["instruments"])
async def search(s: DB, q: Annotated[str, Query(min_length=1, max_length=64)],
                 limit: Annotated[int, Query(ge=1, le=100)] = 20):
    """Symbol / ISIN / name search, ranked: exact symbol, symbol prefix, ISIN, name."""
    rows = (await s.execute(text(f"""
        select * from (
          select x.*, case when upper(x.trading_symbol) = upper(:q) then 'SYMBOL_EXACT'
                           when upper(x.trading_symbol) like upper(:q) || '%' then 'SYMBOL_PREFIX'
                           when upper(x.isin) = upper(:q) then 'ISIN'
                           else 'NAME' end as match
          from ({INSTRUMENT_SQL}) x
          where upper(x.trading_symbol) like upper(:q) || '%' or upper(x.isin) = upper(:q)
             or x.name ilike '%' || :q || '%') y
        order by case match when 'SYMBOL_EXACT' then 0 when 'SYMBOL_PREFIX' then 1
                            when 'ISIN' then 2 else 3 end,
                 lifecycle_status = 'ACTIVE' desc, trading_symbol
        limit :l"""), {"q": q, "l": limit})).mappings().all()          # noqa: S608
    return S.Envelope(data=[S.SearchHit(**r) for r in rows], meta=_meta(now(), False))


# ── 3. profile (incl. 8. sector) ────────────────────────────────────────────
@api.get("/v1/instruments/{instrument_key}/profile", response_model=S.Envelope[S.Profile],
         tags=["instruments"])
async def profile(s: DB, instrument_key: str, as_of: AsOf = None):
    at = _as_of(as_of)
    inst = await _instrument(s, instrument_key)
    sig = (await s.execute(text("select signals from instrument_security_class where "
                                "instrument_key = :k"), {"k": instrument_key})).scalar()
    periods = [dict(r) for r in (await s.execute(text("""
        select p.status, p.valid_from, p.valid_to, p.reason, p.knowable_at
        from instrument_lifecycle_period p join instrument i using (instrument_id)
        where i.instrument_key = :k and p.knowable_at < :a order by p.valid_from"""),
        {"k": instrument_key, "a": at})).mappings().all()]
    prof = await pit.fundamentals(s, instrument_key, at, "profile")
    return S.Envelope(
        data=S.Profile(instrument=S.Instrument(**inst),
                       sector_as_of=await pit.sector(s, instrument_key, at),
                       security_class_signals=sig, lifecycle_periods=periods,
                       profile=prof[0]["payload"] if prof else None),
        meta=_meta(at, True, "instrument.sector is the CURRENT sector; sector_as_of is PIT"))


@api.get("/v1/sectors", response_model=S.Envelope[list[S.SectorCount]], tags=["instruments"])
async def sectors(s: DB):
    """Current sector distribution of ACTIVE stocks (security_class STOCK)."""
    rows = (await s.execute(text("""
        select ci.sector, count(*) as stocks from canon_instrument ci
        join instrument_security_class sc on sc.instrument_key = ci.instrument_key
        where ci.included and ci.lifecycle_status = 'ACTIVE' and sc.security_class = 'STOCK'
        group by 1 order by 2 desc"""))).mappings().all()
    return S.Envelope(data=[S.SectorCount(**r) for r in rows],
                      meta=_meta(now(), False, "sector null = not classified by the vendor"))


# ── 4. candles ──────────────────────────────────────────────────────────────
def _candle(r: dict, tf: str) -> S.Candle:
    return S.Candle(timeframe=tf, bar_start=r["bar_start_utc"], market_date=r["market_date"],
                    open=_f(r["open"]), high=_f(r["high"]), low=_f(r["low"]),
                    close=_f(r["close"]), volume=_f(r["volume"]),
                    open_interest=_f(r.get("open_interest")), knowable_at=r["knowable_at"],
                    fetched_at=r["fetched_at"], price_basis=r.get("price_basis"),
                    basis_as_of=r.get("basis_as_of"),
                    adjustment_status=r.get("adjustment_status"),
                    factor_applied=_f(r.get("factor_applied")),
                    basis_confidence=r.get("basis_confidence"))


@api.get("/v1/instruments/{instrument_key}/candles",
         response_model=S.Envelope[S.CandleSeries], tags=["market data"])
async def candles(s: DB, instrument_key: str,
                  timeframe: Annotated[str, Query(description="1m / 15m / 1h / 1d")],
                  as_of: AsOf = None, start: _dt.date | None = None,
                  end: _dt.date | None = None,
                  limit: Annotated[int | None, Query(ge=1, le=MAX_LIMIT)] = 500,
                  adjusted: bool = False, allow_low_confidence: bool = False):
    """OHLCV as knowable at as_of. adjusted=true: split/bonus-adjusted as a trader
    knew it then (pit.bars_adjusted); low-confidence / reconstructed rows are
    withheld unless allowed, and counted in `refused`."""
    if timeframe not in CANON_TIMEFRAMES:
        raise HTTPException(422, f"timeframe must be one of {', '.join(CANON_TIMEFRAMES)}")
    at = _as_of(as_of)
    await _instrument(s, instrument_key)
    if adjusted:
        res = await pit.bars_adjusted(s, instrument_key, timeframe, at, start=start, end=end,
                                      allow_low_confidence=allow_low_confidence)
        rows, refused = res["rows"][-limit:] if limit else res["rows"], res["refused"]
    else:
        rows = await pit.bars(s, instrument_key, timeframe, at, start=start, end=end,
                              limit=limit)
        refused = None
    return S.Envelope(
        data=S.CandleSeries(instrument_key=instrument_key, timeframe=timeframe,
                            adjusted=adjusted, candles=[_candle(r, timeframe) for r in rows],
                            refused=refused),
        meta=_meta(at, True, "missing bars are absent, never filled: see /quality",
                   "1d history before the CA horizon is vendor-adjusted as of its fetch"))


# ── 5. latest quote ─────────────────────────────────────────────────────────
@api.get("/v1/instruments/{instrument_key}/quote", response_model=S.Envelope[S.Quote],
         tags=["market data"])
async def quote(s: DB, instrument_key: str, as_of: AsOf = None):
    """The newest stored bars. Stage 1 keeps no canonical live tick store (criterion
    L: OUT_OF_SCOPE), so this is NOT a real-time quote; age_seconds says how old."""
    at = _as_of(as_of)
    await _instrument(s, instrument_key)
    m1 = await pit.bars(s, instrument_key, "1m", at, limit=1)
    d1 = await pit.bars(s, instrument_key, "1d", at, limit=1)
    newest = max((r["knowable_at"] for r in m1 + d1), default=None)
    return S.Envelope(
        data=S.Quote(instrument_key=instrument_key,
                     source="latest stored canonical bars (no live tick store in Stage 1)",
                     last_1m=_candle(m1[0], "1m") if m1 else None,
                     last_1d=_candle(d1[0], "1d") if d1 else None,
                     age_seconds=(at - newest).total_seconds() if newest else None),
        meta=_meta(at, True, "not a real-time quote"))


# ── 6. fundamentals ─────────────────────────────────────────────────────────
@api.get("/v1/instruments/{instrument_key}/fundamentals",
         response_model=S.Envelope[list[S.Fundamental]], tags=["reference data"])
async def fundamentals(s: DB, instrument_key: str, as_of: AsOf = None,
                       statement_type: str | None = None):
    """The latest snapshot per statement type knowable before as_of."""
    at = _as_of(as_of)
    await _instrument(s, instrument_key)
    rows = await pit.fundamentals(s, instrument_key, at, statement_type)
    return S.Envelope(data=[S.Fundamental(**{k: r[k] for k in S.Fundamental.model_fields})
                            for r in rows], meta=_meta(at, True))


# ── 7. corporate actions ────────────────────────────────────────────────────
@api.get("/v1/instruments/{instrument_key}/corporate-actions",
         response_model=S.Envelope[list[S.CorporateAction]], tags=["reference data"])
async def corporate_actions(s: DB, instrument_key: str, as_of: AsOf = None):
    """Actions knowable before as_of, with the versioned adjustment factor."""
    at = _as_of(as_of)
    await _instrument(s, instrument_key)
    rows = await pit.corporate_actions(s, at, instrument_key)
    fac = {r["ca_id"]: r for r in (await s.execute(text("""
        select ca_id, status, factor_price, vendor_applied from ca_factor
        where instrument_key = :k"""), {"k": instrument_key})).mappings().all()}
    out = []
    for r in rows:
        f = fac.get(r["id"], {})
        out.append(S.CorporateAction(
            id=r["id"], action_type=r["action_type"], announcement_date=r["announcement_date"],
            ex_date=r["ex_date"], record_date=r["record_date"], amount=_f(r["amount"]),
            ratio_from=_f(r["ratio_from"]), ratio_to=_f(r["ratio_to"]),
            face_value_before=_f(r["face_value_before"]),
            face_value_after=_f(r["face_value_after"]), knowable_at=r["knowable_at"],
            factor_status=f.get("status"), factor_price=_f(f.get("factor_price")),
            vendor_applied=f.get("vendor_applied")))
    return S.Envelope(data=out, meta=_meta(at, True, "the vendor feed is ~1 year deep"))


# ── 9. global markets ───────────────────────────────────────────────────────
@api.get("/v1/global", response_model=S.Envelope[list[S.GlobalInstrument]], tags=["global"])
async def global_markets(s: DB, as_of: AsOf = None):
    """The 13 global indices/indicators with their measured label contract and
    the latest CONFIRMED bar (unconfirmed, revised and placeholder bars are
    never exposed)."""
    at = _as_of(as_of)
    rows = (await s.execute(text("""
        select i.instrument_key, i.name, i.segment, c.label_semantics, c.confirm_hours
        from instrument i left join global_instrument_contract c using (instrument_key)
        where i.valid_to = 'infinity' and i.segment in ('GLOBAL_INDEX', 'GLOBAL_INDICATOR')
        order by i.instrument_key"""))).mappings().all()
    out = []
    for r in rows:
        # finality as of `at` (pit.global_bars), not today's (canon_global_bar)
        bars = sorted(await pit.global_bars(s, r["instrument_key"], at),
                      key=lambda b: b["label_date"])
        last = ({k: bars[-1][k] for k in ("label_date", "close", "finality", "knowable_at")}
                if bars else None)
        out.append(S.GlobalInstrument(**r, latest=last))
    return S.Envelope(data=out, meta=_meta(at, True, "labels are not trading dates (see "
                                                     "label_semantics)"))


@api.get("/v1/global/{instrument_key}/candles", response_model=S.Envelope[list[S.GlobalBar]],
         tags=["global"])
async def global_candles(s: DB, instrument_key: str, as_of: AsOf = None,
                         limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 250):
    at = _as_of(as_of)
    rows = await pit.global_bars(s, instrument_key, at)
    if not rows and not (await s.execute(text(
            "select 1 from instrument where instrument_key = :k and segment like 'GLOBAL%'"),
            {"k": instrument_key})).first():
        raise HTTPException(404, f"unknown global instrument {instrument_key!r}")
    return S.Envelope(data=[S.GlobalBar(
        label_date=r["label_date"], open=_f(r["open"]), high=_f(r["high"]), low=_f(r["low"]),
        close=_f(r["close"]), volume=_f(r["volume"]), finality=r["finality"],
        knowable_at=r["knowable_at"], first_fetched_at=r["first_fetched_at"])
        for r in rows[-limit:]], meta=_meta(at, True))


# ── 10. news ────────────────────────────────────────────────────────────────
@api.get("/v1/news", response_model=S.Envelope[list[S.NewsItem]], tags=["news"])
async def news(s: DB, as_of: AsOf = None, instrument_key: str | None = None,
               since: _dt.datetime | None = None,
               limit: Annotated[int, Query(ge=1, le=1000)] = 100):
    """Upstox news knowable before as_of (the article AND its instrument link), newest
    first. published_at = vendor time; received_at = Prajna's fetch. The
    multi-source layer (sources, stories, derived fields) is /v1/news/articles."""
    at = _as_of(as_of)
    rows = await pit.news(s, at, instrument_key, since)
    rows = sorted(rows, key=lambda r: (r["published_at"] or r["fetched_at"]), reverse=True)
    pub = dict((await s.execute(text("select id, publisher from news_article where id = any(:i)"),
                                {"i": [r["news_id"] for r in rows[:limit]]})).all())
    return S.Envelope(data=[S.NewsItem(
        news_id=r["news_id"], instrument_key=r["instrument_key"], headline=r["headline"],
        publisher=pub.get(r["news_id"]), url=r["url"], published_at=r["published_at"],
        received_at=r["fetched_at"],
        knowable_at=r["knowable_at"]) for r in rows[:limit]],
        meta=_meta(at, True, "the vendor serves 7 days of news; history starts 2026-09-24"))


# ── 10b. multi-source news (point in time; read only; derived != fact) ──────
NEWS_NOTES = ("knowable_at = Prajna's first observation (never the publication time); "
              "enrichments are visible only from their own knowable_at",
              "multi-source rows are visible only when written in PRODUCTION mode (currently "
              "locked: DRY_RUN only), so these lists are empty until a source is enabled",
              "derived fields are rule-based routing aids, not truth and not predictions; "
              "ai_enrichment is never a source fact")


def _article(r: dict, at: _dt.datetime) -> S.NewsArticle:
    lat = ((r["discovered_at"] - r["published_at"]).total_seconds()
           if r["published_at"] and not r["backlog"] and r["backlog"] is not None else None)
    return S.NewsArticle(
        id=r["id"], source=r["source"],
        source_fact={"title": r["title"], "summary": r["summary"], "publisher": r["publisher"],
                     "author": r["author"], "url": r["url"], "published_at": r["published_at"],
                     "published_at_raw": r["published_at_raw"],
                     "updated_at": r["source_updated_at"], "category_raw": r["category_raw"]},
        observation={"first_seen_at": r["discovered_at"], "knowable_at": r["knowable_at"],
                     "processed_at": r["processed_at"], "backlog": r["backlog"],
                     "edited": r["edited"],
                     "latency_class": None if r["backlog"] is None else
                     ("BACKLOG" if r["backlog"] else "LIVE_DISCOVERY"),
                     "discovery_latency_s": lat,
                     "seconds_since_first_observation": (at - r["knowable_at"]).total_seconds(),
                     "source_priority": r["source_priority"], "terms_status": r["terms_status"],
                     "content_fetch_status": r["content_fetch_status"]},
        derived={"category": r["category"], "category_method": r["category_method"],
                 "category_confidence": _f(r["category_confidence"]),
                 "market_scope": r["market_scope"], "potential_impact": r["potential_impact"],
                 "impact_direction": r["impact_direction"], "is_breaking": r["is_breaking"],
                 "breaking_reason": r["breaking_reason"],
                 "assessment_version": r["assessment_version"],
                 "event_group": (r["assessment_evidence"] or {}).get("event_group"),
                 "instruments": r["instruments"] or [], "entities": r["entities"] or [],
                 "story": None if r["story_id"] is None else {
                     "story_id": r["story_id"], "method": r["story_method"],
                     "score": _f(r["story_score"]), "evidence": r["story_evidence"]}},
        ai_enrichment=None if r["ai_output"] is None else {
            "output": r["ai_output"], "model_id": r["ai_model_id"],
            "prompt_version": r["ai_prompt_version"], "generated_at": r["ai_generated_at"],
            "label": "AI ENRICHMENT - not a source fact"})


def _upstox_on() -> bool:
    from app.core.config import get_settings
    return get_settings().PRAJNA_NEWS_UPSTOX_ENABLED


@api.get("/v1/news/articles", response_model=S.Envelope[list[S.NewsArticle]], tags=["news"])
async def news_articles(
        s: DB, as_of: AsOf = None, source: str | None = None, publisher: str | None = None,
        instrument_key: str | None = None, entity: str | None = None,
        category: str | None = None, market_scope: str | None = None,
        potential_impact: str | None = None, impact_direction: str | None = None,
        breaking: bool | None = None, story_id: int | None = None,
        since: _dt.datetime | None = None, include_upstox: bool = False,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0):
    """Multi-source news visible at as_of, newest knowable first, with filters
    (entity e.g. SECTOR:BANKING, INDEX:NIFTY_50, CENTRAL_BANK:RBI). include_upstox
    projects Stage 1 Upstox news (knowable at first fetch) when enabled."""
    from app.canon import news_pit as NP
    at = _as_of(as_of)
    rows = await NP.items(s, at, include_upstox=include_upstox and _upstox_on(), limit=limit,
                          offset=offset, source=source, publisher=publisher,
                          instrument_key=instrument_key, entity=entity, category=category,
                          market_scope=market_scope, potential_impact=potential_impact,
                          impact_direction=impact_direction, breaking=breaking,
                          story_id=story_id, since=since)
    return S.Envelope(data=[_article(r, at) for r in rows], meta=_meta(at, True, *NEWS_NOTES))


@api.get("/v1/news/breaking", response_model=S.Envelope[list[S.NewsArticle]], tags=["news"])
async def news_breaking(s: DB, as_of: AsOf = None,
                        hours: Annotated[float, Query(gt=0, le=72)] = 6,
                        limit: Annotated[int, Query(ge=1, le=500)] = 100):
    """Items flagged breaking by OBSERVABLE rules (a source label; a live HIGH item
    within 15 min of publication; a second publisher within 30 min)."""
    from app.canon import news_pit as NP
    at = _as_of(as_of)
    rows = await NP.items(s, at, breaking=True, since=at - _dt.timedelta(hours=hours),
                          limit=limit)
    return S.Envelope(data=[_article(r, at) for r in rows], meta=_meta(at, True, *NEWS_NOTES))


@api.get("/v1/news/sources", response_model=S.Envelope[list[dict[str, Any]]], tags=["news"])
async def news_sources():
    """Every source: status, terms, per-source write flag and lock state, cadence,
    and dry-run health (not point in time: the current state)."""
    from app.core.config import get_settings
    from app.news import locks as NL
    from app.news.collector import DRYRUN_DIR
    from app.news.report import health, load
    from app.news.sources import SOURCES
    st = get_settings()
    out = []
    for k, src in SOURCES.items():
        polls = load(DRYRUN_DIR / k)[0] if (DRYRUN_DIR / k).exists() else []
        lock = NL.check(k, mode="SHADOW", token=None)
        out.append({"source": k, "name": src.name, "kind": src.kind, "status": src.status,
                    "terms_status": src.compliance, "content_policy": src.content_policy,
                    "priority": src.priority, "write_flag": src.flag,
                    "write_flag_enabled": bool(src.flag and getattr(st, src.flag, False)),
                    "db_write": "UNLOCKED" if lock.ok else "LOCKED",
                    "db_write_failing": lock.summary()["failing"],
                    "cadence_s": {"market": src.market_interval_s, "off": src.off_interval_s,
                                  "weekend": src.weekend_interval_s},
                    "dry_run_health": health(polls, max(src.off_interval_s, 300))
                    if polls else ("UNSUPPORTED" if src.status == "UNSUPPORTED" else "DISABLED"),
                    "dry_run_polls": len(polls), "note": src.note})
    return S.Envelope(data=out, meta=_meta(now(), False, "current state, not point in time"))


def _dry_reports(day: str | None):
    from app.news.collector import DRYRUN_DIR
    from app.news.report import summarise
    from app.news.sources import SOURCES
    return {k: summarise(DRYRUN_DIR / k, day, expected_interval_s=max(v.off_interval_s, 300))
            for k, v in SOURCES.items() if (DRYRUN_DIR / k).exists()}


@api.get("/v1/news/latency", response_model=S.Envelope[dict[str, Any]], tags=["news"])
async def news_latency(day: _dt.date | None = None):
    """Publication -> first observation latency per source (p50/p90/p95/p99/max;
    market vs off hours; backlog excluded), processing and end-to-end latency,
    from the DRY_RUN evidence. Frontend latency is not observable here."""
    reps = _dry_reports(str(day) if day else None)
    return S.Envelope(data={k: {"latency": r.get("latency"), "live_items": r.get("live_items"),
                                "backlog_items": r.get("backlog_items")}
                            for k, r in reps.items()},
                      meta=_meta(now(), False, "DRY_RUN evidence (files), not point in time"))


@api.get("/v1/news/freshness", response_model=S.Envelope[dict[str, Any]], tags=["news"])
async def news_freshness():
    """Per source: last successful poll, last discovered item, health (a source that
    stops responding becomes STALE; it never looks healthy)."""
    reps = _dry_reports(None)
    return S.Envelope(data={k: {x: r.get(x) for x in (
        "health", "last_success", "last_item_discovered", "last_poll", "polls", "errors",
        "rate_limit_events", "http_status", "actual_interval_s")} for k, r in reps.items()},
        meta=_meta(now(), False, "DRY_RUN evidence (files), current state"))


@api.get("/v1/news/stats", response_model=S.Envelope[dict[str, Any]], tags=["news"])
async def news_stats(s: DB, as_of: AsOf = None,
                     hours: Annotated[float, Query(gt=0, le=168)] = 24):
    """Counts of visible news in the window by source, category, scope, impact,
    direction and breaking (point in time)."""
    from collections import Counter

    from app.canon import news_pit as NP
    at = _as_of(as_of)
    rows = await NP.items(s, at, since=at - _dt.timedelta(hours=hours), limit=5000)
    data = {"items": len(rows), **{k: dict(Counter(r[k] for r in rows)) for k in (
        "source", "category", "market_scope", "potential_impact", "impact_direction",
        "is_breaking")}, "stories": len({r["story_id"] for r in rows if r["story_id"]})}
    return S.Envelope(data=data, meta=_meta(at, True, *NEWS_NOTES))


@api.get("/v1/news/{item_id}", response_model=S.Envelope[S.NewsArticle], tags=["news"])
async def news_item(s: DB, item_id: int, as_of: AsOf = None):
    """One item as known at as_of (404 if not yet knowable then)."""
    from app.canon import news_pit as NP
    at = _as_of(as_of)
    r = await NP.item(s, at, item_id, include_upstox=_upstox_on())
    if r is None:
        raise HTTPException(404, f"news item {item_id} is not known at {at.isoformat()}")
    return S.Envelope(data=_article(r, at), meta=_meta(at, True, *NEWS_NOTES))


@api.get("/v1/stories", response_model=S.Envelope[list[S.NewsStory]], tags=["news"])
async def news_stories(s: DB, as_of: AsOf = None, instrument_key: str | None = None,
                       limit: Annotated[int, Query(ge=1, le=500)] = 100):
    """Story groups as known at as_of: an article that joined later is absent."""
    from app.canon import news_pit as NP
    at = _as_of(as_of)
    rows = await NP.stories(s, at, limit=limit, instrument_key=instrument_key)
    return S.Envelope(data=[S.NewsStory(**r) for r in rows], meta=_meta(at, True, *NEWS_NOTES))


@api.get("/v1/stories/{story_id}", response_model=S.Envelope[S.NewsStory], tags=["news"])
async def news_story(s: DB, story_id: int, as_of: AsOf = None):
    from app.canon import news_pit as NP
    at = _as_of(as_of)
    rows = await NP.stories(s, at, story_id=story_id, limit=1)
    if not rows:
        raise HTTPException(404, f"story {story_id} is not known at {at.isoformat()}")
    return S.Envelope(data=S.NewsStory(**rows[0]), meta=_meta(at, True, *NEWS_NOTES))


@api.get("/v1/instruments/{instrument_key}/news", response_model=S.Envelope[list[S.NewsArticle]],
         tags=["news"])
async def instrument_news(s: DB, instrument_key: str, as_of: AsOf = None,
                          limit: Annotated[int, Query(ge=1, le=1000)] = 100):
    """Multi-source news linked to the instrument at as_of (+ Upstox when enabled)."""
    from app.canon import news_pit as NP
    at = _as_of(as_of)
    rows = await NP.items(s, at, instrument_key=instrument_key, limit=limit,
                          include_upstox=_upstox_on())
    return S.Envelope(data=[_article(r, at) for r in rows], meta=_meta(at, True, *NEWS_NOTES))


# ── 11. freshness ───────────────────────────────────────────────────────────
CADENCE = {"candles_1d": ("ohlcv.1d.NSE%", "daily 07:00 IST (previous session)"),
           "candles_1m": ("ohlcv.1m.%", "daily close 16:05 IST"),
           "candles_15m": ("ohlcv.15m.%", "daily close 16:05 IST"),
           "candles_1h": ("ohlcv.1h.%", "daily close 16:05 IST"),
           "global_1d": ("ohlcv.1d.GLOBAL%", "12:40 and 21:10 IST"),
           "news": ("news.%", "every 30 min 09:30-15:30 IST Mon-Fri, close, morning; Sat-Sun 11:00 and 19:00"),
           "fii_dii": ("macro.%", "daily 07:00 IST"),
           "corporate_actions": ("corporate_action.%", "weekly (Sat) + new listings"),
           "fundamentals": ("fundamentals.%", "monthly + new listings"),
           "instrument_master": ("instrument.refresh", "daily 06:30 IST"),
           "canonical_layer": ("canon.process", "after each ingestion")}


@api.get("/v1/freshness", response_model=S.Envelope[list[S.Freshness]], tags=["operations"])
async def freshness(s: DB):
    at = now()
    out = []
    for name, (pattern, cadence) in CADENCE.items():
        r = (await s.execute(text("""
            select max(finished_at) filter (where status = 'COMPLETE'),
                   (array_agg(status order by started_at desc))[1]
            from ingest_run where stream like :p and mode = 'COMMIT'"""),
            {"p": pattern})).one()
        out.append(S.Freshness(dataset=name, last_complete_run_finished=r[0],
                               age_hours=round((at - r[0]).total_seconds() / 3600, 2)
                               if r[0] else None, last_status=r[1], expected_cadence=cadence))
    return S.Envelope(data=out, meta=_meta(at, False))


# ── 12. data quality / provenance ───────────────────────────────────────────
@api.get("/v1/instruments/{instrument_key}/quality", response_model=S.Envelope[S.Quality],
         tags=["operations"])
async def quality(s: DB, instrument_key: str):
    """Current coverage, vendor-revision observations, price basis, quarantines."""
    await _instrument(s, instrument_key)
    iid = (await s.execute(text("select instrument_id from canon_instrument where "
                                "instrument_key = :k"), {"k": instrument_key})).scalar()
    cov = {tf: await pit.current_coverage(s, instrument_key, tf) for tf in CANON_TIMEFRAMES}
    obs = dict((await s.execute(text("""select classification, count(*) from ohlcv_observation
        where instrument_id = :i group by 1"""), {"i": iid})).all())
    basis = dict((await s.execute(text("""select coalesce(pb.price_basis, 'NONE'), count(*)
        from ohlcv_bar b left join ohlcv_payload_basis pb using (payload_sha256)
        where b.instrument_id = :i group by 1"""), {"i": iid})).all())
    quar = (await s.execute(text("select count(*) from canon_excluded_bar where "
                                 "instrument_key = :k"), {"k": instrument_key})).scalar()
    return S.Envelope(
        data=S.Quality(instrument_key=instrument_key,
                       coverage={tf: [{k: v for k, v in r.items() if k != "run_id"}
                                      for r in rows] for tf, rows in cov.items()},
                       observations=obs, price_basis=basis, quarantined_bars=quar,
                       provenance={"source": "Upstox (UPSTOX_REST_V3 / UPSTOX_ASSETS)",
                                   "raw_payloads": "archived before parsing; every row "
                                                   "carries run_id and payload_sha256",
                                   "knowledge_rule": S.KNOWLEDGE_RULE}),
        meta=_meta(now(), False, "coverage is the CURRENT state; PIT coverage: pit.coverage"))


# ── 13. pipeline status / 14. acceptance ────────────────────────────────────
@api.get("/v1/pipeline/status", response_model=S.Envelope[dict[str, Any]], tags=["operations"])
async def pipeline_status(s: DB):
    """Last run per job family, running runs, lock, token AGE (never the token),
    disk, recent runbook markers."""
    from app.ops.status import snapshot
    return S.Envelope(data=await snapshot(s, BASE), meta=_meta(now(), False))


@api.get("/v1/acceptance", response_model=S.Envelope[dict[str, Any]], tags=["operations"])
async def acceptance():
    """The latest generated Stage 1 / Stage 2 acceptance verdicts (read from the
    reports the gates wrote; this endpoint never re-evaluates)."""
    out: dict[str, Any] = {}
    for stage in ("stage1", "stage2"):
        p = BASE / "var" / "acceptance" / f"{stage}.json"
        if not p.exists():
            out[stage] = None
            continue
        d = json.loads(p.read_text())
        out[stage] = {k: d.get(k) for k in ("generated_at", "overall", "live_readiness",
                                            "waiting_for_evidence", "deferred", "failing")
                      if k in d}
        out[stage]["criteria"] = [{"id": c["id"], "name": c.get("name") or c.get("question"),
                                   "status": c["status"]} for c in d.get("criteria", [])]
    out["stage3"] = {"status": "LOCKED", "reason": "production execution is unlocked only "
                     "when every condition of GET /v1/stage3/status holds (Stage 1 COMPLETE, "
                     "Stage 2 PASS, decisions approved, flag on, kill switch off)"}
    p3 = BASE / "var" / "acceptance" / "stage3.json"
    if p3.exists():
        d = json.loads(p3.read_text())
        out["stage3"]["report"] = {"generated_at": d.get("generated_at"),
                                   "overall": d.get("overall"), "levels": d.get("levels"),
                                   "criteria": [{"id": c["id"], "name": c.get("question"),
                                                 "status": c["status"]}
                                                for c in d.get("criteria", [])]}
    return S.Envelope(data=out, meta=_meta(now(), False))


# ── market session / latest prices / global finality (read contracts) ───────
@api.get("/v1/market/session", response_model=S.Envelope[S.MarketSession], tags=["market data"])
async def market_session(s: DB, date: _dt.date | None = None, as_of: AsOf = None):
    """The NSE calendar entry for a date (default: today IST) and, for today,
    the calendar state at as_of. Calendar only: says nothing about feeds."""
    at = _as_of(as_of)
    ist = at.astimezone(IST)
    day = date or ist.date()
    r = (await s.execute(text("""select session_date, is_trading_day, session_type,
        preopen_start_ist, open_ist, close_ist, source from trading_session
        where session_date = :d"""), {"d": day})).mappings().first()
    if r is None:
        raise HTTPException(404, f"no calendar entry for {day}")
    prev_ = (await s.execute(text("select max(session_date) from trading_session where "
                                  "is_trading_day and session_date < :d"), {"d": day})).scalar()
    next_ = (await s.execute(text("select min(session_date) from trading_session where "
                                  "is_trading_day and session_date > :d"), {"d": day})).scalar()
    if not r["is_trading_day"]:
        state = "NON_TRADING_DAY"
    elif day != ist.date():
        state = "CLOSED" if day < ist.date() else "SCHEDULED"
    else:
        t = ist.time()
        if r["preopen_start_ist"] and r["preopen_start_ist"] <= t < r["open_ist"]:
            state = "PRE_OPEN"
        elif r["open_ist"] <= t < r["close_ist"]:
            state = "OPEN"
        else:
            state = "CLOSED"
    return S.Envelope(data=S.MarketSession(
        date=day, is_trading_day=r["is_trading_day"], session_type=r["session_type"],
        preopen_start_ist=r["preopen_start_ist"], open_ist=r["open_ist"],
        close_ist=r["close_ist"], state=state, previous_trading_day=prev_,
        next_trading_day=next_, calendar_source=r["source"]),
        meta=_meta(at, False, "calendar state, not a data-feed status"))


@api.get("/v1/latest", response_model=S.Envelope[list[S.LatestPrice]], tags=["market data"])
async def latest(s: DB, keys: Annotated[str, Query(description="comma-separated instrument "
                                                               "keys (max 200)")],
                 as_of: AsOf = None):
    """Latest daily close and the previous one, per instrument, as knowable at
    as_of. The change is withheld (comparable=false) across a split/bonus ex-date
    or a price-basis difference, where a raw difference is not a market move."""
    at = _as_of(as_of)
    ks = [k for k in (x.strip() for x in keys.split(",")) if k][:200]
    out = []
    for k in ks:
        rows = await pit.bars(s, k, "1d", at, limit=2)
        if not rows:
            continue
        last = rows[-1]
        prev = rows[-2] if len(rows) == 2 else None
        comparable = prev is not None
        reason = None if prev is not None else "no previous session"
        if prev is not None:
            ex = (await s.execute(text("""select count(*) from ca_factor where instrument_key = :k
                and status in ('EXACT', 'UNCERTAIN') and ex_date > :a and ex_date <= :b"""),
                {"k": k, "a": prev["market_date"], "b": last["market_date"]})).scalar()
            if ex:
                comparable, reason = False, "split/bonus ex-date between the sessions"
            elif (prev.get("price_basis"), prev.get("basis_as_of")) != (
                    last.get("price_basis"), last.get("basis_as_of")):
                comparable, reason = False, "the two bars have different price bases"
        close = float(last["close"])
        pclose = _f(prev["close"]) if prev is not None else None
        change = round(close - pclose, 6) if comparable and pclose else None
        out.append(S.LatestPrice(
            instrument_key=k, market_date=last["market_date"], close=close,
            previous_market_date=prev["market_date"] if prev is not None else None,
            previous_close=pclose, change=change,
            change_pct=round(change / pclose * 100, 4) if change is not None else None,
            volume=float(last["volume"]), comparable=comparable, comparable_reason=reason,
            knowable_at=last["knowable_at"], price_basis=last.get("price_basis")))
    return S.Envelope(data=out, meta=_meta(at, True, "daily bars; not a live quote"))


@api.get("/v1/global/{instrument_key}/finality", response_model=S.Envelope[list[S.GlobalLabel]],
         tags=["global"])
async def global_finality(s: DB, instrument_key: str,
                          limit: Annotated[int, Query(ge=1, le=500)] = 30):
    """Every recent label with its finality status. Withheld labels (REVISED /
    PLACEHOLDER / UNCONFIRMED) carry no values. Current state (not PIT)."""
    rows = (await s.execute(text("""
        select session_date, finality, close, fetched_at, confirmed_at, revised_at
        from global_bar_finality where instrument_key = :k
        order by session_date desc limit :l"""), {"k": instrument_key, "l": limit})
            ).mappings().all()
    if not rows:
        raise HTTPException(404, f"unknown global instrument {instrument_key!r}")
    exposed = ("CONFIRMED", "CONFIRMED_BY_AGE")
    return S.Envelope(data=[S.GlobalLabel(
        label_date=r["session_date"], finality=r["finality"], exposed=r["finality"] in exposed,
        close=_f(r["close"]) if r["finality"] in exposed else None,
        first_fetched_at=r["fetched_at"], confirmed_at=r["confirmed_at"],
        revised_at=r["revised_at"]) for r in rows],
        meta=_meta(now(), False, "labels are the vendor's, not trading dates"))


# ── Stage 3 features (stored values only; nothing is computed on request) ───
@api.get("/v1/stage3/status", response_model=S.Envelope[dict[str, Any]], tags=["stage 3"])
async def stage3_status(s: DB):
    """Stage 3 execution state from cheap sources: flags, kill switch, decisions,
    registry, the latest Stage 1/2/3 reports and the last runs. The authoritative
    lock check (Stage 1 evaluated fresh) runs only at execution time
    (`prajna stage3 locks`)."""
    from app.core.config import get_settings
    from app.features import locks
    from app.features.decisions import DECISIONS
    from app.features.registry import summary

    st = get_settings()
    rep1 = BASE / "var" / "acceptance" / "stage1.json"
    s1 = json.loads(rep1.read_text()).get("overall") if rep1.exists() else None
    ok2, d2 = locks.stage2_status()
    runs = [dict(r) for r in (await s.execute(text("""select run_id::text, stream, status,
        started_at, finished_at, rows_written from ingest_run where stream like 'features.%'
        order by started_at desc limit 10"""))).mappings()]
    events = [dict(r) for r in (await s.execute(text("""select at, event, mode, operator,
        run_id::text from stage3_event order by at desc limit 10"""))).mappings()]
    stored = (await s.execute(text("""select count(*), max(session_date) from feature_value"""
                                   ))).one()
    data = {
        "production_execution": "UNLOCKED" if (st.PRAJNA_STAGE3_ENABLED and s1 == "COMPLETE"
                                               and ok2 and not locks.kill_switch_engaged()
                                               and all(v["status"] == "APPROVED"
                                                       for v in DECISIONS.values()))
        else "LOCKED",
        "flags": {"PRAJNA_STAGE3_ENABLED": st.PRAJNA_STAGE3_ENABLED,
                  "PRAJNA_STAGE3_BACKFILL_ENABLED": st.PRAJNA_STAGE3_BACKFILL_ENABLED},
        "kill_switch_engaged": locks.kill_switch_engaged(),
        "prerequisites": {"stage1_latest_report": s1,
                          "stage2": {"ok": ok2, "detail": d2}},
        "decisions": {k: v["status"] for k, v in DECISIONS.items()},
        "registry": summary(),
        "stored": {"feature_values": stored[0], "latest_session": stored[1]},
        "recent_runs": runs, "recent_events": events,
    }
    return S.Envelope(data=data, meta=_meta(now(), False, "execution locks are re-checked "
                                            "fresh (Stage 1 evaluated now) at execution time"))


@api.get("/v1/stage3/registry", response_model=S.Envelope[dict[str, Any]], tags=["stage 3"])
async def stage3_registry():
    """Every feature definition and every diagram item with its status
    (IMPLEMENTED / PARTIAL / UNSUPPORTED / UNKNOWN) and parameter status."""
    from app.features.decisions import DECISIONS
    from app.features.registry import registry_document, summary
    return S.Envelope(data={"summary": summary(), "decisions": DECISIONS, **registry_document()},
                      meta=_meta(now(), False))


@api.get("/v1/instruments/{instrument_key}/features",
         response_model=S.Envelope[list[S.FeatureValue]], tags=["stage 3"])
async def instrument_features(s: DB, instrument_key: str, session: _dt.date,
                              snapshot: Annotated[str, Query(pattern="^(PRE_SESSION|PRE_OPEN)$")]
                              = "PRE_SESSION", as_of: AsOf = None):
    """STORED feature values of one instrument (or context key) at one snapshot,
    as known at `as_of` (computed_at < as_of). Empty while Stage 3 production
    execution is locked; never computed on request."""
    at = _as_of(as_of)
    rows = (await s.execute(text("""select instrument_key, scope, session_date, snapshot,
        as_of as snapshot_as_of, feature_id, feature_version, value, reason,
        input_max_knowable_at, computed_at, registry_sha256 from feature_value
        where instrument_key = :k and session_date = :d and snapshot = :n and computed_at < :a
        order by feature_id, feature_version"""),
        {"k": instrument_key, "d": session, "n": snapshot, "a": at})).mappings().all()
    data = [S.FeatureValue(**{**r, "value": _f(r["value"])}) for r in rows]
    notes = [] if data else ["no stored values (Stage 3 production execution is locked or "
                             "this snapshot was not run)"]
    return S.Envelope(data=data, meta=_meta(at, True, *notes))
