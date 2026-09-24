"""Stage 2 canonical layer: canon_instrument, canon_coverage, canonical views

Additive: two new tables and seven views. Nothing existing is altered.
Market data is not copied; the views read the validated Stage 1 tables and
expose only NSE-universe rows (canon_instrument.included) with explicit
event_start / event_end / market_date / knowable_at / fetched_at.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

STATES = "'DATA','QUARANTINED','EMPTY','VENDOR_ERROR','PENDING_BACKFILL','MISSING'"

VIEWS = {
    # Bars of NSE-universe instruments. Daily (D4): the label is session_date
    # 00:00 IST; the EVENT is the session, open..close IST. Intraday: bar start
    # .. bar start + width, capped at the session close (NSE's last 1h bar,
    # 15:15-15:30, is 15 minutes). knowable_at/fetched_at are Stage 1's.
    "canon_market_bar": """
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
        left join trading_session t on t.session_date = b.session_date""",
    # Global indices / indicators: macro context only (not in the NSE universe).
    "canon_global_bar": """
        select b.instrument_id, i.instrument_key, i.trading_symbol, i.name, i.segment,
               b.timeframe, b.session_date as label_date, b.bar_start_utc,
               b.open, b.high, b.low, b.close, b.volume,
               b.knowable_at, b.knowable_at_verified, b.knowable_at_basis, b.fetched_at,
               b.source, b.run_id, b.payload_sha256
        from ohlcv_bar b
        join instrument i on i.instrument_id = b.instrument_id
        where i.segment in ('GLOBAL_INDEX', 'GLOBAL_INDICATOR') and i.valid_to = 'infinity'""",
    "canon_corporate_action": """
        select c.id, ci.instrument_id, ci.instrument_key, c.isin, ci.trading_symbol,
               c.action_type, c.announcement_date, c.ex_date, c.record_date, c.amount,
               c.ratio_from, c.ratio_to, c.face_value_before, c.face_value_after,
               c.content_sha256, c.knowable_at, c.knowable_at_verified, c.knowable_at_basis,
               c.fetched_at, c.source, c.run_id, c.payload_sha256
        from corporate_action c
        join canon_instrument ci on ci.instrument_key = c.instrument_key and ci.included""",
    # One row per (article, instrument). The association is knowable only when
    # BOTH the article and the vendor's tagging were (Stage 1: link = fetched_at).
    "canon_news": """
        select a.id as news_id, ci.instrument_id, n.instrument_key, a.headline, a.body,
               a.url, a.vendor_article_id, a.published_at,
               greatest(a.knowable_at, n.knowable_at) as knowable_at,
               a.knowable_at as article_knowable_at, n.knowable_at as link_knowable_at,
               greatest(a.fetched_at, n.fetched_at) as fetched_at,
               a.source, a.run_id, a.payload_sha256, n.payload_sha256 as link_payload_sha256
        from news_article a
        join news_instrument n on n.news_id = a.id
        join canon_instrument ci on ci.instrument_key = n.instrument_key and ci.included""",
    "canon_fundamental": """
        select f.id, ci.instrument_id, f.instrument_key, f.isin, f.statement_type,
               f.period_end, f.period_type, f.payload, f.knowable_at, f.knowable_at_verified,
               f.knowable_at_basis, f.fetched_at, f.source, f.run_id, f.payload_sha256
        from fundamental_snapshot f
        join canon_instrument ci on ci.instrument_key = f.instrument_key and ci.included""",
    "canon_preopen": """
        select p.tick_id, ci.instrument_id, p.instrument_key, p.session_date as market_date,
               p.vendor_ts as event_ts, p.iep, p.ieq, p.tbq, p.tsq, p.iiq_total, p.iiq_m,
               p.rp, p.ltp, p.cas_eligible, p.knowable_at, p.knowable_at_verified,
               p.knowable_at_basis, p.fetched_at, p.source, p.run_id, p.payload_sha256
        from preopen_tick p
        join canon_instrument ci on ci.instrument_key = p.instrument_key and ci.included""",
    "canon_macro_observation": """
        select m.id, m.series_code, m.observation_date, m.value, m.unit, m.knowable_at,
               m.knowable_at_verified, m.knowable_at_basis, m.fetched_at, m.source,
               m.run_id, m.payload_sha256
        from macro_observation m""",
}


def upgrade() -> None:
    op.create_table('canon_instrument',
        sa.Column('instrument_id', sa.BigInteger(), nullable=False),
        sa.Column('instrument_key', sa.String(length=80), nullable=False),
        sa.Column('segment', sa.String(length=16), nullable=False),
        sa.Column('exchange', sa.String(length=16), nullable=False),
        sa.Column('trading_symbol', sa.String(length=64), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('isin', sa.String(length=12), nullable=True),
        sa.Column('instrument_type', sa.String(length=8), nullable=True),
        sa.Column('included', sa.Boolean(), nullable=False),
        sa.Column('filter_reason', sa.Text(), nullable=False),
        sa.Column('rules_sha256', sa.CHAR(length=64), nullable=False),
        sa.Column('sector', sa.Text(), nullable=True),
        sa.Column('sector_knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('sector_snapshot_id', sa.BigInteger(), nullable=True),
        sa.Column('preopen_universe_session', sa.Date(), nullable=True),
        sa.Column('content_sha256', sa.CHAR(length=64), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.CheckConstraint('(sector is null) = (sector_knowable_at is null)',
                           name='ck_canon_instrument_sector_time'),
        sa.CheckConstraint("not included or segment in ('NSE_EQ', 'NSE_INDEX')",
                           name='ck_canon_instrument_nse_only'),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.instrument_id'],
                                ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['sector_snapshot_id'], ['fundamental_snapshot.id'],
                                ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('instrument_id'),
        sa.UniqueConstraint('instrument_key'),
    )
    op.create_index('ix_canon_instrument_included', 'canon_instrument', ['included'])
    op.create_table('canon_coverage',
        sa.Column('instrument_id', sa.BigInteger(), nullable=False),
        sa.Column('timeframe', sa.String(length=8), nullable=False),
        sa.Column('from_date', sa.Date(), nullable=False),
        sa.Column('to_date', sa.Date(), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('sessions', sa.Integer(), nullable=False),
        sa.Column('bars', sa.Integer(), nullable=False),
        sa.Column('quarantined', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.CheckConstraint(f"state in ({STATES})", name='ck_canon_coverage_state'),
        sa.CheckConstraint("timeframe in ('1d', '1h', '15m', '1m')",
                           name='ck_canon_coverage_timeframe'),
        sa.CheckConstraint('from_date <= to_date and sessions >= 1 and bars >= 0 '
                           'and quarantined >= 0', name='ck_canon_coverage_range'),
        sa.CheckConstraint("(state = 'DATA') = (bars > 0)", name='ck_canon_coverage_data'),
        sa.ForeignKeyConstraint(['instrument_id'], ['canon_instrument.instrument_id'],
                                ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('instrument_id', 'timeframe', 'from_date'),
    )
    op.create_index('ix_canon_coverage_state', 'canon_coverage', ['timeframe', 'state'])
    for name, sql in VIEWS.items():
        op.execute(f"create view {name} as {sql}")


def downgrade() -> None:
    for name in reversed(list(VIEWS)):
        op.execute(f"drop view if exists {name}")
    op.drop_index('ix_canon_coverage_state', table_name='canon_coverage')
    op.drop_table('canon_coverage')
    op.drop_index('ix_canon_instrument_included', table_name='canon_instrument')
    op.drop_table('canon_instrument')
