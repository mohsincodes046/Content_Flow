"""Schema-versioning and database-layer tests (SQLite)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import config, database, migrate, migrations_runner

pytestmark = pytest.mark.skipif(
    database.database_url().startswith("postgresql"), reason="SQLite-specific migration tests"
)


@pytest.fixture()
def sqlite_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "content_flow.sqlite3")
    monkeypatch.delenv("CONTENT_FLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("CONTENT_FLOW_AUTO_MIGRATE", raising=False)
    return data_dir / "content_flow.sqlite3"


def _schema(path: Path) -> dict[str, object]:
    """Columns, indexes and foreign keys of every application table."""
    with sqlite3.connect(path) as connection:
        tables = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version') ORDER BY name"
            )
        ]
        result: dict[str, object] = {}
        for table in tables:
            # The one known difference: SQLite lets a TEXT PRIMARY KEY hold NULL
            # unless it is declared NOT NULL, and the legacy schema did not declare
            # it. The baseline declares primary keys NOT NULL (as PostgreSQL always
            # does); the app always generates IDs. Primary-key nullability is
            # therefore normalized here and checked separately during data transfer.
            columns = [
                (name, col_type.upper(), 1 if pk else notnull, (default or "").strip("'\""), pk)
                for _, name, col_type, notnull, default, pk in connection.execute(f"PRAGMA table_info({table})")
            ]
            indexes = sorted(
                (unique, tuple(row[2] for row in connection.execute(f"PRAGMA index_info('{name}')")))
                for _, name, unique, _, _ in connection.execute(f"PRAGMA index_list({table})")
            )
            foreign_keys = sorted(
                (row[2], row[3], row[4], row[6]) for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            )
            result[table] = {"columns": columns, "indexes": indexes, "foreign_keys": foreign_keys}
        return result


def test_baseline_migration_matches_the_legacy_schema(sqlite_path: Path, tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(legacy_path) as connection:
        connection.executescript(migrations_runner.LEGACY_SQLITE_SCHEMA)

    migrations_runner.upgrade("0001_baseline")

    assert _schema(sqlite_path) == _schema(legacy_path)
    assert migrations_runner.current_revision() == "0001_baseline"


def test_pre_alembic_database_is_stamped_without_losing_data(sqlite_path: Path) -> None:
    # An old database: created before scheduled_posts gained its publishing columns.
    old_schema = migrations_runner.LEGACY_SQLITE_SCHEMA.replace(
        """    asset_id TEXT REFERENCES assets(id),
    facebook_account_id TEXT,
    timezone_offset_minutes INTEGER NOT NULL DEFAULT 0,
    publish_status TEXT NOT NULL DEFAULT 'scheduled',
    publish_error TEXT,
    published_post_id TEXT
""",
        "",
    ).replace("user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n);", "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE\n);")
    with sqlite3.connect(sqlite_path) as connection:
        connection.executescript(old_schema)
        connection.execute("INSERT INTO users VALUES ('u1', 'a@example.com', 'A', 'hash', '2026-01-01T00:00:00+00:00')")
        connection.execute("INSERT INTO workspaces VALUES ('w1', 'Studio', '2026-01-01T00:00:00+00:00')")
        connection.execute("INSERT INTO memberships VALUES ('u1', 'w1', 'owner')")
        connection.execute(
            "INSERT INTO scheduled_posts (id, media_name, scheduled_date, scheduled_time, platforms_json, caption, created_at, user_id) "
            "VALUES ('p1', 'img.jpg', '2026-12-01', '10:00', '[\"facebook\"]', 'Hi', '2026-01-01', 'u1')"
        )
    assert "publish_status" not in {row[1] for row in sqlite3.connect(sqlite_path).execute("PRAGMA table_info(scheduled_posts)")}

    # 1. Starting the app stamps the old database, then refuses to migrate it unattended.
    with pytest.raises(migrations_runner.SchemaOutOfDateError):
        migrations_runner.ensure_schema()
    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001_baseline"
        assert connection.execute("SELECT email FROM users").fetchall() == [("a@example.com",)]
        assert connection.execute("SELECT publish_status, timezone_offset_minutes FROM scheduled_posts").fetchall() == [
            ("scheduled", 0)
        ]

    # 2. The deliberate upgrade backs up, then moves everything into the workspace.
    assert migrate.main(["upgrade"]) == 0
    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == migrations_runner.head_revision()
        assert connection.execute("SELECT id, workspace_id, user_id FROM scheduled_posts").fetchall() == [("p1", "w1", "u1")]
        assert connection.execute("SELECT role, created_at FROM memberships").fetchall() == [
            ("owner", "2026-01-01T00:00:00+00:00")
        ]
        assert connection.execute("SELECT created_by_user_id FROM workspaces").fetchall() == [("u1",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert len(list((sqlite_path.parent / "backups").glob("*-before-upgrade.sqlite3"))) == 1


def test_tenancy_migration_aborts_without_changes_when_a_user_has_no_workspace(sqlite_path: Path) -> None:
    migrations_runner.upgrade("0001_baseline")
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("INSERT INTO users VALUES ('u1', 'a@example.com', 'A', 'hash', '2026-01-01T00:00:00+00:00')")
    before = _schema(sqlite_path)

    with pytest.raises(RuntimeError, match="do not have exactly one owner workspace"):
        migrations_runner.upgrade("head")

    assert migrations_runner.current_revision() == "0001_baseline"
    assert _schema(sqlite_path) == before


def test_outdated_database_refuses_to_start_unless_auto_migrate(
    sqlite_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations_runner.ensure_schema()
    monkeypatch.setattr(migrations_runner, "head_revision", lambda: "9999_future")
    upgrades: list[str] = []
    monkeypatch.setattr(migrations_runner, "upgrade", lambda revision="head": upgrades.append(revision))

    with pytest.raises(migrations_runner.SchemaOutOfDateError, match="python -m app.migrate upgrade"):
        migrations_runner.ensure_schema()
    assert upgrades == []

    monkeypatch.setenv("CONTENT_FLOW_AUTO_MIGRATE", "true")
    migrations_runner.ensure_schema()
    assert upgrades == ["head"]


def test_migrate_upgrade_takes_a_verified_backup_first(sqlite_path: Path) -> None:
    migrations_runner.ensure_schema()
    with database.connect_database() as connection:
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)", ("u1", "a@example.com", "A", "hash", database.utc_now())
        )

    assert migrate.main(["upgrade"]) == 0

    backups = list((sqlite_path.parent / "backups").glob("*-before-upgrade.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT email FROM users").fetchall() == [("a@example.com",)]


def test_question_marks_inside_string_literals_are_not_parameters(sqlite_path: Path) -> None:
    migrations_runner.ensure_schema()
    with database.connect_database() as connection:
        row = connection.execute("SELECT 'why?' AS text, ? AS value", (42,)).fetchone()
    assert dict(row) == {"text": "why?", "value": 42}
    with pytest.raises(ValueError, match="expects 1 parameters"):
        with database.connect_database() as connection:
            connection.execute("SELECT ?", ())


def test_transactions_roll_back_on_error(sqlite_path: Path) -> None:
    migrations_runner.ensure_schema()
    with pytest.raises(RuntimeError):
        with database.connect_database() as connection:
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)", ("u1", "a@example.com", "A", "hash", database.utc_now())
            )
            raise RuntimeError("boom")
    with database.connect_database() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0


def test_lock_for_write_must_start_a_sqlite_transaction(sqlite_path: Path) -> None:
    migrations_runner.ensure_schema()
    with pytest.raises(RuntimeError, match="first call"):
        with database.connect_database() as connection:
            connection.execute("SELECT 1")
            connection.lock_for_write()

