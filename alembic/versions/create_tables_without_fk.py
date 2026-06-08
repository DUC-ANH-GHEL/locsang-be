"""create all tables without foreign keys

Revision ID: create_tables_without_fk
Revises:
Create Date: 2024-03-19 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tables_without_fk'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create category table
    op.create_table('category',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False, unique=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
    )

    # Create role table
    op.create_table('role',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('name', sa.String(), unique=True, nullable=False),
    )

    # Create users table
    op.create_table('users',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('email', sa.String(), unique=True, index=True, nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Create products table
    op.create_table('products',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('sku', sa.String(50), unique=True, nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False),
        sa.Column('length', sa.Float(), nullable=False),
        sa.Column('width', sa.Float(), nullable=False),
        sa.Column('height', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False)
    )

    # Create product_image table
    op.create_table('product_image',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('image_url', sa.String(), nullable=False),
        sa.Column('is_primary', sa.Boolean(), default=False, nullable=False),
    )

    # Create product_spec table
    op.create_table('product_spec',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
    )

    # Create orders table
    op.create_table('orders',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('total_amount', sa.Float(), nullable=False),
        sa.Column('shipping_fee', sa.Float(), nullable=False),
        sa.Column('status', sa.String(50), default="pending", nullable=False),
        sa.Column('payment_method', sa.String(50), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('tracking_code', sa.String(100), nullable=True),
        sa.Column('viettelpost_order_code', sa.String(100), nullable=True),
    )

    # Create order_items table
    op.create_table('order_items',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Float(), nullable=False),
        sa.Column('subtotal', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Create shipping_info table
    op.create_table('shipping_info',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('recipient_name', sa.String(100), nullable=False),
        sa.Column('recipient_phone', sa.String(15), nullable=False),
        sa.Column('address', sa.String(255), nullable=False),
        sa.Column('province', sa.String(100), nullable=False),
        sa.Column('district', sa.String(100), nullable=False),
        sa.Column('ward', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Create shipping_config table
    op.create_table('shipping_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('api_token', sa.String(255), nullable=False),
        sa.Column('sender_name', sa.String(100), nullable=False),
        sa.Column('sender_phone', sa.String(15), nullable=False),
        sa.Column('sender_address', sa.String(255), nullable=False),
        sa.Column('province', sa.String(100), nullable=False),
        sa.Column('district', sa.String(100), nullable=False),
        sa.Column('ward', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Create viettelpost_status_logs table
    op.create_table('viettelpost_status_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('status_code', sa.String(50), nullable=False),
        sa.Column('status_message', sa.String(255), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table('viettelpost_status_logs')
    op.drop_table('shipping_config')
    op.drop_table('shipping_info')
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('product_spec')
    op.drop_table('product_image')
    op.drop_table('products')
    op.drop_table('users')
    op.drop_table('role')
    op.drop_table('category')
