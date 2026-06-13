"""add public storefront performance indexes

Revision ID: 9a0b1c2d3e4f
Revises: 7a8b9c0d1e2f
Create Date: 2026-06-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "9a0b1c2d3e4f"
down_revision: Union[str, None] = "7a8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
CREATE INDEX IF NOT EXISTS ix_products_public_sellable_category_status
ON products (category_id, status, created_at DESC)
WHERE deleted_at IS NULL AND is_active = TRUE AND status = 'active';
        """
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS ix_product_images_product_id_sort_order
ON product_images (product_id, sort_order);
        """
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS ix_order_items_product_id
ON order_items (product_id);
        """
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS ix_orders_status_deleted_at_created_at
ON orders (status, deleted_at, created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_status_deleted_at_created_at")
    op.execute("DROP INDEX IF EXISTS ix_order_items_product_id")
    op.execute("DROP INDEX IF EXISTS ix_product_images_product_id_sort_order")
    op.execute("DROP INDEX IF EXISTS ix_products_public_sellable_category_status")
