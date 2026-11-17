"""Social connection health, account details and account selection after OAuth.

Revision ID: 0003_social_connections
Revises: 0002_workspace_tenancy
Create Date: 2026-11-16

Additive only: new nullable/defaulted columns on social_accounts and two new
tables. Existing rows keep their values and become status 'active'.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_social_connections"
down_revision = "0002_workspace_tenancy"
branch_labels = None
depends_on = None

NEW_COLUMNS = (
    ("status", "TEXT NOT NULL DEFAULT 'active'"),      # active | needs_reconnect
    ("last_error", "TEXT"),
    ("last_checked_at", "TEXT"),
    ("profile_picture_url", "TEXT"),
    ("parent_account_id", "TEXT"),                    # Instagram -> its linked Facebook Page row
    ("external_user_id", "TEXT"),                      # Meta user who authorized (deletion callbacks)
    ("details_json", "TEXT"),                          # followers, category, can_publish, ...
)


def upgrade() -> None:
    for name, ddl in NEW_COLUMNS:
        op.get_bind().exec_driver_sql(f"ALTER TABLE social_accounts ADD COLUMN {name} {ddl}")
    op.create_index("social_accounts_external_user_idx", "social_accounts", ["external_user_id"])

    # Accounts discovered by an OAuth sign-in, waiting for the user to choose which to add.
    op.create_table(
        "oauth_connections",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("encrypted_payload", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
    )
    # Meta data-deletion requests, so their status can be looked up by confirmation code.
    op.create_table(
        "data_deletion_requests",
        sa.Column("confirmation_code", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("external_user_id", sa.Text, nullable=False),
        sa.Column("accounts_deleted", sa.Integer, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("data_deletion_requests")
    op.drop_table("oauth_connections")
    op.drop_index("social_accounts_external_user_idx", table_name="social_accounts")
    with op.batch_alter_table("social_accounts") as batch:
        for name, _ in reversed(NEW_COLUMNS):
            batch.drop_column(name)
