"""trading_session: a SPECIAL session may have unknown (NULL) hours

Past special sessions (8 weekend sessions since 2020 in the NIFTY 50 daily
history) exist, but Upstox's timings endpoint returns a generic schedule for
past dates, so their hours are unknown. Before: such a day could not be
stored at all.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24
"""
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_session_trading_has_hours', 'trading_session', type_='check')
    op.create_check_constraint(
        'ck_session_trading_has_hours', 'trading_session',
        "not is_trading_day or session_type = 'SPECIAL' "
        "or (open_ist is not null and close_ist is not null)")


def downgrade() -> None:
    op.drop_constraint('ck_session_trading_has_hours', 'trading_session', type_='check')
    op.create_check_constraint(
        'ck_session_trading_has_hours', 'trading_session',
        'not is_trading_day or (open_ist is not null and close_ist is not null)')
