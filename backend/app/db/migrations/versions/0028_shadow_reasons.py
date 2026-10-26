"""Stage 4 v2 P1 additions (user 2026-10-26): four more closed-list skip reasons for
shadow_skip (VOL_TOO_HIGH, SR_BLOCKED, NO_SR_ZONE, HALT_FIRST_STOP). The table is empty
on production (the policy is not frozen); the CHECK is replaced, nothing else changes.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-26
"""
from alembic import op

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None

OLD = ("SKIP_RRR", "CHECKLIST_LT4", "CAP_OPEN_RISK", "CAP_SECTOR", "CAP_LIQUIDITY",
       "HALT_DAILY", "MOVE_GT_3PCT", "NO_INTRADAY_BARS")
NEW = OLD + ("VOL_TOO_HIGH", "SR_BLOCKED", "NO_SR_ZONE", "HALT_FIRST_STOP")


def _in(vals: tuple[str, ...]) -> str:
    return "reason in (" + ",".join(f"'{v}'" for v in vals) + ")"


def upgrade() -> None:
    op.drop_constraint('ck_shadow_skip_reason', 'shadow_skip', type_='check')
    op.create_check_constraint('ck_shadow_skip_reason', 'shadow_skip', _in(NEW))


def downgrade() -> None:
    op.drop_constraint('ck_shadow_skip_reason', 'shadow_skip', type_='check')
    op.create_check_constraint('ck_shadow_skip_reason', 'shadow_skip', _in(OLD))
