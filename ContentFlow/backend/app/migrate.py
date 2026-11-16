"""Database migration command.

    python -m app.migrate status     # current and target revision
    python -m app.migrate backup     # SQLite: verified online backup to data/backups/
    python -m app.migrate upgrade    # SQLite: backup first, then upgrade to head

PostgreSQL backups are taken with Render's tools or pg_dump (see backend/README.md).
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from app import config
from app.database import get_engine
from app.migrations_runner import (
    current_revision,
    ensure_schema,
    head_revision,
    table_names,
    upgrade,
    upgrade_legacy_sqlite_schema,
    stamp,
    BASELINE_REVISION,
)


def _row_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}


def backup_sqlite(label: str = "manual") -> Path:
    """Copy the live SQLite database with the online-backup API and verify the copy."""
    source = config.DATABASE_PATH
    if not source.exists():
        raise SystemExit(f"No SQLite database at {source}.")
    backup_dir = config.DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"content_flow-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{label}.sqlite3"
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    with sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True) as check:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok" or _row_counts(source) != _row_counts(target):
        raise SystemExit(f"Backup verification failed ({integrity}); nothing was changed.")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"Backup written and verified: {target} (sha256 {digest[:16]}...)")
    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.migrate")
    parser.add_argument("action", choices=["status", "backup", "upgrade"])
    args = parser.parse_args(argv)
    sqlite = get_engine().dialect.name == "sqlite"

    if args.action == "status":
        print(f"database: {get_engine().url.render_as_string(hide_password=True)}")
        print(f"current revision: {current_revision()}")
        print(f"code expects:     {head_revision()}")
        return 0
    if args.action == "backup":
        if not sqlite:
            raise SystemExit("Use Render's backups or pg_dump for PostgreSQL.")
        backup_sqlite()
        return 0

    # upgrade
    if sqlite and config.DATABASE_PATH.exists():
        backup_sqlite("before-upgrade")
    tables = table_names()
    if sqlite and "users" in tables and "alembic_version" not in tables:
        upgrade_legacy_sqlite_schema()
        stamp(BASELINE_REVISION)
    if "users" not in tables:
        ensure_schema()
    else:
        upgrade("head")
    print(f"Database is at revision {current_revision()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
