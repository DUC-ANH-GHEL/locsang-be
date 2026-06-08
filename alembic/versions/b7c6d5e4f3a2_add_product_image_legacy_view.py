"""add legacy product_image view

Revision ID: b7c6d5e4f3a2
Revises: a1b2c3d4e5f6
Create Date: 2026-02-13

Why:
- Some older queries/tools still reference the legacy table name `product_image`
  and legacy column name `image_url`.
- The app schema uses `product_images` and `url`.

This migration adds a compatibility VIEW so reads against `product_image`
continue to work without duplicating data.

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7c6d5e4f3a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create/replace view only if the new table exists.
    op.execute(
        """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'product_images'
    ) THEN
        EXECUTE 'DROP VIEW IF EXISTS product_image';
        EXECUTE '
            CREATE VIEW product_image AS
            SELECT
                id,
                product_id,
                url AS image_url,
                is_primary
            FROM product_images
        ';
    END IF;
END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS product_image")
