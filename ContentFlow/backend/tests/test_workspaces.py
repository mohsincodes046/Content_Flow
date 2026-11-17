"""Workspace isolation, roles and membership lifecycle (docs/workspace-tenancy.md)."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from media_samples import jpeg

from app import ai as ai_service, config, database, main, security

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., TestClient]]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")
    monkeypatch.setenv("CONTENT_FLOW_REGISTER_PER_HOUR_LIMIT", "100")
    monkeypatch.setenv("CONTENT_FLOW_FRONTEND_URL", "https://app.example.com")
    clients: list[TestClient] = []

    def factory(email: str, workspace: str | None = "Workspace", invitation_token: str | None = None) -> TestClient:
        client = TestClient(main.app)
        client.__enter__()
        clients.append(client)
        body: dict[str, object] = {"full_name": email.split("@")[0].title(), "email": email, "password": PASSWORD}
        if workspace:
            body["workspace_name"] = workspace
        if invitation_token:
            body["invitation_token"] = invitation_token
        response = client.post("/api/auth/register", json=body)
        assert response.status_code == 201, response.text
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


def invite(client: TestClient, email: str, role: str) -> str:
    response = client.post("/api/workspaces/current/invitations", json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return parse_qs(urlparse(response.json()["invite_url"]).query)["token"][0]


def team(make_client: Callable[..., TestClient]) -> dict[str, TestClient]:
    """An agency workspace with an owner, admin, editor and client, plus an outsider."""
    owner = make_client("owner@example.com", "Agency")
    admin = make_client("admin@example.com", workspace=None, invitation_token=invite(owner, "admin@example.com", "admin"))
    editor = make_client("editor@example.com", workspace=None, invitation_token=invite(owner, "editor@example.com", "editor"))
    client = make_client("client@example.com", workspace=None, invitation_token=invite(owner, "client@example.com", "client"))
    outsider = make_client("outsider@example.com", "Other Company")
    return {"owner": owner, "admin": admin, "editor": editor, "client": client, "outsider": outsider}


def me(client: TestClient) -> dict:
    return client.get("/api/auth/me").json()


def connect_page(client: TestClient, page_id: str = "page-1") -> str:
    """Insert a connected Facebook Page into the client's active workspace (OAuth itself is tested elsewhere)."""
    session = me(client)
    record_id = f"acct-{page_id}-{session['workspace_id'][:8]}"
    key = Fernet.generate_key()
    with database.connect_database() as connection:
        connection.execute(
            "INSERT INTO social_accounts (id, user_id, workspace_id, provider, platform, account_id, account_name, "
            "account_type, encrypted_tokens, expires_at, connected_at, updated_at) "
            "VALUES (?, ?, ?, 'meta', 'facebook', ?, 'Page', 'page', ?, NULL, ?, ?)",
            (record_id, session["id"], session["workspace_id"], page_id,
             Fernet(key).encrypt(b'{"access_token": "t"}').decode(), database.utc_now(), database.utc_now()),
        )
    return record_id


def future_post(**extra: object) -> dict:
    """A draft planned for two days from now (no accounts needed)."""
    when = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=10, minute=0, tzinfo=None)
    return {"title": "Post", "caption": "Hello", "planned_platforms": ["instagram"],
            "schedule": {"local_datetime": when.isoformat(), "timezone": "UTC"}, **extra}


# --- Registration and invitations --------------------------------------------------------------

def test_invited_user_joins_the_workspace_without_creating_their_own(make_client: Callable[..., TestClient]) -> None:
    people = team(make_client)
    editor = me(people["editor"])
    assert editor["workspace_name"] == "Agency"
    assert editor["role"] == "editor"
    assert [w["name"] for w in editor["workspaces"]] == ["Agency"]


def test_registration_without_workspace_or_invitation_is_rejected(make_client: Callable[..., TestClient]) -> None:
    owner = make_client("owner@example.com", "Agency")
    response = owner.post("/api/auth/register", json={"full_name": "X", "email": "x@example.com", "password": PASSWORD})
    assert response.status_code == 422


def test_invitation_rules(make_client: Callable[..., TestClient]) -> None:
    owner = make_client("owner@example.com", "Agency")
    stranger = make_client("stranger@example.com", "Stranger Co")
    token = invite(owner, "friend@example.com", "editor")

    assert owner.post("/api/workspaces/current/invitations",
                      json={"email": "friend@example.com", "role": "client"}).status_code == 409
    assert owner.post("/api/workspaces/current/invitations",
                      json={"email": "owner@example.com", "role": "editor"}).status_code == 409
    assert stranger.get(f"/api/invitations/{token}").json() == {
        "workspace_name": "Agency", "email": "friend@example.com", "role": "editor"}
    # Bound to the invited email.
    assert stranger.post("/api/invitations/accept", json={"token": token}).status_code == 403

    friend = make_client("friend@example.com", workspace=None, invitation_token=token)
    assert me(friend)["role"] == "editor"
    # Single use.
    assert friend.post("/api/invitations/accept", json={"token": token}).status_code == 404

    expired = invite(owner, "late@example.com", "client")
    with database.connect_database() as connection:
        connection.execute("UPDATE invitations SET expires_at = '2000-01-01T00:00:00+00:00' WHERE email = 'late@example.com'")
    assert owner.get(f"/api/invitations/{expired}").status_code == 404

    revoked = invite(owner, "gone@example.com", "client")
    invitation_id = next(i["id"] for i in owner.get("/api/workspaces/current/invitations").json()
                         if i["email"] == "gone@example.com")
    assert owner.delete(f"/api/workspaces/current/invitations/{invitation_id}").status_code == 204
    assert owner.get(f"/api/invitations/{revoked}").status_code == 404


def test_existing_user_accepts_an_invitation_and_gains_a_second_workspace(make_client: Callable[..., TestClient]) -> None:
    agency = make_client("agency@example.com", "Agency")
    brand = make_client("brand@example.com", "Brand")
    token = invite(brand, "agency@example.com", "admin")

    accepted = agency.post("/api/invitations/accept", json={"token": token})
    assert accepted.status_code == 200
    assert accepted.json()["workspace_name"] == "Brand"
    assert sorted(w["name"] for w in accepted.json()["workspaces"]) == ["Agency", "Brand"]


# --- Isolation ---------------------------------------------------------------------------------

def test_another_workspace_cannot_see_or_touch_any_resource(make_client: Callable[..., TestClient]) -> None:
    a = make_client("a@example.com", "A")
    b = make_client("b@example.com", "B")

    asset = a.post("/api/assets", files={"file": ("x.jpg", jpeg(), "image/jpeg")}).json()
    submission = a.post("/api/submissions", json={
        "campaign": "", "audience": "All", "instructions": "Do it", "language": "English",
        "platforms": ["instagram"], "asset_ids": [],
    }).json()
    post = a.post("/api/posts", json=future_post()).json()
    page = connect_page(a)

    assert b.get("/api/submissions").json() == []
    assert b.get(f"/api/submissions/{submission['id']}").status_code == 404
    assert b.get("/api/posts").json() == []
    assert b.get(f"/api/posts/{post['id']}").status_code == 404
    assert b.patch(f"/api/posts/{post['id']}", json={"caption": "hijack"}).status_code == 404
    assert b.delete(f"/api/posts/{post['id']}").status_code == 404
    assert b.post(f"/api/posts/{post['id']}/review", json={"decision": "approve"}).status_code == 404
    assert b.get(f"/api/assets/{asset['id']}/content").status_code == 404
    assert b.delete(f"/api/assets/{asset['id']}").status_code == 404
    assert b.delete(f"/api/social/accounts/{page}").status_code == 404
    meta = next(p for p in b.get("/api/social/providers").json() if p["provider"] == "meta")
    assert meta["accounts"] == []
    # Cannot use A's asset or A's Facebook Page in B's content.
    assert b.post("/api/submissions", json={
        "campaign": "", "audience": "All", "instructions": "Do it", "language": "English",
        "platforms": ["instagram"], "asset_ids": [asset["id"]],
    }).status_code == 400
    assert b.post("/api/posts", json=future_post(asset_ids=[asset["id"]])).status_code == 400
    assert b.post("/api/posts", json=future_post(targets=[{"social_account_id": page}])).status_code == 400

    # And A still has everything.
    assert len(a.get("/api/posts").json()) == 1
    assert a.get(f"/api/submissions/{submission['id']}").status_code == 200


def test_switching_to_a_workspace_you_do_not_belong_to_is_not_found(make_client: Callable[..., TestClient]) -> None:
    a = make_client("a@example.com", "A")
    b = make_client("b@example.com", "B")
    assert a.post(f"/api/workspaces/{me(b)['workspace_id']}/switch").status_code == 404
    assert me(a)["workspace_name"] == "A"


def test_workspace_switching_changes_what_you_see(make_client: Callable[..., TestClient]) -> None:
    person = make_client("person@example.com", "First")
    person.post("/api/posts", json=future_post())
    first_id = me(person)["workspace_id"]
    created = person.post("/api/workspaces", json={"name": "Second"})
    assert created.status_code == 201 and created.json()["workspace_name"] == "Second"
    assert person.get("/api/posts").json() == []
    person.post(f"/api/workspaces/{first_id}/switch")
    assert len(person.get("/api/posts").json()) == 1


def test_every_private_route_requires_a_signed_in_user() -> None:
    """Route guard: a new endpoint cannot accidentally skip authentication."""
    public = {
        ("GET", "/api/health"), ("POST", "/api/auth/register"), ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"), ("GET", "/api/social/oauth/{provider}/callback"),
        ("GET", "/api/social/webhook"), ("POST", "/api/social/webhook"), ("GET", "/api/invitations/{token}"),
        # Meta calls these directly; they are authenticated by Meta's signed_request instead.
        ("POST", "/api/social/meta/deauthorize"), ("POST", "/api/social/meta/data-deletion"),
        ("GET", "/api/social/meta/data-deletion/{code}"),
        # Meta downloads media through signed, expiring links.
        ("GET", "/api/media/{storage_name}"),
    }

    def depends_on_user(dependant) -> bool:  # type: ignore[no-untyped-def]
        return any(d.call is security.get_current_user or depends_on_user(d) for d in dependant.dependencies)

    unguarded = [
        (method, route.path)
        for route in main.app.routes if isinstance(route, APIRoute)
        for method in route.methods
        if (method, route.path) not in public and not depends_on_user(route.dependant)
    ]
    assert unguarded == []


# --- Roles -------------------------------------------------------------------------------------

def test_role_permissions(make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch) -> None:
    people = team(make_client)
    monkeypatch.setenv("CONTENT_FLOW_AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    async def fake_provider(*args: object, **kwargs: object) -> str:
        return '{"posts":[{"platform":"instagram","caption":"Hi.","hashtags":[]}]}'

    monkeypatch.setattr(ai_service, "call_caption_provider", fake_provider)
    caption = {"topic": "t", "audience": "a", "platforms": ["instagram"]}

    for hour, role in enumerate(("owner", "admin", "editor"), start=9):
        c = people[role]
        assert c.post("/api/posts", json=future_post(title=role)).status_code == 201, role
        assert c.post("/api/assets", files={"file": ("x.jpg", jpeg(), "image/jpeg")}).status_code == 201, role
        assert c.post("/api/ai/captions", json=caption).status_code == 200, role
        assert c.get("/api/workspaces/current/members").status_code == 200, role

    client = people["client"]
    for method, path, kwargs in [
        ("post", "/api/posts", {"json": future_post()}),
        ("get", "/api/assets", {}),
        ("post", "/api/assets", {"files": {"file": ("x.jpg", jpeg(), "image/jpeg")}}),
        ("post", "/api/ai/captions", {"json": caption}),
        ("get", "/api/submissions", {}),
        ("get", "/api/social/providers", {}),
        ("get", "/api/workspaces/current/members", {}),
        ("post", "/api/workspaces/current/invitations", {"json": {"email": "x@example.com", "role": "client"}}),
    ]:
        assert getattr(client, method)(path, **kwargs).status_code == 403, (method, path)

    editor = people["editor"]
    assert editor.post("/api/workspaces/current/invitations",
                       json={"email": "x@example.com", "role": "editor"}).status_code == 403
    assert editor.get("/api/social/oauth/meta/start", follow_redirects=False).status_code == 403
    assert editor.patch("/api/workspaces/current", json={"name": "Renamed"}).status_code == 403

    admin = people["admin"]
    assert admin.patch("/api/workspaces/current", json={"name": "Agency Ltd"}).status_code == 200
    assert admin.post("/api/workspaces/current/invitations",
                      json={"email": "new@example.com", "role": "editor"}).status_code == 201


def test_the_owner_cannot_be_demoted_removed_or_duplicated(make_client: Callable[..., TestClient]) -> None:
    people = team(make_client)
    owner_id, admin_id = me(people["owner"])["id"], me(people["admin"])["id"]

    assert people["admin"].patch(f"/api/workspaces/current/members/{owner_id}", json={"role": "editor"}).status_code == 409
    assert people["admin"].delete(f"/api/workspaces/current/members/{owner_id}").status_code == 409
    assert people["owner"].delete(f"/api/workspaces/current/members/{owner_id}").status_code == 409
    # "owner" is not an assignable role.
    assert people["owner"].patch(f"/api/workspaces/current/members/{admin_id}", json={"role": "owner"}).status_code == 422
    assert people["admin"].post("/api/workspaces/current/transfer-ownership",
                                json={"user_id": admin_id}).status_code == 403

    transferred = people["owner"].post("/api/workspaces/current/transfer-ownership", json={"user_id": admin_id})
    assert transferred.status_code == 200
    roles = {m["email"]: m["role"] for m in transferred.json()}
    assert roles["admin@example.com"] == "owner" and roles["owner@example.com"] == "admin"
    assert list(roles.values()).count("owner") == 1


def test_removed_member_loses_access_immediately(make_client: Callable[..., TestClient]) -> None:
    people = team(make_client)
    editor = people["editor"]
    assert editor.get("/api/posts").status_code == 200

    editor_id = me(editor)["id"]
    assert people["admin"].delete(f"/api/workspaces/current/members/{editor_id}").status_code == 204

    # Same session cookie, next request: no workspace left.
    assert editor.get("/api/posts").status_code == 409
    assert me(editor)["workspaces"] == []


def test_members_can_leave_but_the_owner_cannot(make_client: Callable[..., TestClient]) -> None:
    people = team(make_client)
    client_id = me(people["client"])["id"]
    owner_id = me(people["owner"])["id"]
    assert people["client"].delete(f"/api/workspaces/current/members/{client_id}").status_code == 204
    assert people["owner"].delete(f"/api/workspaces/current/members/{owner_id}").status_code == 409


def test_ai_quota_is_shared_by_the_workspace(make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch) -> None:
    people = team(make_client)
    monkeypatch.setenv("CONTENT_FLOW_AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("CONTENT_FLOW_AI_DAILY_LIMIT", "2")

    async def fake_provider(*args: object, **kwargs: object) -> str:
        return '{"posts":[{"platform":"instagram","caption":"Hi.","hashtags":[]}]}'

    monkeypatch.setattr(ai_service, "call_caption_provider", fake_provider)
    caption = {"topic": "t", "audience": "a", "platforms": ["instagram"]}
    assert people["owner"].post("/api/ai/captions", json=caption).status_code == 200
    assert people["editor"].post("/api/ai/captions", json=caption).status_code == 200
    assert people["admin"].post("/api/ai/captions", json=caption).status_code == 429
    # A different workspace has its own quota.
    assert people["outsider"].post("/api/ai/captions", json=caption).status_code == 200


def test_publisher_only_uses_the_posts_own_workspace_token(
    make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app import meta_graph, publisher

    a = make_client("a@example.com", "A")
    b = make_client("b@example.com", "B")
    b_page = connect_page(b, "b-page")
    post = a.post("/api/posts", json=future_post(caption="Hi")).json()
    # Simulate a corrupted row: a target in A pointing at B's Page, due now.
    with database.connect_database() as connection:
        connection.execute(
            "INSERT INTO post_targets (id, post_id, social_account_id, platform, account_name, status) "
            "VALUES ('t1', ?, ?, 'facebook', 'Page', 'queued')", (post["id"], b_page))
        connection.execute("UPDATE posts SET status = 'scheduled', scheduled_at = '2020-01-01T00:00:00+00:00' "
                           "WHERE id = ?", (post["id"],))

    async def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("Meta must not be called with another workspace's token")

    monkeypatch.setattr(meta_graph, "request", never)
    asyncio.run(publisher.publish_due())
    target = a.get(f"/api/posts/{post['id']}").json()["targets"][0]
    assert target["status"] == "failed"
    assert "disconnected" in target["last_error"]
