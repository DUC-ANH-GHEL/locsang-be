"""Add public product fields and indexes

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-02-14

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("original_price", sa.Float(), nullable=True))
    op.add_column("products", sa.Column("thumbnail", sa.String(length=500), nullable=True))

    # Required indexes for list performance (create if missing)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_name') THEN
                CREATE INDEX idx_product_name ON products (name);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_price') THEN
                CREATE INDEX idx_product_price ON products (price);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_status') THEN
                CREATE INDEX idx_product_status ON products (status);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_category') THEN
                CREATE INDEX idx_product_category ON products (category_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_created') THEN
                CREATE INDEX idx_product_created ON products (created_at);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Drop indexes if they exist
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_name') THEN
                DROP INDEX idx_product_name;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_price') THEN
                DROP INDEX idx_product_price;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_status') THEN
                DROP INDEX idx_product_status;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_category') THEN
                DROP INDEX idx_product_category;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_product_created') THEN
                DROP INDEX idx_product_created;
            END IF;
        END $$;
        """
    )

    op.drop_column("products", "thumbnail")
    op.drop_column("products", "original_price")
