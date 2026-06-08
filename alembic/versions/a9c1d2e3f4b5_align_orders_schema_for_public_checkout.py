"""align orders schema for public checkout

Revision ID: a9c1d2e3f4b5
Revises: f1a2b3c4d5e6
Create Date: 2026-03-18 20:56:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9c1d2e3f4b5'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def _get_column_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {col['name'] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _get_column_names(bind, 'orders')

    if 'shipping_address' not in columns:
        op.add_column('orders', sa.Column('shipping_address', sa.String(), nullable=True))
    if 'payment_status' not in columns:
        op.add_column('orders', sa.Column('payment_status', sa.String(), nullable=False, server_default='pending'))
    if 'receiver_name' not in columns:
        op.add_column('orders', sa.Column('receiver_name', sa.String(), nullable=True))
    if 'receiver_phone' not in columns:
        op.add_column('orders', sa.Column('receiver_phone', sa.String(), nullable=True))
    if 'receiver_address' not in columns:
        op.add_column('orders', sa.Column('receiver_address', sa.String(), nullable=True))
    if 'receiver_province_id' not in columns:
        op.add_column('orders', sa.Column('receiver_province_id', sa.Integer(), nullable=True))
    if 'receiver_district_id' not in columns:
        op.add_column('orders', sa.Column('receiver_district_id', sa.Integer(), nullable=True))
    if 'receiver_ward_id' not in columns:
        op.add_column('orders', sa.Column('receiver_ward_id', sa.Integer(), nullable=True))

    # Public checkout creates guest orders without authenticated user.
    op.alter_column('orders', 'user_id', existing_type=sa.Integer(), nullable=True)



def downgrade() -> None:
    bind = op.get_bind()
    columns = _get_column_names(bind, 'orders')

    if 'receiver_ward_id' in columns:
        op.drop_column('orders', 'receiver_ward_id')
    if 'receiver_district_id' in columns:
        op.drop_column('orders', 'receiver_district_id')
    if 'receiver_province_id' in columns:
        op.drop_column('orders', 'receiver_province_id')
    if 'receiver_address' in columns:
        op.drop_column('orders', 'receiver_address')
    if 'receiver_phone' in columns:
        op.drop_column('orders', 'receiver_phone')
    if 'receiver_name' in columns:
        op.drop_column('orders', 'receiver_name')
    if 'payment_status' in columns:
        op.drop_column('orders', 'payment_status')
    if 'shipping_address' in columns:
        op.drop_column('orders', 'shipping_address')

    op.alter_column('orders', 'user_id', existing_type=sa.Integer(), nullable=False)
