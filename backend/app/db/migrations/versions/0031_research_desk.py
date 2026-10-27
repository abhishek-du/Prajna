"""Research Desk (user 2026-10-27): the agentic investigation of every stock (rules + LLM),
the auto-managed watchlist and the live tracking of its suggestions. PAPER ONLY: a verdict
is a research suggestion; nothing here describes an order.

Additive only. Five append-only tables (trigger). The current watchlist is derived from
the event log; a suggestion's life (entry triggered, T1, T2, stop, expiry) is one event row
per kind.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
PX = sa.Numeric(18, 4)
TABLES = ("desk_run", "desk_dossier", "desk_verdict", "desk_watch_event", "desk_track_event")
KINDS = ("EVENING", "MORNING", "INTRADAY")
STATUS = ("OK", "INVALID", "ERROR")
DECISIONS = ("STRONG_BUY", "BUY", "WATCH", "AVOID", "SELL")
WATCH = ("ADD", "REMOVE", "UPDATE")
TRACK = ("ENTRY_TRIGGERED", "T1", "T2", "STOP", "EXPIRED", "INVALIDATED")
NOW = sa.text('clock_timestamp()')


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} in (" + ",".join(f"'{v}'" for v in vals) + ")"


def upgrade() -> None:
    op.create_table(
        'desk_run',
        sa.Column('run_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('desk_version', sa.String(32), nullable=False),
        sa.Column('model_id', sa.String(64), nullable=False),
        sa.Column('prompt_version', sa.String(32), nullable=False),
        sa.Column('counts', postgresql.JSONB(), nullable=False),
        sa.Column('code_git_sha', sa.String(64), nullable=False),
        sa.Column('created_at', TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(_in('kind', KINDS), name='ck_desk_run_kind'))
    op.create_index('ix_desk_run_session', 'desk_run', ['session_date', 'created_at'])
    op.create_table(
        'desk_dossier',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('desk_run.run_id'),
                  nullable=False),
        sa.Column('instrument_key', sa.String(64), nullable=False),
        sa.Column('symbol', sa.String(64), nullable=True),
        sa.Column('packet', postgresql.JSONB(), nullable=False),
        sa.Column('packet_sha256', sa.CHAR(64), nullable=False),
        sa.UniqueConstraint('run_id', 'instrument_key', name='uq_desk_dossier_run'))
    op.create_table(
        'desk_verdict',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('desk_run.run_id'),
                  nullable=False),
        sa.Column('dossier_id', sa.BigInteger(), sa.ForeignKey('desk_dossier.id'),
                  nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('instrument_key', sa.String(64), nullable=False),
        sa.Column('symbol', sa.String(64), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('invalid_reason', sa.Text(), nullable=True),
        sa.Column('decision', sa.String(16), nullable=True),
        sa.Column('horizon', sa.String(16), nullable=True),
        sa.Column('score', sa.SmallInteger(), nullable=True),
        sa.Column('pov', postgresql.JSONB(), nullable=True),
        sa.Column('entry_lo', PX, nullable=True),
        sa.Column('entry_hi', PX, nullable=True),
        sa.Column('stop', PX, nullable=True),
        sa.Column('t1', PX, nullable=True),
        sa.Column('t2', PX, nullable=True),
        sa.Column('levels_basis', postgresql.JSONB(), nullable=True),
        sa.Column('why_moved', postgresql.JSONB(), nullable=True),
        sa.Column('thesis', sa.Text(), nullable=True),
        sa.Column('risks', postgresql.JSONB(), nullable=True),
        sa.Column('invalidation', sa.Text(), nullable=True),
        sa.Column('evidence_ids', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('rule_decision', sa.String(16), nullable=False),
        sa.Column('rule_flags', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('rule_plan', postgresql.JSONB(), nullable=False),
        sa.Column('conflicts', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('model_id', sa.String(64), nullable=False),
        sa.Column('prompt_sha256', sa.CHAR(64), nullable=False),
        sa.Column('response_raw', sa.Text(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint('run_id', 'instrument_key', name='uq_desk_verdict_run'),
        sa.CheckConstraint(_in('status', STATUS), name='ck_desk_verdict_status'),
        sa.CheckConstraint("decision is null or " + _in('decision', DECISIONS),
                           name='ck_desk_verdict_decision'),
        sa.CheckConstraint("status <> 'OK' or decision is not null",
                           name='ck_desk_verdict_ok_has_decision'))
    op.create_index('ix_desk_verdict_key', 'desk_verdict', ['instrument_key', 'created_at'])
    op.create_index('ix_desk_verdict_session', 'desk_verdict', ['session_date', 'score'])
    op.create_table(
        'desk_watch_event',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('instrument_key', sa.String(64), nullable=False),
        sa.Column('symbol', sa.String(64), nullable=True),
        sa.Column('event', sa.String(16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('verdict_id', sa.BigInteger(), sa.ForeignKey('desk_verdict.id'),
                  nullable=True),
        sa.Column('score', sa.SmallInteger(), nullable=True),
        sa.Column('decision', sa.String(16), nullable=True),
        sa.Column('created_at', TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(_in('event', WATCH), name='ck_desk_watch_event'))
    op.create_index('ix_desk_watch_key', 'desk_watch_event', ['instrument_key', 'id'])
    op.create_table(
        'desk_track_event',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('verdict_id', sa.BigInteger(), sa.ForeignKey('desk_verdict.id'),
                  nullable=False),
        sa.Column('instrument_key', sa.String(64), nullable=False),
        sa.Column('symbol', sa.String(64), nullable=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('price', PX, nullable=True),
        sa.Column('at', TS, nullable=False),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('created_at', TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint('verdict_id', 'kind', name='uq_desk_track_once'),
        sa.CheckConstraint(_in('kind', TRACK), name='ck_desk_track_kind'))
    op.execute("""
        create function desk_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function desk_append_only()""")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
        op.drop_table(t)
    op.execute("drop function if exists desk_append_only()")
