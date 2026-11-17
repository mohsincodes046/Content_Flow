"""The publisher sleeps until the next due post (so a scale-to-zero database can sleep
too) and wakes at once when a request changes something."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from test_posts import env, later  # noqa: F401  (fixture re-export)

from app import publisher


def test_next_wake_is_the_earliest_scheduled_post(env: dict) -> None:
    editor = env["editor"]
    assert publisher.next_wake_at() is None
    first = editor.post("/api/posts", json={"caption": "a", "targets": [{"social_account_id": "fb"}],
                                            "action": "schedule", "schedule": later(3)}).json()
    editor.post("/api/posts", json={"caption": "b", "targets": [{"social_account_id": "fb"}],
                                    "action": "schedule", "schedule": later(5)})
    wake = publisher.next_wake_at()
    assert wake == datetime.fromisoformat(first["scheduled_at"])

    editor.post(f"/api/posts/{first['id']}/unschedule")
    assert publisher.next_wake_at() > wake  # only the later post remains


def test_next_wake_waits_for_retry_backoff(env: dict) -> None:
    editor = env["editor"]
    post = editor.post("/api/posts", json={"caption": "a", "targets": [{"social_account_id": "fb"}],
                                           "action": "schedule", "schedule": later(1)}).json()
    retry_at = datetime.now(timezone.utc) + timedelta(days=4)
    from app.database import connect_database
    with connect_database() as connection:
        connection.execute("UPDATE post_targets SET next_attempt_at = ? WHERE post_id = ?",
                           (retry_at.isoformat(), post["id"]))
    assert publisher.next_wake_at() == retry_at


def test_scheduler_sleeps_until_woken(monkeypatch: pytest.MonkeyPatch) -> None:
    passes: list[float] = []

    async def fake_publish_due() -> int:
        passes.append(asyncio.get_running_loop().time())
        return 0

    monkeypatch.setattr(publisher, "publish_due", fake_publish_due)
    monkeypatch.setattr(publisher, "recover_interrupted", lambda: 0)
    monkeypatch.setattr(publisher, "next_wake_at", lambda: None)  # nothing scheduled
    monkeypatch.setenv("CONTENT_FLOW_PUBLISHER_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("CONTENT_FLOW_PUBLISHER_IDLE_SECONDS", "3600")

    async def scenario() -> None:
        task = asyncio.create_task(publisher.run_publisher_scheduler())
        await asyncio.sleep(0.2)
        assert len(passes) == 1  # one pass at start, then a long idle sleep
        await asyncio.sleep(0.5)
        assert len(passes) == 1
        publisher.wake_publisher()
        await asyncio.sleep(1.5)
        assert len(passes) == 2  # woken by the request, not by the timer
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_successful_writes_wake_the_publisher(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    woken: list[int] = []
    monkeypatch.setattr("app.main.wake_publisher", lambda: woken.append(1))
    editor = env["editor"]
    editor.get("/api/posts")
    assert woken == []
    editor.post("/api/posts", json={"caption": "a", "targets": [{"social_account_id": "fb"}],
                                    "action": "schedule", "schedule": later(2)})
    assert woken == [1]
    past = {"local_datetime": "2020-01-01T09:00:00", "timezone": "UTC"}
    rejected = editor.post("/api/posts", json={"caption": "a", "targets": [{"social_account_id": "fb"}],
                                               "action": "schedule", "schedule": past})
    assert rejected.status_code == 422
    assert woken == [1]
