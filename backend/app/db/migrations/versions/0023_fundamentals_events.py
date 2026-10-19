"""Stage 1 fundamentals F1/F2/F4/F5b (docs/STAGE1_FUNDAMENTALS_RND.md, approved 2026-10-19)

Additive only. Two append-only tables (trigger):
  results_event        one row per results event: INTIMATION (the results calendar, F2),
                       OUTCOME (results disseminated: the F1 trigger), HISTORICAL_FILING
                       (a user-exported NSE Financial Results CSV, F4) and ESTIMATE_NEWS
                       (a beat / miss / in-line headline, F5b). event_at is the exchange's
                       or publisher's own time; knowable_at is when Prajna had it
  fundamental_refresh  one row per (instrument, triggering OUTCOME event) refreshed by the
                       event-driven fundamentals job (F1), with its ingest run

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
TABLES = ("results_event", "fundamental_refresh")


def upgrade() -> None:
    op.create_table('results_event',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('instrument_key', sa.String(80), nullable=False),
        sa.Column('isin', sa.String(12), nullable=True),
        sa.Column('news_item_id', sa.BigInteger(), sa.ForeignKey('news_item.id'), nullable=True),
        sa.Column('meeting_date', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('period_kind', sa.String(4), nullable=True),
        sa.Column('verdict', sa.String(8), nullable=True),
        sa.Column('flags', postgresql.ARRAY(sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::text[]")),
        sa.Column('event_at', TS, nullable=True),
        sa.Column('knowable_at', TS, nullable=False),
        sa.Column('source', sa.String(40), nullable=False),
        sa.Column('provenance', postgresql.JSONB(), nullable=False),
        sa.Column('text_sha256', sa.CHAR(64), nullable=False),
        sa.Column('parser_version', sa.String(32), nullable=False),
        sa.Column('created_at', TS, nullable=False),
        sa.CheckConstraint("kind in ('INTIMATION','OUTCOME','HISTORICAL_FILING','ESTIMATE_NEWS')",
                           name='ck_results_event_kind'),
        sa.CheckConstraint("verdict is null or verdict in ('BEAT','MISS','INLINE','MIXED')",
                           name='ck_results_event_verdict'),
        sa.CheckConstraint("(kind = 'ESTIMATE_NEWS') = (verdict is not null)",
                           name='ck_results_event_verdict_kind'),
        sa.CheckConstraint("(kind = 'HISTORICAL_FILING') = (news_item_id is null)",
                           name='ck_results_event_news'),
        sa.CheckConstraint("event_at is null or event_at <= knowable_at",
                           name='ck_results_event_knowable'),
        sa.UniqueConstraint('kind', 'instrument_key', 'text_sha256', 'parser_version',
                            name='uq_results_event_text'))
    op.create_index('ix_results_event_key_kind', 'results_event',
                    ['instrument_key', 'kind', 'knowable_at'])
    op.create_index('ix_results_event_news', 'results_event', ['news_item_id'])
    op.create_table('fundamental_refresh',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('event_id', sa.BigInteger(), sa.ForeignKey('results_event.id'), nullable=False),
        sa.Column('instrument_key', sa.String(80), nullable=False),
        sa.Column('isin', sa.String(12), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('snapshots_inserted', sa.Integer(), nullable=False),
        sa.Column('refreshed_at', TS, nullable=False),
        sa.Column('authz_token_sha256', sa.CHAR(64), nullable=False),
        sa.UniqueConstraint('event_id', 'instrument_key', name='uq_fundamental_refresh_event'))
    op.execute("""
        create function fundamentals_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in TABLES:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function fundamentals_append_only()""")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
        op.drop_table(t)
    op.execute("drop function if exists fundamentals_append_only()")
