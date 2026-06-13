"""align roles admin schema

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-06-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS description VARCHAR")
    op.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()")
    op.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()")
    op.execute("UPDATE roles SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE roles SET updated_at = now() WHERE updated_at IS NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE roles DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE roles DROP COLUMN IF EXISTS created_at")
    op.execute("ALTER TABLE roles DROP COLUMN IF EXISTS description")
