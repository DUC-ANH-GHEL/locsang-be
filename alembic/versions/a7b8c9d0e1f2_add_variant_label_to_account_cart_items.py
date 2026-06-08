"""add variant label to account cart items

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-01
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE account_cart_items
        ADD COLUMN IF NOT EXISTS variant_label VARCHAR(255) NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE account_cart_items
        DROP COLUMN IF EXISTS variant_label;
        """
    )
