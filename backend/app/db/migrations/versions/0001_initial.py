"""initial schema — 16 tables, Upstox-only, provenance-bearing

Revision ID: 0001
Revises: 
Create Date: 2026-09-22 11:58:30.792400+00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Required by the GiST EXCLUDE constraint on instrument(instrument_key,
    # daterange(valid_from, valid_to)) which makes overlapping SCD2 validity
    # ranges impossible at the database level.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table('ingest_run',
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('stream', sa.String(length=64), nullable=False),
    sa.Column('logical_date', sa.Date(), nullable=True),
    sa.Column('vendor_endpoint', sa.Text(), nullable=False),
    sa.Column('request_params', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('code_git_sha', sa.String(length=40), nullable=False),
    sa.Column('config_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('argv', sa.ARRAY(sa.Text()), nullable=False),
    sa.Column('operator', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=9), nullable=False),
    sa.Column('authz_token_sha256', sa.CHAR(length=64), nullable=True),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('finished_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('rows_written', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.CheckConstraint("mode <> 'COMMIT' or authz_token_sha256 is not null", name='ck_run_commit_requires_authz'),
    sa.CheckConstraint("mode <> 'DRY_RUN' or rows_written = 0", name='ck_run_dryrun_writes_nothing'),
    sa.CheckConstraint("mode in ('DRY_RUN','COMMIT')", name='ck_run_mode'),
    sa.CheckConstraint("status <> 'COMPLETE' or finished_at is not null", name='ck_run_complete_has_finish'),
    sa.CheckConstraint("status in ('RUNNING','COMPLETE','FAILED','ABORTED')", name='ck_run_status'),
    sa.PrimaryKeyConstraint('run_id')
    )
    op.create_index('ix_run_source_status', 'ingest_run', ['source', 'status'], unique=False)
    op.create_index('ix_run_stream_logical', 'ingest_run', ['stream', 'logical_date'], unique=False)
    op.create_table('ingest_watermark',
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('stream', sa.String(length=64), nullable=False),
    sa.Column('last_logical_date', sa.Date(), nullable=True),
    sa.Column('last_success_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('last_run_id', sa.UUID(), nullable=True),
    sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False),
    sa.Column('expected_cadence', sa.Interval(), nullable=True),
    sa.Column('rows_last_run', sa.BigInteger(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('source', 'stream')
    )
    op.create_table('ingest_anomaly',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('severity', sa.String(length=4), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('subject', sa.Text(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.CheckConstraint("severity in ('WARN','FAIL')", name='ck_anomaly_severity'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_anomaly_kind_created', 'ingest_anomaly', ['kind', 'created_at'], unique=False)
    op.create_index('ix_anomaly_run', 'ingest_anomaly', ['run_id'], unique=False)
    op.create_table('raw_payload',
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('vendor_endpoint', sa.Text(), nullable=False),
    sa.Column('request_params', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('content_type', sa.String(length=64), nullable=False),
    sa.Column('storage_uri', sa.Text(), nullable=False),
    sa.Column('first_seen_run', sa.UUID(), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('vendor_reported_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['first_seen_run'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('payload_sha256')
    )
    op.create_index('ix_payload_source_fetched', 'raw_payload', ['source', 'fetched_at'], unique=False)
    op.create_table('corporate_action',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('isin', sa.String(length=12), nullable=False),
    sa.Column('instrument_key', sa.String(length=80), nullable=True),
    sa.Column('trading_symbol', sa.String(length=64), nullable=True),
    sa.Column('action_type', sa.String(length=16), nullable=False),
    sa.Column('ex_date', sa.Date(), nullable=True),
    sa.Column('record_date', sa.Date(), nullable=True),
    sa.Column('announced_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('ratio_from', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('ratio_to', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('amount', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('face_value_before', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('face_value_after', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('vendor_action_id', sa.String(length=64), nullable=True),
    sa.Column('vendor_payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint("action_type in ('SPLIT','BONUS','DIVIDEND','RIGHTS','MERGER','DEMERGER','SYMBOL_CHANGE','ISIN_CHANGE','OTHER')", name='ck_ca_action_type'),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_ca_knowable'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('isin', 'action_type', 'ex_date', 'vendor_action_id', 'source', name='uq_ca_observation')
    )
    op.create_index('ix_ca_ex_date', 'corporate_action', ['ex_date'], unique=False)
    op.create_index('ix_ca_isin_ex', 'corporate_action', ['isin', 'ex_date'], unique=False)
    op.create_index(op.f('ix_corporate_action_run_id'), 'corporate_action', ['run_id'], unique=False)
    op.create_table('fundamental_snapshot',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('instrument_key', sa.String(length=80), nullable=False),
    sa.Column('isin', sa.String(length=12), nullable=True),
    sa.Column('statement_type', sa.String(length=32), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=True),
    sa.Column('period_type', sa.String(length=16), nullable=True),
    sa.Column('reported_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_fund_knowable'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instrument_key', 'statement_type', 'period_end', 'knowable_at', 'source', name='uq_fundamental_observation')
    )
    op.create_index('ix_fund_key_type', 'fundamental_snapshot', ['instrument_key', 'statement_type'], unique=False)
    op.create_index(op.f('ix_fundamental_snapshot_run_id'), 'fundamental_snapshot', ['run_id'], unique=False)
    op.create_table('instrument',
    sa.Column('instrument_id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('instrument_key', sa.String(length=80), nullable=False),
    sa.Column('segment', sa.String(length=16), nullable=False),
    sa.Column('exchange', sa.String(length=16), nullable=False),
    sa.Column('trading_symbol', sa.String(length=64), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('short_name', sa.Text(), nullable=True),
    sa.Column('isin', sa.String(length=12), nullable=True),
    sa.Column('instrument_type', sa.String(length=8), nullable=True),
    sa.Column('security_type', sa.String(length=16), nullable=True),
    sa.Column('exchange_token', sa.String(length=24), nullable=True),
    sa.Column('lot_size', sa.Integer(), nullable=True),
    sa.Column('tick_size', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('freeze_quantity', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('qty_multiplier', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('cas_eligible', sa.Boolean(), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), server_default='infinity', nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    postgresql.ExcludeConstraint((sa.column('instrument_key'), '='), (sa.text("daterange(valid_from, valid_to, '[)')"), '&&'), using='gist', name='ex_instrument_no_overlap'),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_instrument_knowable'),
    sa.CheckConstraint('valid_from < valid_to', name='ck_instrument_validity_order'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('instrument_id')
    )
    op.create_index('ix_instrument_isin', 'instrument', ['isin'], unique=False)
    op.create_index('ix_instrument_key', 'instrument', ['instrument_key'], unique=False)
    op.create_index(op.f('ix_instrument_run_id'), 'instrument', ['run_id'], unique=False)
    op.create_index('ix_instrument_segment_type', 'instrument', ['segment', 'instrument_type'], unique=False)
    op.create_index('ix_instrument_symbol', 'instrument', ['trading_symbol'], unique=False)
    op.create_table('instrument_universe_membership',
    sa.Column('universe', sa.String(length=48), nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('instrument_key', sa.String(length=80), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_universe_knowable'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('universe', 'session_date', 'instrument_key')
    )
    op.create_index(op.f('ix_instrument_universe_membership_run_id'), 'instrument_universe_membership', ['run_id'], unique=False)
    op.create_index('ix_universe_session', 'instrument_universe_membership', ['universe', 'session_date'], unique=False)
    op.create_table('macro_observation',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('series_code', sa.String(length=48), nullable=False),
    sa.Column('observation_date', sa.Date(), nullable=False),
    sa.Column('observation_ts', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('value', sa.Numeric(precision=24, scale=6), nullable=False),
    sa.Column('unit', sa.String(length=24), nullable=True),
    sa.Column('vendor_payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_macro_knowable'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_code', 'observation_date', 'knowable_at', 'source', name='uq_macro_observation')
    )
    op.create_index(op.f('ix_macro_observation_run_id'), 'macro_observation', ['run_id'], unique=False)
    op.create_index('ix_macro_series_date', 'macro_observation', ['series_code', 'observation_date'], unique=False)
    op.create_table('news_article',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('headline', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('publisher', sa.String(length=120), nullable=True),
    sa.Column('published_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('headline_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('vendor_article_id', sa.String(length=128), nullable=True),
    sa.Column('vendor_payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_news_knowable'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('headline_sha256', 'published_at', 'source', name='uq_news_observation')
    )
    op.create_index(op.f('ix_news_article_run_id'), 'news_article', ['run_id'], unique=False)
    op.create_index('ix_news_published', 'news_article', ['published_at'], unique=False)
    op.create_index('ix_news_publisher', 'news_article', ['publisher'], unique=False)
    op.create_table('tick_archive',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('instrument_key', sa.String(length=80), nullable=False),
    sa.Column('vendor_ts', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('ltp', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('ltq', sa.BigInteger(), nullable=True),
    sa.Column('vtt', sa.BigInteger(), nullable=True),
    sa.Column('atp', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('tbq', sa.Numeric(precision=22, scale=2), nullable=True),
    sa.Column('tsq', sa.Numeric(precision=22, scale=2), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_tick_knowable'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tick_archive_run_id'), 'tick_archive', ['run_id'], unique=False)
    op.create_index('ix_tick_session_instr', 'tick_archive', ['session_date', 'instrument_key'], unique=False)
    op.create_table('trading_session',
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('is_trading_day', sa.Boolean(), nullable=False),
    sa.Column('session_type', sa.String(length=16), nullable=False),
    sa.Column('preopen_start_ist', sa.Time(), nullable=True),
    sa.Column('preopen_end_ist', sa.Time(), nullable=True),
    sa.Column('open_ist', sa.Time(), nullable=True),
    sa.Column('close_ist', sa.Time(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint("session_type in ('NORMAL','MUHURAT','SPECIAL','HOLIDAY','WEEKEND')", name='ck_session_type'),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_trading_session_knowable'),
    sa.CheckConstraint('not is_trading_day or (open_ist is not null and close_ist is not null)', name='ck_session_trading_has_hours'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('session_date')
    )
    op.create_index(op.f('ix_trading_session_run_id'), 'trading_session', ['run_id'], unique=False)
    op.create_table('ohlcv_bar',
    sa.Column('instrument_id', sa.BigInteger(), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('bar_start_utc', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('instrument_key', sa.String(length=80), nullable=False),
    sa.Column('open', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('high', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('low', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('close', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('volume', sa.Numeric(precision=22, scale=0), nullable=False),
    sa.Column('open_interest', sa.Numeric(precision=22, scale=0), nullable=True),
    sa.Column('vendor_ts_raw', sa.Text(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('high >= low and high >= open and high >= close and low <= open and low <= close and volume >= 0', name='ck_ohlcv_sane'),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_ohlcv_knowable'),
    sa.ForeignKeyConstraint(['instrument_id'], ['instrument.instrument_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('instrument_id', 'timeframe', 'session_date', 'bar_start_utc', 'source')
    )
    op.create_index(op.f('ix_ohlcv_bar_run_id'), 'ohlcv_bar', ['run_id'], unique=False)
    op.create_index('ix_ohlcv_instrument_tf_session', 'ohlcv_bar', ['instrument_id', 'timeframe', 'session_date'], unique=False)
    op.create_index('ix_ohlcv_key_tf', 'ohlcv_bar', ['instrument_key', 'timeframe'], unique=False)
    op.create_index('ix_ohlcv_tf_session', 'ohlcv_bar', ['timeframe', 'session_date'], unique=False)
    op.create_table('preopen_session_status',
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('segment', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('vendor_updated_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('observed_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_preopen_status_knowable'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_date'], ['trading_session.session_date'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('session_date', 'segment', 'status', 'vendor_updated_at')
    )
    op.create_index(op.f('ix_preopen_session_status_run_id'), 'preopen_session_status', ['run_id'], unique=False)
    op.create_index('ix_preopen_status_session', 'preopen_session_status', ['session_date'], unique=False)
    op.create_table('preopen_tick',
    sa.Column('tick_id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('instrument_key', sa.String(length=80), nullable=False),
    sa.Column('instrument_id', sa.BigInteger(), nullable=True),
    sa.Column('frame_seq', sa.BigInteger(), nullable=False),
    sa.Column('vendor_ts', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('feed_type', sa.String(length=16), nullable=False),
    sa.Column('request_mode', sa.String(length=16), nullable=False),
    sa.Column('iep', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('ieq', sa.BigInteger(), nullable=True),
    sa.Column('iiq_total', sa.BigInteger(), nullable=True),
    sa.Column('iiq_m', sa.BigInteger(), nullable=True),
    sa.Column('rp', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('tbq', sa.Numeric(precision=22, scale=2), nullable=True),
    sa.Column('tsq', sa.Numeric(precision=22, scale=2), nullable=True),
    sa.Column('cas_eligible', sa.Boolean(), nullable=True),
    sa.Column('atp', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('vtt', sa.BigInteger(), nullable=True),
    sa.Column('oi', sa.Numeric(precision=22, scale=2), nullable=True),
    sa.Column('iv', sa.Numeric(precision=14, scale=6), nullable=True),
    sa.Column('ltp', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('ltt', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('ltq', sa.BigInteger(), nullable=True),
    sa.Column('cp', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('ltpc_iep', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('iep is null or iep >= 0', name='ck_preopen_tick_iep_sign'),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_preopen_tick_knowable'),
    sa.ForeignKeyConstraint(['instrument_id'], ['instrument.instrument_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_date'], ['trading_session.session_date'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('tick_id'),
    sa.UniqueConstraint('session_date', 'instrument_key', 'vendor_ts', 'source', name='uq_preopen_tick_observation')
    )
    op.create_index(op.f('ix_preopen_tick_run_id'), 'preopen_tick', ['run_id'], unique=False)
    op.create_index('ix_preopen_tick_session_instr', 'preopen_tick', ['session_date', 'instrument_key'], unique=False)
    op.create_index('ix_preopen_tick_session_vendor_ts', 'preopen_tick', ['session_date', 'vendor_ts'], unique=False)
    op.create_table('preopen_book',
    sa.Column('tick_id', sa.BigInteger(), nullable=False),
    sa.Column('rung_no', sa.SmallInteger(), nullable=False),
    sa.Column('bid_qty', sa.BigInteger(), nullable=True),
    sa.Column('bid_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('ask_qty', sa.BigInteger(), nullable=True),
    sa.Column('ask_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.CheckConstraint('rung_no >= 0 and rung_no < 30', name='ck_preopen_book_rung_range'),
    sa.ForeignKeyConstraint(['tick_id'], ['preopen_tick.tick_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('tick_id', 'rung_no')
    )


def downgrade() -> None:
    op.drop_table('preopen_book')
    op.drop_index('ix_preopen_tick_session_vendor_ts', table_name='preopen_tick')
    op.drop_index('ix_preopen_tick_session_instr', table_name='preopen_tick')
    op.drop_index(op.f('ix_preopen_tick_run_id'), table_name='preopen_tick')
    op.drop_table('preopen_tick')
    op.drop_index('ix_preopen_status_session', table_name='preopen_session_status')
    op.drop_index(op.f('ix_preopen_session_status_run_id'), table_name='preopen_session_status')
    op.drop_table('preopen_session_status')
    op.drop_index('ix_ohlcv_tf_session', table_name='ohlcv_bar')
    op.drop_index('ix_ohlcv_key_tf', table_name='ohlcv_bar')
    op.drop_index('ix_ohlcv_instrument_tf_session', table_name='ohlcv_bar')
    op.drop_index(op.f('ix_ohlcv_bar_run_id'), table_name='ohlcv_bar')
    op.drop_table('ohlcv_bar')
    op.drop_index(op.f('ix_trading_session_run_id'), table_name='trading_session')
    op.drop_table('trading_session')
    op.drop_index('ix_tick_session_instr', table_name='tick_archive')
    op.drop_index(op.f('ix_tick_archive_run_id'), table_name='tick_archive')
    op.drop_table('tick_archive')
    op.drop_index('ix_news_publisher', table_name='news_article')
    op.drop_index('ix_news_published', table_name='news_article')
    op.drop_index(op.f('ix_news_article_run_id'), table_name='news_article')
    op.drop_table('news_article')
    op.drop_index('ix_macro_series_date', table_name='macro_observation')
    op.drop_index(op.f('ix_macro_observation_run_id'), table_name='macro_observation')
    op.drop_table('macro_observation')
    op.drop_index('ix_universe_session', table_name='instrument_universe_membership')
    op.drop_index(op.f('ix_instrument_universe_membership_run_id'), table_name='instrument_universe_membership')
    op.drop_table('instrument_universe_membership')
    op.drop_index('ix_instrument_symbol', table_name='instrument')
    op.drop_index('ix_instrument_segment_type', table_name='instrument')
    op.drop_index(op.f('ix_instrument_run_id'), table_name='instrument')
    op.drop_index('ix_instrument_key', table_name='instrument')
    op.drop_index('ix_instrument_isin', table_name='instrument')
    op.drop_table('instrument')
    op.drop_index(op.f('ix_fundamental_snapshot_run_id'), table_name='fundamental_snapshot')
    op.drop_index('ix_fund_key_type', table_name='fundamental_snapshot')
    op.drop_table('fundamental_snapshot')
    op.drop_index(op.f('ix_corporate_action_run_id'), table_name='corporate_action')
    op.drop_index('ix_ca_isin_ex', table_name='corporate_action')
    op.drop_index('ix_ca_ex_date', table_name='corporate_action')
    op.drop_table('corporate_action')
    op.drop_index('ix_payload_source_fetched', table_name='raw_payload')
    op.drop_table('raw_payload')
    op.drop_index('ix_anomaly_run', table_name='ingest_anomaly')
    op.drop_index('ix_anomaly_kind_created', table_name='ingest_anomaly')
    op.drop_table('ingest_anomaly')
    op.drop_table('ingest_watermark')
    op.drop_index('ix_run_stream_logical', table_name='ingest_run')
    op.drop_index('ix_run_source_status', table_name='ingest_run')
    op.drop_table('ingest_run')
