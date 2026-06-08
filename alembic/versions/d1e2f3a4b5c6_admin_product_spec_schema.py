"""Admin product spec schema

Revision ID: d1e2f3a4b5c6
Revises: c8d7e6f5a4b3
Create Date: 2026-02-14

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c8d7e6f5a4b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # products
    op.add_column("products", sa.Column("short_description", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("status", sa.String(), nullable=False, server_default="active"))
    op.add_column("products", sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("products", sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("products", sa.Column("has_variants", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("products", sa.Column("deleted_at", sa.DateTime(), nullable=True))

    # product_images as media
    op.add_column("product_images", sa.Column("type", sa.String(), nullable=False, server_default="image"))

    # product_variants additional fields
    op.add_column("product_variants", sa.Column("compare_price", sa.Float(), nullable=True))
    op.add_column("product_variants", sa.Column("cost_price", sa.Float(), nullable=True))
    op.add_column("product_variants", sa.Column("manage_stock", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("product_variants", sa.Column("allow_backorder", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("product_variants", sa.Column("status", sa.String(), nullable=False, server_default="active"))
    op.add_column("product_variants", sa.Column("image_url", sa.String(), nullable=True))

    # Attributes tables
    op.create_table(
        "product_attributes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("product_id", "name", name="uq_product_attributes_product_name"),
    )

    op.create_table(
        "product_attribute_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attribute_id", sa.Integer(), sa.ForeignKey("product_attributes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("attribute_id", "value", name="uq_product_attribute_values_attribute_value"),
    )

    op.create_table(
        "variant_attribute_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("variant_id", sa.Integer(), sa.ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attribute_id", sa.Integer(), sa.ForeignKey("product_attributes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attribute_value_id", sa.Integer(), sa.ForeignKey("product_attribute_values.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.UniqueConstraint("variant_id", "attribute_id", name="uq_variant_attribute_values_variant_attribute"),
    )

    # order_items: link to variant (nullable for backward compatibility)
    op.add_column("order_items", sa.Column("product_variant_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_order_items_product_variant",
        "order_items",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # indexes (some may already exist via unique/index=True, but keep explicit per spec)
    op.create_index("idx_products_slug", "products", ["slug"], unique=False)
    op.create_index("idx_variants_sku", "product_variants", ["sku"], unique=False)
    op.create_index("idx_variants_product", "product_variants", ["product_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_variants_product", table_name="product_variants")
    op.drop_index("idx_variants_sku", table_name="product_variants")
    op.drop_index("idx_products_slug", table_name="products")

    op.drop_constraint("fk_order_items_product_variant", "order_items", type_="foreignkey")
    op.drop_column("order_items", "product_variant_id")

    op.drop_table("variant_attribute_values")
    op.drop_table("product_attribute_values")
    op.drop_table("product_attributes")

    op.drop_column("product_variants", "image_url")
    op.drop_column("product_variants", "status")
    op.drop_column("product_variants", "allow_backorder")
    op.drop_column("product_variants", "manage_stock")
    op.drop_column("product_variants", "cost_price")
    op.drop_column("product_variants", "compare_price")

    op.drop_column("product_images", "type")

    op.drop_column("products", "deleted_at")
    op.drop_column("products", "has_variants")
    op.drop_column("products", "tags")
    op.drop_column("products", "featured")
    op.drop_column("products", "status")
    op.drop_column("products", "short_description")
