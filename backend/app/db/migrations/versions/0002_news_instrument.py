"""news_instrument: the vendor's article-to-instrument association

Additive only: one new table, nothing existing is altered.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('news_instrument',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('news_id', sa.BigInteger(), nullable=False),
    sa.Column('instrument_key', sa.String(length=80), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('knowable_at_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    sa.CheckConstraint('knowable_at <= fetched_at', name='ck_news_instrument_knowable'),
    sa.ForeignKeyConstraint(['news_id'], ['news_article.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('news_id', 'instrument_key', 'source', name='uq_news_instrument')
    )
    op.create_index(op.f('ix_news_instrument_run_id'), 'news_instrument', ['run_id'], unique=False)
    op.create_index('ix_news_instrument_key', 'news_instrument', ['instrument_key'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_news_instrument_key', table_name='news_instrument')
    op.drop_index(op.f('ix_news_instrument_run_id'), table_name='news_instrument')
    op.drop_table('news_instrument')
