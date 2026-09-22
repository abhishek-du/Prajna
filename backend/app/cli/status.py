"""`prajna db status` — row counts and provenance coverage.

Provenance coverage is printed for every observation table because
"100% of rows carry full provenance" is a claim that should be continuously
re-proved, not asserted once in a design document.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.engine import get_engine

# Tables carrying the ProvenanceMixin.
PROVENANCED = [
    "trading_session", "instrument", "instrument_universe_membership",
    "preopen_tick", "preopen_session_status", "ohlcv_bar", "tick_archive",
    "corporate_action", "fundamental_snapshot", "macro_observation", "news_article",
]


async def print_status() -> None:
    engine = get_engine()
    async with engine.connect() as c:
        db = (await c.execute(text("select current_database()"))).scalar()
        tables = [
            r[0] for r in (await c.execute(text(
                "select tablename from pg_tables where schemaname='public' order by 1"
            ))).all()
        ]
        print(f"database: {db}\ntables:   {len(tables)}\n")
        print(f"{'table':<36}{'rows':>12}  provenance")
        print("-" * 68)
        for t in tables:
            n = (await c.execute(text(f"select count(*) from {t}"))).scalar()
            note = ""
            if t in PROVENANCED and n:
                gaps = (await c.execute(text(
                    f"select count(*) from {t} where source is null or run_id is null "
                    f"or payload_sha256 is null or fetched_at is null or knowable_at is null"
                ))).scalar()
                verified = (await c.execute(text(
                    f"select count(*) from {t} where knowable_at_verified"
                ))).scalar()
                note = f"gaps={gaps}  knowable_verified={verified}/{n}"
            elif t in PROVENANCED:
                note = "—"
            print(f"{t:<36}{n:>12}  {note}")
    await engine.dispose()
