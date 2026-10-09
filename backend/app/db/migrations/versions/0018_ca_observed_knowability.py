"""Corporate actions knowable when Prajna OBSERVED them (decision CA-OBSERVED, 2026-10-09).

KN-CA (2026-09-24) made a corporate action knowable at the end of its announcement
DATE, which is always before Prajna fetched it (all 2,336 stored actions; median 134
days earlier; Upstox lists an action around its ex-date). A Stage 3 run that starts
after its as_of, and every recompute or backfill, could therefore use an action
Prajna did not have at as_of (review docs/STAGE4_POST_BACKFILL_REVIEW.md, F1).

Additive, no stored row changes (corporate_action / ca_factor keep the KN-CA value for
audit):
  canon_corporate_action        knowable_at = greatest(KN-CA, fetched_at)
  canon_corporate_action_kn_ca  the previous definition (announcement evidence)
  canon_ca_factor               ca_factor with knowable_at = greatest(KN-CA,
                                the action's fetched_at); the PIT reader uses it
Training shadows keep their own semantics: train_strict / train_asif2 get a
canon_ca_factor (their ca_factor views) and train_asif2 reads the KN-CA view (its
policy is ex-date + measured lag from KN-CA, migration 0017), so the stored
datasets' definitions are unchanged.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-09
"""
from alembic import op

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None

COLS = ("c.id, ci.instrument_id, ci.instrument_key, c.isin, ci.trading_symbol, c.action_type, "
        "c.announcement_date, c.ex_date, c.record_date, c.amount, c.ratio_from, c.ratio_to, "
        "c.face_value_before, c.face_value_after, c.content_sha256")
TAIL = "c.fetched_at, c.source, c.run_id, c.payload_sha256"
JOIN = ("from corporate_action c join canon_instrument ci "
        "on ci.instrument_key = c.instrument_key and ci.included")
F_COLS = ("f.id, f.ca_id, f.instrument_key, f.action_type, f.ex_date, f.status, f.method, "
          "f.factor_price, f.factor_volume")
F_TAIL = ("f.vendor_applied, f.vendor_evidence, f.reason, f.inputs, f.method_version, "
          "f.derived_at, f.run_id")
ASIF_CA = ("case when a.ex_date is null then greatest(a.knowable_at, a.fetched_at) "
           "else least(greatest(a.knowable_at, a.fetched_at), greatest(a.knowable_at, "
           "(a.ex_date::timestamp at time zone 'Asia/Kolkata') + make_interval(secs => "
           "(select seconds from public.training_policy_param where policy = 'AS_IF_LIVE-v2' "
           "and family = 'corporate_action' and key = 'after_ex')))) end")


def upgrade() -> None:
    op.execute(f"""create view canon_corporate_action_kn_ca as
        select {COLS}, c.knowable_at, c.knowable_at_verified, c.knowable_at_basis, {TAIL}
        {JOIN}""")
    # train_asif2 keeps its KN-CA based policy: repoint before the production view changes
    op.execute(f"""create or replace view train_asif2.canon_corporate_action as
        select a.id, a.instrument_id, a.instrument_key, a.isin, a.trading_symbol, a.action_type,
               a.announcement_date, a.ex_date, a.record_date, a.amount, a.ratio_from,
               a.ratio_to, a.face_value_before, a.face_value_after, a.content_sha256,
               {ASIF_CA} as knowable_at, a.knowable_at_verified, a.knowable_at_basis,
               a.fetched_at, a.source, a.run_id, a.payload_sha256
        from public.canon_corporate_action_kn_ca a""")
    op.execute(f"""create or replace view canon_corporate_action as
        select {COLS}, greatest(c.knowable_at, c.fetched_at) as knowable_at,
               c.knowable_at_verified,
               cast(case when c.knowable_at < c.fetched_at
                    then 'OBSERVED (CA-OBSERVED): fetched_at; announcement end-of-day '
                         || 'in canon_corporate_action_kn_ca'
                    else c.knowable_at_basis end as varchar(200)) as knowable_at_basis,
               {TAIL}
        {JOIN}""")
    op.execute(f"""create view canon_ca_factor as
        select {F_COLS}, greatest(f.knowable_at, c.fetched_at) as knowable_at, {F_TAIL}
        from ca_factor f join corporate_action c on c.id = f.ca_id""")
    op.execute("create view train_strict.canon_ca_factor as select * from train_strict.ca_factor")
    op.execute("create view train_asif2.canon_ca_factor as select * from train_asif2.ca_factor")


def downgrade() -> None:
    op.execute("drop view train_asif2.canon_ca_factor")
    op.execute("drop view train_strict.canon_ca_factor")
    op.execute("drop view canon_ca_factor")
    op.execute(f"""create or replace view canon_corporate_action as
        select {COLS}, c.knowable_at, c.knowable_at_verified, c.knowable_at_basis, {TAIL}
        {JOIN}""")
    op.execute(f"""create or replace view train_asif2.canon_corporate_action as
        select a.id, a.instrument_id, a.instrument_key, a.isin, a.trading_symbol, a.action_type,
               a.announcement_date, a.ex_date, a.record_date, a.amount, a.ratio_from,
               a.ratio_to, a.face_value_before, a.face_value_after, a.content_sha256,
               {ASIF_CA} as knowable_at, a.knowable_at_verified, a.knowable_at_basis,
               a.fetched_at, a.source, a.run_id, a.payload_sha256
        from public.canon_corporate_action a""")
    op.execute("drop view canon_corporate_action_kn_ca")
