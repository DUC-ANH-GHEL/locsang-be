"""collapse_order_statuses

Revision ID: 5e6f7a8b9c0d
Revises: 4d5e6f7a8b9c
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op


revision: str = "5e6f7a8b9c0d"
down_revision: Union[str, None] = "4d5e6f7a8b9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE orders
        SET status = 'processing',
            updated_at = COALESCE(updated_at, NOW())
        WHERE LOWER(status::text) IN ('shipped', 'delivered')
        """
    )


def downgrade() -> None:
    # The old values cannot be restored accurately after collapsing both into processing.
    pass
