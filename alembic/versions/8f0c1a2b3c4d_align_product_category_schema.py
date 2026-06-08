"""align product/category schema

Revision ID: 8f0c1a2b3c4d
Revises: 4cc0ef05ef86
Create Date: 2026-02-13

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f0c1a2b3c4d"
down_revision: Union[str, None] = "4cc0ef05ef86"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Normalize table names to match SQLAlchemy models
    op.execute('ALTER TABLE IF EXISTS category RENAME TO categories')
    op.execute('ALTER TABLE IF EXISTS role RENAME TO roles')
    op.execute('ALTER TABLE IF EXISTS product_image RENAME TO product_images')

    # --- categories ---
    op.execute("ALTER TABLE IF EXISTS categories ADD COLUMN IF NOT EXISTS description TEXT")
    op.execute("ALTER TABLE IF EXISTS categories ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE IF EXISTS categories ADD COLUMN IF NOT EXISTS image TEXT")
    op.execute(
        "ALTER TABLE IF EXISTS categories ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()"
    )
    op.execute(
        "ALTER TABLE IF EXISTS categories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()"
    )

    # --- product_images ---
    # Rename image_url -> url if needed
    op.execute(
        """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'product_images'
          AND column_name = 'image_url'
    ) THEN
        EXECUTE 'ALTER TABLE product_images RENAME COLUMN image_url TO url';
    END IF;
END $$;
        """
    )

    op.execute("ALTER TABLE IF EXISTS product_images ADD COLUMN IF NOT EXISTS public_id TEXT")
    op.execute("ALTER TABLE IF EXISTS product_images ADD COLUMN IF NOT EXISTS alt_text TEXT")
    op.execute("ALTER TABLE IF EXISTS product_images ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE IF EXISTS product_images ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()"
    )
    op.execute(
        "ALTER TABLE IF EXISTS product_images ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()"
    )

    # --- products ---
    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS sale_price DOUBLE PRECISION")
    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS currency VARCHAR NOT NULL DEFAULT 'VND'")
    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS stock INTEGER NOT NULL DEFAULT 0")

    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS brand VARCHAR")
    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS material VARCHAR")
    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS size VARCHAR")
    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS color VARCHAR")
    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS pet_type VARCHAR")
    op.execute("ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS season VARCHAR")

    # Ensure slug is non-null for new code (best-effort fill before setting NOT NULL)
    op.execute("UPDATE products SET slug = COALESCE(slug, sku, CONCAT('product-', id))")
    op.execute("ALTER TABLE products ALTER COLUMN slug SET NOT NULL")


def downgrade() -> None:
    # Downgrade is intentionally minimal (schema alignment migration)
    pass
