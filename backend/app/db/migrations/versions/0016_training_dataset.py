"""Stage 4 training dataset: historical Stage 3 replay and future-outcome labels.

Additive and isolated: new tables only; feature_value (the live Stage 3 history)
is never read for writing or modified. Two knowability policies (user decision
2026-10-08), stored as separate dataset versions and never mixed:

  STRICT_PIT      the production canonical views as they are: an input is
                  knowable when Prajna actually observed it (fetched_at)
  AS_IF_LIVE-v1   research only: history downloaded in bulk is treated as if it
                  had been collected by the live schedule, at the event end plus
                  the lag MEASURED on the live-collected period (training_policy_param).
                  Implemented as views in schema train_asif that shadow only the
                  relations the PIT reader queries by unqualified name; the engine
                  runs with search_path = train_asif, public. Production views keep
                  their resolved relations, so nothing else can see the shadow.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None

TS = postgresql.TIMESTAMP(timezone=True)
STATUSES = ("'VALID','MISSING_INPUT','STALE_INPUT','INVALID','NOT_APPLICABLE',"
            "'NOT_AVAILABLE_HISTORICALLY'")
APPEND_ONLY = ("training_feature_value", "training_label", "training_session_done",
               "training_policy_param")
POLICY = "AS_IF_LIVE-v1"


def upgrade() -> None:
    op.create_table('training_policy_param',
        sa.Column('policy', sa.String(32), primary_key=True),
        sa.Column('family', sa.String(32), primary_key=True),
        sa.Column('key', sa.String(32), primary_key=True),
        sa.Column('seconds', sa.Integer(), nullable=False),
        sa.Column('basis', sa.Text(), nullable=False),
        sa.Column('measured_at', TS, nullable=False))

    op.create_table('training_dataset_run',
        sa.Column('run_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dataset_version', sa.String(48), nullable=False),
        sa.Column('knowability_policy', sa.String(32), nullable=False),
        sa.Column('policy_params', postgresql.JSONB(), nullable=False),
        sa.Column('registry_version', sa.String(32), nullable=False),
        sa.Column('registry_sha256', sa.CHAR(64), nullable=False),
        sa.Column('feature_count', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('snapshots', postgresql.ARRAY(sa.String(16)), nullable=False),
        sa.Column('instrument_limit', sa.Integer()),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('sessions_done', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('row_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('symbol_count', sa.Integer()),
        sa.Column('coverage_summary', postgresql.JSONB()),
        sa.Column('validation_summary', postgresql.JSONB()),
        sa.Column('error', sa.Text()),
        sa.Column('operator', sa.String(64), nullable=False),
        sa.Column('started_at', TS, nullable=False),
        sa.Column('completed_at', TS),
        sa.CheckConstraint("status in ('RUNNING','COMPLETE','FAILED')",
                           name='ck_training_run_status'),
        sa.CheckConstraint("knowability_policy in ('STRICT_PIT','AS_IF_LIVE-v1')",
                           name='ck_training_run_policy'))

    op.create_table('training_feature_value',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('dataset_version', sa.String(48), nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('snapshot', sa.String(16), nullable=False),
        sa.Column('as_of', TS, nullable=False),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('instrument_key', sa.String(64), nullable=False),
        sa.Column('feature_id', sa.String(64), nullable=False),
        sa.Column('feature_version', sa.String(16), nullable=False),
        sa.Column('value', sa.Float()),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('reason', sa.String(32)),
        sa.Column('inputs_sha256', sa.CHAR(64), nullable=False),
        sa.Column('input_max_knowable_at', TS),
        sa.Column('run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('training_dataset_run.run_id', ondelete='RESTRICT'),
                  nullable=False),
        sa.UniqueConstraint('dataset_version', 'session_date', 'snapshot', 'instrument_key',
                            'feature_id', name='uq_training_feature_value'),
        sa.CheckConstraint(f"status in ({STATUSES})", name='ck_training_fv_status'),
        sa.CheckConstraint("(status = 'VALID') = (value is not null)",
                           name='ck_training_fv_value'),
        sa.CheckConstraint("value is null or value::text not in ('NaN','Infinity','-Infinity')",
                           name='ck_training_fv_finite'),
        sa.CheckConstraint("input_max_knowable_at is null or input_max_knowable_at < as_of",
                           name='ck_training_fv_pit'))

    op.create_table('training_session_done',
        sa.Column('dataset_version', sa.String(48), primary_key=True),
        sa.Column('session_date', sa.Date(), primary_key=True),
        sa.Column('snapshot', sa.String(16), primary_key=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('training_dataset_run.run_id', ondelete='RESTRICT'),
                  nullable=False),
        sa.Column('as_of', TS, nullable=False),
        sa.Column('rows', sa.Integer(), nullable=False),
        sa.Column('instruments', sa.Integer(), nullable=False),
        sa.Column('rows_sha256', sa.CHAR(64), nullable=False),
        sa.Column('stats', postgresql.JSONB(), nullable=False),
        sa.Column('done_at', TS, nullable=False))

    op.create_table('training_label',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('label_version', sa.String(32), nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('instrument_key', sa.String(64), nullable=False),
        sa.Column('label_id', sa.String(32), nullable=False),
        sa.Column('value', sa.Float()),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('label_start_at', TS, nullable=False),
        sa.Column('label_end_at', TS, nullable=False),
        sa.Column('inputs_sha256', sa.CHAR(64), nullable=False),
        sa.Column('computed_at', TS, nullable=False),
        sa.UniqueConstraint('label_version', 'session_date', 'instrument_key', 'label_id',
                            name='uq_training_label'),
        sa.CheckConstraint("status in ('VALID','MISSING_INPUT')", name='ck_training_label_status'),
        sa.CheckConstraint("(status = 'VALID') = (value is not null)",
                           name='ck_training_label_value'),
        sa.CheckConstraint("label_end_at > label_start_at", name='ck_training_label_window'))

    op.execute("""
        create function training_append_only() returns trigger language plpgsql as $$
        begin
          raise exception '% is append-only (% refused)', tg_table_name, tg_op;
        end $$""")
    for t in APPEND_ONLY:
        op.execute(f"""create trigger tr_{t}_append_only before update or delete on {t}
                       for each row execute function training_append_only()""")

    # ── AS_IF_LIVE-v1 shadow schema ─────────────────────────────────────────────
    op.execute("create schema train_asif")
    op.execute("""create view train_asif.next_session as
        select session_date, lead(session_date) over (order by session_date) as next_date
        from public.trading_session where is_trading_day""")
    # 1d bars (stocks and NSE indices): knowable at the next session + the measured
    # live fetch time; a bar observed live earlier keeps its real knowable_at (least)
    op.execute(f"""create view train_asif.canon_market_bar as
        select b.instrument_id, b.instrument_key, b.trading_symbol, b.segment, b.isin,
               b.timeframe, b.market_date, b.session_type, b.event_start, b.event_end,
               b.bar_start_utc, b.open, b.high, b.low, b.close, b.volume, b.open_interest,
               case when b.timeframe = '1d' then least(b.knowable_at,
                 (n.next_date::timestamp at time zone 'Asia/Kolkata')
                   + make_interval(secs => p.seconds)) else b.knowable_at end as knowable_at,
               b.knowable_at_verified,
               cast(case when b.timeframe = '1d' and b.knowable_at > (n.next_date::timestamp
                      at time zone 'Asia/Kolkata') + make_interval(secs => p.seconds)
                    then 'ASSUMED ({POLICY}): next session + measured live fetch time'
                    else b.knowable_at_basis end as varchar(200)) as knowable_at_basis,
               b.fetched_at, b.source, b.run_id, b.payload_sha256, b.price_basis,
               b.basis_as_of
        from public.canon_market_bar b
        join train_asif.next_session n on n.session_date = b.market_date
        cross join (select seconds from public.training_policy_param
                    where policy = '{POLICY}' and family = 'daily_bar'
                      and key = 'next_session_ist') p""")
    op.execute(f"""create view train_asif.canon_macro_observation as
        select m.id, m.series_code, m.observation_date, m.value, m.unit,
               least(m.knowable_at, (n.next_date::timestamp at time zone 'Asia/Kolkata')
                     + make_interval(secs => p.seconds)) as knowable_at,
               m.knowable_at_verified, m.knowable_at_basis, m.fetched_at, m.source,
               m.run_id, m.payload_sha256
        from public.canon_macro_observation m
        join (select t.d as session_date, (select min(session_date) from
                public.trading_session x where x.is_trading_day and x.session_date > t.d)
                as next_date
              from (select distinct observation_date as d
                    from public.canon_macro_observation) t) n
          on n.session_date = m.observation_date
        cross join (select seconds from public.training_policy_param
                    where policy = '{POLICY}' and family = 'fii_dii'
                      and key = 'next_session_ist') p""")
    # global 1d labels: first observed at label + measured first-fetch lag (per
    # weekday of the label) and confirmed at label + measured confirmation lag
    lag = ("(select seconds from public.training_policy_param where policy = '" + POLICY
           + "' and family = 'global' and key = '{k}' || extract(isodow from b.session_date)::int)")
    first = (f"(b.session_date::timestamp at time zone 'Asia/Kolkata') "
             f"+ make_interval(secs => {lag.format(k='first_wd')})")
    conf = (f"(b.session_date::timestamp at time zone 'Asia/Kolkata') "
            f"+ make_interval(secs => {lag.format(k='confirm_wd')})")
    op.execute(f"""create view train_asif.global_bar_policy as
        select b.instrument_id, b.timeframe, b.session_date, b.bar_start_utc,
               b.fetched_at as real_fetched_at, {first} as assumed_first,
               {conf} as assumed_confirm, b.fetched_at > {first} as assumed
        from public.ohlcv_bar b join public.instrument i on i.instrument_id = b.instrument_id
        where i.segment in ('GLOBAL_INDEX','GLOBAL_INDICATOR') and b.timeframe = '1d'""")
    op.execute("""create view train_asif.ohlcv_bar as
        select b.instrument_id, b.timeframe, b.session_date, b.bar_start_utc, b.source,
               b.instrument_key, b.open, b.high, b.low, b.close, b.volume, b.open_interest,
               b.vendor_ts_raw, b.run_id, b.payload_sha256,
               case when g.assumed then g.assumed_first else b.fetched_at end as fetched_at,
               case when g.assumed then g.assumed_first else b.knowable_at end as knowable_at,
               b.knowable_at_verified,
               cast(case when g.assumed then 'ASSUMED (AS_IF_LIVE-v1): label + measured live lag'
                    else b.knowable_at_basis end as varchar(200)) as knowable_at_basis
        from public.ohlcv_bar b
        left join train_asif.global_bar_policy g on g.instrument_id = b.instrument_id
          and g.timeframe = b.timeframe and g.bar_start_utc = b.bar_start_utc""")
    # the same column types as public.ohlcv_observation (a cached plan revalidated
    # under another search_path must keep its result types)
    op.execute("""create view train_asif.ohlcv_observation as
        select o.id, o.instrument_id, o.timeframe, o.session_date, o.bar_start_utc, o.source,
               o.instrument_key, o.open, o.high, o.low, o.close, o.volume, o.open_interest,
               o.run_id, o.payload_sha256, o.fetched_at, o.classification, o.reason,
               o.explained_by, o.method_version, o.created_at
        from public.ohlcv_observation o
        union all
        select null::bigint, g.instrument_id, g.timeframe, g.session_date, g.bar_start_utc,
               cast('AS_IF_LIVE-v1' as varchar(32)), null::varchar(80), null::numeric(18,4),
               null::numeric(18,4), null::numeric(18,4), null::numeric(18,4),
               null::numeric(22,0), null::numeric(22,0), null::uuid, null::char(64),
               g.assumed_confirm, cast('REOBSERVED' as varchar(20)),
               'ASSUMED confirmation (AS_IF_LIVE-v1)', null::jsonb,
               cast('AS_IF_LIVE-v1' as varchar(32)), null::timestamptz
        from train_asif.global_bar_policy g where g.assumed""")


def downgrade() -> None:
    op.execute("drop schema if exists train_asif cascade")
    for t in APPEND_ONLY:
        op.execute(f"drop trigger if exists tr_{t}_append_only on {t}")
    op.execute("drop function if exists training_append_only()")
    for t in ("training_label", "training_session_done", "training_feature_value",
              "training_dataset_run", "training_policy_param"):
        op.drop_table(t)
