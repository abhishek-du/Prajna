"""Stage 4 dataset builder v3: build contract, label-v2 provenance, samples, splits.

Additive only; no existing row is touched (v1/v2 datasets and label-v1 stay as
built, append-only):
  training_dataset_run   + label_version, code_git_sha, source_fingerprints,
                           build_contract (nullable)
  training_label         + flags, reason, run_id (nullable: label-v1 rows have none)
  training_label_run     one row per label build: knowledge cutoff, registry, code,
                           source fingerprints, window, counts
  training_sample        one row per (dataset, label version, session, snapshot,
                           instrument): feature eligibility, label validity, masks and
                           exclusion reasons - recorded, never deleted
  training_split         chronological walk-forward folds with an embargo

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
TEXTS = postgresql.ARRAY(sa.Text())
NEW_APPEND_ONLY = ("training_sample", "training_split", "training_label_run")


def upgrade() -> None:
    op.add_column('training_dataset_run', sa.Column('label_version', sa.String(32)))
    op.add_column('training_dataset_run', sa.Column('code_git_sha', sa.String(48)))
    op.add_column('training_dataset_run', sa.Column('source_fingerprints', postgresql.JSONB()))
    op.add_column('training_dataset_run', sa.Column('build_contract', postgresql.JSONB()))

    op.create_table('training_label_run',
        sa.Column('run_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('label_version', sa.String(32), nullable=False),
        sa.Column('knowledge_cutoff', TS, nullable=False),
        sa.Column('registry_sha256', sa.CHAR(64), nullable=False),
        sa.Column('code_git_sha', sa.String(48), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('instruments', sa.Integer(), nullable=False),
        sa.Column('rows', sa.BigInteger(), nullable=False),
        sa.Column('rows_sha256', sa.CHAR(64), nullable=False),
        sa.Column('source_fingerprints', postgresql.JSONB(), nullable=False),
        sa.Column('summary', postgresql.JSONB(), nullable=False),
        sa.Column('started_at', TS, nullable=False),
        sa.Column('completed_at', TS, nullable=False))

    op.add_column('training_label', sa.Column('flags', TEXTS))
    op.add_column('training_label', sa.Column('reason', sa.String(64)))
    op.add_column('training_label', sa.Column(
        'run_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('training_label_run.run_id', ondelete='RESTRICT', deferrable=True,
                      initially='DEFERRED')))

    op.create_table('training_sample',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('dataset_version', sa.String(48), nullable=False),
        sa.Column('label_version', sa.String(32), nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('snapshot', sa.String(16), nullable=False),
        sa.Column('as_of', TS, nullable=False),
        sa.Column('instrument_key', sa.String(64), nullable=False),
        sa.Column('core_valid', sa.SmallInteger(), nullable=False),
        sa.Column('core_total', sa.SmallInteger(), nullable=False),
        sa.Column('core_not_valid', TEXTS, nullable=False),
        sa.Column('feature_eligible', sa.Boolean(), nullable=False),
        sa.Column('labels_valid', TEXTS, nullable=False),
        sa.Column('label_flags', TEXTS, nullable=False),
        sa.Column('masks', TEXTS, nullable=False),
        sa.Column('exclusion_reasons', TEXTS, nullable=False),
        sa.Column('eligible', sa.Boolean(), nullable=False),
        sa.Column('label_start_at', TS),
        sa.Column('build_sha256', sa.CHAR(64), nullable=False),
        sa.Column('built_at', TS, nullable=False),
        sa.UniqueConstraint('dataset_version', 'label_version', 'session_date', 'snapshot',
                            'instrument_key', name='uq_training_sample'),
        sa.CheckConstraint("eligible = (cardinality(exclusion_reasons) = 0)",
                           name='ck_training_sample_eligible'),
        sa.CheckConstraint("label_start_at is null or label_start_at > as_of",
                           name='ck_training_sample_no_leak'))

    op.create_table('training_split',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('dataset_version', sa.String(48), nullable=False),
        sa.Column('label_version', sa.String(32), nullable=False),
        sa.Column('snapshot', sa.String(16), nullable=False),
        sa.Column('scheme', sa.String(48), nullable=False),
        sa.Column('fold', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(8), nullable=False),
        sa.Column('session_from', sa.Date(), nullable=False),
        sa.Column('session_to', sa.Date(), nullable=False),
        sa.Column('sessions', sa.Integer(), nullable=False),
        sa.Column('embargo_sessions', sa.Integer(), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.UniqueConstraint('dataset_version', 'label_version', 'snapshot', 'scheme', 'fold',
                            'role', name='uq_training_split'),
        sa.CheckConstraint("role in ('TRAIN','VALID','TEST')", name='ck_training_split_role'),
        sa.CheckConstraint("session_to >= session_from", name='ck_training_split_window'))

    for t in NEW_APPEND_ONLY:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function training_append_only()""")


def downgrade() -> None:
    for t in NEW_APPEND_ONLY:
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
    op.drop_table('training_split')
    op.drop_table('training_sample')
    op.drop_column('training_label', 'run_id')
    op.drop_column('training_label', 'reason')
    op.drop_column('training_label', 'flags')
    op.drop_table('training_label_run')
    for c in ('build_contract', 'source_fingerprints', 'code_git_sha', 'label_version'):
        op.drop_column('training_dataset_run', c)
