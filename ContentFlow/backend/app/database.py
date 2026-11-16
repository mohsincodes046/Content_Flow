"""Database access for SQLite (development, tests) and PostgreSQL (production).

`connect_database()` keeps the small interface the routers were written against:

    with connect_database() as connection:
        connection.lock_for_write()          # optional, must come first
        row = connection.execute("SELECT ... WHERE id = ?", (value,)).fetchone()

The block commits on success and rolls back on any exception. `?` placeholders
are translated to SQLAlchemy bind parameters, and rows are read-only mappings
(`row["column"]`). `lock_for_write()` gives the same "one writer at a time"
guarantee on both databases: BEGIN IMMEDIATE on SQLite, a transaction-scoped
advisory lock on PostgreSQL.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterator, Mapping, Optional, Sequence, Union

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Connection, CursorResult, Engine
from sqlalchemy.pool import NullPool

from app import config

logger = logging.getLogger(__name__)

Row = Mapping[str, Any]
Params = Union[Sequence[Any], Mapping[str, Any]]

# Arbitrary constant: the single application-wide write lock on PostgreSQL,
# mirroring SQLite's database-level write lock taken by BEGIN IMMEDIATE.
POSTGRES_WRITE_LOCK_KEY = 4_815_162_342

_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_url() -> str:
    """CONTENT_FLOW_DATABASE_URL if set (PostgreSQL), otherwise the SQLite file."""
    url = os.environ.get("CONTENT_FLOW_DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{config.DATABASE_PATH.as_posix()}"
    # Render and most hosts hand out postgres:// or postgresql:// URLs; use psycopg 3.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _create_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # A fresh connection per use, like the original sqlite3 code. This also
        # avoids holding file handles open (which matters on Windows).
        engine = sa.create_engine(url, poolclass=NullPool, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_on_connect(dbapi_connection: Any, _record: Any) -> None:
            # Let SQLAlchemy's "begin" hook below issue BEGIN itself, so we control
            # DEFERRED vs IMMEDIATE (pysqlite's own transaction handling cannot).
            dbapi_connection.isolation_level = None
            dbapi_connection.execute("PRAGMA foreign_keys = ON")

        @event.listens_for(engine, "begin")
        def _sqlite_on_begin(connection: Connection) -> None:
            mode = "IMMEDIATE" if connection.info.get("write_lock") else "DEFERRED"
            connection.exec_driver_sql(f"BEGIN {mode}")

        return engine
    return sa.create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def get_engine() -> Engine:
    url = database_url()
    with _engines_lock:
        engine = _engines.get(url)
        if engine is None:
            engine = _create_engine(url)
            _engines[url] = engine
        return engine


@lru_cache(maxsize=512)
def _translate(sql: str) -> tuple[str, int]:
    """Replace `?` placeholders outside string literals with :p0, :p1, ..."""
    out: list[str] = []
    in_literal = False
    count = 0
    for char in sql:
        if char == "'":
            in_literal = not in_literal
            out.append(char)
        elif char == "?" and not in_literal:
            out.append(f":p{count}")
            count += 1
        else:
            out.append(char)
    return "".join(out), count


class QueryResult:
    """The parts of a DB-API cursor the application uses, returning mapping rows."""

    def __init__(self, result: CursorResult) -> None:
        self._result = result
        self.rowcount = result.rowcount

    def fetchone(self) -> Optional[Row]:
        if not self._result.returns_rows:
            return None
        return self._result.mappings().fetchone()

    def fetchall(self) -> list[Row]:
        if not self._result.returns_rows:
            return []
        return list(self._result.mappings().fetchall())

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class DatabaseConnection:
    def __init__(self, engine: Engine) -> None:
        self._connection = engine.connect()
        self._transaction: Optional[sa.engine.Transaction] = None

    @property
    def dialect(self) -> str:
        return self._connection.dialect.name

    def _begin(self) -> None:
        if self._transaction is None:
            self._transaction = self._connection.begin()

    def lock_for_write(self) -> None:
        """Serialize this transaction with every other writer that also locks."""
        if self.dialect == "sqlite":
            if self._transaction is not None:
                raise RuntimeError("lock_for_write() must be the first call in a SQLite transaction.")
            self._connection.info["write_lock"] = True
            self._begin()
        else:
            self._begin()
            self._connection.execute(
                sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": POSTGRES_WRITE_LOCK_KEY}
            )

    def execute(self, sql: str, params: Params = ()) -> QueryResult:
        self._begin()
        if isinstance(params, Mapping):
            return QueryResult(self._connection.execute(sa.text(sql), dict(params)))
        translated, expected = _translate(sql)
        values = list(params)
        if len(values) != expected:
            raise ValueError(f"Query expects {expected} parameters, got {len(values)}.")
        bound = {f"p{index}": value for index, value in enumerate(values)}
        return QueryResult(self._connection.execute(sa.text(translated), bound))

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if self._transaction is not None and self._transaction.is_active:
                if exc_type is None:
                    self._transaction.commit()
                else:
                    self._transaction.rollback()
        finally:
            self._connection.info.pop("write_lock", None)
            self._connection.close()


def connect_database() -> DatabaseConnection:
    return DatabaseConnection(get_engine())


def initialize_storage() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    from app.migrations_runner import ensure_schema

    ensure_schema()
