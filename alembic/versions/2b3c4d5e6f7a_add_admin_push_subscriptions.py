"""add admin push subscriptions

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-06-09 23:30:00
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_push_subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NULL REFERENCES users(id),
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent VARCHAR(500) NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMP WITHOUT TIME ZONE NULL
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_push_subscriptions_id ON admin_push_subscriptions (id);")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_admin_push_subscriptions_endpoint ON admin_push_subscriptions (endpoint);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_push_subscriptions_is_active ON admin_push_subscriptions (is_active);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_admin_push_subscriptions_is_active;")
    op.execute("DROP INDEX IF EXISTS ix_admin_push_subscriptions_endpoint;")
    op.execute("DROP INDEX IF EXISTS ix_admin_push_subscriptions_id;")
    op.drop_table("admin_push_subscriptions")
