"""add avatar_url to users

Revision ID: 0a1b2c3d4e5f
Revises: f7b8c9d0e1f2
Create Date: 2026-04-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0a1b2c3d4e5f"
down_revision: Union[str, None] = "f7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
