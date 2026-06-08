"""drop_legacy_order_columns_for_pancake_only

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS shipping_fee;")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS shipping_address;")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS viettelpost_order_code;")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS receiver_name;")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS receiver_address;")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS receiver_province_id;")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS receiver_district_id;")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS receiver_ward_id;")


def downgrade() -> None:
    op.add_column("orders", sa.Column("shipping_fee", sa.Float(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("shipping_address", sa.String(), nullable=False, server_default=""))
    op.add_column("orders", sa.Column("viettelpost_order_code", sa.String(length=100), nullable=True))
    op.add_column("orders", sa.Column("receiver_name", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("receiver_address", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("receiver_province_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("receiver_district_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("receiver_ward_id", sa.Integer(), nullable=True))
