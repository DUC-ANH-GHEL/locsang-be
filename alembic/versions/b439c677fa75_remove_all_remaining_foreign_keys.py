"""remove_all_remaining_foreign_keys

Revision ID: b439c677fa75
Revises: 2cfee97a15b7
Create Date: 2025-06-17 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'b439c677fa75'
down_revision: Union[str, None] = '2cfee97a15b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # Get all foreign key constraints
    result = conn.execute(text("""
        SELECT tc.table_name, tc.constraint_name
        FROM information_schema.table_constraints tc
        WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = 'public'
    """))

    # Drop each foreign key constraint
    for table_name, constraint_name in result:
        try:
            op.drop_constraint(constraint_name, table_name, type_='foreignkey')
        except Exception as e:
            print(f"Could not drop constraint {constraint_name} on table {table_name}: {str(e)}")


def downgrade() -> None:
    """Downgrade schema."""
    # No downgrade needed as we're removing constraints
    pass
