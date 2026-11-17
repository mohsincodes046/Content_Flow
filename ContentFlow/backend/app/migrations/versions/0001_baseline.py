"""Baseline: the schema as it existed before Alembic.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-16

Mirrors app.migrations_runner.LEGACY_SQLITE_SCHEMA exactly (verified by
tests/test_migrations.py). Timestamps stay ISO-8601 text on both databases so
query semantics are identical on SQLite and PostgreSQL.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _email_type() -> sa.types.TypeEngine:
    # Case-insensitive uniqueness: COLLATE NOCASE on SQLite, a lower(email)
    # unique index on PostgreSQL (created below).
    return sa.Text().with_variant(sa.Text(collation="NOCASE"), "sqlite")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("email", _email_type(), nullable=False, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_index("users_email_lower_idx", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Text, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "workspace_id"),
        sa.CheckConstraint("role IN ('owner', 'member')", name="memberships_role_check"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_table(
        "submissions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("campaign", sa.Text, nullable=False),
        sa.Column("audience", sa.Text, nullable=False),
        sa.Column("instructions", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("platforms_json", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.CheckConstraint("status IN ('submitted')", name="submissions_status_check"),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("media_type", sa.Text, nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("storage_name", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("submission_id", sa.Text, sa.ForeignKey("submissions.id")),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.CheckConstraint("size > 0", name="assets_size_check"),
    )
    op.create_table(
        "scheduled_posts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("media_name", sa.Text, nullable=False),
        sa.Column("scheduled_date", sa.Text, nullable=False),
        sa.Column("scheduled_time", sa.Text, nullable=False),
        sa.Column("platforms_json", sa.Text, nullable=False),
        sa.Column("caption", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Text, sa.ForeignKey("assets.id")),
        sa.Column("facebook_account_id", sa.Text),
        sa.Column("timezone_offset_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("publish_status", sa.Text, nullable=False, server_default="scheduled"),
        sa.Column("publish_error", sa.Text),
        sa.Column("published_post_id", sa.Text),
    )
    op.create_index(
        "scheduled_posts_user_date_idx", "scheduled_posts", ["user_id", "scheduled_date", "scheduled_time"]
    )
    op.create_table(
        "oauth_states",
        sa.Column("state_hash", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
    )
    op.create_table(
        "social_accounts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("platform", sa.Text, nullable=False),
        sa.Column("account_id", sa.Text, nullable=False),
        sa.Column("account_name", sa.Text, nullable=False),
        sa.Column("account_type", sa.Text, nullable=False),
        sa.Column("encrypted_tokens", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text),
        sa.Column("connected_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.UniqueConstraint("user_id", "platform", "account_id", name="social_accounts_user_platform_account_key"),
    )
    op.create_index("social_accounts_user_idx", "social_accounts", ["user_id", "platform"])
    op.create_table(
        "rate_limit_events",
        sa.Column("bucket", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("rate_limit_events_lookup_idx", "rate_limit_events", ["bucket", "subject", "created_at"])
    op.create_index("rate_limit_events_created_idx", "rate_limit_events", ["created_at"])


def downgrade() -> None:
    for table in (
        "rate_limit_events", "social_accounts", "oauth_states", "scheduled_posts",
        "assets", "submissions", "sessions", "memberships", "workspaces", "users",
    ):
        op.drop_table(table)
