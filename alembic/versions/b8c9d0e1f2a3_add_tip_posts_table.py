"""add tip posts table

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tip_posts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("slug", sa.String(length=260), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("featured_image", sa.String(length=1200), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("seo_title", sa.String(length=320), nullable=True),
        sa.Column("seo_description", sa.String(length=500), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_tip_posts_id", "tip_posts", ["id"], unique=False)
    op.create_index("ix_tip_posts_slug", "tip_posts", ["slug"], unique=True)
    op.create_index("ix_tip_posts_status", "tip_posts", ["status"], unique=False)
    op.create_index("ix_tip_posts_published_at", "tip_posts", ["published_at"], unique=False)
    op.create_index("ix_tip_posts_featured", "tip_posts", ["featured"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tip_posts_featured", table_name="tip_posts")
    op.drop_index("ix_tip_posts_published_at", table_name="tip_posts")
    op.drop_index("ix_tip_posts_status", table_name="tip_posts")
    op.drop_index("ix_tip_posts_slug", table_name="tip_posts")
    op.drop_index("ix_tip_posts_id", table_name="tip_posts")
    op.drop_table("tip_posts")
