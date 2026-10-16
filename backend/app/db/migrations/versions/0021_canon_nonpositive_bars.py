"""canon_market_bar: no bar with a price <= 0; canon_excluded_bar shows them

Found on the real DB (2026-10-16): the historical 1h backfill stored Upstox bars with
open = high = low = close = 0 (and one with open = low = 0), e.g. partly-paid and rights
ISINs and the 2023-11-12 Muhurat session. The ingest sanity check (validate_bar, mirrored
by the ohlcv_bar CHECK) tested the OHLC ordering but not positivity, so they reached the
canonical layer and Stage 2 J (invalid_ohlc) failed. A price <= 0 is not a market
observation: the canonical view now drops such bars, and every one stays visible, with
its reason, in canon_excluded_bar (as 0006 did for non-session placeholders). Stage 1
data is untouched; the parser quarantines new ones (Q1).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-16
"""
from alembic import op

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None

POSITIVE = "least(b.open, b.high, b.low, b.close) > 0"


def _load(name: str):
    import importlib.util
    import pathlib
    p = pathlib.Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name[:5], p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _views() -> tuple[str, str, str, str]:
    m6, m10 = _load("0006_canon_session_bars.py"), _load("0010_global_finality.py")
    market_old = m10._market_bar(m6.MARKET_BAR)
    market_new = market_old + f"\n        where {POSITIVE}"
    excluded_old = m6.EXCLUDED
    excluded_new = excluded_old + f"""
        union all
        select b.instrument_id, b.instrument_key, b.timeframe, b.session_date,
               b.bar_start_utc, b.open, b.high, b.low, b.close, b.volume,
               t.session_type,
               'non-positive price (vendor placeholder)' as reason,
               b.run_id, b.payload_sha256, b.knowable_at, b.fetched_at
        from ohlcv_bar b
        join canon_instrument ci on ci.instrument_id = b.instrument_id and ci.included
        join trading_session t on t.session_date = b.session_date and t.is_trading_day
        where not ({POSITIVE})"""
    return market_old, market_new, excluded_old, excluded_new


def upgrade() -> None:
    _, market_new, _, excluded_new = _views()
    op.execute("create or replace view canon_market_bar as " + market_new)
    op.execute("create or replace view canon_excluded_bar as " + excluded_new)


def downgrade() -> None:
    market_old, _, excluded_old, _ = _views()
    op.execute("create or replace view canon_market_bar as " + market_old)
    op.execute("create or replace view canon_excluded_bar as " + excluded_old)
