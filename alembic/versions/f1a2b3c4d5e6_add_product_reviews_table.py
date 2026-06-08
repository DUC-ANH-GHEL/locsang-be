"""add product reviews table

Revision ID: f1a2b3c4d5e6
Revises: e2f3a4b5c6d7
Create Date: 2026-03-18 00:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_name", sa.String(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_verified_purchase", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_reviews_id", "product_reviews", ["id"], unique=False)
    op.create_index("ix_product_reviews_product_id", "product_reviews", ["product_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_product_reviews_product_id", table_name="product_reviews")
    op.drop_index("ix_product_reviews_id", table_name="product_reviews")
    op.drop_table("product_reviews")
