"""Security classification (hardening phase 3)

Criterion D's sector denominator counted every NSE_EQ instrument, including
351 fund units (ISIN issuer type F) and 2 rights entitlements, which have no
sector by nature. D must measure operating-company STOCKS only. This table
holds an explainable, multi-signal classification per instrument. Additive:
one new table, nothing existing changes.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('instrument_security_class',
        sa.Column('instrument_id', sa.BigInteger(), nullable=False),
        sa.Column('instrument_key', sa.String(length=80), nullable=False),
        sa.Column('security_class', sa.String(length=24), nullable=True),
        sa.Column('subclass', sa.String(length=24), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('signals', postgresql.JSONB(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('method_version', sa.String(length=32), nullable=False),
        sa.Column('classified_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.CheckConstraint("security_class is null or security_class in "
                           "('STOCK','FUND_UNIT','RIGHTS_ENTITLEMENT','OTHER')",
                           name='ck_secclass_class'),
        sa.CheckConstraint("status in ('CLASSIFIED','REVIEW','UNCLASSIFIED')",
                           name='ck_secclass_status'),
        sa.CheckConstraint("(status = 'CLASSIFIED') = (security_class is not null)",
                           name='ck_secclass_classified_has_class'),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.instrument_id'],
                                ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('instrument_id'),
    )
    op.create_index('ix_secclass_class', 'instrument_security_class',
                    ['security_class', 'status'])


def downgrade() -> None:
    op.drop_index('ix_secclass_class', table_name='instrument_security_class')
    op.drop_table('instrument_security_class')
