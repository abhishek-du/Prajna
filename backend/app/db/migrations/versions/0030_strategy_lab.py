"""Strategy Lab (user 2026-10-27): per-day strategy performance, trade and day forensics,
the morning brief and the strategy on/off switches, for the admin dashboard.

Additive only. Six append-only tables (trigger). A recomputation is a new lab_run; readers
take the latest run of a session. shadow_skip gains the closed reason SWITCHED_OFF (a P1
variant the admin switched off records one skip row per session instead of trades).

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
PX = sa.Numeric(18, 4)
INR = sa.Numeric(18, 2)
TABLES = ("strategy_switch", "lab_run", "strategy_day", "trade_forensic", "day_forensic",
          "daily_brief")
SKIP_OLD = ("SKIP_RRR", "CHECKLIST_LT4", "CAP_OPEN_RISK", "CAP_SECTOR", "CAP_LIQUIDITY",
            "HALT_DAILY", "MOVE_GT_3PCT", "NO_INTRADAY_BARS", "VOL_TOO_HIGH", "SR_BLOCKED",
            "NO_SR_ZONE", "HALT_FIRST_STOP")
SKIP_NEW = (*SKIP_OLD, "SWITCHED_OFF")


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} in (" + ",".join(f"'{v}'" for v in vals) + ")"


def _run_fk() -> sa.Column:
    return sa.Column('run_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('lab_run.run_id'), nullable=False)


def upgrade() -> None:
    op.create_table(
        'strategy_switch',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('strategy', sa.String(64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=True),
        sa.Column('created_at', TS, nullable=False, server_default=sa.text('clock_timestamp()')))
    op.create_index('ix_strategy_switch_strategy', 'strategy_switch', ['strategy', 'id'])
    op.create_table(
        'lab_run',
        sa.Column('run_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('lab_version', sa.String(32), nullable=False),
        sa.Column('inputs_sha256', sa.CHAR(64), nullable=False),
        sa.Column('counts', postgresql.JSONB(), nullable=False),
        sa.Column('code_git_sha', sa.String(64), nullable=False),
        sa.Column('created_at', TS, nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint(_in('kind', ("DAILY", "BRIEF")), name='ck_lab_run_kind'))
    op.create_index('ix_lab_run_session', 'lab_run', ['kind', 'session_date', 'created_at'])
    op.create_table(
        'strategy_day',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        _run_fk(),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('strategy', sa.String(64), nullable=False),
        sa.Column('family', sa.String(16), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('trades', sa.Integer(), nullable=False),
        sa.Column('wins', sa.Integer(), nullable=False),
        sa.Column('losses', sa.Integer(), nullable=False),
        sa.Column('gross_inr', INR, nullable=False),
        sa.Column('charges_inr', INR, nullable=False),
        sa.Column('net_inr', INR, nullable=False),
        sa.Column('net_r', sa.Float(), nullable=True),
        sa.Column('placebo_trades', sa.Integer(), nullable=True),
        sa.Column('placebo_net_inr', INR, nullable=True),
        sa.Column('regime_pre', sa.String(16), nullable=True),
        sa.Column('regime_open', sa.String(16), nullable=True),
        sa.Column('day_type', sa.String(16), nullable=True),
        sa.Column('equity_inr', INR, nullable=False),
        sa.Column('drawdown', sa.Float(), nullable=False),
        sa.Column('detail', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('run_id', 'strategy', name='uq_strategy_day_run'))
    op.create_index('ix_strategy_day_session', 'strategy_day', ['session_date', 'strategy'])
    op.create_table(
        'trade_forensic',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        _run_fk(),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('strategy', sa.String(64), nullable=False),
        sa.Column('family', sa.String(16), nullable=False),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('instrument_key', sa.String(64), nullable=False),
        sa.Column('symbol', sa.String(64), nullable=True),
        sa.Column('sector', sa.String(128), nullable=True),
        sa.Column('side', sa.SmallInteger(), nullable=False),
        sa.Column('is_placebo', sa.Boolean(), nullable=False),
        sa.Column('signal_at', TS, nullable=True),
        sa.Column('entry_at', TS, nullable=True),
        sa.Column('exit_at', TS, nullable=True),
        sa.Column('entry_px', PX, nullable=True),
        sa.Column('exit_px', PX, nullable=True),
        sa.Column('stop', PX, nullable=True),
        sa.Column('target', PX, nullable=True),
        sa.Column('qty', sa.Integer(), nullable=True),
        sa.Column('net_inr', INR, nullable=True),
        sa.Column('net_r', sa.Float(), nullable=True),
        sa.Column('exit_reason', sa.String(32), nullable=True),
        sa.Column('outcome_class', sa.String(32), nullable=False),
        sa.Column('outcome_rule', sa.Text(), nullable=False),
        sa.Column('mfe_pct', sa.Float(), nullable=True),
        sa.Column('mae_pct', sa.Float(), nullable=True),
        sa.Column('mfe_r', sa.Float(), nullable=True),
        sa.Column('mae_r', sa.Float(), nullable=True),
        sa.Column('target_after_exit', sa.Boolean(), nullable=True),
        sa.Column('regime_state', sa.String(16), nullable=True),
        sa.Column('day_type', sa.String(16), nullable=True),
        sa.Column('ai_verdict', sa.String(16), nullable=True),
        sa.Column('first_news_lag_min', sa.Float(), nullable=True),
        sa.Column('news_before', postgresql.JSONB(), nullable=False),
        sa.Column('news_after', postgresql.JSONB(), nullable=False),
        sa.Column('plan', postgresql.JSONB(), nullable=False),
        sa.Column('path', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('run_id', 'source', 'source_id', name='uq_trade_forensic_run'))
    op.create_index('ix_trade_forensic_session', 'trade_forensic',
                    ['session_date', 'strategy'])
    op.create_table(
        'day_forensic',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        _run_fk(),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('strategy', sa.String(64), nullable=False),
        sa.Column('thought', postgresql.JSONB(), nullable=False),
        sa.Column('happened', postgresql.JSONB(), nullable=False),
        sa.Column('why', postgresql.JSONB(), nullable=False),
        sa.Column('narrative', postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint('run_id', 'strategy', name='uq_day_forensic_run'))
    op.create_table(
        'daily_brief',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        _run_fk(),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('regime', postgresql.JSONB(), nullable=False),
        sa.Column('events', postgresql.JSONB(), nullable=False),
        sa.Column('candidates', postgresql.JSONB(), nullable=False),
        sa.Column('news', postgresql.JSONB(), nullable=False),
        sa.Column('disclaimer', sa.Text(), nullable=False),
        sa.UniqueConstraint('run_id', name='uq_daily_brief_run'))
    op.execute("""
        create function lab_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function lab_append_only()""")
    op.drop_constraint('ck_shadow_skip_reason', 'shadow_skip', type_='check')
    op.create_check_constraint('ck_shadow_skip_reason', 'shadow_skip', _in('reason', SKIP_NEW))


def downgrade() -> None:
    op.drop_constraint('ck_shadow_skip_reason', 'shadow_skip', type_='check')
    op.create_check_constraint('ck_shadow_skip_reason', 'shadow_skip', _in('reason', SKIP_OLD))
    for t in reversed(TABLES):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
        op.drop_table(t)
    op.execute("drop function if exists lab_append_only()")
