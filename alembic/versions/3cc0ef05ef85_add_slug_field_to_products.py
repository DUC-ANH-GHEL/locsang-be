"""add_slug_field_to_products

Revision ID: 3cc0ef05ef85
Revises: d39b396eb5a0
Create Date: 2025-06-17 23:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cc0ef05ef85'
down_revision: Union[str, None] = 'd39b396eb5a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add slug field to products table
    op.add_column('products', sa.Column('slug', sa.String(), nullable=True))

    # Create index for slug field
    op.create_index(op.f('ix_products_slug'), 'products', ['slug'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index for slug field
    op.drop_index(op.f('ix_products_slug'), table_name='products')

    # Remove slug field from products table
    op.drop_column('products', 'slug')
