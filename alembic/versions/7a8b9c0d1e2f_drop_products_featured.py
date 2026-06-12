"""drop products featured flag

Revision ID: 7a8b9c0d1e2f
Revises: 6f7a8b9c0d1e
Create Date: 2026-06-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, None] = "6f7a8b9c0d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS featured")


def downgrade() -> None:
    op.add_column("products", sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.alter_column("products", "featured", server_default=None)
