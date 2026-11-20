"""Posts end to end through the API: drafts, platform versions, review, scheduling,
publishing, retries and media links. Only Meta's network calls are replaced."""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from media_samples import jpeg, mp4, png

from app import config, database, main, media, meta_graph, publisher

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CONTENT_FLOW_API_PUBLIC_URL", "https://api.example.com")
    monkeypatch.setenv("CONTENT_FLOW_REGISTER_PER_HOUR_LIMIT", "100")
    clients: list[TestClient] = []

    def client() -> TestClient:
        c = TestClient(main.app)
        c.__enter__()
        clients.append(c)
        return c

    owner = client()
    owner.post("/api/auth/register", json={"full_name": "Owner", "workspace_name": "Agency",
                                           "email": "owner@example.com", "password": PASSWORD})

    def invited(email: str, role: str) -> TestClient:
        link = owner.post("/api/workspaces/current/invitations", json={"email": email, "role": role}).json()["invite_url"]
        c = client()
        c.post("/api/auth/register", json={"full_name": role.title(), "email": email, "password": PASSWORD,
                                           "invitation_token": parse_qs(urlparse(link).query)["token"][0]})
        return c

    editor = invited("editor@example.com", "editor")
    reviewer = invited("client@example.com", "client")
    other_client = invited("other@example.com", "client")
    me = owner.get("/api/auth/me").json()
    from app.security import token_cipher

    with database.connect_database() as connection:
        for account_id, platform, name in (("fb", "facebook", "Agency Page"), ("ig", "instagram", "agency.ig")):
            connection.execute(
                "INSERT INTO social_accounts (id, user_id, workspace_id, provider, platform, account_id, account_name, "
                "account_type, encrypted_tokens, expires_at, connected_at, updated_at) "
                "VALUES (?, ?, ?, 'meta', ?, ?, ?, 'page', ?, NULL, ?, ?)",
                (account_id, me["id"], me["workspace_id"], platform, f"meta-{account_id}", name,
                 token_cipher().encrypt(b'{"access_token": "page-token"}').decode(), database.utc_now(), database.utc_now()),
            )
    yield {"owner": owner, "editor": editor, "client": reviewer, "other_client": other_client,
           "client_id": reviewer.get("/api/auth/me").json()["id"]}
    for c in clients:
        c.__exit__(None, None, None)


def upload(c: TestClient, data: bytes = b"", name: str = "photo.jpg", kind: str = "image/jpeg") -> str:
    response = c.post("/api/assets", files={"file": (name, data or jpeg(), kind)})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def later(days: int = 2, hour: int = 9) -> dict[str, str]:
    when = (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=hour, minute=30, second=0, microsecond=0)
    return {"local_datetime": when.replace(tzinfo=None).isoformat(), "timezone": "Asia/Karachi"}


class FakeMeta:
    """Stand-in for meta_graph's publishing calls; records what was sent."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[str, str, str, list]] = []
        self.failures: list[meta_graph.GraphError] = []

        async def facebook(page_id, token, message, files, link=None):  # type: ignore[no-untyped-def]
            return self._answer("facebook", page_id, message, [(f.filename, f.media_type) for f in files])

        async def instagram(ig_id, token, caption, items):  # type: ignore[no-untyped-def]
            return self._answer("instagram", ig_id, caption, items)

        monkeypatch.setattr(meta_graph, "publish_facebook", facebook)
        monkeypatch.setattr(meta_graph, "publish_instagram", instagram)

    def _answer(self, platform: str, account: str, text: str, media_items: list) -> meta_graph.PublishResult:
        if self.failures:
            raise self.failures.pop(0)
        self.calls.append((platform, account, text, media_items))
        return meta_graph.PublishResult(f"{platform}-post-{len(self.calls)}", f"https://example.com/{platform}/{len(self.calls)}")


def run_due() -> None:
    asyncio.run(publisher.publish_due())


# --- Drafts, platform versions and validation --------------------------------------------------

def test_draft_with_platform_versions_and_live_validation(env: dict) -> None:
    editor = env["editor"]
    gif = upload(editor, png(), "a.png", "image/png")
    created = editor.post("/api/posts", json={
        "title": "Launch", "caption": "Our new menu #food",
        "asset_ids": [gif],
        "targets": [{"social_account_id": "fb"},
                    {"social_account_id": "ig", "caption_override": "Insta version " + "#tag " * 31}],
    })
    assert created.status_code == 201
    post = created.json()
    assert post["status"] == "draft"
    assert {t["platform"]: t["caption_override"] for t in post["targets"]}["facebook"] is None
    assert [i["message"] for i in post["issues"]] == ["Instagram allows at most 30 hashtags."]

    edited = editor.patch(f"/api/posts/{post['id']}", json={
        "title": "Launch", "caption": "Our new menu", "asset_ids": [gif],
        "targets": [{"social_account_id": "fb"}, {"social_account_id": "ig", "caption_override": "Insta version"}],
    }).json()
    assert edited["issues"] == []
    assert [e["kind"] for e in edited["events"]] == ["created", "edited"]


def test_instagram_rules(env: dict) -> None:
    editor = env["editor"]
    wide = upload(editor, jpeg(2000, 800))
    post = editor.post("/api/posts", json={"caption": "text only", "targets": [{"social_account_id": "ig"}]}).json()
    assert "Instagram posts need at least one photo or video." in [i["message"] for i in post["issues"]]
    post = editor.post("/api/posts", json={"asset_ids": [wide], "targets": [{"social_account_id": "ig"}]}).json()
    assert "aspect ratio" in post["issues"][0]["message"]


def test_uploads_are_checked_and_listed(env: dict) -> None:
    editor = env["editor"]
    assert editor.post("/api/assets", files={"file": ("x.jpg", b"not really", "image/jpeg")}).status_code == 415
    assert editor.post("/api/assets", files={"file": ("x.mp4", b"not a video at all", "video/mp4")}).status_code == 415
    video = upload(editor, mp4(), "clip.mp4", "video/mp4")
    photo = upload(editor, jpeg(1080, 1350))
    listed = {a["id"]: a for a in editor.get("/api/assets").json()}
    assert (listed[photo]["width"], listed[photo]["height"]) == (1080, 1350)
    assert listed[video]["media_type"] == "video/mp4"
    assert editor.get(f"/api/assets/{photo}/content").content == jpeg(1080, 1350)
    assert [a["id"] for a in editor.get("/api/assets?kind=video").json()] == [video]


def test_media_is_protected_only_while_a_post_may_still_publish(env: dict) -> None:
    editor = env["editor"]
    scheduled_media, draft_media, unused = upload(editor), upload(editor), upload(editor)
    scheduled = editor.post("/api/posts", json={"asset_ids": [scheduled_media], "targets": [{"social_account_id": "fb"}],
                                                "action": "schedule", "schedule": later(2)}).json()
    draft = editor.post("/api/posts", json={"caption": "keep me", "asset_ids": [draft_media],
                                            "targets": [{"social_account_id": "fb"}]}).json()
    blocked = editor.delete(f"/api/assets/{scheduled_media}")
    assert blocked.status_code == 409 and "scheduled" in blocked.json()["detail"]

    assert editor.delete(f"/api/assets/{draft_media}").status_code == 204  # the draft just loses the file
    kept = editor.get(f"/api/posts/{draft['id']}").json()
    assert kept["caption"] == "keep me" and kept["status"] == "draft"
    assert draft_media not in str(kept)

    editor.post(f"/api/posts/{scheduled['id']}/unschedule")
    assert editor.delete(f"/api/assets/{scheduled_media}").status_code == 204  # no longer waiting to publish
    assert editor.delete(f"/api/assets/{unused}").status_code == 204
    assert editor.get(f"/api/assets/{unused}/content").status_code == 404


# --- Scheduling ---------------------------------------------------------------------------------

def test_scheduling_converts_the_local_time_to_utc(env: dict) -> None:
    editor = env["editor"]
    post = editor.post("/api/posts", json={
        "caption": "Hello", "targets": [{"social_account_id": "fb"}], "action": "schedule",
        "schedule": {"local_datetime": "2030-03-10T09:30:00", "timezone": "America/New_York"},
    }).json()
    # 10 March 2030 is after the US switch to daylight time: 09:30 EDT = 13:30 UTC.
    assert post["status"] == "scheduled"
    assert post["scheduled_at"] == "2030-03-10T13:30:00+00:00"
    assert post["timezone"] == "America/New_York"
    assert [t["status"] for t in post["targets"]] == ["queued"]


def test_scheduling_is_refused_for_bad_input(env: dict) -> None:
    editor = env["editor"]
    base = {"caption": "Hello", "targets": [{"social_account_id": "fb"}], "action": "schedule"}
    past = {"local_datetime": "2020-01-01T09:00:00", "timezone": "UTC"}
    assert editor.post("/api/posts", json={**base, "schedule": past}).status_code == 422
    assert editor.post("/api/posts", json={**base, "schedule": {**later(), "timezone": "Mars/Base"}}).status_code == 422
    assert editor.post("/api/posts", json={**base, "targets": []} | {"schedule": later()}).status_code == 422
    invalid = {**base, "targets": [{"social_account_id": "ig"}], "schedule": later()}
    response = editor.post("/api/posts", json=invalid)
    assert response.status_code == 422 and "Instagram posts need at least one photo" in response.json()["detail"]
    assert editor.get("/api/posts").json() == []  # nothing half-created


def test_bulk_scheduling_is_all_or_nothing(env: dict) -> None:
    editor = env["editor"]
    good = {"caption": "ok", "targets": [{"social_account_id": "fb"}], "action": "schedule", "schedule": later(2)}
    bad = {**good, "schedule": {"local_datetime": "2020-01-01T09:00:00", "timezone": "UTC"}}
    response = editor.post("/api/posts/bulk", json={"posts": [good, bad]})
    assert response.status_code == 422 and response.json()["detail"].startswith("Post 2:")
    assert editor.get("/api/posts").json() == []
    created = editor.post("/api/posts/bulk", json={"posts": [good, {**good, "schedule": later(3)}]})
    assert created.status_code == 201 and len(created.json()) == 2


def test_same_account_cannot_be_double_booked_at_the_same_minute(env: dict) -> None:
    editor = env["editor"]
    when = later()
    first = {"caption": "a", "targets": [{"social_account_id": "fb"}], "action": "schedule", "schedule": when}
    assert editor.post("/api/posts", json=first).status_code == 201
    assert editor.post("/api/posts", json=first).status_code == 409
    other_account = {**first, "targets": [{"social_account_id": "ig"}], "asset_ids": [upload(editor)]}
    assert editor.post("/api/posts", json=other_account).status_code == 201


def test_unschedule_and_reschedule(env: dict) -> None:
    editor = env["editor"]
    post = editor.post("/api/posts", json={"caption": "x", "targets": [{"social_account_id": "fb"}],
                                           "action": "schedule", "schedule": later(2)}).json()
    assert editor.post(f"/api/posts/{post['id']}/unschedule").json()["status"] == "draft"
    moved = editor.post(f"/api/posts/{post['id']}/schedule", json={"schedule": later(5)}).json()
    assert moved["status"] == "scheduled" and moved["scheduled_at"] > post["scheduled_at"]


# --- Client review -----------------------------------------------------------------------------

def test_client_review_workflow(env: dict) -> None:
    editor, client, other = env["editor"], env["client"], env["other_client"]
    photo = upload(editor)
    post = editor.post("/api/posts", json={
        "caption": "For approval", "asset_ids": [photo], "targets": [{"social_account_id": "fb"}],
        "action": "submit", "reviewer_user_id": env["client_id"], "schedule": later(),
    }).json()
    assert post["status"] == "in_review" and post["reviewer_name"] == "Client"
    hidden = editor.post("/api/posts", json={"caption": "Internal draft"}).json()

    # The client sees only what was sent to them, including its media.
    assert [p["id"] for p in client.get("/api/posts").json()] == [post["id"]]
    assert client.get(f"/api/posts/{hidden['id']}").status_code == 404
    assert client.get(f"/api/assets/{photo}/content").status_code == 200
    assert other.get("/api/posts").json() == []
    assert other.get(f"/api/assets/{photo}/content").status_code == 404
    # Clients only review: no editing, scheduling or library access.
    assert client.patch(f"/api/posts/{post['id']}", json={"caption": "x"}).status_code == 403
    assert client.post(f"/api/posts/{post['id']}/schedule", json={"schedule": later()}).status_code == 403
    assert other.post(f"/api/posts/{post['id']}/review", json={"decision": "approve"}).status_code == 404
    assert editor.post(f"/api/posts/{post['id']}/review", json={"decision": "approve"}).status_code == 403

    # Scheduling waits for approval.
    assert editor.post(f"/api/posts/{post['id']}/schedule", json={"schedule": later()}).status_code == 409
    assert client.post(f"/api/posts/{post['id']}/review", json={"decision": "request_changes"}).status_code == 422
    changes = client.post(f"/api/posts/{post['id']}/review",
                          json={"decision": "request_changes", "comment": "Use the logo version"}).json()
    assert changes["status"] == "changes_requested"
    client.post(f"/api/posts/{post['id']}/comments", json={"message": "Thanks!"})

    editor.patch(f"/api/posts/{post['id']}", json={"caption": "With logo", "asset_ids": [photo],
                                                    "targets": [{"social_account_id": "fb"}]})
    editor.post(f"/api/posts/{post['id']}/submit", json={"reviewer_user_id": env["client_id"], "message": "Updated"})
    approved = client.post(f"/api/posts/{post['id']}/review", json={"decision": "approve", "comment": "Great"}).json()
    assert approved["status"] == "approved"
    history = [(e["kind"], e["actor_name"], e["message"]) for e in approved["events"]]
    assert history == [
        ("created", "Editor", None), ("submitted", "Editor", None),
        ("changes_requested", "Client", "Use the logo version"), ("comment", "Client", "Thanks!"),
        ("edited", "Editor", None), ("submitted", "Editor", "Updated"), ("approved", "Client", "Great"),
    ]
    scheduled = editor.post(f"/api/posts/{post['id']}/schedule", json={"schedule": later()}).json()
    assert scheduled["status"] == "scheduled"


def test_editing_approved_content_needs_a_new_approval(env: dict) -> None:
    editor, client = env["editor"], env["client"]
    post = editor.post("/api/posts", json={"caption": "v1", "targets": [{"social_account_id": "fb"}],
                                           "action": "submit", "reviewer_user_id": env["client_id"]}).json()
    client.post(f"/api/posts/{post['id']}/review", json={"decision": "approve"})
    editor.post(f"/api/posts/{post['id']}/schedule", json={"schedule": later()})
    changed = editor.patch(f"/api/posts/{post['id']}", json={"caption": "v2 changed after approval",
                                                             "targets": [{"social_account_id": "fb"}]}).json()
    assert changed["status"] == "draft"
    assert changed["targets"][0]["status"] == "pending"
    assert "review again" in changed["events"][-1]["message"]


# --- Publishing --------------------------------------------------------------------------------

def test_publish_now_sends_each_platform_version(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = FakeMeta(monkeypatch)
    editor = env["editor"]
    photo = upload(editor, png(1080, 1080), "square.png", "image/png")
    post = editor.post("/api/posts", json={
        "caption": "Base caption", "asset_ids": [photo],
        "targets": [{"social_account_id": "fb"}, {"social_account_id": "ig", "caption_override": "IG caption"}],
    }).json()
    response = editor.post(f"/api/posts/{post['id']}/publish-now")
    assert response.status_code == 202
    published = editor.get(f"/api/posts/{post['id']}").json()  # the background task has run

    assert published["status"] == "published"
    sent = {call[0]: call for call in meta.calls}
    assert sent["facebook"][1:3] == ("meta-fb", "Base caption")
    assert sent["facebook"][3] == [("square.png", "image/png")]
    assert sent["instagram"][1:3] == ("meta-ig", "IG caption")
    # Instagram gets a signed, expiring JPEG link it can download.
    (kind, url), = sent["instagram"][3]
    assert kind == "image/jpeg" and url.startswith("https://api.example.com/api/media/")
    assert all(t["status"] == "published" and t["external_id"] and t["external_url"] for t in published["targets"])
    assert {e["kind"] for e in published["events"]} >= {"publish_requested", "published"}


def test_signed_media_links(env: dict) -> None:
    editor = env["editor"]
    photo = upload(editor, png(1080, 1080), "square.png", "image/png")
    with database.connect_database() as connection:
        storage = connection.execute("SELECT storage_name FROM assets WHERE id = ?", (photo,)).fetchone()["storage_name"]
    url = urlparse(media.signed_media_url(media.instagram_image(storage, "image/png")))
    anonymous = TestClient(main.app)
    fetched = anonymous.get(f"{url.path}?{url.query}")
    assert fetched.status_code == 200 and fetched.headers["content-type"] == "image/jpeg"
    assert fetched.content[:3] == b"\xff\xd8\xff"  # converted to JPEG
    forged = url.query.replace("signature=", "signature=0")
    assert anonymous.get(f"{url.path}?{forged}").status_code == 403
    expired = urlparse(media.signed_media_url(storage, now=0))
    assert anonymous.get(f"{expired.path}?{expired.query}").status_code == 403


def test_scheduled_posts_publish_when_due(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = FakeMeta(monkeypatch)
    editor = env["editor"]
    post = editor.post("/api/posts", json={"caption": "Later", "targets": [{"social_account_id": "fb"}],
                                           "action": "schedule", "schedule": later()}).json()
    run_due()
    assert meta.calls == []  # not due yet
    with database.connect_database() as connection:
        connection.execute("UPDATE posts SET scheduled_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (post["id"],))
    run_due()
    run_due()  # a second pass must not publish again
    assert len(meta.calls) == 1
    assert editor.get(f"/api/posts/{post['id']}").json()["status"] == "published"


def _due(editor: TestClient, accounts: list[str]) -> str:
    post = editor.post("/api/posts", json={"caption": "Hi", "asset_ids": [upload(editor)],
                                           "targets": [{"social_account_id": a} for a in accounts],
                                           "action": "schedule", "schedule": later()}).json()
    with database.connect_database() as connection:
        connection.execute("UPDATE posts SET scheduled_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (post["id"],))
    return post["id"]


def test_temporary_errors_are_retried_with_backoff(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = FakeMeta(monkeypatch)
    meta.failures = [meta_graph.GraphError("Please retry", status=500, code=2, transient=True)]
    post_id = _due(env["editor"], ["fb"])
    run_due()
    target = env["editor"].get(f"/api/posts/{post_id}").json()["targets"][0]
    assert target["status"] == "queued" and target["attempts"] == 1 and target["next_attempt_at"]
    run_due()
    assert meta.calls == []  # waits for the backoff
    with database.connect_database() as connection:
        connection.execute("UPDATE post_targets SET next_attempt_at = '2020-01-01T00:00:00+00:00'")
    run_due()
    post = env["editor"].get(f"/api/posts/{post_id}").json()
    assert post["status"] == "published" and post["targets"][0]["attempts"] == 2


def test_partial_failure_and_manual_retry(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = FakeMeta(monkeypatch)
    meta.failures = [meta_graph.GraphError("(#100) Invalid parameter", status=400, code=100)]
    editor = env["editor"]
    post_id = _due(editor, ["fb", "ig"])
    run_due()
    post = editor.get(f"/api/posts/{post_id}").json()
    assert post["status"] == "partially_published"
    failed = next(t for t in post["targets"] if t["status"] == "failed")
    assert "Invalid parameter" in failed["last_error"]

    retried = editor.post(f"/api/posts/{post_id}/retry")
    assert retried.status_code == 202
    post = editor.get(f"/api/posts/{post_id}").json()
    assert post["status"] == "published" and len(meta.calls) == 2
    # Published posts are a record: no deleting or editing.
    assert editor.delete(f"/api/posts/{post_id}").status_code == 409
    assert editor.patch(f"/api/posts/{post_id}", json={"caption": "x"}).status_code == 409


def test_unconfirmed_network_errors_are_not_retried_automatically(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = FakeMeta(monkeypatch)
    meta.failures = [meta_graph.GraphError("Meta did not respond in time.", transient=True)]
    post_id = _due(env["editor"], ["fb"])
    run_due()
    target = env["editor"].get(f"/api/posts/{post_id}").json()["targets"][0]
    assert target["status"] == "failed"
    assert "Check the account before retrying" in target["last_error"]


def test_expired_tokens_flag_the_account(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = FakeMeta(monkeypatch)
    meta.failures = [meta_graph.GraphError("Session expired. Reconnect.", status=400, code=190)]
    editor = env["editor"]
    post_id = _due(editor, ["fb"])
    run_due()
    assert editor.get(f"/api/posts/{post_id}").json()["targets"][0]["status"] == "failed"
    account = next(a for a in env["owner"].get("/api/social/providers").json()[0]["accounts"] if a["id"] == "fb")
    assert account["status"] == "needs_reconnect"
    # New posts to that account are blocked until it is reconnected.
    blocked = editor.post("/api/posts", json={"caption": "x", "targets": [{"social_account_id": "fb"}],
                                              "action": "schedule", "schedule": later()})
    assert blocked.status_code == 422 and "reconnected" in blocked.json()["detail"]


def test_interrupted_publishing_is_never_resent(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = FakeMeta(monkeypatch)
    post_id = _due(env["editor"], ["fb"])
    with database.connect_database() as connection:
        connection.execute("UPDATE post_targets SET status = 'publishing', claimed_at = '2020-01-01T00:00:00+00:00'")
        connection.execute("UPDATE posts SET status = 'publishing'")
    assert publisher.recover_interrupted() == 1
    run_due()
    assert meta.calls == []
    target = env["editor"].get(f"/api/posts/{post_id}").json()["targets"][0]
    assert target["status"] == "failed" and "interrupted" in target["last_error"]


def test_disconnecting_an_account_keeps_the_post_and_explains(env: dict) -> None:
    editor = env["editor"]
    post = editor.post("/api/posts", json={"caption": "x", "targets": [{"social_account_id": "fb"}]}).json()
    assert env["owner"].delete("/api/social/accounts/fb").status_code == 204
    after = editor.get(f"/api/posts/{post['id']}").json()
    assert after["targets"][0]["account_name"] == "Agency Page"
    assert "disconnected" in after["issues"][0]["message"]

