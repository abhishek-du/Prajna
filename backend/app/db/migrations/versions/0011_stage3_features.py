"""Stage 3 (feature engineering) storage: feature_value and stage3_event

Additive: two new append-only tables; no existing table, view or row changes.

  feature_value  one feature of one instrument/context at one snapshot of one
                 session; exactly one of value/reason; input_max_knowable_at <
                 as_of (point-in-time, enforced); unique per (key, session,
                 snapshot, feature, version); UPDATE/DELETE refused by trigger
  stage3_event   audit of lock refusals, kill-switch changes and run outcomes

Writing feature_value is locked (app.features.locks): the tables stay empty
until Stage 3 production execution is unlocked.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('feature_value',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('scope', sa.String(length=12), nullable=False),
        sa.Column('instrument_key', sa.String(length=80), nullable=False),
        sa.Column('instrument_id', sa.BigInteger(), nullable=True),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('snapshot', sa.String(length=12), nullable=False),
        sa.Column('as_of', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('feature_id', sa.String(length=64), nullable=False),
        sa.Column('feature_version', sa.Integer(), nullable=False),
        sa.Column('registry_sha256', sa.CHAR(length=64), nullable=False),
        sa.Column('value', sa.Numeric(30, 12), nullable=True),
        sa.Column('reason', sa.String(length=32), nullable=True),
        sa.Column('inputs_sha256', sa.CHAR(length=64), nullable=False),
        sa.Column('input_max_knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('computed_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.CheckConstraint("scope in ('INSTRUMENT','CONTEXT')", name='ck_feature_scope'),
        sa.CheckConstraint("snapshot in ('PRE_SESSION','PRE_OPEN')", name='ck_feature_snapshot'),
        sa.CheckConstraint("(value is null) <> (reason is null)",
                           name='ck_feature_value_or_reason'),
        sa.CheckConstraint("input_max_knowable_at is null or input_max_knowable_at < as_of",
                           name='ck_feature_pit'),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.instrument_id'],
                                ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instrument_key', 'session_date', 'snapshot', 'feature_id',
                            'feature_version', name='uq_feature_value'),
    )
    op.create_index('ix_feature_value_session', 'feature_value', ['session_date', 'snapshot'])
    op.create_index('ix_feature_value_run', 'feature_value', ['run_id'])

    op.create_table('stage3_event',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('at', postgresql.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('event', sa.String(length=24), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('operator', sa.String(length=64), nullable=False),
        sa.Column('detail', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('run_id', sa.UUID(), nullable=True),
        sa.CheckConstraint("event in ('REFUSED','KILL_ON','KILL_OFF','RUN_COMPLETE','RUN_FAILED')",
                           name='ck_stage3_event'),
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_stage3_event_at', 'stage3_event', ['at'])

    op.execute("""
        create function stage3_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in ('feature_value', 'stage3_event'):
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function stage3_append_only()""")


def downgrade() -> None:
    for t in ('feature_value', 'stage3_event'):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
    op.execute("drop function if exists stage3_append_only()")
    op.drop_index('ix_stage3_event_at', table_name='stage3_event')
    op.drop_table('stage3_event')
    op.drop_index('ix_feature_value_run', table_name='feature_value')
    op.drop_index('ix_feature_value_session', table_name='feature_value')
    op.drop_table('feature_value')
