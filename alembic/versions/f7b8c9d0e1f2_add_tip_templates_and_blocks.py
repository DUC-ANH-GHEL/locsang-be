"""add tip templates and content blocks

Revision ID: f7b8c9d0e1f2
Revises: e2a3b4c5d6e7
Create Date: 2026-04-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f7b8c9d0e1f2"
down_revision: Union[str, None] = "e2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tip_posts", sa.Column("template_key", sa.String(length=80), nullable=True))
    op.add_column(
        "tip_posts",
        sa.Column(
            "content_blocks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tip_posts", "content_blocks")
    op.drop_column("tip_posts", "template_key")
