"""News intelligence layers: normalisation fields, story groups, entity mentions,
rule-based assessments, article content, AI enrichment

Additive. The news_* tables are empty while writes are locked. New columns on
news_item are nullable or defaulted; every new table is append-only (the 0013
trigger function) and carries its own knowable_at, so a later grouping,
assessment or AI output is a NEW row visible only from then: a past as_of
never learns it.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
TABLES = ('news_story', 'news_story_member', 'news_entity_mention', 'news_assessment',
          'news_content', 'news_ai_enrichment')
CONTENT = ("'AVAILABLE','NOT_AVAILABLE','ROBOTS_BLOCKED','TERMS_BLOCKED','PAYWALL',"
           "'HTTP_BLOCKED','ERROR'")


def upgrade() -> None:
    for name, col in (
            ('source_priority', sa.Column('source_priority', sa.SmallInteger())),
            ('terms_status', sa.Column('terms_status', sa.String(12))),
            ('robots_allowed', sa.Column('robots_allowed', sa.Boolean())),
            ('content_fetch_status', sa.Column('content_fetch_status', sa.String(16),
                                               nullable=False, server_default='NOT_AVAILABLE')),
            ('metadata_sha256', sa.Column('metadata_sha256', sa.CHAR(64))),
            ('content_sha256', sa.Column('content_sha256', sa.CHAR(64))),
            ('processed_at', sa.Column('processed_at', TS))):
        op.add_column('news_item', col)
    op.create_check_constraint('ck_news_item_content_status', 'news_item',
                               f"content_fetch_status in ({CONTENT})")
    op.create_check_constraint('ck_news_item_processed', 'news_item',
                               'processed_at is null or processed_at >= discovered_at')

    op.create_table('news_story',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('first_item_id', sa.BigInteger(),
                  sa.ForeignKey('news_item.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('rule_version', sa.String(32), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint('knowable_at >= created_at', name='ck_news_story_knowable'),
    )
    op.create_table('news_story_member',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('story_id', sa.BigInteger(),
                  sa.ForeignKey('news_story.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('item_id', sa.BigInteger(),
                  sa.ForeignKey('news_item.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('method', sa.String(24), nullable=False),
        sa.Column('score', sa.Numeric(5, 4), nullable=False),
        sa.Column('evidence', postgresql.JSONB(), nullable=False),
        sa.Column('rule_version', sa.String(32), nullable=False),
        sa.Column('joined_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint("method in ('FOUNDER','SAME_URL','SAME_TITLE','SIMILAR')",
                           name='ck_news_story_member_method'),
        sa.CheckConstraint('score between 0 and 1', name='ck_news_story_member_score'),
        sa.CheckConstraint('knowable_at >= joined_at', name='ck_news_story_member_knowable'),
        sa.UniqueConstraint('item_id', 'rule_version', name='uq_news_story_member'),
    )
    op.create_index('ix_news_story_member_story', 'news_story_member', ['story_id'])

    op.create_table('news_entity_mention',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('item_id', sa.BigInteger(),
                  sa.ForeignKey('news_item.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('entity_type', sa.String(24), nullable=False),
        sa.Column('entity_id', sa.String(80), nullable=False),
        sa.Column('method', sa.String(24), nullable=False),
        sa.Column('confidence', sa.Numeric(4, 3), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('mapped_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint("entity_type in ('INDEX','SECTOR','COMMODITY','CURRENCY','BOND_YIELD',"
                           "'GEOPOLITICAL','REGULATOR','GOVERNMENT','CENTRAL_BANK','MACRO_INDICATOR',"
                           "'EXCHANGE','COURT')", name='ck_news_mention_type'),
        sa.CheckConstraint('confidence between 0 and 1', name='ck_news_mention_conf'),
        sa.CheckConstraint('knowable_at >= mapped_at', name='ck_news_mention_knowable'),
        sa.UniqueConstraint('item_id', 'entity_type', 'entity_id', 'version',
                            name='uq_news_mention'),
    )

    op.create_table('news_assessment',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('item_id', sa.BigInteger(),
                  sa.ForeignKey('news_item.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('basis', sa.String(8), nullable=False),
        sa.Column('market_scope', sa.String(8), nullable=False),
        sa.Column('potential_impact', sa.String(8), nullable=False),
        sa.Column('impact_direction', sa.String(8), nullable=False),
        sa.Column('is_breaking', sa.Boolean(), nullable=False),
        sa.Column('breaking_reason', sa.Text()),
        sa.Column('evidence', postgresql.JSONB(), nullable=False),
        sa.Column('rule_version', sa.String(32), nullable=False),
        sa.Column('assessed_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint("basis in ('RULES','AI')", name='ck_news_assess_basis'),
        sa.CheckConstraint("market_scope in ('STOCK','SECTOR','INDEX','MARKET','MACRO','GLOBAL',"
                           "'UNKNOWN')", name='ck_news_assess_scope'),
        sa.CheckConstraint("potential_impact in ('LOW','MEDIUM','HIGH','UNKNOWN')",
                           name='ck_news_assess_impact'),
        sa.CheckConstraint("impact_direction in ('POSITIVE','NEGATIVE','MIXED','NEUTRAL','UNKNOWN')",
                           name='ck_news_assess_direction'),
        sa.CheckConstraint('knowable_at >= assessed_at', name='ck_news_assess_knowable'),
        sa.UniqueConstraint('item_id', 'basis', 'rule_version', name='uq_news_assessment'),
    )

    op.create_table('news_content',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('item_id', sa.BigInteger(),
                  sa.ForeignKey('news_item.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('http_status', sa.Integer()),
        sa.Column('robots_allowed', sa.Boolean()),
        sa.Column('terms_status', sa.String(12)),
        sa.Column('body', sa.Text()),
        sa.Column('content_sha256', sa.CHAR(64)),
        sa.Column('error', sa.Text()),
        sa.Column('fetched_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint(f"status in ({CONTENT})", name='ck_news_content_status'),
        sa.CheckConstraint("(status = 'AVAILABLE') = (body is not null)",
                           name='ck_news_content_body'),
        sa.CheckConstraint('knowable_at >= fetched_at', name='ck_news_content_knowable'),
    )

    op.create_table('news_ai_enrichment',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('item_id', sa.BigInteger(),
                  sa.ForeignKey('news_item.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('model_id', sa.String(120), nullable=False),
        sa.Column('model_version', sa.String(60)),
        sa.Column('prompt_version', sa.String(32), nullable=False),
        sa.Column('input_sha256', sa.CHAR(64), nullable=False),
        sa.Column('output', postgresql.JSONB()),
        sa.Column('error', sa.Text()),
        sa.Column('generated_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint("status in ('OK','ERROR','TIMEOUT','INVALID')", name='ck_news_ai_status'),
        sa.CheckConstraint("(status = 'OK') = (output is not null)", name='ck_news_ai_output'),
        sa.CheckConstraint('knowable_at >= generated_at', name='ck_news_ai_knowable'),
        sa.UniqueConstraint('item_id', 'model_id', 'prompt_version', 'input_sha256',
                            name='uq_news_ai'),
    )

    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function news_append_only()""")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
    for t in reversed(TABLES):
        op.drop_table(t)
    op.drop_constraint('ck_news_item_processed', 'news_item')
    op.drop_constraint('ck_news_item_content_status', 'news_item')
    for c in ('processed_at', 'content_sha256', 'metadata_sha256', 'content_fetch_status',
              'robots_allowed', 'terms_status', 'source_priority'):
        op.drop_column('news_item', c)
