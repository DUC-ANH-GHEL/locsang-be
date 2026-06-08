"""drop legacy product_image view and ensure product_images table

Revision ID: c8d7e6f5a4b3
Revises: b7c6d5e4f3a2
Create Date: 2026-02-13

This revision removes the compatibility VIEW added previously and ensures
`product_images` table exists with the expected columns.

NOTE: This does NOT delete `product_images` data.
If you truly want to drop & recreate the table (data loss), do it manually.

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c8d7e6f5a4b3"
down_revision: Union[str, None] = "b7c6d5e4f3a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # User requested: do not keep any legacy VIEW
    op.execute("DROP VIEW IF EXISTS product_image")

    # Ensure the real table exists (no-op if already exists)
    op.execute(
        """
CREATE TABLE IF NOT EXISTS product_images (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    public_id TEXT NULL,
    alt_text TEXT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_product_images_product_id ON product_images (product_id);
        """
    )

    # If an old singular table exists for some reason, drop it (dangerous if it contains data).
    # Keeping it commented to avoid accidental data loss.
    # op.execute("DROP TABLE IF EXISTS product_image CASCADE")


def downgrade() -> None:
    # We intentionally do not recreate the legacy view.
    pass
