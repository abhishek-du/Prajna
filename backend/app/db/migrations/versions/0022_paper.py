"""Stage 7 step 2: paper execution records (docs/STAGE7_8_PAPER_DESIGN.md, P8/P9)

Additive only. Four append-only tables (trigger): a run per (strategy, session), its
orders (the targets, in priority order), their simulated fills and the day's summary.
Every row carries mode, and a CHECK admits only 'PAPER': no row can describe a live
order. Nothing here talks to a broker.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
TABLES = ("paper_run", "paper_order", "paper_fill", "paper_day")


def _mode(t: str) -> sa.CheckConstraint:
    return sa.CheckConstraint("mode = 'PAPER'", name=f"ck_{t}_paper_only")


def upgrade() -> None:
    op.create_table('paper_run',
        sa.Column('run_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('strategy', sa.String(64), nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('mode', sa.String(8), nullable=False),
        sa.Column('targets_sha256', sa.CHAR(64), nullable=False),
        sa.Column('inputs_sha256', sa.CHAR(64), nullable=False),
        sa.Column('config', postgresql.JSONB(), nullable=False),
        sa.Column('bars_knowable_max', TS, nullable=True),
        sa.Column('code_git_sha', sa.String(48), nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.UniqueConstraint('strategy', 'session_date', name='uq_paper_run_strategy_session'),
        _mode('paper_run'))
    op.create_table('paper_order',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('paper_run.run_id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('instrument_key', sa.String(80), nullable=False),
        sa.Column('product', sa.String(8), nullable=False),
        sa.Column('order_value_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('mode', sa.String(8), nullable=False),
        sa.UniqueConstraint('run_id', 'instrument_key', name='uq_paper_order_run_key'),
        sa.UniqueConstraint('run_id', 'seq', name='uq_paper_order_run_seq'),
        sa.CheckConstraint("product = 'MIS'", name='ck_paper_order_mis'),
        _mode('paper_order'))
    op.create_table('paper_fill',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('paper_run.run_id'), nullable=False),
        sa.Column('instrument_key', sa.String(80), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('qty', sa.BigInteger(), nullable=False),
        sa.Column('buy_px', sa.Numeric(18, 4), nullable=True),
        sa.Column('sell_px', sa.Numeric(18, 4), nullable=True),
        sa.Column('buy_value_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('sell_value_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('charges', postgresql.JSONB(), nullable=False),
        sa.Column('pnl_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('mode', sa.String(8), nullable=False),
        sa.UniqueConstraint('run_id', 'instrument_key', name='uq_paper_fill_run_key'),
        sa.CheckConstraint("status in ('FILLED','PARTIAL','NOT_FILLED')",
                           name='ck_paper_fill_status'),
        sa.CheckConstraint("(qty > 0) = (status <> 'NOT_FILLED')", name='ck_paper_fill_qty'),
        _mode('paper_fill'))
    op.create_table('paper_day',
        sa.Column('run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('paper_run.run_id'), primary_key=True),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('targets', sa.Integer(), nullable=False),
        sa.Column('filled', sa.Integer(), nullable=False),
        sa.Column('not_filled', postgresql.JSONB(), nullable=False),
        sa.Column('start_cash_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('end_cash_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('pnl_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('charges_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('turnover_inr', sa.Numeric(18, 4), nullable=False),
        sa.Column('mode', sa.String(8), nullable=False),
        _mode('paper_day'))
    op.execute("""
        create function paper_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function paper_append_only()""")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
        op.drop_table(t)
    op.execute("drop function if exists paper_append_only()")
