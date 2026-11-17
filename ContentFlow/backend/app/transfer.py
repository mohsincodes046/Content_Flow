"""Copy all application data between databases, then prove the copy is exact.

    python -m app.transfer --source sqlite:///data/content_flow.sqlite3 \
                           --target postgresql://user:pass@host:5432/db [--dry-run]
    python -m app.transfer --source <url> --target <url> --verify-only

Safety rules:
  * The source is only read (SQLite sources are opened read-only).
  * The target must be at the same schema revision as the source and contain
    no application rows; otherwise nothing is written.
  * All rows are copied in one transaction: either everything lands or nothing.
  * Afterwards every table is verified by row count and by a SHA-256 over the
    canonical contents of every row (ordered by primary key). Any difference
    is reported and the command exits non-zero.
  * A SQLite target must be a new file; an existing file is never overwritten.
    That direction (PostgreSQL -> new SQLite file) is the rollback path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import sqlalchemy as sa
from alembic import command
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection, Engine

from app.database import _create_engine
from app.migrations_runner import alembic_config, head_revision

# Parents before children, so foreign keys are satisfied while inserting.
TABLE_ORDER = (
    "users",
    "workspaces",
    "memberships",
    "sessions",
    "submissions",
    "assets",
    "scheduled_posts",
    "oauth_states",
    "social_accounts",
    "rate_limit_events",
)
BATCH_SIZE = 500


@dataclass
class TableReport:
    table: str
    source_rows: int
    target_rows: int
    source_digest: str
    target_digest: str

    @property
    def matches(self) -> bool:
        return self.source_rows == self.target_rows and self.source_digest == self.target_digest


def normalize_url(url: str) -> str:
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def sqlite_file(url: str) -> Optional[Path]:
    return Path(url.split("sqlite:///", 1)[1]) if url.startswith("sqlite:///") else None


def open_source(url: str) -> Engine:
    path = sqlite_file(url)
    if path is not None:
        if not path.exists():
            raise SystemExit(f"Source database {path} does not exist.")
        # Read-only: the source can never be modified by this tool.
        return sa.create_engine(
            "sqlite://", creator=lambda: __import__("sqlite3").connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        )
    return _create_engine(normalize_url(url))


def open_target(url: str, *, must_be_new: bool) -> Engine:
    path = sqlite_file(url)
    if path is not None and must_be_new and path.exists():
        raise SystemExit(f"Refusing to write into existing file {path}; choose a new file name.")
    return _create_engine(normalize_url(url))


def revision_of(connection: Connection) -> Optional[str]:
    return MigrationContext.configure(connection).get_current_revision()


def ordering_columns(table: sa.Table) -> list[sa.Column]:
    primary_key = list(table.primary_key.columns)
    return primary_key or sorted(table.columns, key=lambda column: column.name)


def canonical_rows(connection: Connection, table: sa.Table) -> Iterable[dict[str, Any]]:
    query = sa.select(table).order_by(*ordering_columns(table))
    for row in connection.execute(query).mappings():
        yield {key: row[key] for key in sorted(row.keys())}


def digest(connection: Connection, table: sa.Table) -> tuple[int, str]:
    hasher = hashlib.sha256()
    count = 0
    for row in canonical_rows(connection, table):
        hasher.update(json.dumps(row, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8"))
        hasher.update(b"\n")
        count += 1
    return count, hasher.hexdigest()


def reflect(connection: Connection) -> dict[str, sa.Table]:
    metadata = sa.MetaData()
    metadata.reflect(bind=connection, only=list(TABLE_ORDER))
    return {name: metadata.tables[name] for name in TABLE_ORDER}


def preflight(source: Connection, target: Connection) -> dict[str, sa.Table]:
    source_revision = revision_of(source)
    target_revision = revision_of(target)
    if source_revision != head_revision():
        raise SystemExit(
            f"Source is at revision {source_revision!r}, expected {head_revision()!r}. "
            "Run `python -m app.migrate upgrade` on the source first (it takes a backup)."
        )
    if target_revision != source_revision:
        raise SystemExit(f"Target is at revision {target_revision!r}, source at {source_revision!r}.")
    source_tables = reflect(source)
    target_tables = reflect(target)
    for name in TABLE_ORDER:
        source_columns = set(source_tables[name].columns.keys())
        target_columns = set(target_tables[name].columns.keys())
        if source_columns != target_columns:
            raise SystemExit(f"Column mismatch in {name}: {sorted(source_columns ^ target_columns)}")
        populated = target.execute(sa.select(sa.func.count()).select_from(target_tables[name])).scalar_one()
        if populated:
            raise SystemExit(f"Target table {name} already has {populated} rows; refusing to write.")
        for column in source_tables[name].primary_key.columns:
            nulls = source.execute(
                sa.select(sa.func.count()).select_from(source_tables[name]).where(column.is_(None))
            ).scalar_one()
            if nulls:
                raise SystemExit(f"Source table {name} has {nulls} rows with a NULL {column.name}.")
    return target_tables


def copy_all(source: Connection, target: Connection, target_tables: dict[str, sa.Table]) -> None:
    source_tables = reflect(source)
    for name in TABLE_ORDER:
        batch: list[dict[str, Any]] = []
        for row in canonical_rows(source, source_tables[name]):
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                target.execute(sa.insert(target_tables[name]), batch)
                batch = []
        if batch:
            target.execute(sa.insert(target_tables[name]), batch)


def verify(source: Connection, target: Connection) -> list[TableReport]:
    source_tables = reflect(source)
    target_tables = reflect(target)
    reports = []
    for name in TABLE_ORDER:
        source_rows, source_digest = digest(source, source_tables[name])
        target_rows, target_digest = digest(target, target_tables[name])
        reports.append(TableReport(name, source_rows, target_rows, source_digest, target_digest))
    return reports


def print_report(reports: list[TableReport]) -> bool:
    ok = all(report.matches for report in reports)
    print(f"{'table':<20}{'source':>8}{'target':>8}  digest match")
    for report in reports:
        print(f"{report.table:<20}{report.source_rows:>8}{report.target_rows:>8}  "
              f"{'yes' if report.matches else 'NO'}  {report.source_digest[:12]}")
    print("RESULT:", "all tables identical" if ok else "DIFFERENCES FOUND")
    return ok


def run(source_url: str, target_url: str, *, dry_run: bool = False, verify_only: bool = False) -> bool:
    source_engine = open_source(source_url)
    target_engine = open_target(target_url, must_be_new=not verify_only)
    with source_engine.connect() as source:
        if verify_only:
            with target_engine.connect() as target:
                return print_report(verify(source, target))
        with target_engine.connect() as target:
            if revision_of(target) is None and not sa.inspect(target).get_table_names():
                cfg = alembic_config()
                cfg.attributes["connection"] = target
                command.upgrade(cfg, revision_of(source) or "head")
                target.commit()
        with target_engine.begin() as target:
            target_tables = preflight(source, target)
            if dry_run:
                print("Dry run: preflight passed; no rows were written.")
                return True
            copy_all(source, target, target_tables)
            reports = verify(source, target)
            ok = print_report(reports)
            if not ok:
                raise RuntimeError("Verification failed; the copy has been rolled back.")
        return ok


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.transfer")
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    return 0 if run(args.source, args.target, dry_run=args.dry_run, verify_only=args.verify_only) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
