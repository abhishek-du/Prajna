"""Price basis, observation history, corporate-action factors (hardening 6-7)

Proven 2026-09-25 (live curl + archives): Upstox rewrites the 1D AND intraday
history of an instrument when a split/bonus goes ex (CHAVDA: 740/740 bars =
half-even(raw / 2, 0.05), volume x 2); it serves history adjusted as of the
fetch, inconsistently (4 of 10 checked events never adjusted); its corporate-
action feed covers ~1 year. Stored history is therefore of mixed basis and
raw values before ~2025-09 are unrecoverable.

Additive only (no existing row is rewritten; 5M ohlcv_bar rows untouched):
  ohlcv_payload_basis  price basis per archived payload: RAW_OBSERVED
                       (intraday endpoint, global instruments) / VENDOR_ADJUSTED
                       (historical endpoint, as of the fetch date); seeded
  ohlcv_observation    append-only later observations of a stored bar, with a
                       classification; UPDATE/DELETE forbidden by trigger
  corporate_action     + first_seen_at, last_seen_at (seeded = fetched_at)
  ca_factor            derived, versioned factors with the vendor's observed
                       treatment (applied or not) and the evidence

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

BASES = "'RAW_OBSERVED','VENDOR_ADJUSTED','RECONSTRUCTED_RAW'"
CLASSES = "'CA_ADJUSTMENT','ROUNDING','SETTLEMENT','GLOBAL_REVISION','UNEXPLAINED'"


def upgrade() -> None:
    op.create_table('ohlcv_payload_basis',
        sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
        sa.Column('endpoint', sa.String(length=16), nullable=True),
        sa.Column('price_basis', sa.String(length=20), nullable=False),
        sa.Column('basis_as_of', sa.Date(), nullable=False),
        sa.Column('basis_confidence', sa.String(length=8), nullable=False),
        sa.Column('method_version', sa.String(length=32), nullable=False),
        sa.Column('evidence', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.CheckConstraint(f"price_basis in ({BASES})", name='ck_payload_basis_basis'),
        sa.CheckConstraint("basis_confidence in ('HIGH','LOW')", name='ck_payload_basis_conf'),
        sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'],
                                ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('payload_sha256'),
    )
    op.execute("""
        insert into ohlcv_payload_basis (payload_sha256, endpoint, price_basis, basis_as_of,
               basis_confidence, method_version, evidence)
        select distinct on (b.payload_sha256) b.payload_sha256,
               r.request_params->>'endpoint',
               case when i.segment like 'GLOBAL%' or r.request_params->>'endpoint' = 'intraday'
                    then 'RAW_OBSERVED' else 'VENDOR_ADJUSTED' end,
               (b.fetched_at at time zone 'Asia/Kolkata')::date, 'HIGH', 'basis-v1',
               jsonb_build_object('seed', 'migration 0009',
                 'rule', case when i.segment like 'GLOBAL%' then 'global: no corporate actions'
                              when r.request_params->>'endpoint' = 'intraday'
                              then 'intraday endpoint: same-day bars as traded'
                              else 'historical endpoint: vendor-adjusted as of the fetch' end)
        from ohlcv_bar b join ingest_run r using (run_id)
        join instrument i on i.instrument_id = b.instrument_id
        order by b.payload_sha256""")

    op.create_table('ohlcv_observation',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('instrument_id', sa.BigInteger(), nullable=False),
        sa.Column('timeframe', sa.String(length=8), nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('bar_start_utc', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('instrument_key', sa.String(length=80), nullable=False),
        sa.Column('open', sa.Numeric(18, 4), nullable=False),
        sa.Column('high', sa.Numeric(18, 4), nullable=False),
        sa.Column('low', sa.Numeric(18, 4), nullable=False),
        sa.Column('close', sa.Numeric(18, 4), nullable=False),
        sa.Column('volume', sa.Numeric(22, 0), nullable=False),
        sa.Column('open_interest', sa.Numeric(22, 0), nullable=True),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
        sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('classification', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('explained_by', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('method_version', sa.String(length=32), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.CheckConstraint(f"classification in ({CLASSES})", name='ck_observation_class'),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.instrument_id'],
                                ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'],
                                ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_observation_bar', 'ohlcv_observation',
                    ['instrument_id', 'timeframe', 'bar_start_utc'])
    op.execute("""
        create function ohlcv_observation_append_only() returns trigger language plpgsql as $$
        begin
          raise exception 'ohlcv_observation is append-only (% refused)', tg_op;
        end $$""")
    op.execute("""create trigger tr_observation_append_only before update or delete
                  on ohlcv_observation for each row execute function
                  ohlcv_observation_append_only()""")

    op.add_column('corporate_action', sa.Column('first_seen_at',
                  postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('corporate_action', sa.Column('last_seen_at',
                  postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.execute("update corporate_action set first_seen_at = fetched_at, last_seen_at = fetched_at")

    op.create_table('ca_factor',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('ca_id', sa.BigInteger(), nullable=False),
        sa.Column('instrument_key', sa.String(length=80), nullable=True),
        sa.Column('action_type', sa.String(length=16), nullable=False),
        sa.Column('ex_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('method', sa.String(length=16), nullable=False),
        sa.Column('factor_price', sa.Numeric(24, 12), nullable=True),
        sa.Column('factor_volume', sa.Numeric(24, 12), nullable=True),
        sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('vendor_applied', sa.String(length=12), nullable=False),
        sa.Column('vendor_evidence', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('inputs', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('method_version', sa.String(length=32), nullable=False),
        sa.Column('derived_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.CheckConstraint("status in ('EXACT','UNCERTAIN','UNSUPPORTED')",
                           name='ck_ca_factor_status'),
        sa.CheckConstraint("vendor_applied in ('APPLIED','NOT_APPLIED','UNKNOWN','N/A')",
                           name='ck_ca_factor_vendor'),
        sa.CheckConstraint("(status = 'EXACT') = (factor_price is not null)",
                           name='ck_ca_factor_exact_has_factor'),
        sa.ForeignKeyConstraint(['ca_id'], ['corporate_action.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ca_id', 'method_version', name='uq_ca_factor_version'),
    )
    op.create_index('ix_ca_factor_key', 'ca_factor', ['instrument_key', 'ex_date'])


def downgrade() -> None:
    op.drop_index('ix_ca_factor_key', table_name='ca_factor')
    op.drop_table('ca_factor')
    op.drop_column('corporate_action', 'last_seen_at')
    op.drop_column('corporate_action', 'first_seen_at')
    op.execute("drop trigger if exists tr_observation_append_only on ohlcv_observation")
    op.drop_index('ix_observation_bar', table_name='ohlcv_observation')
    op.drop_table('ohlcv_observation')
    op.execute("drop function if exists ohlcv_observation_append_only()")
    op.drop_table('ohlcv_payload_basis')
