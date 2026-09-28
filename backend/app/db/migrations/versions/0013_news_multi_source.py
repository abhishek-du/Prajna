"""Multi-source news (pilot): polls, items, observations, classification,
entity links, audit

Additive: six new append-only tables; the existing Upstox news tables are not
touched. knowable_at of an item is Prajna's first observation (discovered_at),
enforced as knowable_at >= discovered_at. Nothing is visible to Stage 2/3 or the
API (no views read these tables yet), and writing is locked (app.news.locks).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
TABLES = ('news_poll', 'news_item', 'news_item_observation', 'news_classification',
          'news_entity_link', 'news_audit')


def upgrade() -> None:
    op.create_table('news_poll',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('source', sa.String(40), nullable=False),
        sa.Column('mode', sa.String(12), nullable=False),
        sa.Column('run_id', sa.UUID(), sa.ForeignKey('ingest_run.run_id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('started_at', TS, nullable=False),
        sa.Column('finished_at', TS, nullable=False),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('http_status', sa.Integer()),
        sa.Column('bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('items_seen', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('items_new', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('items_changed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('backlog', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('etag', sa.Text()),
        sa.Column('last_modified', sa.Text()),
        sa.Column('payload_sha256', sa.CHAR(64)),
        sa.Column('error', sa.Text()),
        sa.CheckConstraint("mode in ('SHADOW','PRODUCTION')", name='ck_news_poll_mode'),
        sa.CheckConstraint("outcome in ('OK','NOT_MODIFIED','RATE_LIMITED','BLOCKED',"
                           "'AUTH_FAILED','ERROR','MALFORMED')", name='ck_news_poll_outcome'),
        sa.CheckConstraint('finished_at >= started_at', name='ck_news_poll_time'),
    )
    op.create_index('ix_news_poll_source_time', 'news_poll', ['source', 'started_at'])

    op.create_table('news_item',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('source', sa.String(40), nullable=False),
        sa.Column('source_article_id', sa.Text(), nullable=False),
        sa.Column('url', sa.Text()),
        sa.Column('canonical_url', sa.Text()),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('title_norm_hash', sa.CHAR(64), nullable=False),
        sa.Column('summary', sa.Text()),
        sa.Column('body', sa.Text()),
        sa.Column('publisher', sa.Text(), nullable=False),
        sa.Column('author', sa.Text()),
        sa.Column('category_raw', sa.Text()),
        sa.Column('symbol_raw', sa.String(64)),
        sa.Column('attachment_url', sa.Text()),
        sa.Column('language', sa.String(8)),
        sa.Column('region', sa.String(8)),
        sa.Column('published_at', TS),
        sa.Column('published_at_raw', sa.Text()),
        sa.Column('source_updated_at', TS),
        sa.Column('discovered_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.Column('backlog', sa.Boolean(), nullable=False),
        sa.Column('content_available', sa.Boolean(), nullable=False),
        sa.Column('first_poll_id', sa.BigInteger(),
                  sa.ForeignKey('news_poll.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('payload_sha256', sa.CHAR(64), nullable=False),
        sa.UniqueConstraint('source', 'source_article_id', name='uq_news_item_source_id'),
        sa.CheckConstraint('knowable_at >= discovered_at', name='ck_news_item_knowable'),
    )
    op.create_index('ix_news_item_knowable', 'news_item', ['knowable_at'])
    op.create_index('ix_news_item_title_hash', 'news_item', ['title_norm_hash'])

    op.create_table('news_item_observation',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('news_item.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('poll_id', sa.BigInteger(), sa.ForeignKey('news_poll.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('observed_at', TS, nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text()),
        sa.Column('published_at', TS),
        sa.Column('source_updated_at', TS),
        sa.Column('changed', postgresql.ARRAY(sa.Text()), nullable=False),
    )
    op.create_index('ix_news_obs_item', 'news_item_observation', ['item_id'])

    op.create_table('news_classification',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('news_item.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('category', sa.String(32), nullable=False),
        sa.Column('confidence', sa.Numeric(4, 3), nullable=False),
        sa.Column('method', sa.String(32), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('classified_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint('confidence between 0 and 1', name='ck_news_class_conf'),
        sa.CheckConstraint('knowable_at >= classified_at', name='ck_news_class_knowable'),
        sa.UniqueConstraint('item_id', 'method', 'version', name='uq_news_class'),
    )

    op.create_table('news_entity_link',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('news_item.id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('instrument_key', sa.String(80)),
        sa.Column('method', sa.String(24), nullable=False),
        sa.Column('confidence', sa.Numeric(4, 3), nullable=False),
        sa.Column('matched_text', sa.Text()),
        sa.Column('reason', sa.Text()),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('mapped_at', TS, nullable=False),
        sa.Column('knowable_at', TS, nullable=False),
        sa.CheckConstraint("method in ('EXACT_SYMBOL','ISIN','COMPANY_NAME','ALIAS',"
                           "'MANUAL_RULE','ENTITY_MODEL','UNRESOLVED')",
                           name='ck_news_link_method'),
        sa.CheckConstraint("(method = 'UNRESOLVED') = (instrument_key is null)",
                           name='ck_news_link_unresolved'),
        sa.CheckConstraint('confidence between 0 and 1', name='ck_news_link_conf'),
        sa.CheckConstraint('knowable_at >= mapped_at', name='ck_news_link_knowable'),
        sa.UniqueConstraint('item_id', 'version', 'instrument_key', name='uq_news_link'),
    )
    op.create_index('ix_news_link_instrument', 'news_entity_link', ['instrument_key'])

    op.create_table('news_audit',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('at', TS, nullable=False, server_default=sa.text('now()')),
        sa.Column('event', sa.String(24), nullable=False),
        sa.Column('source', sa.String(40)),
        sa.Column('operator', sa.String(64), nullable=False),
        sa.Column('detail', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.CheckConstraint("event in ('REFUSED','KILL_ON','KILL_OFF','BLOCKED')",
                           name='ck_news_audit_event'),
    )

    op.execute("""
        create function news_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function news_append_only()""")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
    op.execute("drop function if exists news_append_only()")
    for t in reversed(TABLES):
        op.drop_table(t)
