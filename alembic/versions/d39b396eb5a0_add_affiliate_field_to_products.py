"""add_affiliate_field_to_products

Revision ID: d39b396eb5a0
Revises: b439c677fa75
Create Date: 2025-06-17 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd39b396eb5a0'
down_revision: Union[str, None] = 'b439c677fa75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add affiliate field to products table
    op.add_column('products', sa.Column('affiliate', sa.Boolean(), nullable=True, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove affiliate field from products table
    op.drop_column('products', 'affiliate')
