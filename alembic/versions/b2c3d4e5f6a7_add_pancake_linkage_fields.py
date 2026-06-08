"""add Pancake linkage fields

Revision ID: b2c3d4e5f6a7
Revises: a9c1d2e3f4b5
Create Date: 2026-03-19 18:40:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a9c1d2e3f4b5"
branch_labels = None
depends_on = None


def _get_column_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def _index_exists(bind, index_name: str) -> bool:
    row = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = :index_name
            LIMIT 1
            """
        ),
        {"index_name": index_name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()

    product_columns = _get_column_names(bind, "products")
    if "pancake_product_id" not in product_columns:
        op.add_column("products", sa.Column("pancake_product_id", sa.String(length=100), nullable=True))
    if "pancake_payload" not in product_columns:
        op.add_column("products", sa.Column("pancake_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    product_variant_columns = _get_column_names(bind, "product_variants")
    if "pancake_variation_id" not in product_variant_columns:
        op.add_column("product_variants", sa.Column("pancake_variation_id", sa.String(length=100), nullable=True))
    if "pancake_payload" not in product_variant_columns:
        op.add_column("product_variants", sa.Column("pancake_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    order_columns = _get_column_names(bind, "orders")
    if "pancake_order_id" not in order_columns:
        op.add_column("orders", sa.Column("pancake_order_id", sa.String(length=100), nullable=True))
    if "pancake_payload" not in order_columns:
        op.add_column("orders", sa.Column("pancake_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    order_item_columns = _get_column_names(bind, "order_items")
    if "pancake_variation_id" not in order_item_columns:
        op.add_column("order_items", sa.Column("pancake_variation_id", sa.String(length=100), nullable=True))

    if not _index_exists(bind, "ix_products_pancake_product_id"):
        op.create_index("ix_products_pancake_product_id", "products", ["pancake_product_id"], unique=True)
    if not _index_exists(bind, "ix_product_variants_pancake_variation_id"):
        op.create_index("ix_product_variants_pancake_variation_id", "product_variants", ["pancake_variation_id"], unique=True)
    if not _index_exists(bind, "ix_orders_pancake_order_id"):
        op.create_index("ix_orders_pancake_order_id", "orders", ["pancake_order_id"], unique=False)
    if not _index_exists(bind, "ix_order_items_pancake_variation_id"):
        op.create_index("ix_order_items_pancake_variation_id", "order_items", ["pancake_variation_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _index_exists(bind, "ix_order_items_pancake_variation_id"):
        op.drop_index("ix_order_items_pancake_variation_id", table_name="order_items")
    if _index_exists(bind, "ix_orders_pancake_order_id"):
        op.drop_index("ix_orders_pancake_order_id", table_name="orders")
    if _index_exists(bind, "ix_product_variants_pancake_variation_id"):
        op.drop_index("ix_product_variants_pancake_variation_id", table_name="product_variants")
    if _index_exists(bind, "ix_products_pancake_product_id"):
        op.drop_index("ix_products_pancake_product_id", table_name="products")

    order_item_columns = _get_column_names(bind, "order_items")
    if "pancake_variation_id" in order_item_columns:
        op.drop_column("order_items", "pancake_variation_id")

    order_columns = _get_column_names(bind, "orders")
    if "pancake_payload" in order_columns:
        op.drop_column("orders", "pancake_payload")
    if "pancake_order_id" in order_columns:
        op.drop_column("orders", "pancake_order_id")

    product_variant_columns = _get_column_names(bind, "product_variants")
    if "pancake_payload" in product_variant_columns:
        op.drop_column("product_variants", "pancake_payload")
    if "pancake_variation_id" in product_variant_columns:
        op.drop_column("product_variants", "pancake_variation_id")

    product_columns = _get_column_names(bind, "products")
    if "pancake_payload" in product_columns:
        op.drop_column("products", "pancake_payload")
    if "pancake_product_id" in product_columns:
        op.drop_column("products", "pancake_product_id")
