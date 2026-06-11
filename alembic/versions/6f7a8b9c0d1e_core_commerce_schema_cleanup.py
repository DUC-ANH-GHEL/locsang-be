"""core_commerce_schema_cleanup

Revision ID: 6f7a8b9c0d1e
Revises: 5e6f7a8b9c0d
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op


revision: str = "6f7a8b9c0d1e"
down_revision: Union[str, None] = "5e6f7a8b9c0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_HOME_KEYS = [
    "header_nav_tips_text",
    "secondary_cta_link",
    "bottom_cta_button_link",
    "shorts_section_title",
    "shorts_section_subtitle",
    "shorts_section_link_text",
    "community_section_title",
    "community_section_subtitle",
    "testimonial_section_title",
]


def _drop_legacy_home_keys(column_name: str) -> None:
    expression = f"COALESCE({column_name}, '{{}}'::jsonb)"
    for key in LEGACY_HOME_KEYS:
        expression = f"({expression} - '{key}')"
    op.execute(f"UPDATE home_contents SET {column_name} = {expression}")


def upgrade() -> None:
    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE text USING LOWER(status::text)")
    op.execute(
        """
        UPDATE orders
        SET status = 'processed',
            updated_at = COALESCE(updated_at, NOW())
        WHERE status IN ('processing', 'shipped', 'delivered')
        """
    )
    op.execute(
        """
        UPDATE orders
        SET status = CASE
            WHEN status = 'cancelled' THEN 'cancelled'
            ELSE 'pending'
        END
        WHERE status NOT IN ('pending', 'processed', 'cancelled')
        """
    )

    op.execute("DROP TYPE IF EXISTS orderstatus")
    op.execute("CREATE TYPE orderstatus AS ENUM ('pending', 'processed', 'cancelled')")
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE orderstatus USING status::orderstatus")
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'pending'::orderstatus")

    for index_name in (
        "ix_products_affiliate",
        "ix_products_pet_type",
        "ix_products_season",
        "ix_product_variants_compare_price",
        "ix_product_variants_cost_price",
        "ix_product_variants_size",
        "ix_product_variants_color",
        "ix_product_variants_material",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")

    for column_name in (
        "original_price",
        "affiliate",
        "material",
        "size",
        "color",
        "pet_type",
        "season",
        "height",
        "width",
        "length",
        "weight",
    ):
        op.execute(f"ALTER TABLE products DROP COLUMN IF EXISTS {column_name}")

    for column_name in ("size", "color", "material", "compare_price", "cost_price"):
        op.execute(f"ALTER TABLE product_variants DROP COLUMN IF EXISTS {column_name}")

    for table_name in (
        "product_reviews",
        "contacts",
        "customers",
        "customer_stories",
        "tip_posts",
        "tip_categories",
        "shipping_config",
        "shipping_info",
        "viettelpost_status_logs",
        "product_spec",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")

    _drop_legacy_home_keys("draft_content")
    _drop_legacy_home_keys("published_content")


def downgrade() -> None:
    # Destructive cleanup migration: data in removed tables/columns cannot be
    # reconstructed. Restore from a Neon branch/backup if rollback is needed.
    pass
