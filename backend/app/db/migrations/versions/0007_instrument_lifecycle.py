"""Instrument lifecycle and attribute history (hardening phase 2)

Found 2026-09-25: the instrument master was never refreshed after its
2026-09-23 load. RCDL-RE (INE0BZQ20011) left the vendor master and the
vendor rejects its key (UDAPI100011), yet it stayed current; 4 new listings
were missing; 16 instruments changed attributes in two days, which the M3.0
load could only FAIL on.

Additive only:
  instrument                  + lifecycle_status (default ACTIVE, metadata-only
                                change), first_seen, last_seen
  instrument_lifecycle_period   append-only listing-state periods (GiST: no
                                overlap per instrument)
  instrument_attribute_version  append-only vendor-attribute versions (GiST)
  canon_instrument            + lifecycle_status, lifecycle_since (Stage 2
                                passthrough: coverage of a non-ACTIVE instrument
                                stops where it left ACTIVE; its bars stay visible)
Seeded: one ACTIVE period and one attribute version per existing instrument,
with the instrument's own provenance. No existing row changes except the new
columns' values.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

STATES = "'ACTIVE','REMOVED_FROM_MASTER','VENDOR_REJECTED','INELIGIBLE'"
ATTRS = ("trading_symbol", "name", "short_name", "isin", "instrument_type", "security_type",
         "exchange_token", "lot_size", "tick_size", "freeze_quantity", "qty_multiplier",
         "cas_eligible", "segment", "exchange")
PROV = ("source", "run_id", "payload_sha256", "fetched_at", "knowable_at",
        "knowable_at_verified", "knowable_at_basis")


def _prov_columns():
    return [
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('payload_sha256', sa.CHAR(length=64), nullable=False),
        sa.Column('fetched_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('knowable_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('knowable_at_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('knowable_at_basis', sa.String(length=200), nullable=False),
    ]


def _prov_fks(table):
    return [
        sa.ForeignKeyConstraint(['run_id'], ['ingest_run.run_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['payload_sha256'], ['raw_payload.payload_sha256'],
                                ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.instrument_id'],
                                ondelete='RESTRICT'),
    ]


def upgrade() -> None:
    op.add_column('instrument', sa.Column('lifecycle_status', sa.String(length=24),
                                          nullable=False, server_default='ACTIVE'))
    op.add_column('instrument', sa.Column('first_seen', sa.Date(), nullable=True))
    op.add_column('instrument', sa.Column('last_seen', sa.Date(), nullable=True))
    op.create_check_constraint('ck_instrument_lifecycle_status', 'instrument',
                               f"lifecycle_status in ({STATES})")
    op.create_index('ix_instrument_lifecycle', 'instrument', ['lifecycle_status'])

    op.create_table('instrument_lifecycle_period',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('instrument_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('valid_from', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('valid_to', postgresql.TIMESTAMP(timezone=True), nullable=False,
                  server_default='infinity'),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('evidence', postgresql.JSONB(), nullable=False, server_default='{}'),
        *_prov_columns(),
        *_prov_fks('instrument_lifecycle_period'),
        postgresql.ExcludeConstraint(
            (sa.column('instrument_id'), '='),
            (sa.text("tstzrange(valid_from, valid_to, '[)')"), '&&'),
            name='ex_lifecycle_no_overlap', using='gist'),
        sa.CheckConstraint('valid_from < valid_to', name='ck_lifecycle_order'),
        sa.CheckConstraint(f"status in ({STATES})", name='ck_lifecycle_status'),
        sa.CheckConstraint('knowable_at <= fetched_at', name='ck_lifecycle_knowable'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lifecycle_instrument', 'instrument_lifecycle_period',
                    ['instrument_id', 'valid_from'])
    op.create_index(op.f('ix_instrument_lifecycle_period_run_id'),
                    'instrument_lifecycle_period', ['run_id'])

    op.create_table('instrument_attribute_version',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('instrument_id', sa.BigInteger(), nullable=False),
        sa.Column('trading_symbol', sa.String(length=64), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('short_name', sa.Text(), nullable=True),
        sa.Column('isin', sa.String(length=12), nullable=True),
        sa.Column('instrument_type', sa.String(length=8), nullable=True),
        sa.Column('security_type', sa.String(length=16), nullable=True),
        sa.Column('exchange_token', sa.String(length=24), nullable=True),
        sa.Column('lot_size', sa.Integer(), nullable=True),
        sa.Column('tick_size', sa.Numeric(14, 4), nullable=True),
        sa.Column('freeze_quantity', sa.Numeric(20, 2), nullable=True),
        sa.Column('qty_multiplier', sa.Numeric(14, 4), nullable=True),
        sa.Column('cas_eligible', sa.Boolean(), nullable=True),
        sa.Column('segment', sa.String(length=16), nullable=False),
        sa.Column('exchange', sa.String(length=16), nullable=False),
        sa.Column('valid_from', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('valid_to', postgresql.TIMESTAMP(timezone=True), nullable=False,
                  server_default='infinity'),
        *_prov_columns(),
        *_prov_fks('instrument_attribute_version'),
        postgresql.ExcludeConstraint(
            (sa.column('instrument_id'), '='),
            (sa.text("tstzrange(valid_from, valid_to, '[)')"), '&&'),
            name='ex_attr_version_no_overlap', using='gist'),
        sa.CheckConstraint('valid_from < valid_to', name='ck_attr_version_order'),
        sa.CheckConstraint('knowable_at <= fetched_at', name='ck_attr_version_knowable'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_attr_version_instrument', 'instrument_attribute_version',
                    ['instrument_id', 'valid_from'])
    op.create_index(op.f('ix_instrument_attribute_version_run_id'),
                    'instrument_attribute_version', ['run_id'])

    op.add_column('canon_instrument', sa.Column('lifecycle_status', sa.String(length=24),
                                                nullable=True))
    op.add_column('canon_instrument', sa.Column('lifecycle_since',
                                                postgresql.TIMESTAMP(timezone=True),
                                                nullable=True))

    # seed: every existing instrument is ACTIVE from the moment its master was held
    op.execute("""update instrument set first_seen = valid_from,
                  last_seen = (fetched_at at time zone 'Asia/Kolkata')::date""")
    prov = ", ".join(PROV)
    op.execute(f"""
        insert into instrument_lifecycle_period (instrument_id, status, valid_from, reason,
               evidence, {prov})
        select instrument_id, 'ACTIVE', fetched_at,
               'seed (migration 0007): current at the initial master load',
               jsonb_build_object('valid_from', valid_from), {prov}
        from instrument""")  # noqa: S608 (constant column lists)
    attrs = ", ".join(ATTRS)
    op.execute(f"""
        insert into instrument_attribute_version (instrument_id, {attrs}, valid_from, {prov})
        select instrument_id, {attrs}, fetched_at, {prov} from instrument""")  # noqa: S608


def downgrade() -> None:
    op.execute("alter table canon_instrument drop column if exists lifecycle_since, "
               "drop column if exists lifecycle_status")
    op.drop_table('instrument_attribute_version')
    op.drop_table('instrument_lifecycle_period')
    op.drop_index('ix_instrument_lifecycle', table_name='instrument')
    op.drop_constraint('ck_instrument_lifecycle_status', 'instrument', type_='check')
    op.drop_column('instrument', 'last_seen')
    op.drop_column('instrument', 'first_seen')
    op.drop_column('instrument', 'lifecycle_status')
