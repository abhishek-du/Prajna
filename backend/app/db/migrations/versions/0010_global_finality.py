"""Global-market finality, vendor-absent dates, price basis in the canonical view

Proven 2026-09-25: global daily labels are not trading dates (USDINR: Monday
sessions labelled Sunday; N225: Friday sessions labelled Saturday); the N225
label 2026-09-24 stored at 13:41 IST changed by 14:11 (even its open); the
"label + 1 day 12:00 IST" completeness rule is therefore not valid; a flat
bar is not a reliable holiday marker.

Additive:
  global_instrument_contract  measured per-instrument label semantics, gap
                              distribution, placeholder counts, confirmation
                              window (prajna derive global-contracts)
  ohlcv_observation           + class REOBSERVED (an identical later global
                              observation: the positive evidence of finality)
  global_bar_finality (view)  every global daily bar with a status:
      REVISED           a later fetch returned different values -> never exposed
      PLACEHOLDER       O=H=L=C = previous close with no volume -> never exposed
      CONFIRMED         re-observed unchanged >= confirm_hours after the first
                        observation (knowable only from that re-observation)
      CONFIRMED_BY_AGE  first observed >= 72 h after the label date (history)
      UNCONFIRMED       otherwise -> not exposed yet
  canon_global_bar (view)     only CONFIRMED / CONFIRMED_BY_AGE, with knowable_at
                              and fetched_at moved to the confirmation
  canon_global_vendor_absent  weekdays inside a COMPLETE fetch window the vendor
                              returned no bar for (never an ingestion failure)
  canon_market_bar (view)     + price_basis, basis_as_of (appended columns)
Stage 1 rows are untouched.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

CLASSES_OLD = "'CA_ADJUSTMENT','ROUNDING','SETTLEMENT','GLOBAL_REVISION','UNEXPLAINED'"
CLASSES_NEW = CLASSES_OLD + ",'REOBSERVED'"

FINALITY = """
    with g as (
      select b.instrument_id, i.instrument_key, i.trading_symbol, i.name, i.segment,
             b.timeframe, b.session_date, b.bar_start_utc, b.open, b.high, b.low, b.close,
             b.volume, b.knowable_at, b.knowable_at_verified, b.knowable_at_basis,
             b.fetched_at, b.source, b.run_id, b.payload_sha256,
             coalesce(c.confirm_hours, 6) as confirm_hours,
             lag(b.close) over (partition by b.instrument_id order by b.session_date)
               as prev_close
      from ohlcv_bar b
      join instrument i on i.instrument_id = b.instrument_id
      left join global_instrument_contract c on c.instrument_key = i.instrument_key
      where i.segment in ('GLOBAL_INDEX', 'GLOBAL_INDICATOR') and i.valid_to = 'infinity'
        and b.timeframe = '1d')
    select g.*,
      case when rev.id is not null then 'REVISED'
           when g.open = g.high and g.high = g.low and g.low = g.close
                and g.close = g.prev_close and g.volume = 0 then 'PLACEHOLDER'
           when conf.fetched_at is not null then 'CONFIRMED'
           when g.fetched_at >= ((g.session_date + 4)::timestamp at time zone 'Asia/Kolkata')
                then 'CONFIRMED_BY_AGE'
           else 'UNCONFIRMED' end as finality,
      case when rev.id is not null then null
           when conf.fetched_at is not null then conf.fetched_at
           when g.fetched_at >= ((g.session_date + 4)::timestamp at time zone 'Asia/Kolkata')
                then g.fetched_at end as confirmed_at,
      rev.fetched_at as revised_at
    from g
    left join lateral (
      select o.id, o.fetched_at from ohlcv_observation o
      where o.instrument_id = g.instrument_id and o.timeframe = '1d'
        and o.bar_start_utc = g.bar_start_utc and o.classification = 'GLOBAL_REVISION'
      order by o.fetched_at limit 1) rev on true
    left join lateral (
      select o.fetched_at from ohlcv_observation o
      where o.instrument_id = g.instrument_id and o.timeframe = '1d'
        and o.bar_start_utc = g.bar_start_utc and o.classification = 'REOBSERVED'
        and o.fetched_at >= g.fetched_at + make_interval(hours => g.confirm_hours)
      order by o.fetched_at limit 1) conf on true"""

GLOBAL_BAR_OLD = """
        select b.instrument_id, i.instrument_key, i.trading_symbol, i.name, i.segment,
               b.timeframe, b.session_date as label_date, b.bar_start_utc,
               b.open, b.high, b.low, b.close, b.volume,
               b.knowable_at, b.knowable_at_verified, b.knowable_at_basis, b.fetched_at,
               b.source, b.run_id, b.payload_sha256
        from ohlcv_bar b
        join instrument i on i.instrument_id = b.instrument_id
        where i.segment in ('GLOBAL_INDEX', 'GLOBAL_INDICATOR') and i.valid_to = 'infinity'"""

GLOBAL_BAR_NEW = """
        select f.instrument_id, f.instrument_key, f.trading_symbol, f.name, f.segment,
               f.timeframe, f.session_date as label_date, f.bar_start_utc,
               f.open, f.high, f.low, f.close, f.volume,
               greatest(f.knowable_at, f.confirmed_at) as knowable_at,
               f.knowable_at_verified,
               case when f.finality = 'CONFIRMED'
                    then 'confirmed by an unchanged re-observation; ' || f.knowable_at_basis
                    else f.knowable_at_basis end as knowable_at_basis,
               greatest(f.fetched_at, f.confirmed_at) as fetched_at,
               f.source, f.run_id, f.payload_sha256,
               f.finality, f.confirmed_at, f.fetched_at as first_fetched_at
        from global_bar_finality f
        where f.finality in ('CONFIRMED', 'CONFIRMED_BY_AGE')"""

VENDOR_ABSENT = """
    select distinct on (i.instrument_key, d::date)
           i.instrument_id, i.instrument_key, d::date as absent_date, r.run_id,
           r.started_at as observed_at
    from ingest_run r
    join instrument i on r.stream = 'ohlcv.1d.' || i.instrument_key
    cross join lateral generate_series(
        (r.request_params->'window'->>0)::date,
        least((r.request_params->'window'->>1)::date,
              (r.started_at at time zone 'Asia/Kolkata')::date - 2),
        interval '1 day') d
    where i.segment in ('GLOBAL_INDEX', 'GLOBAL_INDICATOR') and i.valid_to = 'infinity'
      and r.status = 'COMPLETE' and r.mode = 'COMMIT' and r.request_params ? 'window'
      and extract(isodow from d) < 6
      and not exists (select 1 from ohlcv_bar b where b.instrument_id = i.instrument_id
                        and b.timeframe = '1d' and b.session_date = d::date)
    order by i.instrument_key, d::date, r.started_at"""


def _market_bar(module_sql: str) -> str:
    """0006's canon_market_bar with the price basis appended."""
    return module_sql.replace(
        "b.source, b.run_id, b.payload_sha256\n        from ohlcv_bar b",
        "b.source, b.run_id, b.payload_sha256,\n"
        "               pb.price_basis, pb.basis_as_of\n        from ohlcv_bar b") + \
        "\n        left join ohlcv_payload_basis pb on pb.payload_sha256 = b.payload_sha256"


def _load_0006():
    import importlib.util
    import pathlib
    p = pathlib.Path(__file__).with_name("0006_canon_session_bars.py")
    spec = importlib.util.spec_from_file_location("m0006", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MARKET_BAR


def upgrade() -> None:
    op.create_table('global_instrument_contract',
        sa.Column('instrument_key', sa.String(length=80), nullable=False),
        sa.Column('label_semantics', sa.Text(), nullable=False),
        sa.Column('weekday_profile', postgresql.JSONB(), nullable=False),
        sa.Column('weekend_label_share', sa.Numeric(8, 4), nullable=False),
        sa.Column('absent_weekdays_per_year', sa.Numeric(8, 2), nullable=False),
        sa.Column('gap_days_p50', sa.Integer(), nullable=False),
        sa.Column('gap_days_p99', sa.Integer(), nullable=False),
        sa.Column('gap_days_max', sa.Integer(), nullable=False),
        sa.Column('placeholder_flat_repeat', sa.Integer(), nullable=False),
        sa.Column('same_open_as_previous', sa.Integer(), nullable=False),
        sa.Column('revisions_observed', sa.Integer(), nullable=False),
        sa.Column('confirm_hours', sa.Integer(), nullable=False),
        sa.Column('completion_rule', sa.Text(), nullable=False),
        sa.Column('measured_through', sa.Date(), nullable=False),
        sa.Column('evidence', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('method_version', sa.String(length=32), nullable=False),
        sa.Column('measured_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('instrument_key'),
    )
    op.execute("alter table ohlcv_observation drop constraint ck_observation_class")
    op.execute(f"alter table ohlcv_observation add constraint ck_observation_class "
               f"check (classification in ({CLASSES_NEW}))")
    op.execute("create view global_bar_finality as " + FINALITY)
    op.execute("drop view canon_global_bar")
    op.execute("create view canon_global_bar as " + GLOBAL_BAR_NEW)
    op.execute("create view canon_global_vendor_absent as " + VENDOR_ABSENT)
    op.execute("create or replace view canon_market_bar as " + _market_bar(_load_0006()))


def downgrade() -> None:
    op.execute("drop view canon_market_bar")
    op.execute("create view canon_market_bar as " + _load_0006())
    op.execute("drop view canon_global_vendor_absent")
    op.execute("drop view canon_global_bar")
    op.execute("create view canon_global_bar as " + GLOBAL_BAR_OLD)
    op.execute("drop view global_bar_finality")
    # append-only: REOBSERVED rows are never deleted; the old check applies to
    # new rows only (NOT VALID), so the downgrade cannot destroy evidence
    op.execute("alter table ohlcv_observation drop constraint ck_observation_class")
    op.execute(f"alter table ohlcv_observation add constraint ck_observation_class "
               f"check (classification in ({CLASSES_OLD})) not valid")
    op.drop_table('global_instrument_contract')
