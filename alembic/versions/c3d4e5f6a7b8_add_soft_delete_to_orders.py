"""add soft delete to orders

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-19 22:15:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
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
    columns = _get_column_names(bind, "orders")

    if "deleted_at" not in columns:
        op.add_column("orders", sa.Column("deleted_at", sa.DateTime(), nullable=True))

    if not _index_exists(bind, "ix_orders_deleted_at"):
        op.create_index("ix_orders_deleted_at", "orders", ["deleted_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _index_exists(bind, "ix_orders_deleted_at"):
        op.drop_index("ix_orders_deleted_at", table_name="orders")

    columns = _get_column_names(bind, "orders")
    if "deleted_at" in columns:
        op.drop_column("orders", "deleted_at")
