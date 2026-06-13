"""add phone login to users

Revision ID: a0b1c2d3e4f5
Revises: 9a0b1c2d3e4f
Create Date: 2026-06-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "9a0b1c2d3e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone ON users (phone) WHERE phone IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_phone")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS phone")
