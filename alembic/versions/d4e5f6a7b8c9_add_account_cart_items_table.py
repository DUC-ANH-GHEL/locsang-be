"""add_account_cart_items_table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_cart_items (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            item_key VARCHAR(120) NOT NULL,
            product_id INTEGER NULL,
            product_variant_id INTEGER NULL,
            sku VARCHAR(120) NULL,
            title VARCHAR(255) NOT NULL,
            image VARCHAR(1000) NOT NULL DEFAULT '',
            price DOUBLE PRECISION NOT NULL DEFAULT 0,
            quantity INTEGER NOT NULL DEFAULT 1,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_account_cart_user_item_key UNIQUE (user_id, item_key)
        );
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='users') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name='fk_account_cart_items_user_id_users'
                ) THEN
                    ALTER TABLE account_cart_items
                    ADD CONSTRAINT fk_account_cart_items_user_id_users
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE;
                END IF;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_account_cart_items_user_id
        ON account_cart_items (user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_cart_items;")
