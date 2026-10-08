"""Stage 4 training data v2: corporate actions knowable when Prajna OBSERVED them.

Found while validating dataset v1 (2026-10-08): canonical corporate actions (and the
ca_factor rows derived from them) are knowable at the END OF THE ANNOUNCEMENT DATE
(decision KN-CA), not when Prajna fetched them. Every one of the 2,336 stored
actions was fetched more than a day after that instant, and the Upstox endpoint
lists an action around its ex-date, so live Prajna learns of it days to months
after the announcement. A historical replay through the production views
therefore used actions Prajna did not have at the snapshot - backdating, which the
Stage 4 rules forbid. Production (KN-CA, live Stage 3) is unchanged; only the
training datasets change:

  STRICT_PIT-v2   schema train_strict: canon_corporate_action / ca_factor knowable at
                  greatest(knowable_at, fetched_at) - when Prajna observed the row
  AS_IF_LIVE-v2   schema train_asif2: the AS_IF_LIVE-v1 shadow (bars, FII/DII,
                  globals; parameters of policy AS_IF_LIVE-v2) plus actions knowable
                  at least(observed, greatest(announcement EOD, ex-date + measured
                  live lag)); an action without an ex-date: observed
v1 datasets stay stored and their runs are marked SUPERSEDED (nothing is deleted).
The global-label shadow now joins its parameters (v1 used correlated sub-queries:
8 s per read).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-08
"""
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None

POLICY = "AS_IF_LIVE-v2"
CA_COLS = ("id, instrument_id, instrument_key, isin, trading_symbol, action_type, "
           "announcement_date, ex_date, record_date, amount, ratio_from, ratio_to, "
           "face_value_before, face_value_after, content_sha256")
CA_TAIL = "knowable_at_verified, knowable_at_basis, fetched_at, source, run_id, payload_sha256"
F_COLS = ("f.id, f.ca_id, f.instrument_key, f.action_type, f.ex_date, f.status, f.method, "
          "f.factor_price, f.factor_volume")
F_TAIL = ("f.vendor_applied, f.vendor_evidence, f.reason, f.inputs, f.method_version, "
          "f.derived_at, f.run_id")


def _param(fam: str, key: str) -> str:
    return (f"(select seconds from public.training_policy_param where policy = '{POLICY}' "
            f"and family = '{fam}' and key = '{key}')")


def upgrade() -> None:
    op.execute("alter table training_dataset_run drop constraint ck_training_run_status")
    op.execute("""alter table training_dataset_run add constraint ck_training_run_status
                  check (status in ('RUNNING','COMPLETE','FAILED','SUPERSEDED'))""")
    op.execute("alter table training_dataset_run drop constraint ck_training_run_policy")
    op.execute("""alter table training_dataset_run add constraint ck_training_run_policy
                  check (knowability_policy in ('STRICT_PIT','AS_IF_LIVE-v1','STRICT_PIT-v2',
                                                'AS_IF_LIVE-v2'))""")

    # ── STRICT_PIT-v2 ────────────────────────────────────────────────────────────
    op.execute("create schema train_strict")
    op.execute(f"""create view train_strict.canon_corporate_action as
        select {CA_COLS}, greatest(knowable_at, fetched_at) as knowable_at, {CA_TAIL}
        from public.canon_corporate_action""")
    op.execute(f"""create view train_strict.ca_factor as
        select {F_COLS}, greatest(f.knowable_at, c.fetched_at) as knowable_at, {F_TAIL}
        from public.ca_factor f join public.corporate_action c on c.id = f.ca_id""")

    # ── AS_IF_LIVE-v2 ────────────────────────────────────────────────────────────
    s = "train_asif2"
    op.execute(f"create schema {s}")
    op.execute(f"""create view {s}.next_session as
        select session_date, lead(session_date) over (order by session_date) as next_date
        from public.trading_session where is_trading_day""")
    op.execute(f"""create view {s}.canon_market_bar as
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
        join {s}.next_session n on n.session_date = b.market_date
        cross join (select {_param('daily_bar', 'next_session_ist')} as seconds) p""")
    op.execute(f"""create view {s}.canon_macro_observation as
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
        cross join (select {_param('fii_dii', 'next_session_ist')} as seconds) p""")
    op.execute(f"""create view {s}.global_lag as
        select f.wd, f.seconds as first_s, c.seconds as confirm_s
        from (select substring(key from 9)::int as wd, seconds from public.training_policy_param
              where policy = '{POLICY}' and family = 'global' and key like 'first_wd%%') f
        join (select substring(key from 11)::int as wd, seconds
              from public.training_policy_param
              where policy = '{POLICY}' and family = 'global' and key like 'confirm_wd%%') c
          using (wd)""")
    op.execute(f"""create view {s}.global_bar_policy as
        select x.instrument_id, x.timeframe, x.session_date, x.bar_start_utc,
               x.real_fetched_at, x.assumed_first, x.assumed_confirm,
               x.real_fetched_at > x.assumed_first as assumed
        from (select b.instrument_id, b.timeframe, b.session_date, b.bar_start_utc,
                     b.fetched_at as real_fetched_at,
                     (b.session_date::timestamp at time zone 'Asia/Kolkata')
                       + make_interval(secs => l.first_s) as assumed_first,
                     (b.session_date::timestamp at time zone 'Asia/Kolkata')
                       + make_interval(secs => l.confirm_s) as assumed_confirm
              from public.ohlcv_bar b
              join public.instrument i on i.instrument_id = b.instrument_id
              join {s}.global_lag l on l.wd = extract(isodow from b.session_date)::int
              where i.segment in ('GLOBAL_INDEX','GLOBAL_INDICATOR')
                and b.timeframe = '1d') x""")
    op.execute(f"""create view {s}.ohlcv_bar as
        select b.instrument_id, b.timeframe, b.session_date, b.bar_start_utc, b.source,
               b.instrument_key, b.open, b.high, b.low, b.close, b.volume, b.open_interest,
               b.vendor_ts_raw, b.run_id, b.payload_sha256,
               case when g.assumed then g.assumed_first else b.fetched_at end as fetched_at,
               case when g.assumed then g.assumed_first else b.knowable_at end as knowable_at,
               b.knowable_at_verified,
               cast(case when g.assumed then 'ASSUMED ({POLICY}): label + measured live lag'
                    else b.knowable_at_basis end as varchar(200)) as knowable_at_basis
        from public.ohlcv_bar b
        left join {s}.global_bar_policy g on g.instrument_id = b.instrument_id
          and g.timeframe = b.timeframe and g.bar_start_utc = b.bar_start_utc""")
    op.execute(f"""create view {s}.ohlcv_observation as
        select o.id, o.instrument_id, o.timeframe, o.session_date, o.bar_start_utc, o.source,
               o.instrument_key, o.open, o.high, o.low, o.close, o.volume, o.open_interest,
               o.run_id, o.payload_sha256, o.fetched_at, o.classification, o.reason,
               o.explained_by, o.method_version, o.created_at
        from public.ohlcv_observation o
        union all
        select null::bigint, g.instrument_id, g.timeframe, g.session_date, g.bar_start_utc,
               cast('{POLICY}' as varchar(32)), null::varchar(80), null::numeric(18,4),
               null::numeric(18,4), null::numeric(18,4), null::numeric(18,4),
               null::numeric(22,0), null::numeric(22,0), null::uuid, null::char(64),
               g.assumed_confirm, cast('REOBSERVED' as varchar(20)),
               'ASSUMED confirmation ({POLICY})', null::jsonb,
               cast('{POLICY}' as varchar(32)), null::timestamptz
        from {s}.global_bar_policy g where g.assumed""")
    ca_kn = ("case when {x} is null then greatest({k}, {f}) "
             "else least(greatest({k}, {f}), greatest({k}, "
             "({x}::timestamp at time zone 'Asia/Kolkata') + make_interval(secs => "
             + _param("corporate_action", "after_ex") + "))) end")
    op.execute(f"""create view {s}.canon_corporate_action as
        select {CA_COLS}, {ca_kn.format(k='a.knowable_at', f='a.fetched_at', x='a.ex_date')}
               as knowable_at, {CA_TAIL}
        from public.canon_corporate_action a""")
    op.execute(f"""create view {s}.ca_factor as
        select {F_COLS}, {ca_kn.format(k='f.knowable_at', f='c.fetched_at', x='f.ex_date')}
               as knowable_at, {F_TAIL}
        from public.ca_factor f join public.corporate_action c on c.id = f.ca_id""")


def downgrade() -> None:
    op.execute("drop schema if exists train_asif2 cascade")
    op.execute("drop schema if exists train_strict cascade")
    op.execute("alter table training_dataset_run drop constraint ck_training_run_policy")
    op.execute("""alter table training_dataset_run add constraint ck_training_run_policy
                  check (knowability_policy in ('STRICT_PIT','AS_IF_LIVE-v1'))""")
    op.execute("alter table training_dataset_run drop constraint ck_training_run_status")
    op.execute("""alter table training_dataset_run add constraint ck_training_run_status
                  check (status in ('RUNNING','COMPLETE','FAILED'))""")
