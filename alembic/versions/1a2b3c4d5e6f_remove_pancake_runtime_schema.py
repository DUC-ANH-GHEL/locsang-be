"""remove Pancake runtime schema

Revision ID: 1a2b3c4d5e6f
Revises: 0a1b2c3d4e5f
Create Date: 2026-06-09 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "0a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_pancake_product_id")
    op.execute("DROP INDEX IF EXISTS ix_product_variants_pancake_variation_id")
    op.execute("DROP INDEX IF EXISTS ix_orders_pancake_order_id")
    op.execute("DROP INDEX IF EXISTS ix_order_items_pancake_variation_id")

    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS pancake_product_id")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS pancake_payload")
    op.execute("ALTER TABLE product_variants DROP COLUMN IF EXISTS pancake_variation_id")
    op.execute("ALTER TABLE product_variants DROP COLUMN IF EXISTS pancake_payload")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS pancake_order_id")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS pancake_payload")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS pancake_variation_id")

    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS receiver_name VARCHAR")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS receiver_address TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS receiver_address")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS receiver_name")
