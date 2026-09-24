"""canon_market_bar: only bars on real trading sessions; canon_excluded_bar

Found on the real DB (2026-09-24): Upstox serves daily bars for 68 NSE
instruments on Saturday 2025-04-26, a WEEKEND in the calendar (no NIFTY bar,
no holiday entry). All 68 are placeholders: open = high = low = close and
volume 0. They are not market observations, so the canonical bar view now
exposes only bars on trading sessions, and every excluded bar stays visible,
with its reason, in canon_excluded_bar. Stage 1 data is untouched.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-24
"""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

MARKET_BAR = """
        select b.instrument_id, ci.instrument_key, ci.trading_symbol, ci.segment, ci.isin,
               b.timeframe, b.session_date as market_date, t.session_type,
               case when b.timeframe = '1d'
                    then (b.session_date + t.open_ist) at time zone 'Asia/Kolkata'
                    else b.bar_start_utc end as event_start,
               case when b.timeframe = '1d'
                    then (b.session_date + t.close_ist) at time zone 'Asia/Kolkata'
                    else least(b.bar_start_utc + case b.timeframe
                                 when '1m' then interval '1 minute'
                                 when '5m' then interval '5 minutes'
                                 when '15m' then interval '15 minutes'
                                 when '1h' then interval '1 hour' end,
                               coalesce((b.session_date + t.close_ist)
                                        at time zone 'Asia/Kolkata', 'infinity'))
               end as event_end,
               b.bar_start_utc, b.open, b.high, b.low, b.close, b.volume, b.open_interest,
               b.knowable_at, b.knowable_at_verified, b.knowable_at_basis, b.fetched_at,
               b.source, b.run_id, b.payload_sha256
        from ohlcv_bar b
        join canon_instrument ci on ci.instrument_id = b.instrument_id and ci.included
        join trading_session t on t.session_date = b.session_date
                              and t.is_trading_day"""

OLD_MARKET_BAR = """
        select b.instrument_id, ci.instrument_key, ci.trading_symbol, ci.segment, ci.isin,
               b.timeframe, b.session_date as market_date, t.session_type,
               case when b.timeframe = '1d'
                    then (b.session_date + t.open_ist) at time zone 'Asia/Kolkata'
                    else b.bar_start_utc end as event_start,
               case when b.timeframe = '1d'
                    then (b.session_date + t.close_ist) at time zone 'Asia/Kolkata'
                    else least(b.bar_start_utc + case b.timeframe
                                 when '1m' then interval '1 minute'
                                 when '5m' then interval '5 minutes'
                                 when '15m' then interval '15 minutes'
                                 when '1h' then interval '1 hour' end,
                               coalesce((b.session_date + t.close_ist)
                                        at time zone 'Asia/Kolkata', 'infinity'))
               end as event_end,
               b.bar_start_utc, b.open, b.high, b.low, b.close, b.volume, b.open_interest,
               b.knowable_at, b.knowable_at_verified, b.knowable_at_basis, b.fetched_at,
               b.source, b.run_id, b.payload_sha256
        from ohlcv_bar b
        join canon_instrument ci on ci.instrument_id = b.instrument_id and ci.included
        left join trading_session t on t.session_date = b.session_date"""

EXCLUDED = """
        select b.instrument_id, b.instrument_key, b.timeframe, b.session_date,
               b.bar_start_utc, b.open, b.high, b.low, b.close, b.volume,
               coalesce(t.session_type, 'NO_CALENDAR_ROW') as session_type,
               case when t.session_date is null then 'no calendar row for this date'
                    else 'no trading session on this date (' || t.session_type || ')'
               end as reason,
               b.run_id, b.payload_sha256, b.knowable_at, b.fetched_at
        from ohlcv_bar b
        join canon_instrument ci on ci.instrument_id = b.instrument_id and ci.included
        left join trading_session t on t.session_date = b.session_date
        where t.is_trading_day is not true"""


def upgrade() -> None:
    op.execute("create or replace view canon_market_bar as " + MARKET_BAR)
    op.execute("create view canon_excluded_bar as " + EXCLUDED)


def downgrade() -> None:
    op.execute("drop view canon_excluded_bar")
    op.execute("create or replace view canon_market_bar as " + OLD_MARKET_BAR)
