"""Cache of platform insights, so dashboards do not hit Meta's rate limits.

Revision ID: 0005_analytics_cache
Revises: 0004_posts
Create Date: 2026-11-16

Additive only.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_analytics_cache"
down_revision = "0004_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_cache",
        sa.Column("cache_key", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("fetched_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("analytics_cache")
