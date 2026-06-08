"""add_order_status_enum

Revision ID: 2cfee97a15b7
Revises: create_tables_without_fk
Create Date: 2025-06-17 22:29:13.411039

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2cfee97a15b7'
down_revision: Union[str, None] = 'create_tables_without_fk'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create ENUM type first
    orderstatus = postgresql.ENUM('pending', 'processing', 'shipped', 'delivered', 'cancelled', name='orderstatus')
    orderstatus.create(op.get_bind(), checkfirst=True)

    # Convert existing data to lowercase
    op.execute("UPDATE orders SET status = LOWER(status)")

    # Alter status column with USING clause
    op.execute('ALTER TABLE orders ALTER COLUMN status TYPE orderstatus USING status::orderstatus')

    # NOTE: order_items table is created in the base revision (create_tables_without_fk).


def downgrade() -> None:
    """Downgrade schema."""
    # Revert status column to VARCHAR
    op.execute('ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(50)')

    # Drop ENUM type
    postgresql.ENUM(name='orderstatus').drop(op.get_bind(), checkfirst=True)
