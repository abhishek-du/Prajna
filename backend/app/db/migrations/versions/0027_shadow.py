"""Stage 4 v2 P1: regime engine + shadow strategy library
(docs/STAGE4_P1_SHADOW_PREREGISTRATION.md §8)

Additive only. Five append-only tables (trigger): the frozen policy, a run per (policy,
session), the regime snapshots, the shadow trades (real and placebo; zero capital) and
the rejected candidates. Every trade row is mode 'SHADOW' by CHECK: nothing here can
describe an order.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
PX = sa.Numeric(18, 4)
TABLES = ("shadow_policy", "shadow_run", "regime_snapshot", "shadow_trade", "shadow_skip")
EXIT_REASONS = ("STOP", "STOP_GAP", "TARGET", "TIME_NOT_WORKING", "EOD", "NO_EXIT_BAR")
SKIP_REASONS = ("SKIP_RRR", "CHECKLIST_LT4", "CAP_OPEN_RISK", "CAP_SECTOR", "CAP_LIQUIDITY",
                "HALT_DAILY", "MOVE_GT_3PCT", "NO_INTRADAY_BARS")
CHECKPOINTS = ("PRE", "OPEN", "0930", "1030", "1200", "1330")


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} in (" + ",".join(f"'{v}'" for v in vals) + ")"


def _run_fk() -> sa.Column:
    return sa.Column('run_id', postgresql.UUID(as_uuid=True),
                     sa.ForeignKey('shadow_run.run_id'), nullable=False)


def upgrade() -> None:
    op.create_table('shadow_policy',
        sa.Column('policy_version', sa.String(32), primary_key=True),
        sa.Column('spec', postgresql.JSONB(), nullable=False),
        sa.Column('spec_sha256', sa.CHAR(64), nullable=False),
        sa.Column('code_git_sha', sa.String(48), nullable=False),
        sa.Column('event_calendar_sha256', sa.CHAR(64), nullable=False),
        sa.Column('forward_from', sa.Date(), nullable=False),
        sa.Column('frozen_at', TS, nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=False))
    op.create_table('shadow_run',
        sa.Column('run_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('policy_version', sa.String(32),
                  sa.ForeignKey('shadow_policy.policy_version'), nullable=False),
        sa.Column('market_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(8), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('cutoff', TS, nullable=False),
        sa.Column('inputs_sha256', sa.CHAR(64), nullable=False),
        sa.Column('rows_sha256', sa.CHAR(64), nullable=False),
        sa.Column('counts', postgresql.JSONB(), nullable=False),
        sa.Column('code_git_sha', sa.String(48), nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.UniqueConstraint('policy_version', 'market_date', name='uq_shadow_run_policy_date'),
        sa.CheckConstraint("status in ('DONE','SKIPPED')", name='ck_shadow_run_status'),
        sa.CheckConstraint("(status = 'SKIPPED') = (reason is not null)",
                           name='ck_shadow_run_reason'))
    op.create_table('regime_snapshot',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        _run_fk(),
        sa.Column('policy_version', sa.String(32), nullable=False),
        sa.Column('market_date', sa.Date(), nullable=False),
        sa.Column('checkpoint', sa.String(8), nullable=False),
        sa.Column('features', postgresql.JSONB(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('rule_fired', sa.Text(), nullable=False),
        sa.Column('risk_mult', sa.Float(), nullable=False),
        sa.Column('day_type', sa.String(16), nullable=True),
        sa.UniqueConstraint('policy_version', 'market_date', 'checkpoint',
                            name='uq_regime_snapshot_policy_date_cp'),
        sa.CheckConstraint(_in('checkpoint', CHECKPOINTS), name='ck_regime_snapshot_checkpoint'),
        sa.CheckConstraint(_in('state', ('SHOCK', 'EVENT_WAIT', 'TREND_UP', 'TREND_DOWN',
                                         'RANGE', 'MIXED')), name='ck_regime_snapshot_state'))
    op.create_table('shadow_trade',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        _run_fk(),
        sa.Column('policy_version', sa.String(32), nullable=False),
        sa.Column('market_date', sa.Date(), nullable=False),
        sa.Column('strategy', sa.String(32), nullable=False),
        sa.Column('instrument_key', sa.String(80), nullable=False),
        sa.Column('side', sa.SmallInteger(), nullable=False),
        sa.Column('is_placebo', sa.Boolean(), nullable=False),
        sa.Column('signal_at', TS, nullable=False),
        sa.Column('entry_at', TS, nullable=False),
        sa.Column('exit_at', TS, nullable=False),
        sa.Column('time_stop', TS, nullable=False),
        sa.Column('entry_raw', PX, nullable=False),
        sa.Column('stop', PX, nullable=False),
        sa.Column('target', PX, nullable=False),
        sa.Column('atr', sa.Float(), nullable=False),
        sa.Column('qty', sa.BigInteger(), nullable=False),
        sa.Column('size_factor', sa.Float(), nullable=False),
        sa.Column('risk_inr', PX, nullable=False),
        sa.Column('rrr', sa.Float(), nullable=False),
        sa.Column('checklist', postgresql.JSONB(), nullable=False),
        sa.Column('checklist_score', sa.SmallInteger(), nullable=False),
        sa.Column('exit_raw', PX, nullable=False),
        sa.Column('exit_reason', sa.String(16), nullable=False),
        sa.Column('entry_px', PX, nullable=False),
        sa.Column('exit_px', PX, nullable=False),
        sa.Column('gross_inr', PX, nullable=False),
        sa.Column('charges', postgresql.JSONB(), nullable=False),
        sa.Column('net_inr', PX, nullable=False),
        sa.Column('net_r', sa.Float(), nullable=False),
        sa.Column('by_slippage', postgresql.JSONB(), nullable=False),
        sa.Column('sector', sa.String(64), nullable=True),
        sa.Column('regime_state', sa.String(16), nullable=False),
        sa.Column('risk_mult', sa.Float(), nullable=False),
        sa.Column('day_type', sa.String(16), nullable=True),
        sa.Column('guard_flags', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('evidence', postgresql.JSONB(), nullable=False),
        sa.Column('mode', sa.String(8), nullable=False),
        sa.UniqueConstraint('policy_version', 'market_date', 'strategy', 'instrument_key',
                            'is_placebo', name='uq_shadow_trade_natural'),
        sa.CheckConstraint("side in (-1, 1)", name='ck_shadow_trade_side'),
        sa.CheckConstraint("qty > 0", name='ck_shadow_trade_qty'),
        sa.CheckConstraint("entry_at < exit_at",
                           name='ck_shadow_trade_times'),
        sa.CheckConstraint(_in('exit_reason', EXIT_REASONS), name='ck_shadow_trade_exit'),
        sa.CheckConstraint("mode = 'SHADOW'", name='ck_shadow_trade_shadow_only'))
    op.create_table('shadow_skip',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        _run_fk(),
        sa.Column('policy_version', sa.String(32), nullable=False),
        sa.Column('market_date', sa.Date(), nullable=False),
        sa.Column('strategy', sa.String(32), nullable=False),
        sa.Column('instrument_key', sa.String(80), nullable=False),
        sa.Column('reason', sa.String(20), nullable=False),
        sa.Column('signal_at', TS, nullable=True),
        sa.Column('detail', postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint('policy_version', 'market_date', 'strategy', 'instrument_key',
                            name='uq_shadow_skip_natural'),
        sa.CheckConstraint(_in('reason', SKIP_REASONS), name='ck_shadow_skip_reason'))
    op.execute("""
        create function shadow_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function shadow_append_only()""")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
        op.drop_table(t)
    op.execute("drop function if exists shadow_append_only()")
