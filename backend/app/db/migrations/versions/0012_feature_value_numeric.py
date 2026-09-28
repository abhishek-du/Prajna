"""feature_value.value: unconstrained numeric (was numeric(30,12))

numeric(30,12) keeps 12 DECIMAL PLACES, which truncates small feature values
(0.00549450549451 -> 0.005494505495) and breaks the determinism check that
compares a recompute with the stored value. Values are normalised to 12
SIGNIFICANT digits before storage; unconstrained numeric stores them exactly.
A widening change: no value is altered (the table is empty while Stage 3
production execution is locked).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('feature_value', 'value', type_=sa.Numeric(),
                    existing_type=sa.Numeric(30, 12), existing_nullable=True)


def downgrade() -> None:
    op.alter_column('feature_value', 'value', type_=sa.Numeric(30, 12),
                    existing_type=sa.Numeric(), existing_nullable=True)
