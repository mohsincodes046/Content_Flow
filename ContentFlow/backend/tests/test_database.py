"""Database behavior that must hold on both SQLite and PostgreSQL."""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app import config, database, migrations_runner, publisher, security, social_oauth, workspaces


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "content_flow.sqlite3")
    database.initialize_storage()
    return database.get_engine().dialect.name


def _run_in_threads(count: int, target) -> None:  # type: ignore[no-untyped-def]
    threads = [threading.Thread(target=target) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_schema_is_at_head(db: str) -> None:
    assert migrations_runner.current_revision() == migrations_runner.head_revision()


def test_rate_limit_is_exact_under_concurrency(db: str) -> None:
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            security.check_rate_limit("concurrency", "subject", 5, timedelta(minutes=5))
            result = "allowed"
        except HTTPException:
            result = "limited"
        with lock:
            outcomes.append(result)

    _run_in_threads(20, attempt)

    assert outcomes.count("allowed") == 5
    assert outcomes.count("limited") == 15


def test_concurrent_publishers_never_publish_a_post_twice(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key()
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", key.decode("ascii"))
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    now = database.utc_now()
    with database.connect_database() as connection:
        connection.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)", ("u1", "a@example.com", "A", "hash", now))
        workspace_id = workspaces.create_workspace(connection, "u1", "W")
        connection.execute(
            "INSERT INTO social_accounts (id, user_id, workspace_id, provider, platform, account_id, account_name, "
            "account_type, encrypted_tokens, expires_at, connected_at, updated_at) "
            "VALUES (?, ?, ?, 'meta', 'facebook', ?, ?, 'page', ?, NULL, ?, ?)",
            ("page", "u1", workspace_id, "meta-page", "Page", Fernet(key).encrypt(b'{"access_token": "t"}').decode(),
             now, now),
        )
        for index in range(10):
            (config.UPLOAD_DIR / f"a{index}.upload").write_bytes(b"img")
            connection.execute(
                "INSERT INTO assets (id, filename, media_type, size, storage_name, created_at, user_id, workspace_id) "
                "VALUES (?, ?, 'image/jpeg', 3, ?, ?, 'u1', ?)",
                (f"a{index}", f"a{index}.jpg", f"a{index}.upload", now, workspace_id),
            )
            connection.execute(
                "INSERT INTO scheduled_posts (id, media_name, scheduled_date, scheduled_time, platforms_json, caption, "
                "created_at, user_id, asset_id, facebook_account_id, timezone_offset_minutes, workspace_id) "
                "VALUES (?, ?, '2020-01-01', '00:00', ?, 'c', ?, 'u1', ?, 'page', 0, ?)",
                (f"p{index}", f"a{index}.jpg", json.dumps(["facebook"]), now, f"a{index}", workspace_id),
            )

    published: list[str] = []
    lock = threading.Lock()

    async def fake_publish(page_id, token, media_path, filename, media_type, caption):  # type: ignore[no-untyped-def]
        with lock:
            published.append(filename)
        return f"meta-{filename}"

    monkeypatch.setattr(social_oauth, "publish_facebook_photo", fake_publish)
    _run_in_threads(4, lambda: asyncio.run(publisher.publish_due_scheduled_posts(datetime.now(timezone.utc))))

    assert sorted(published) == sorted(f"a{index}.jpg" for index in range(10))
    with database.connect_database() as connection:
        statuses = connection.execute("SELECT publish_status, COUNT(*) AS n FROM scheduled_posts GROUP BY publish_status").fetchall()
    assert [dict(row) for row in statuses] == [{"publish_status": "published", "n": 10}]
