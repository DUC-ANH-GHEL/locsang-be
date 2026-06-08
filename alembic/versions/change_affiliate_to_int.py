"""change affiliate to int

Revision ID: 4cc0ef05ef86
Revises: 3cc0ef05ef85
Create Date: 2024-02-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cc0ef05ef86'
down_revision: Union[str, None] = '3cc0ef05ef85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new integer column
    op.add_column('products', sa.Column('affiliate_int', sa.Integer(), nullable=True))

    # Copy data from boolean to integer column
    op.execute("UPDATE products SET affiliate_int = CASE WHEN affiliate THEN 1 ELSE 0 END")

    # Drop old column and rename new column
    op.drop_column('products', 'affiliate')
    op.alter_column('products', 'affiliate_int', new_column_name='affiliate')


def downgrade() -> None:
    # Add new boolean column
    op.add_column('products', sa.Column('affiliate_bool', sa.Boolean(), nullable=True))

    # Copy data from integer to boolean column
    op.execute("UPDATE products SET affiliate_bool = CASE WHEN affiliate = 1 THEN true ELSE false END")

    # Drop old column and rename new column
    op.drop_column('products', 'affiliate')
    op.alter_column('products', 'affiliate_bool', new_column_name='affiliate')
