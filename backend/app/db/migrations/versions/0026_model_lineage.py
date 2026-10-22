"""Stage 4 E5.1 prerequisites: production refits and their lineage
(docs/STAGE4_E5_AFTER_THE_LOOK.md; user 2026-10-22)

Additive only.
  model_version.purpose          + 'PRODUCTION' (a scheduled refit of an ACCEPTED recipe)
  model_version.previous_sha256  the model it replaces (lineage); required for PRODUCTION

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('model_version', sa.Column('previous_sha256', sa.CHAR(64), nullable=True))
    op.create_foreign_key('fk_model_version_previous', 'model_version', 'model_version',
                          ['previous_sha256'], ['model_sha256'], ondelete='RESTRICT')
    op.drop_constraint('ck_model_version_purpose', 'model_version', type_='check')
    op.create_check_constraint('ck_model_version_purpose', 'model_version',
                               "purpose in ('FORWARD_TEST','RESEARCH','PRODUCTION')")
    op.create_check_constraint('ck_model_version_lineage', 'model_version',
                               "purpose <> 'PRODUCTION' or previous_sha256 is not null")


def downgrade() -> None:
    op.drop_constraint('ck_model_version_lineage', 'model_version', type_='check')
    op.drop_constraint('ck_model_version_purpose', 'model_version', type_='check')
    op.create_check_constraint('ck_model_version_purpose', 'model_version',
                               "purpose in ('FORWARD_TEST','RESEARCH')")
    op.drop_constraint('fk_model_version_previous', 'model_version', type_='foreignkey')
    op.drop_column('model_version', 'previous_sha256')
