"""Stage 4 E5 models (docs/STAGE4_E5_PREREGISTRATION.md; approved by the user 2026-10-21)

Additive only. Two append-only tables (trigger):
  model_version     one row per fitted recipe artefact: its sha256 (the content of every
                    member), the training sessions, the artefact file and its sha256, the
                    code commit and the frozen configuration
  model_prediction  one row per (model, session, instrument): the outputs computed at the
                    PRE_SESSION snapshot (prob_up, exp_return, range, volatility, confidence,
                    score), the selection, and when it was written. A prediction must be
                    written before the session's open (predicted_at < deadline_at, the 09:15
                    IST open) - the forward test's point-in-time guarantee
PAPER ONLY: nothing here places, modifies or cancels an order.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
TABLES = ("model_version", "model_prediction")


def upgrade() -> None:
    op.create_table('model_version',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('model_sha256', sa.CHAR(64), nullable=False),
        sa.Column('recipe', sa.String(32), nullable=False),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('trained_from', sa.Date(), nullable=False),
        sa.Column('trained_to', sa.Date(), nullable=False),
        sa.Column('train_sessions', sa.Integer(), nullable=False),
        sa.Column('train_rows', sa.Integer(), nullable=False),
        sa.Column('artefact_path', sa.Text(), nullable=False),
        sa.Column('artefact_sha256', sa.CHAR(64), nullable=False),
        sa.Column('code_git_sha', sa.String(40), nullable=False),
        sa.Column('config', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=False),
        sa.CheckConstraint("purpose in ('FORWARD_TEST','RESEARCH')",
                           name='ck_model_version_purpose'),
        sa.CheckConstraint("trained_from <= trained_to", name='ck_model_version_dates'),
        sa.UniqueConstraint('model_sha256', name='uq_model_version_sha'))
    op.create_table('model_prediction',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('model_sha256', sa.CHAR(64), sa.ForeignKey('model_version.model_sha256'),
                  nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('snapshot', sa.String(16), nullable=False),
        sa.Column('instrument_key', sa.String(80), nullable=False),
        sa.Column('prob_up', sa.Float(), nullable=False),
        sa.Column('exp_return', sa.Float(), nullable=False),
        sa.Column('range_lo', sa.Float(), nullable=False),
        sa.Column('range_hi', sa.Float(), nullable=False),
        sa.Column('volatility', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('selected', sa.Boolean(), nullable=False),
        sa.Column('features_as_of', TS, nullable=False),
        sa.Column('inputs_sha256', sa.CHAR(64), nullable=False),
        sa.Column('predicted_at', TS, nullable=False),
        sa.Column('deadline_at', TS, nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("predicted_at < deadline_at", name='ck_model_prediction_deadline'),
        sa.CheckConstraint("features_as_of <= predicted_at", name='ck_model_prediction_asof'),
        sa.CheckConstraint("prob_up >= 0 and prob_up <= 1 and confidence >= 0 "
                           "and confidence <= 1 and range_lo <= range_hi and volatility >= 0",
                           name='ck_model_prediction_ranges'),
        sa.UniqueConstraint('model_sha256', 'session_date', 'snapshot', 'instrument_key',
                            name='uq_model_prediction'))
    op.create_index('ix_model_prediction_session', 'model_prediction',
                    ['session_date', 'model_sha256'])
    op.execute("""
        create function models_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function models_append_only()""")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
        op.drop_table(t)
    op.execute("drop function if exists models_append_only()")
