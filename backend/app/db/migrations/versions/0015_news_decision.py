"""News dedup decisions: why each stored article or edit was classified the way
it was (NEW_ARTICLE, DUPLICATE_ARTICLE, STORY_RELATED, STORY_UPDATE,
STORY_CORRECTION), with the rule, its version and the evidence.

Additive. One new append-only table (the 0013 trigger function); nothing is
deleted or merged - a duplicate is still stored as its own news_item and only
MARKED here. A decision carries its own knowable_at (when it was made), so a
past as_of never learns a later decision.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
DECISIONS = ("'NEW_ARTICLE','DUPLICATE_ARTICLE','STORY_RELATED','STORY_UPDATE',"
             "'STORY_CORRECTION'")


def upgrade() -> None:
    op.create_table('news_decision',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('item_id', sa.BigInteger(),
                  sa.ForeignKey('news_item.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('observation_id', sa.BigInteger(),
                  sa.ForeignKey('news_item_observation.id', ondelete='RESTRICT')),
        sa.Column('poll_id', sa.BigInteger(),
                  sa.ForeignKey('news_poll.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('rule', sa.String(32), nullable=False),
        sa.Column('rule_version', sa.String(32), nullable=False),
        sa.Column('related_item_id', sa.BigInteger(),
                  sa.ForeignKey('news_item.id', ondelete='RESTRICT')),
        sa.Column('story_id', sa.BigInteger(),
                  sa.ForeignKey('news_story.id', ondelete='RESTRICT')),
        sa.Column('evidence', postgresql.JSONB(), nullable=False),
        sa.Column('decided_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint(f"decision in ({DECISIONS})", name='ck_news_decision_kind'),
        # an edit is an UPDATE or a CORRECTION; an UPDATE is always an edit (a correction
        # may also arrive as a new article)
        sa.CheckConstraint("observation_id is null or decision in ('STORY_UPDATE',"
                           "'STORY_CORRECTION')", name='ck_news_decision_observation'),
        sa.CheckConstraint("decision <> 'STORY_UPDATE' or observation_id is not null",
                           name='ck_news_decision_update'),
        sa.CheckConstraint("decision <> 'DUPLICATE_ARTICLE' or related_item_id is not null",
                           name='ck_news_decision_duplicate_of'),
        sa.CheckConstraint('knowable_at >= decided_at', name='ck_news_decision_knowable'),
    )
    # one decision per stored article, and one per stored edit, for each rule version
    op.create_index('uq_news_decision_item', 'news_decision', ['item_id', 'rule_version'],
                    unique=True, postgresql_where=sa.text('observation_id is null'))
    op.create_index('uq_news_decision_observation', 'news_decision',
                    ['observation_id', 'rule_version'], unique=True,
                    postgresql_where=sa.text('observation_id is not null'))
    op.create_index('ix_news_decision_poll', 'news_decision', ['poll_id'])
    op.execute("""create trigger tr_news_decision_append_only before update or delete
                  on news_decision for each row execute function news_append_only()""")


def downgrade() -> None:
    op.execute("drop trigger if exists tr_news_decision_append_only on news_decision")
    op.drop_table('news_decision')
