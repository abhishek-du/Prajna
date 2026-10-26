"""Stage 4 v2 P2: the LLM reviewer in shadow (docs/STAGE4_P2_REVIEWER_PREREGISTRATION.md)

Additive only. Two append-only tables (trigger): the frozen reviewer (model id, prompt
version, spec sha, forward start) and one review per (shadow trade, reviewer version):
the outcome-blind evidence packet, the prompt sha, the raw answer, the validated verdict
and the effective verdict (failures count as PASS). Every review row is mode 'SHADOW'.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
TABLES = ("llm_reviewer", "llm_review")


def upgrade() -> None:
    op.create_table('llm_reviewer',
        sa.Column('reviewer_version', sa.String(32), primary_key=True),
        sa.Column('policy_version', sa.String(32),
                  sa.ForeignKey('shadow_policy.policy_version'), nullable=False),
        sa.Column('model_id', sa.String(80), nullable=False),
        sa.Column('prompt_version', sa.String(32), nullable=False),
        sa.Column('spec', postgresql.JSONB(), nullable=False),
        sa.Column('spec_sha256', sa.CHAR(64), nullable=False),
        sa.Column('code_git_sha', sa.String(48), nullable=False),
        sa.Column('forward_from', sa.Date(), nullable=False),
        sa.Column('frozen_at', TS, nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=False))
    op.create_table('llm_review',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('trade_id', sa.BigInteger(), sa.ForeignKey('shadow_trade.id'), nullable=False),
        sa.Column('reviewer_version', sa.String(32),
                  sa.ForeignKey('llm_reviewer.reviewer_version'), nullable=False),
        sa.Column('policy_version', sa.String(32), nullable=False),
        sa.Column('market_date', sa.Date(), nullable=False),
        sa.Column('strategy', sa.String(32), nullable=False),
        sa.Column('instrument_key', sa.String(80), nullable=False),
        sa.Column('is_placebo', sa.Boolean(), nullable=False),
        sa.Column('model_id', sa.String(80), nullable=False),
        sa.Column('model_version', sa.String(80), nullable=True),
        sa.Column('prompt_version', sa.String(32), nullable=False),
        sa.Column('prompt_sha256', sa.CHAR(64), nullable=False),
        sa.Column('packet', postgresql.JSONB(), nullable=False),
        sa.Column('packet_sha256', sa.CHAR(64), nullable=False),
        sa.Column('n_evidence', sa.Integer(), nullable=False),
        sa.Column('response_raw', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('invalid_reason', sa.Text(), nullable=True),
        sa.Column('verdict', sa.String(8), nullable=True),
        sa.Column('reason_codes', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('evidence_ids', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('effective_verdict', sa.String(8), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('code_git_sha', sa.String(48), nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('mode', sa.String(8), nullable=False),
        sa.UniqueConstraint('trade_id', 'reviewer_version', name='uq_llm_review_trade_version'),
        sa.CheckConstraint("status in ('OK','INVALID','INVALID_EVIDENCE','ERROR','TIMEOUT')",
                           name='ck_llm_review_status'),
        sa.CheckConstraint("verdict is null or verdict in ('PASS','SHRINK','VETO')",
                           name='ck_llm_review_verdict'),
        sa.CheckConstraint("effective_verdict in ('PASS','SHRINK','VETO')",
                           name='ck_llm_review_effective'),
        sa.CheckConstraint("status = 'OK' or effective_verdict = 'PASS'",
                           name='ck_llm_review_failsafe'),
        sa.CheckConstraint("mode = 'SHADOW'", name='ck_llm_review_shadow_only'))
    op.execute("""
        create function llm_review_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function llm_review_append_only()""")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
        op.drop_table(t)
    op.execute("drop function if exists llm_review_append_only()")
