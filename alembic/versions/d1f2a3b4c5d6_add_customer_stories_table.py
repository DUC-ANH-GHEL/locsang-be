"""add customer stories table

Revision ID: d1f2a3b4c5d6
Revises: c9d0e1f2a3b4
Create Date: 2026-04-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1f2a3b4c5d6"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_stories",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("customer_name", sa.String(length=140), nullable=False),
        sa.Column("pet_name", sa.String(length=140), nullable=True),
        sa.Column("customer_title", sa.String(length=180), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("image_url", sa.String(length=1200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_customer_stories_id", "customer_stories", ["id"], unique=False)
    op.create_index("ix_customer_stories_is_active", "customer_stories", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_customer_stories_is_active", table_name="customer_stories")
    op.drop_index("ix_customer_stories_id", table_name="customer_stories")
    op.drop_table("customer_stories")
