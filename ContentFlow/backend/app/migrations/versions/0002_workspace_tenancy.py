"""Workspace multi-tenancy (docs/workspace-tenancy.md).

Revision ID: 0002_workspace_tenancy
Revises: 0001_baseline
Create Date: 2026-11-16

Every content row moves from "owned by a user" to "owned by a workspace". The
creator stays recorded in `user_id`, which becomes nullable with ON DELETE SET
NULL so removing a person never deletes workspace content.

Precondition (checked before any change): every user has exactly one owner
membership. Postconditions (checked before commit): row counts unchanged, no
workspace-owned row without a workspace, exactly one owner per workspace.

SQLite tables are rebuilt from explicit definitions (SQLite's documented
table-rebuild procedure), which works whether or not the existing constraints
have names (databases created before Alembic have unnamed ones). PostgreSQL is
altered in place.

Rollback: restore the verified backup that `python -m app.migrate upgrade`
takes before migrating. Downgrade is intentionally not supported.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_workspace_tenancy"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

CONTENT_TABLES = ("submissions", "assets", "scheduled_posts", "social_accounts", "oauth_states")
COUNTED_TABLES = ("users", "workspaces", "memberships", "sessions") + CONTENT_TABLES + ("rate_limit_events",)

OWNER_WORKSPACE = "(SELECT m.workspace_id FROM memberships m WHERE m.user_id = {table}.user_id AND m.role = 'owner')"

# Target definitions for the SQLite rebuild. Column order = original order + new columns.
SQLITE_TABLES = {
    "memberships": """
        CREATE TABLE memberships__new (
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            role TEXT NOT NULL,
            invited_by_user_id TEXT,
            created_at TEXT NOT NULL,
            CONSTRAINT memberships_pkey PRIMARY KEY (user_id, workspace_id),
            CONSTRAINT memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT memberships_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT memberships_invited_by_fkey FOREIGN KEY (invited_by_user_id) REFERENCES users (id) ON DELETE SET NULL,
            CONSTRAINT memberships_role_check CHECK (role IN ('owner', 'admin', 'editor', 'client'))
        )""",
    "submissions": """
        CREATE TABLE submissions__new (
            id TEXT NOT NULL PRIMARY KEY,
            campaign TEXT NOT NULL,
            audience TEXT NOT NULL,
            instructions TEXT NOT NULL,
            language TEXT NOT NULL,
            platforms_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id TEXT,
            workspace_id TEXT NOT NULL,
            CONSTRAINT submissions_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
            CONSTRAINT submissions_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT submissions_status_check CHECK (status IN ('submitted'))
        )""",
    "assets": """
        CREATE TABLE assets__new (
            id TEXT NOT NULL PRIMARY KEY,
            filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size INTEGER NOT NULL,
            storage_name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            submission_id TEXT,
            user_id TEXT,
            workspace_id TEXT NOT NULL,
            CONSTRAINT assets_submission_id_fkey FOREIGN KEY (submission_id) REFERENCES submissions (id),
            CONSTRAINT assets_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
            CONSTRAINT assets_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT assets_size_check CHECK (size > 0)
        )""",
    "scheduled_posts": """
        CREATE TABLE scheduled_posts__new (
            id TEXT NOT NULL PRIMARY KEY,
            media_name TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            platforms_json TEXT NOT NULL,
            caption TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id TEXT,
            asset_id TEXT,
            facebook_account_id TEXT,
            timezone_offset_minutes INTEGER NOT NULL DEFAULT 0,
            publish_status TEXT NOT NULL DEFAULT 'scheduled',
            publish_error TEXT,
            published_post_id TEXT,
            workspace_id TEXT NOT NULL,
            CONSTRAINT scheduled_posts_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
            CONSTRAINT scheduled_posts_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES assets (id),
            CONSTRAINT scheduled_posts_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
        )""",
    "social_accounts": """
        CREATE TABLE social_accounts__new (
            id TEXT NOT NULL PRIMARY KEY,
            user_id TEXT,
            provider TEXT NOT NULL,
            platform TEXT NOT NULL,
            account_id TEXT NOT NULL,
            account_name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            encrypted_tokens TEXT NOT NULL,
            expires_at TEXT,
            connected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            CONSTRAINT social_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
            CONSTRAINT social_accounts_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT social_accounts_workspace_platform_account_key UNIQUE (workspace_id, platform, account_id)
        )""",
    "oauth_states": """
        CREATE TABLE oauth_states__new (
            state_hash TEXT NOT NULL PRIMARY KEY,
            provider TEXT NOT NULL,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            CONSTRAINT oauth_states_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT oauth_states_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
        )""",
}


def _scalar(sql: str) -> int:
    return op.get_bind().execute(sa.text(sql)).scalar_one()


def _counts() -> dict[str, int]:
    return {table: _scalar(f"SELECT COUNT(*) FROM {table}") for table in COUNTED_TABLES}


def _old_columns(table: str) -> list[str]:
    return [row[1] for row in op.get_bind().exec_driver_sql(f"PRAGMA table_info({table})")]


def _rebuild_sqlite(table: str, extra: dict[str, str]) -> None:
    """Create the new table, copy every row (computing `extra` columns), swap."""
    bind = op.get_bind()
    bind.exec_driver_sql(SQLITE_TABLES[table])
    old = _old_columns(table)
    columns = old + list(extra)
    values = old + [expression.format(table=table) for expression in extra.values()]
    bind.exec_driver_sql(
        f"INSERT INTO {table}__new ({', '.join(columns)}) SELECT {', '.join(values)} FROM {table}"
    )
    bind.exec_driver_sql(f"DROP TABLE {table}")
    bind.exec_driver_sql(f"ALTER TABLE {table}__new RENAME TO {table}")


def _upgrade_sqlite() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("ALTER TABLE workspaces ADD COLUMN created_by_user_id TEXT REFERENCES users (id) ON DELETE SET NULL")
    bind.exec_driver_sql("ALTER TABLE sessions ADD COLUMN active_workspace_id TEXT REFERENCES workspaces (id) ON DELETE SET NULL")
    bind.exec_driver_sql("UPDATE memberships SET role = 'editor' WHERE role = 'member'")
    _rebuild_sqlite("memberships", {
        "created_at": "(SELECT u.created_at FROM users u WHERE u.id = {table}.user_id)",
    })
    for table in CONTENT_TABLES:
        # The old indexes on these tables go away with them; upgrade() creates
        # the workspace-based replacements.
        _rebuild_sqlite(table, {"workspace_id": OWNER_WORKSPACE})


def _upgrade_postgresql() -> None:
    bind = op.get_bind()
    run = bind.exec_driver_sql
    run("ALTER TABLE workspaces ADD COLUMN created_by_user_id TEXT REFERENCES users (id) ON DELETE SET NULL")
    run("ALTER TABLE sessions ADD COLUMN active_workspace_id TEXT REFERENCES workspaces (id) ON DELETE SET NULL")
    run("ALTER TABLE memberships ADD COLUMN invited_by_user_id TEXT")
    run("ALTER TABLE memberships ADD COLUMN created_at TEXT")
    run("UPDATE memberships SET role = 'editor' WHERE role = 'member'")
    run("UPDATE memberships SET created_at = (SELECT u.created_at FROM users u WHERE u.id = memberships.user_id)")
    run("ALTER TABLE memberships ALTER COLUMN created_at SET NOT NULL")
    run("ALTER TABLE memberships ADD CONSTRAINT memberships_invited_by_fkey "
        "FOREIGN KEY (invited_by_user_id) REFERENCES users (id) ON DELETE SET NULL")
    run("ALTER TABLE memberships DROP CONSTRAINT memberships_role_check")
    run("ALTER TABLE memberships ADD CONSTRAINT memberships_role_check "
        "CHECK (role IN ('owner', 'admin', 'editor', 'client'))")
    for table in CONTENT_TABLES:
        run(f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT")
        run(f"UPDATE {table} SET workspace_id = {OWNER_WORKSPACE.format(table=table)}")
        run(f"ALTER TABLE {table} ALTER COLUMN workspace_id SET NOT NULL")
        run(f"ALTER TABLE {table} ADD CONSTRAINT {table}_workspace_id_fkey "
            f"FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE")
    for table in ("submissions", "assets", "scheduled_posts", "social_accounts"):
        run(f"ALTER TABLE {table} ALTER COLUMN user_id DROP NOT NULL")
        run(f"ALTER TABLE {table} DROP CONSTRAINT {table}_user_id_fkey")
        run(f"ALTER TABLE {table} ADD CONSTRAINT {table}_user_id_fkey "
            f"FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL")
    run("ALTER TABLE social_accounts DROP CONSTRAINT social_accounts_user_platform_account_key")
    run("ALTER TABLE social_accounts ADD CONSTRAINT social_accounts_workspace_platform_account_key "
        "UNIQUE (workspace_id, platform, account_id)")
    run("DROP INDEX social_accounts_user_idx")
    run("DROP INDEX scheduled_posts_user_date_idx")


def upgrade() -> None:
    bad_users = _scalar(
        "SELECT COUNT(*) FROM users u "
        "WHERE (SELECT COUNT(*) FROM memberships m WHERE m.user_id = u.id AND m.role = 'owner') <> 1"
    )
    if bad_users:
        raise RuntimeError(
            f"Aborting: {bad_users} user(s) do not have exactly one owner workspace; nothing was changed."
        )
    for table in CONTENT_TABLES:
        orphans = _scalar(f"SELECT COUNT(*) FROM {table} WHERE {OWNER_WORKSPACE.format(table=table)} IS NULL")
        if orphans:
            raise RuntimeError(f"Aborting: {orphans} row(s) in {table} have no owning workspace; nothing was changed.")
    counts_before = _counts()

    if op.get_bind().dialect.name == "sqlite":
        _upgrade_sqlite()
    else:
        _upgrade_postgresql()

    bind = op.get_bind()
    bind.exec_driver_sql("UPDATE workspaces SET created_by_user_id = "
                         "(SELECT m.user_id FROM memberships m WHERE m.workspace_id = workspaces.id AND m.role = 'owner')")
    bind.exec_driver_sql(f"UPDATE sessions SET active_workspace_id = {OWNER_WORKSPACE.format(table='sessions')}")

    op.create_index(
        "memberships_one_owner", "memberships", ["workspace_id"], unique=True,
        sqlite_where=sa.text("role = 'owner'"), postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_index("memberships_workspace_idx", "memberships", ["workspace_id"])
    op.create_index("social_accounts_workspace_idx", "social_accounts", ["workspace_id", "platform"])
    op.create_index(
        "scheduled_posts_workspace_date_idx", "scheduled_posts", ["workspace_id", "scheduled_date", "scheduled_time"]
    )
    op.create_index("submissions_workspace_idx", "submissions", ["workspace_id", "created_at"])
    op.create_index("assets_workspace_idx", "assets", ["workspace_id"])

    op.create_table(
        "invitations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("invited_by_user_id", sa.Text, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("accepted_at", sa.Text),
        sa.Column("accepted_by_user_id", sa.Text, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revoked_at", sa.Text),
        sa.CheckConstraint("role IN ('admin', 'editor', 'client')", name="invitations_role_check"),
    )
    op.create_index(
        "invitations_one_open", "invitations", ["workspace_id", "email"], unique=True,
        sqlite_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Text, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target_type", sa.Text, nullable=False),
        sa.Column("target_id", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("details_json", sa.Text),
    )
    op.create_index("audit_log_workspace_idx", "audit_log", ["workspace_id", "created_at"])

    counts_after = _counts()
    if counts_after != counts_before:
        raise RuntimeError(f"Aborting: row counts changed {counts_before} -> {counts_after}.")
    for table in CONTENT_TABLES:
        if _scalar(f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL"):
            raise RuntimeError(f"Aborting: {table} has rows without a workspace.")
    if _scalar(
        "SELECT COUNT(*) FROM workspaces w "
        "WHERE (SELECT COUNT(*) FROM memberships m WHERE m.workspace_id = w.id AND m.role = 'owner') <> 1"
    ):
        raise RuntimeError("Aborting: a workspace does not have exactly one owner.")


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrading tenancy is not supported. Restore the verified backup taken by "
        "`python -m app.migrate upgrade` (backend/data/backups/)."
    )
