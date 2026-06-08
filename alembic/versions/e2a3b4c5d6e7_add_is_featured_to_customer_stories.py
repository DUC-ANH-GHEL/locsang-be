"""add is_featured to customer stories

Revision ID: e2a3b4c5d6e7
Revises: d1f2a3b4c5d6
Create Date: 2026-04-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2a3b4c5d6e7"
down_revision: Union[str, None] = "d1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_stories",
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_customer_stories_is_featured", "customer_stories", ["is_featured"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_customer_stories_is_featured", table_name="customer_stories")
    op.drop_column("customer_stories", "is_featured")
