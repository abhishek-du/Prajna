"""prajna — command line.

--dry-run is the DEFAULT for every ingestion command. Writing requires both
--commit and a valid write token (constraint #10). A flag alone is not
authorization.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import typer

from app.core.config import get_settings
from app.core.logging import configure, get_logger

app = typer.Typer(add_completion=False, help="AutoTrade Pro V2 (prajna) — Upstox-only ingestion")
db_app = typer.Typer(help="database / migrations")
ingest_app = typer.Typer(help="ingestion runs (dry-run by default)")
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")


@app.callback()
def _root(
    log_level: str = typer.Option(None, help="override PRAJNA_LOG_LEVEL"),
    plain: bool = typer.Option(False, help="human-readable logs instead of JSON"),
):
    s = get_settings()
    configure(level=log_level or s.PRAJNA_LOG_LEVEL, json_output=not plain)


# ── db ──────────────────────────────────────────────────────────────────────
def _alembic(*args: str, dsn: str | None = None) -> int:
    cmd = [sys.executable, "-m", "alembic", "-c", "alembic.ini"]
    if dsn:
        cmd += ["-x", f"dsn={dsn}"]
    return subprocess.call([*cmd, *args])


@db_app.command("upgrade")
def db_upgrade(
    revision: str = typer.Argument("head"),
    test_db: bool = typer.Option(False, "--test-db", help="target PRAJNA_TEST_DATABASE_URL"),
):
    dsn = get_settings().PRAJNA_TEST_DATABASE_URL if test_db else None
    raise typer.Exit(_alembic("upgrade", revision, dsn=dsn))


@db_app.command("downgrade")
def db_downgrade(revision: str = typer.Argument(...)):
    raise typer.Exit(_alembic("downgrade", revision))


@db_app.command("current")
def db_current():
    raise typer.Exit(_alembic("current"))


@db_app.command("status")
def db_status():
    """Row counts and provenance coverage for every table."""
    from app.cli.status import print_status
    asyncio.run(print_status())


@db_app.command("sql")
def db_sql(
    statement: str = typer.Argument(..., help="SQL to run"),
    limit: int = typer.Option(100, help="max rows to print"),
    allow_write: bool = typer.Option(
        False, "--allow-write",
        help="open a writable transaction (default is READ ONLY, enforced by Postgres)",
    ),
):
    """Run ad-hoc SQL. Read-only unless --allow-write."""
    from app.cli.sql import main as run
    run(statement, allow_write, limit)


@db_app.command("tables")
def db_tables():
    """List tables with row counts and size."""
    from app.cli.sql import main as run
    run(
        """
        select c.relname as table,
               c.reltuples::bigint as est_rows,
               pg_size_pretty(pg_total_relation_size(c.oid)) as size
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where c.relkind = 'r' and n.nspname = 'public'
        order by c.relname
        """,
        False, 200,
    )


@db_app.command("describe")
def db_describe(table: str = typer.Argument(...)):
    """Show columns, types and constraints for one table."""
    from app.cli.sql import main as run
    run(f"""
        select column_name, data_type, is_nullable, coalesce(column_default,'') as default
        from information_schema.columns
        where table_schema='public' and table_name='{table}'
        order by ordinal_position
    """, False, 200)


@db_app.command("web")
def db_web(
    port: int = typer.Option(8081, help="port (8080 is taken by another app on this host)"),
    host: str = typer.Option("127.0.0.1", help="bind address; loopback only by default"),
):
    """Read-only web browser for the database."""
    from app.web.viewer import serve
    serve(host=host, port=port)


@db_app.command("check-isolation")
def db_check_isolation():
    """Prove the configured DSN is not a V1 database."""
    from app.core.config import database_name
    from app.db.engine import assert_not_v1

    dsn = get_settings().PRAJNA_DATABASE_URL
    assert_not_v1(dsn)
    typer.echo(f"OK: target database is '{database_name(dsn)}' (not a V1 database)")


# ── ingest ──────────────────────────────────────────────────────────────────
@ingest_app.command("preopen")
def ingest_preopen(
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
    replay_from: str = typer.Option(None, "--replay-from-archive", help="re-parse one archive"),
    replay_session_manifest: str = typer.Option(
        None, "--replay-from-session", help="re-parse every archive of a capture session"),
    session_date: str = typer.Option(
        None, "--session-date", help="YYYY-MM-DD; defaults to the archive header's"),
):
    """Replay pre-open archives into the database (dry-run by default).

    Recording is `ingest preopen-capture`; this command turns archives into
    rows. A session (several connections) replays each archive as its own run.
    """
    import datetime as _dt
    import json as _json
    import pathlib

    log = get_logger("cli")
    if bool(replay_from) == bool(replay_session_manifest):
        log.error("choose_one", options="--replay-from-archive | --replay-from-session",
                  hint="recording is `ingest preopen-capture`")
        raise typer.Exit(2)

    from app.db.engine import get_sessionmaker
    from app.ingest.preopen import replay_archive, replay_session

    def _plain(report) -> dict:
        out = {k: getattr(report, k) for k in report.__slots__}
        out["rows_written"] = report.rows_written
        return out

    async def _go():
        async with get_sessionmaker()() as s:
            if replay_session_manifest:
                return await replay_session(s, pathlib.Path(replay_session_manifest),
                                            commit=commit, token=token)
            return await replay_archive(
                s, pathlib.Path(replay_from), commit=commit, token=token,
                session_date=_dt.date.fromisoformat(session_date) if session_date else None,
            )

    report = asyncio.run(_go())
    if replay_session_manifest:
        out = {"session_id": report.session_id, "session_date": report.session_date,
               "status": report.status, "rows_written": report.rows_written,
               "error": report.error, "shards": [_plain(r) for r in report.shards]}
    else:
        out = _plain(report)
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


@ingest_app.command("calendar")
def ingest_calendar_cmd(
    date_from: str = typer.Option(..., "--from", help="YYYY-MM-DD"),
    date_to: str = typer.Option(..., "--to", help="YYYY-MM-DD (inclusive, <= 400 days)"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
):
    """NSE trading sessions from Upstox /v2/market/holidays + /v2/market/timings.

    One timings call per date (hours are never assumed). Uses the cached Upstox
    token; an invalid token stops the run (blocker B0).
    """
    import datetime as _dt
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.calendar import ingest_calendar
    from app.sources.upstox_calendar import UpstoxCalendarClient
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached

    log = get_logger("cli")
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        from sqlalchemy import text as _text

        from app.core.clock import now_ist
        client = UpstoxCalendarClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                # Past dates: session evidence = the NIFTY 50 daily bars already
                # stored (timings is a generic schedule for past dates).
                bars = set((await s.execute(_text(
                    "select session_date from ohlcv_bar where timeframe='1d' "
                    "and instrument_key='NSE_INDEX|Nifty 50'"))).scalars())
                # weekdays with NO NSE trading at all in Upstox data: no bar of any
                # of the 3 indices and zero NSE_EQ daily bars (one query, the range)
                closed = set((await s.execute(_text("""
                    select d::date from generate_series(cast(:a as date), cast(:b as date),
                                                        interval '1 day') d
                    where extract(isodow from d) < 6 and not exists (
                      select 1 from ohlcv_bar b join instrument i
                        on i.instrument_id = b.instrument_id
                      where b.timeframe = '1d' and b.session_date = d::date
                        and i.segment in ('NSE_EQ', 'NSE_INDEX'))"""),
                    {"a": _dt.date.fromisoformat(date_from),
                     "b": _dt.date.fromisoformat(date_to)})).scalars())
                return await ingest_calendar(
                    s, date_from=_dt.date.fromisoformat(date_from),
                    date_to=_dt.date.fromisoformat(date_to),
                    holidays=client.holidays, timings=client.timings,
                    store=PayloadStore(get_settings().archive_dir),
                    commit=commit, token=token, holiday_on=client.holiday_on,
                    past_before=now_ist().date(), index_bar_dates=bars,
                    market_closed_dates=closed,
                )
        finally:
            await client.aclose()

    report = asyncio.run(_go())
    out = report.public()
    out["sessions"] = [x for x in report.sessions if x["session_type"] != "NORMAL"]
    out["anomalies"] = [{k: a[k] for k in ("severity", "kind", "subject")} | {
        "reason": a["detail"].get("reason")} for a in report.anomalies]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


@ingest_app.command("instruments")
def ingest_instruments(
    payload_sha256: str = typer.Option(
        ..., "--payload-sha256", help="sha256 of an ALREADY ARCHIVED instrument master"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
):
    """M3.0: load CURRENT instrument rows from an archived Upstox master.

    Never downloads. Verifies the archived bytes against --payload-sha256
    before parsing. Identical rows are a no-op; a changed attribute fails.
    """
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.instruments import load_current_instruments

    async def _go():
        async with get_sessionmaker()() as s:
            return await load_current_instruments(
                s, master_sha256=payload_sha256, archive_root=get_settings().archive_dir,
                commit=commit, token=token)

    report = asyncio.run(_go())
    out = report.public()
    out["anomalies"] = [{k: a[k] for k in ("severity", "kind", "subject")}
                        for a in report.anomalies]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


@ingest_app.command("candles")
def ingest_candles(
    timeframe: list[str] = typer.Option(..., "--timeframe", help="repeatable: 1m 5m 15m 1h 1d"),
    date_from: str = typer.Option(None, "--from", help="YYYY-MM-DD (historical)"),
    date_to: str = typer.Option(None, "--to", help="YYYY-MM-DD (historical, inclusive)"),
    intraday: bool = typer.Option(False, "--intraday", help="today's bars (intraday endpoint)"),
    key: list[str] = typer.Option(None, "--key", help="repeatable instrument_key"),
    keys_file: str = typer.Option(None, "--keys-file", help="instrument_keys, one per line"),
    all_instruments: bool = typer.Option(
        False, "--all-instruments", help="every current NSE_EQ + NSE_INDEX instrument"),
    global_instruments: bool = typer.Option(
        False, "--global", help="every current GLOBAL_INDEX / GLOBAL_INDICATOR instrument "
                                "(daily only: their sessions are not on the NSE grid)"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
    no_resume: bool = typer.Option(False, "--no-resume", help="ignore watermarks"),
):
    """Ingest Upstox candles into ohlcv_bar (dry-run by default). M4.3.

    Only COMPLETE bars are persisted. Every response is archived first.
    Timeframes and ranges are yours to choose (D1/D2 are not decided here).
    A rate limit stops the batch with every checkpoint intact.
    """
    import datetime as _dt
    import json as _json
    import pathlib

    from sqlalchemy import literal_column, select

    from app.db.engine import get_sessionmaker
    from app.db.models import Instrument
    from app.ingest.candles import CandleIngestor, CandleJob, plan_jobs
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    if sum(bool(x) for x in (key, keys_file, all_instruments, global_instruments)) != 1:
        log.error("choose_one_key_source",
                  options="--key | --keys-file | --all-instruments | --global")
        raise typer.Exit(2)
    if global_instruments and set(timeframe) != {"1d"}:
        log.error("global_is_daily_only", reason="intraday grid checks use NSE sessions")
        raise typer.Exit(2)
    if intraday == bool(date_from or date_to) or (not intraday and not (date_from and date_to)):
        log.error("choose_range", options="--from/--to (historical) | --intraday")
        raise typer.Exit(2)
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    keys: list[str] = list(key or [])
    if keys_file:
        keys = [ln.split("#", 1)[0].strip()
                for ln in pathlib.Path(keys_file).read_text().splitlines()]
        keys = [k for k in keys if k]

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                ks = keys
                if all_instruments or global_instruments:
                    from app.contracts.identity import GLOBAL_SEGMENTS
                    segs = (sorted(GLOBAL_SEGMENTS) if global_instruments
                            else ["NSE_EQ", "NSE_INDEX"])
                    ks = list((await s.execute(select(Instrument.instrument_key).where(
                        Instrument.valid_to == literal_column("'infinity'::date"),
                        Instrument.segment.in_(segs))
                        .order_by(Instrument.instrument_key))).scalars())
                if intraday:
                    jobs, unavailable = [CandleJob(k, tf, None) for k in sorted(set(ks))
                                         for tf in timeframe], []
                else:
                    jobs, unavailable = plan_jobs(ks, timeframe,
                                                  _dt.date.fromisoformat(date_from),
                                                  _dt.date.fromisoformat(date_to))
                ing = CandleIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                     commit=commit, token=token)
                return await ing.run(jobs, resume=not no_resume), unavailable
        finally:
            await rest.aclose()

    rep, unavailable = asyncio.run(_go())
    out = rep.summary()
    out["before_availability"] = len(unavailable)
    out["failed"] = [{"key": r.job.instrument_key, "tf": r.job.timeframe,
                      "window": r.coverage and r.coverage["window"], "error": r.error}
                     for r in rep.results if r.status in ("FAILED", "ABORTED")][:50]
    out["coverage"] = {o: sum(1 for r in rep.results if r.coverage and
                              r.coverage["outcome"] == o)
                       for o in ("DATA", "EMPTY", "VENDOR_ERROR")}
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not rep.stopped and not rep.count("FAILED") else 1)


@ingest_app.command("institutional")
def ingest_institutional(
    side: list[str] = typer.Option(["FII", "DII"], "--side", help="repeatable: FII DII"),
    data_type: list[str] = typer.Option(
        None, "--data-type", help="repeatable, e.g. NSE_EQ|CASH; default: every type of the side"),
    start: str = typer.Option("2026-04-01", "--start",
                              help="YYYY-MM-DD; the vendor has nothing before 2026-04-01"),
    max_requests: int = typer.Option(20, "--max-requests", help="per series"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
    no_resume: bool = typer.Option(False, "--no-resume", help="ignore watermarks"),
):
    """Ingest Upstox FII/DII activity (1D) into macro_observation (dry-run by default).

    Every response is archived first. Only dates before today (IST) are
    persisted; knowable_at = fetched_at (unverified). A changed value for a
    stored date FAILS (D3's current policy); nothing is overwritten.
    """
    import datetime as _dt
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.institutional import InstitutionalIngestor
    from app.parsers.upstox_institutional import DATA_TYPES
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    series = [(sd.upper(), t) for sd in side for t in (data_type or DATA_TYPES.get(sd.upper(), ()))]
    bad = [p for p in series if p[1] not in DATA_TYPES.get(p[0], ())]
    if not series or bad:
        log.error("unsupported_series", series=bad or series, supported=DATA_TYPES)
        raise typer.Exit(2)
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                ing = InstitutionalIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                            commit=commit, token=token)
                return await ing.run(series, start=_dt.date.fromisoformat(start),
                                     resume=not no_resume, max_requests=max_requests)
        finally:
            await rest.aclose()

    rep = asyncio.run(_go())
    out = rep.summary()
    out["problems"] = [{"series": f"{r.side} {r.data_type}", "from": str(r.end),
                        "status": r.status, "error": r.error}
                       for r in rep.results if r.status != "COMPLETE"][:50]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not out["problems"] else 1)


@ingest_app.command("news")
def ingest_news(
    key: list[str] = typer.Option(None, "--key", help="repeatable instrument_key; "
                                  "default: every current instrument"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
):
    """Ingest Upstox news (/v2/news, last 7 days) into news_article + news_instrument.

    Batches of 30 keys, every page archived first. Articles are identified by
    (heading, published_time); a changed article is never overwritten (WARN).
    Run at least daily: the vendor serves only the last 7 days.
    """
    import json as _json

    from sqlalchemy import literal_column, select

    from app.db.engine import get_sessionmaker
    from app.db.models import Instrument
    from app.ingest.news import NewsIngestor
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                ks = list(key or [])
                if not ks:
                    ks = list((await s.execute(select(Instrument.instrument_key).where(
                        Instrument.valid_to == literal_column("'infinity'::date"),
                        Instrument.segment == "NSE_EQ")
                        .order_by(Instrument.instrument_key))).scalars())
                ing = NewsIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                   commit=commit, token=token)
                return await ing.run(ks)
        finally:
            await rest.aclose()

    rep = asyncio.run(_go())
    out = rep.summary()
    out["problems"] = [{"keys": f"{r.keys[0]}..({len(r.keys)})", "status": r.status,
                        "error": r.error} for r in rep.results if r.status != "COMPLETE"][:50]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not out["problems"] else 1)


@ingest_app.command("corporate-actions")
def ingest_corporate_actions(
    isin: list[str] = typer.Option(None, "--isin", help="repeatable ISIN; "
                                   "default: every current NSE_EQ instrument"),
    resume_hours: int = typer.Option(0, "--resume-hours", help="skip ISINs already swept by a "
                                     "COMPLETE, non-superseded commit run in the last N hours"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
):
    """Ingest Upstox corporate actions (/v2/fundamentals/{ISIN}/corporate-actions).

    Dividends, bonus, splits, rights: what Upstox serves (about one year back).
    Announcement is a DATE (no time is invented); knowable_at = fetched_at.
    """
    import json as _json

    from sqlalchemy import literal_column, select

    from app.db.engine import get_sessionmaker
    from app.db.models import Instrument
    from app.ingest.corporate_actions import CorporateActionIngestor
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                isins = list(isin or [])
                if not isins:
                    isins = [x for x in (await s.execute(select(Instrument.isin).where(
                        Instrument.valid_to == literal_column("'infinity'::date"),
                        Instrument.segment == "NSE_EQ"))).scalars() if x]
                if resume_hours:
                    from sqlalchemy import text as _t
                    done = set((await s.execute(_t(
                        "select distinct jsonb_array_elements_text(request_params->'isins') "
                        "from ingest_run where stream='corporate_action.isin' and mode='COMMIT' "
                        "and status='COMPLETE' and not request_params ? 'superseded' "
                        "and started_at > now() - make_interval(hours => :h)"),
                        {"h": resume_hours})).scalars())
                    isins = [i for i in isins if i not in done]
                ing = CorporateActionIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                              commit=commit, token=token)
                return await ing.run(isins)
        finally:
            await rest.aclose()

    rep = asyncio.run(_go())
    out = rep.summary()
    out["problems"] = [{"isins": f"{r.isins[0]}..({len(r.isins)})", "status": r.status,
                        "error": r.error} for r in rep.results if r.status != "COMPLETE"][:50]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not out["problems"] else 1)


@ingest_app.command("fundamentals")
def ingest_fundamentals(
    isin: list[str] = typer.Option(None, "--isin", help="repeatable ISIN; "
                                   "default: every current NSE_EQ instrument"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
):
    """Ingest Upstox fundamentals (12 variants per ISIN) into fundamental_snapshot.

    profile, key ratios, shareholding, competitors, balance sheet / cash flow
    (consolidated + standalone) and income statement (x yearly/quarterly), each
    kept as sent. A new snapshot is stored only when the content changed.
    """
    import json as _json

    from sqlalchemy import literal_column, select

    from app.db.engine import get_sessionmaker
    from app.db.models import Instrument
    from app.ingest.fundamentals import FundamentalsIngestor
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                isins = list(isin or [])
                if not isins:
                    isins = [x for x in (await s.execute(select(Instrument.isin).where(
                        Instrument.valid_to == literal_column("'infinity'::date"),
                        Instrument.segment == "NSE_EQ"))).scalars() if x]
                ing = FundamentalsIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                           commit=commit, token=token)
                return await ing.run(isins)
        finally:
            await rest.aclose()

    rep = asyncio.run(_go())
    out = rep.summary()
    out["problems"] = [{"isins": f"{r.isins[0]}..({len(r.isins)})", "status": r.status,
                        "error": r.error} for r in rep.results if r.status != "COMPLETE"][:50]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not out["problems"] else 1)


@ingest_app.command("instruments-global")
def ingest_instruments_global(
    payload_sha256: str = typer.Option(None, "--payload-sha256",
                                       help="use an already archived global.json.gz"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
):
    """Load Upstox's global instruments (S&P, Dow, USD/INR, Brent, ...) into instrument.

    Downloads the public global.json.gz (no token) and archives it first,
    unless --payload-sha256 names an archived copy.
    """
    import json as _json
    import pathlib

    import httpx

    from app.core.clock import now
    from app.db.engine import get_sessionmaker
    from app.ingest.global_instruments import GLOBAL_URL, load_global_instruments
    from app.ingest.instruments import locate_archived, resolve_fetched_at
    from app.storage.payload_store import PayloadStore, StoredPayload

    store = PayloadStore(get_settings().archive_dir)

    async def _go():
        async with get_sessionmaker()() as s:
            if payload_sha256:
                path = locate_archived(pathlib.Path(get_settings().archive_dir), payload_sha256)
                fetched, _ = await resolve_fetched_at(s, payload_sha256, path)
                data = PayloadStore.read(path, payload_sha256)
                stored = StoredPayload(payload_sha256, path, len(data), "application/gzip",
                                       fetched, None, True)
            else:
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
                    r = await c.get(GLOBAL_URL)
                    fetched = now()
                r.raise_for_status()
                stored = store.put(r.content, source="UPSTOX_ASSETS",
                                   content_type="application/gzip", ext="json.gz",
                                   fetched_at=fetched)
            return await load_global_instruments(s, stored, commit=commit, token=token)

    rep = asyncio.run(_go())
    typer.echo(_json.dumps({"status": rep.status, "committed": rep.committed,
                            "payload_sha256": rep.payload_sha256, "rows": rep.rows_in_file,
                            "inserted": rep.inserted, "already_current": rep.already_current,
                            "keys": rep.keys, "error": rep.error}, indent=2))
    raise typer.Exit(0 if rep.status == "COMPLETE" else 1)


@ingest_app.command("universe")
def ingest_universe(
    from_file: str = typer.Option(None, "--from-file", help="a local copy of NSE.json.gz"),
    payload_sha256: str = typer.Option(
        None, "--payload-sha256", help="re-select from a master already in raw_payload"),
    download: bool = typer.Option(
        False, "--download", help="fetch the public master from assets.upstox.com (no token)"),
    session_date: str = typer.Option(None, "--session-date", help="YYYY-MM-DD; default today IST"),
    cap: int = typer.Option(
        0, "--cap", help="cap the universe itself (0 = none; connection capacity is applied "
                         "at capture, not here)"),
    keys_out: str = typer.Option(None, "--keys-out", help="write the subscribed keys here"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
):
    """Select the pre-open universe from the Upstox instrument master.

    Exactly one source: --from-file, --payload-sha256, or --download. The
    master is archived before it is parsed. --keys-out feeds
    `ingest preopen-capture --keys-file`.
    """
    import datetime as _dt
    import json as _json
    import pathlib

    from app.core.clock import now, now_ist
    from app.db.engine import get_sessionmaker
    from app.ingest.universe import load_archived_master, select_universe
    from app.sources.upstox_instruments import MASTER_URL, download_master
    from app.storage.payload_store import PayloadStore

    log = get_logger("cli")
    if sum(bool(x) for x in (from_file, payload_sha256, download)) != 1:
        log.error("choose_one_source", options="--from-file | --payload-sha256 | --download")
        raise typer.Exit(2)
    day = _dt.date.fromisoformat(session_date) if session_date else now_ist().date()
    store = PayloadStore(get_settings().archive_dir)

    local_bytes, local_uri = b"", ""
    if from_file:
        p = pathlib.Path(from_file)
        local_bytes, local_uri = p.read_bytes(), f"file://{p.resolve()}"

    async def _go():
        async with get_sessionmaker()() as s:
            status, uri = None, MASTER_URL
            if download:
                d = await download_master()
                data, fetched, status, uri = d.data, d.fetched_at, d.http_status, d.url
            elif payload_sha256:
                data, fetched, status = await load_archived_master(s, payload_sha256)
            else:
                # We cannot know when a local copy was downloaded; now() is the
                # bound that can never be too early.
                data, fetched, uri = local_bytes, now(), local_uri
            return await select_universe(
                s, data, fetched_at=fetched, session_date=day, cap=cap or None,
                commit=commit, token=token, store=store, source_uri=uri, http_status=status,
            )

    report = asyncio.run(_go())
    if keys_out and report.status == "COMPLETE":
        lines = [
            f"# prajna pre-open universe {report.universe} for {report.session_date}",
            f"# run_id {report.run_id}  master_sha256 {report.master_sha256}",
            f"# rules {report.rules_version} {report.rules_sha256}",
            f"# cap {report.cap} (UNVERIFIED, B5)  subscribed {report.subscribed}"
            f"  sha256 {report.subscribed_sha256}",
            *report.subscribed_keys,
        ]
        pathlib.Path(keys_out).write_text("\n".join(lines) + "\n")
    out = report.public()
    out["cap_excluded"] = f"{len(report.cap_excluded)} keys (named in ingest_anomaly)"
    out["anomalies"] = [{k: a[k] for k in ("severity", "kind", "subject")}
                        for a in report.anomalies]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


@ingest_app.command("preopen-capture")
def ingest_preopen_capture(
    keys_file: str = typer.Option(
        None, "--keys-file", help="instrument_keys, one per line (# comments ok)"),
    universe_date: str = typer.Option(
        None, "--universe-date", help="use the committed `preopen` universe for this date"),
    session_date: str = typer.Option(None, "--session-date", help="YYYY-MM-DD; default today IST"),
    until: str = typer.Option("09:20", "--until", help="stop at this IST wall time (HH:MM)"),
    mode: str = typer.Option("full", "--mode", help="wire subscribe mode (full -> full_d5)"),
    connections: int = typer.Option(
        2, "--connections", help="max concurrent connections (2 measured 2026-09-23)"),
    per_connection: int = typer.Option(
        2000, "--per-connection", help="keys per connection (2000 measured 2026-09-23)"),
    max_frames: int = typer.Option(
        None, "--max-frames", help="stop each connection after N frames (smoke test)"),
    stale_after: float = typer.Option(30.0, "--stale-after", help="seconds without data"),
):
    """Record the Upstox pre-open WebSocket feed. Writes archives, NO rows.

    The universe is split, in sorted order, into shards of <= --per-connection
    keys, one connection each. Uses the cached Upstox token only and never logs
    in by itself: an invalid token stops the capture (blocker B0). Replay with
    `ingest preopen --replay-from-session <manifest>`.
    """
    import datetime as _dt
    import hashlib
    import json as _json
    import pathlib
    import signal

    from sqlalchemy import select

    from app.contracts.identity import parse_instrument_key
    from app.contracts.universe import PREOPEN_UNIVERSE, plan_shards
    from app.core.clock import IST, ist_at, now, now_ist
    from app.db.engine import get_sessionmaker
    from app.db.models import InstrumentUniverseMembership as Member
    from app.sources.upstox_preopen_session import PreopenCaptureSession
    from app.sources.upstox_preopen_ws import RecorderConfig
    from app.vendor.upstox.auth import load_cached, probe
    from app.vendor.upstox.feed_auth import authorize_feed_v3

    log = get_logger("cli")
    if bool(keys_file) == bool(universe_date):
        log.error("choose_one_universe", options="--keys-file | --universe-date")
        raise typer.Exit(2)

    extra: dict = {}
    if keys_file:
        raw = pathlib.Path(keys_file).read_bytes()
        keys = [ln.split("#", 1)[0].strip() for ln in raw.decode().splitlines()]
        keys = [k for k in keys if k]
        extra = {"universe_source": "keys_file",
                 "keys_file": str(pathlib.Path(keys_file).resolve()),
                 "keys_file_sha256": hashlib.sha256(raw).hexdigest()}
    else:
        udate = _dt.date.fromisoformat(universe_date)

        async def _load():
            async with get_sessionmaker()() as s:
                return (await s.execute(
                    select(Member.instrument_key, Member.run_id, Member.payload_sha256)
                    .where(Member.universe == PREOPEN_UNIVERSE, Member.session_date == udate)
                    .order_by(Member.instrument_key))).all()
        rows = asyncio.run(_load())
        keys = [r.instrument_key for r in rows]
        extra = {"universe_source": "instrument_universe_membership",
                 "universe_date": universe_date,
                 "universe_run_ids": sorted({str(r.run_id) for r in rows}),
                 "instrument_master_sha256": sorted({r.payload_sha256 for r in rows})}
    for k in keys:
        parse_instrument_key(k)
    if not keys:
        log.error("empty_universe", **{k: v for k, v in extra.items() if isinstance(v, str)})
        raise typer.Exit(2)

    day = _dt.date.fromisoformat(session_date) if session_date else now_ist().date()
    hh, mm = (int(x) for x in until.split(":"))
    stop_at = ist_at(day, _dt.time(hh, mm))
    if stop_at <= now():
        log.error("window_already_over", until_ist=stop_at.astimezone(IST).isoformat())
        raise typer.Exit(2)

    rec = load_cached()
    ok, detail = probe(rec.access_token) if rec else (False, {"reason": "no cached token"})
    if not ok:
        log.error("upstox_token_invalid", blocker="B0",
                  action="refresh it with `prajna upstox login`; capture never logs in itself",
                  detail=str(detail)[:200])
        raise typer.Exit(3)
    extra["upstox_user_id"] = rec.user_id

    plan = plan_shards(keys, per_connection=per_connection, max_connections=connections)
    cfg = RecorderConfig(mode=mode, cap=per_connection, stale_after=stale_after)

    async def _go():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        cap_session = PreopenCaptureSession(
            get_settings().archive_dir, session_date=day, plan=plan,
            authorize=lambda: authorize_feed_v3(rec.access_token), config=cfg,
            stop_at=stop_at, max_frames_per_connection=max_frames, stop=stop,
            extra_header=extra,
        )
        typer.echo(f"session manifest: {cap_session.manifest_path}", err=True)
        return cap_session.manifest_path, await cap_session.run()

    manifest, doc = asyncio.run(_go())
    out = {"manifest": str(manifest), "status": doc["status"], "coverage": {
        k: v for k, v in (doc["coverage"] or {}).items() if k != "never_seen_keys"},
        "shards": [{"index": sh["index"], "keys": sh["keys"], "error": sh["error"],
                    "frames": (sh["summary"] or {}).get("frames"),
                    "reconnects": (sh["summary"] or {}).get("reconnects")}
                   for sh in doc["shards"]],
        "excluded_by_capacity": len(doc["universe"]["excluded_by_capacity"]),
        "next": f"ingest preopen --replay-from-session {manifest}"}
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if doc["status"] == "complete" else 1)


acceptance_app = typer.Typer(help="acceptance evidence (read-only)")
app.add_typer(acceptance_app, name="acceptance")


@acceptance_app.command("stage1")
def acceptance_stage1(
    out: str = typer.Option("var/acceptance/stage1.json", "--out", help="JSON report"),
    md: str = typer.Option("../docs/STAGE_1_FINAL_ACCEPTANCE.md", "--md",
                           help="regenerate the acceptance document here ('' = no)"),
):
    """Stage-1 final gate: criteria A-Y from the REAL database. Read-only.

    Exit 0 only when the overall verdict is COMPLETE.
    """
    import json as _json
    import pathlib

    from app.acceptance.stage1 import evaluate, to_markdown
    from app.db.engine import get_sessionmaker

    async def _go():
        async with get_sessionmaker()() as s:
            return await evaluate(s)

    rep = asyncio.run(_go())
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(_json.dumps(rep, indent=2, default=str))
    if md:
        pathlib.Path(md).write_text(to_markdown(rep))
    for c in rep["criteria"]:
        typer.echo(f"{c['id']}  {c['status']:13} {c['name']}"
                   + (f"   [blocked by {', '.join(c['decisions'])}]" if c["decisions"] else ""))
    typer.echo(f"OVERALL: {rep['overall']}")
    raise typer.Exit(0 if rep["overall"] == "COMPLETE" else 1)


@acceptance_app.command("preopen")
def acceptance_preopen(
    session_manifest: str = typer.Option(..., "--session", help="<stem>.session.json"),
    out: str = typer.Option(None, "--out", help="also write the JSON report here"),
):
    """Grade one real trading day's pre-open capture, end to end. Read-only.

    Replay the session with --commit first. B7/B8 are only graded from
    production-feed data whose ticks fall inside the pre-open window.
    """
    import json as _json
    import pathlib

    from app.acceptance.preopen_day import evaluate
    from app.db.engine import get_sessionmaker

    async def _go():
        async with get_sessionmaker()() as s:
            return await evaluate(s, pathlib.Path(session_manifest))

    doc = asyncio.run(_go()).as_dict()
    body = _json.dumps(doc, indent=2, default=str)
    if out:
        pathlib.Path(out).write_text(body + "\n")
    typer.echo(body)
    raise typer.Exit(0 if doc["verdict"] in ("PASS", "WARN") else 1)


@acceptance_app.command("instruments")
def acceptance_instruments(
    payload_sha256: str = typer.Option(..., "--payload-sha256", help="the loaded master"),
    out: str = typer.Option(None, "--out", help="also write the JSON report here"),
):
    """M3.0: archived master -> sha -> parse -> selection -> provenance ->
    instrument table -> replay (DRY_RUN) -> no changes."""
    import json as _json
    import pathlib

    from app.acceptance.instruments import evaluate
    from app.db.engine import get_sessionmaker

    async def _go():
        async with get_sessionmaker()() as s:
            return await evaluate(s, master_sha256=payload_sha256,
                                  archive_root=get_settings().archive_dir)

    doc = asyncio.run(_go())
    body = _json.dumps(doc, indent=2, default=str)
    if out:
        pathlib.Path(out).write_text(body + "\n")
    typer.echo(body)
    raise typer.Exit(0 if doc["verdict"] == "PASS" else 1)


upstox_app = typer.Typer(help="Upstox vendor operations")
app.add_typer(upstox_app, name="upstox")


@upstox_app.command("token-status")
def upstox_token_status():
    """Probe the cached token against /v2/user/profile. Never prints the token."""
    import json as _json

    from app.vendor.upstox.auth import token_status
    typer.echo(_json.dumps(token_status(), indent=2, default=str))


@upstox_app.command("login")
def upstox_login(
    force: bool = typer.Option(False, "--force", help="mint even if the cached token works"),
    insecure_tls: bool = typer.Option(
        False, "--insecure-tls",
        help="disable TLS verification (V1 did this unconditionally; V2 does not)",
    ),
):
    """Mint an Upstox access token via the TOTP flow. Performs a REAL login."""
    import json as _json

    from app.vendor.upstox.auth import ensure_access_token
    rec = ensure_access_token(force=force, verify_tls=not insecure_tls)
    typer.echo(_json.dumps({
        "ok": True,
        "user_id": rec.user_id,
        "email": rec.email,
        "token_length": len(rec.access_token),
        "minted_at": rec.minted_at.isoformat(),
        "cached_at": "backend/var/upstox_token.json (0600, gitignored)",
    }, indent=2))




# ── Stage 2 ──────────────────────────────────────────────────────────────────
stage2_app = typer.Typer(help="Stage 2 data processing (derived from Stage 1; no vendor calls)")
app.add_typer(stage2_app, name="stage2")


@stage2_app.command("process")
def stage2_process(
    commit: bool = typer.Option(False, "--commit", help="write canon_* tables"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
    full: bool = typer.Option(False, "--full", help="recompute every pair (not incremental)"),
    live: bool = typer.Option(False, "--live", help="continuous mode (needs "
                              "STAGE2_LIVE_ENABLED=true; not approved)"),
):
    """Stage 1 tables -> canon_instrument + canon_coverage. Incremental, idempotent."""
    import json as _json

    from app.canon.process import process
    from app.db.engine import get_sessionmaker

    if live and not get_settings().STAGE2_LIVE_ENABLED:
        get_logger("cli").error("stage2_live_disabled",
                                reason="STAGE2_LIVE_ENABLED is false (not approved)")
        raise typer.Exit(2)

    async def _go():
        async with get_sessionmaker()() as s:
            return await process(s, commit=commit, token=token, full=full)

    rep = asyncio.run(_go())
    typer.echo(_json.dumps(rep.summary(), indent=2, default=str))
    raise typer.Exit(0 if rep.status == "COMPLETE" else 1)


@stage2_app.command("quality")
def stage2_quality(out: str = typer.Option(None, "--out", help="also write the JSON here")):
    """Stage 2 data-quality gates over the canonical layer. Read-only."""
    import json as _json
    import pathlib

    from app.canon.quality import run_gates
    from app.db.engine import get_sessionmaker

    async def _go():
        async with get_sessionmaker()() as s:
            return await run_gates(s)

    rep = asyncio.run(_go())
    if out:
        pathlib.Path(out).write_text(_json.dumps(rep, indent=2, default=str))
    for g in rep["gates"]:
        typer.echo(f"{g['status']:5} {g['count']:>8}  {g['gate']}"
                   + (f"   -> {g['diagnostic']}" if g["diagnostic"] else ""))
    typer.echo(f"QUALITY: {rep['status']}  {rep['informational']}")
    raise typer.Exit(0 if rep["status"] == "PASS" else 1)

if __name__ == "__main__":
    app()
