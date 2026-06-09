"""add admin notifications

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-06-10 00:20:00
"""

from typing import Union

from alembic import op


revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, None] = "2b3c4d5e6f7a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_notifications (
            id SERIAL PRIMARY KEY,
            type VARCHAR(50) NOT NULL DEFAULT 'order',
            title VARCHAR(200) NOT NULL,
            body TEXT NOT NULL,
            url VARCHAR(500) NULL,
            order_id INTEGER NULL,
            tracking_code VARCHAR(100) NULL,
            read_at TIMESTAMP WITHOUT TIME ZONE NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_notifications_id ON admin_notifications (id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_notifications_order_id ON admin_notifications (order_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_notifications_read_at ON admin_notifications (read_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_notifications_created_at ON admin_notifications (created_at DESC);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_admin_notifications_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_admin_notifications_read_at;")
    op.execute("DROP INDEX IF EXISTS ix_admin_notifications_order_id;")
    op.execute("DROP INDEX IF EXISTS ix_admin_notifications_id;")
    op.drop_table("admin_notifications")
