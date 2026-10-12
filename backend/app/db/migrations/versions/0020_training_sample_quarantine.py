"""Stage 4: an append-only quarantine register for out-of-contract training_sample slices.

Additive only; no existing row is touched. A quarantine record names one slice
(dataset_version, label_version, snapshot) whose stored rows fall outside that label's
contract, with the row count and fingerprint seen when it was recorded and the approval.
The rows themselves stay in training_sample (append-only); readers skip a quarantined
slice, and the integrity checks keep reporting it (PASS_WITH_QUARANTINE, never PASS).
A later change to a quarantined slice (count or fingerprint) is reported as drift.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.create_table('training_sample_quarantine',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('dataset_version', sa.String(48), nullable=False),
        sa.Column('label_version', sa.String(32), nullable=False),
        sa.Column('snapshot', sa.String(16), nullable=False),
        sa.Column('rows', sa.BigInteger(), nullable=False),
        sa.Column('rows_md5', sa.CHAR(32), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('approved_by', sa.String(64), nullable=False),
        sa.Column('approval_ref', sa.Text(), nullable=False),
        sa.Column('code_git_sha', sa.String(48), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.UniqueConstraint('dataset_version', 'label_version', 'snapshot',
                            name='uq_training_sample_quarantine'),
        sa.CheckConstraint('rows > 0', name='ck_training_sample_quarantine_rows'))
    op.execute("""create trigger tr_training_sample_quarantine_append_only before update or
                  delete on training_sample_quarantine for each row
                  execute function training_append_only()""")


def downgrade() -> None:
    op.execute("drop trigger if exists tr_training_sample_quarantine_append_only "
               "on training_sample_quarantine")
    op.drop_table('training_sample_quarantine')
