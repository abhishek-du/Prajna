"""corporate_action: announcement_date + content_sha256 identity

Upstox corporate actions carry no event id and announce by DATE only.
Additive: two nullable columns and one unique constraint on an empty table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('corporate_action', sa.Column('announcement_date', sa.Date(), nullable=True))
    op.add_column('corporate_action', sa.Column('content_sha256', sa.CHAR(length=64), nullable=True))
    op.create_unique_constraint('uq_ca_content', 'corporate_action',
                                ['isin', 'content_sha256', 'source'])


def downgrade() -> None:
    op.drop_constraint('uq_ca_content', 'corporate_action', type_='unique')
    op.drop_column('corporate_action', 'content_sha256')
    op.drop_column('corporate_action', 'announcement_date')
