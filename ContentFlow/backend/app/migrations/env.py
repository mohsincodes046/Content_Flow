"""Alembic environment: uses the application's own engine (SQLite or PostgreSQL)."""
from __future__ import annotations

from alembic import context

from app.database import get_engine


def run_migrations() -> None:
    connectable = context.config.attributes.get("connection")
    if connectable is not None:
        _run(connectable)
        return
    with get_engine().connect() as connection:
        _run(connection)


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    sqlite = connection.dialect.name == "sqlite"
    if sqlite and not connection.in_transaction():
        # Table rebuilds (batch mode) drop and recreate tables. With foreign keys
        # enforced, SQLite would treat the drop as a DELETE and cascade it into
        # child tables, so enforcement is paused (outside any transaction, where
        # the pragma takes effect) and every relationship is re-verified below.
        connection.connection.driver_connection.execute("PRAGMA foreign_keys = OFF")
    context.configure(
        connection=connection,
        target_metadata=None,
        # SQLite cannot ALTER most constraints; batch mode rebuilds tables instead.
        render_as_batch=sqlite,
        compare_type=True,
    )
    try:
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:
                violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(f"Migration left broken relationships: {violations[:5]}")
    finally:
        if sqlite:
            connection.connection.driver_connection.execute("PRAGMA foreign_keys = ON")


if context.is_offline_mode():
    raise RuntimeError("Offline (SQL script) migrations are not supported; run against a database.")
run_migrations()
