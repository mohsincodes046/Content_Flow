"""Schema versioning with Alembic.

Startup policy (`ensure_schema`):
  * empty database                 -> create the schema (no data at risk)
  * SQLite created before Alembic  -> apply the old additive fix-ups, then mark it
                                      as the baseline revision (no data changes)
  * database behind the code       -> refuse to start, unless
                                      CONTENT_FLOW_AUTO_MIGRATE=true, so data is
                                      never migrated by an unattended restart

Run migrations deliberately with:  python -m app.migrate upgrade
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.database import connect_database, get_engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE_REVISION = "0001_baseline"


class SchemaOutOfDateError(RuntimeError):
    pass


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def head_revision() -> Optional[str]:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision() -> Optional[str]:
    with get_engine().connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def table_names() -> set[str]:
    with get_engine().connect() as connection:
        return set(sa.inspect(connection).get_table_names())


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)


def stamp(revision: str) -> None:
    command.stamp(alembic_config(), revision)


def auto_migrate_enabled() -> bool:
    return os.environ.get("CONTENT_FLOW_AUTO_MIGRATE", "false").strip().lower() in {"1", "true", "yes", "on"}


def upgrade_legacy_sqlite_schema() -> None:
    """Bring a SQLite database created before Alembic up to the baseline schema.

    This is the exact create-if-missing / add-missing-column logic the app ran on
    every start before Alembic. It only ever adds tables and columns.
    """
    with connect_database() as connection:
        for statement in LEGACY_SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(statement)
        missing_columns = {
            "submissions": {
                "user_id": "ALTER TABLE submissions ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE",
            },
            "assets": {
                "user_id": "ALTER TABLE assets ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE",
            },
            "scheduled_posts": {
                "asset_id": "ALTER TABLE scheduled_posts ADD COLUMN asset_id TEXT REFERENCES assets(id)",
                "facebook_account_id": "ALTER TABLE scheduled_posts ADD COLUMN facebook_account_id TEXT",
                "timezone_offset_minutes": (
                    "ALTER TABLE scheduled_posts ADD COLUMN timezone_offset_minutes INTEGER NOT NULL DEFAULT 0"
                ),
                "publish_status": (
                    "ALTER TABLE scheduled_posts ADD COLUMN publish_status TEXT NOT NULL DEFAULT 'scheduled'"
                ),
                "publish_error": "ALTER TABLE scheduled_posts ADD COLUMN publish_error TEXT",
                "published_post_id": "ALTER TABLE scheduled_posts ADD COLUMN published_post_id TEXT",
            },
        }
        for table, migrations in missing_columns.items():
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column, ddl in migrations.items():
                if column not in existing:
                    connection.execute(ddl)


def ensure_schema() -> None:
    engine = get_engine()
    tables = table_names()
    head = head_revision()

    if "alembic_version" not in tables and "users" in tables:
        if engine.dialect.name != "sqlite":
            raise SchemaOutOfDateError(
                "This PostgreSQL database has application tables but no Alembic version. "
                "Refusing to guess its schema."
            )
        logger.info("Existing SQLite database predates Alembic; applying legacy fix-ups and stamping baseline.")
        upgrade_legacy_sqlite_schema()
        stamp(BASELINE_REVISION)

    current = current_revision()
    if current == head:
        return
    if current is None and "users" not in tables:
        logger.info("Empty database; creating schema at revision %s.", head)
        upgrade("head")
        return
    if auto_migrate_enabled():
        logger.warning("Migrating database from %s to %s (CONTENT_FLOW_AUTO_MIGRATE=true).", current, head)
        upgrade("head")
        return
    raise SchemaOutOfDateError(
        f"Database schema is at revision {current!r} but this code needs {head!r}. "
        "Back up the database, then run: python -m app.migrate upgrade"
    )


# The pre-Alembic schema, verbatim. Used only by upgrade_legacy_sqlite_schema().
LEGACY_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('owner', 'member')),
    PRIMARY KEY (user_id, workspace_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    campaign TEXT NOT NULL,
    audience TEXT NOT NULL,
    instructions TEXT NOT NULL,
    language TEXT NOT NULL,
    platforms_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('submitted')),
    created_at TEXT NOT NULL,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL CHECK(size > 0),
    storage_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    submission_id TEXT REFERENCES submissions(id),
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id TEXT PRIMARY KEY,
    media_name TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    platforms_json TEXT NOT NULL,
    caption TEXT NOT NULL,
    created_at TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asset_id TEXT REFERENCES assets(id),
    facebook_account_id TEXT,
    timezone_offset_minutes INTEGER NOT NULL DEFAULT 0,
    publish_status TEXT NOT NULL DEFAULT 'scheduled',
    publish_error TEXT,
    published_post_id TEXT
);
CREATE INDEX IF NOT EXISTS scheduled_posts_user_date_idx
    ON scheduled_posts(user_id, scheduled_date, scheduled_time);
CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS social_accounts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    platform TEXT NOT NULL,
    account_id TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    encrypted_tokens TEXT NOT NULL,
    expires_at TEXT,
    connected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, platform, account_id)
);
CREATE INDEX IF NOT EXISTS social_accounts_user_idx
    ON social_accounts(user_id, platform);
CREATE TABLE IF NOT EXISTS rate_limit_events (
    bucket TEXT NOT NULL,
    subject TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_limit_events_lookup_idx
    ON rate_limit_events(bucket, subject, created_at);
CREATE INDEX IF NOT EXISTS rate_limit_events_created_idx
    ON rate_limit_events(created_at)
"""
