"""add tip categories table

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-04-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tip_categories",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_tip_categories_id", "tip_categories", ["id"], unique=False)
    op.create_index("ix_tip_categories_name", "tip_categories", ["name"], unique=False)
    op.create_index("ix_tip_categories_slug", "tip_categories", ["slug"], unique=True)
    op.create_index("ix_tip_categories_is_active", "tip_categories", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tip_categories_is_active", table_name="tip_categories")
    op.drop_index("ix_tip_categories_slug", table_name="tip_categories")
    op.drop_index("ix_tip_categories_name", table_name="tip_categories")
    op.drop_index("ix_tip_categories_id", table_name="tip_categories")
    op.drop_table("tip_categories")
