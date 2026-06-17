"""sync default variant status with product status

Revision ID: c6d7e8f9a0b1
Revises: b1c2d3e4f5a6
Create Date: 2026-06-17
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH variant_counts AS (
            SELECT product_id, COUNT(*) AS variant_count
            FROM product_variants
            GROUP BY product_id
        )
        UPDATE product_variants pv
        SET
            status = CASE WHEN p.status = 'active' THEN 'active' ELSE 'inactive' END,
            is_active = CASE WHEN p.status = 'active' THEN TRUE ELSE FALSE END,
            updated_at = now()
        FROM products p
        JOIN variant_counts vc ON vc.product_id = p.id
        WHERE pv.product_id = p.id
          AND (
              p.status <> 'active'
              OR COALESCE(p.has_variants, FALSE) = FALSE
              OR vc.variant_count <= 1
          )
          AND (
              pv.status IS DISTINCT FROM CASE WHEN p.status = 'active' THEN 'active' ELSE 'inactive' END
              OR pv.is_active IS DISTINCT FROM CASE WHEN p.status = 'active' THEN TRUE ELSE FALSE END
          )
        """
    )


def downgrade() -> None:
    pass
