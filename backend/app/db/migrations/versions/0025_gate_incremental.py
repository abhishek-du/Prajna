"""Stage 1 gate, incremental ohlcv_bar checks (decision GATE-INCR, user 2026-10-21)

Additive only.
  ohlcv_bar             append-only trigger: no code updates or deletes a stored bar
                        (revisions are new rows); the incremental gate relies on it
  gate_scan_checkpoint  append-only: the ohlcv_bar check counts (B, C, X) and the
                        per-instrument bar counts (F-J evidence) over every run finished up
                        to a cut; FULL rescans and records whether it equals the previous
                        checkpoint + the increment (consistent)

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.create_table('gate_scan_checkpoint',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('scope', sa.String(40), nullable=False),
        sa.Column('method', sa.String(12), nullable=False),
        sa.Column('through_finished_at', TS, nullable=False),
        sa.Column('counts', postgresql.JSONB(), nullable=False),
        sa.Column('bars', postgresql.JSONB(), nullable=False),
        sa.Column('consistent', sa.Boolean(), nullable=True),
        sa.Column('previous_id', sa.BigInteger(), sa.ForeignKey('gate_scan_checkpoint.id'),
                  nullable=True),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('code_git_sha', sa.String(40), nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=False),
        sa.CheckConstraint("method in ('FULL','INCREMENTAL')", name='ck_gate_scan_method'))
    op.execute("""
        create function gate_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in ("gate_scan_checkpoint", "ohlcv_bar"):
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function gate_append_only()""")


def downgrade() -> None:
    for t in ("ohlcv_bar", "gate_scan_checkpoint"):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
    op.drop_table('gate_scan_checkpoint')
    op.execute("drop function if exists gate_append_only()")
