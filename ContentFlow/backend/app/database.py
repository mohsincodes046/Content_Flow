from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app import config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_database() -> sqlite3.Connection:
    connection = sqlite3.connect(config.DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_storage() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect_database() as connection:
        connection.executescript(
            """
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
                ON rate_limit_events(created_at);
            """
        )
        submission_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(submissions)")
        }
        if "user_id" not in submission_columns:
            connection.execute(
                "ALTER TABLE submissions ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE"
            )
        asset_columns = {row["name"] for row in connection.execute("PRAGMA table_info(assets)")}
        if "user_id" not in asset_columns:
            connection.execute(
                "ALTER TABLE assets ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE"
            )
        scheduled_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(scheduled_posts)")
        }
        scheduled_migrations = {
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
        }
        for column, migration in scheduled_migrations.items():
            if column not in scheduled_columns:
                connection.execute(migration)
