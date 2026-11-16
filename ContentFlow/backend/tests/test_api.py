import asyncio
import json
import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from urllib.parse import parse_qs, urlparse

from app import ai as ai_service, config, database, main, meta_graph, publisher, security, social_oauth


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")
    with TestClient(main.app) as test_client:
        register_response = test_client.post(
            "/api/auth/register",
            json={
                "full_name": "Test User",
                "workspace_name": "Test Workspace",
                "email": "test@example.com",
                "password": "correct-horse-battery",
            },
        )
        assert register_response.status_code == 201
        yield test_client


def test_protected_content_api_requires_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "unauthenticated-data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")

    with TestClient(main.app) as unauthenticated_client:
        response = unauthenticated_client.get("/api/submissions")
        scheduled_posts = unauthenticated_client.get("/api/scheduled-posts")

    assert response.status_code == 401
    assert scheduled_posts.status_code == 401


def test_registration_creates_workspace_and_http_only_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "registration-data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")

    with TestClient(main.app) as registration_client:
        registered = registration_client.post(
            "/api/auth/register",
            json={
                "full_name": "Institute Admin",
                "workspace_name": "Content Flow Institute",
                "email": "ADMIN@example.com",
                "password": "a-strong-password-123",
            },
        )
        session = registration_client.get("/api/auth/me")

    assert registered.status_code == 201
    assert registered.json()["email"] == "admin@example.com"
    assert registered.json()["workspace_name"] == "Content Flow Institute"
    assert "content_flow_session" in registered.cookies
    assert "httponly" in registered.headers["set-cookie"].lower()
    assert session.status_code == 200
    assert session.json()["full_name"] == "Institute Admin"


def test_registration_rejects_weak_password_and_duplicate_email(client: TestClient) -> None:
    weak_password = client.post(
        "/api/auth/register",
        json={
            "full_name": "Another User",
            "workspace_name": "Another Workspace",
            "email": "another@example.com",
            "password": "short7!",
        },
    )
    duplicate_email = client.post(
        "/api/auth/register",
        json={
            "full_name": "Duplicate User",
            "workspace_name": "Duplicate Workspace",
            "email": "TEST@example.com",
            "password": "a-strong-password-456",
        },
    )

    assert weak_password.status_code == 422
    assert duplicate_email.status_code == 409


def test_registration_accepts_eight_character_password(client: TestClient) -> None:
    registered = client.post(
        "/api/auth/register",
        json={
            "full_name": "Short Password User",
            "workspace_name": "Short Password Workspace",
            "email": "eight@example.com",
            "password": "passw0rd",
        },
    )
    login = client.post(
        "/api/auth/login",
        json={"email": "eight@example.com", "password": "passw0rd"},
    )

    assert registered.status_code == 201
    assert login.status_code == 200


def test_login_and_logout_revoke_session(client: TestClient) -> None:
    login_response = client.post(
        "/api/auth/login",
        json={"email": "TEST@example.com", "password": "correct-horse-battery"},
    )
    authenticated = client.get("/api/auth/me")
    logout_response = client.post("/api/auth/logout")
    unauthenticated = client.get("/api/auth/me")

    assert login_response.status_code == 200
    assert authenticated.status_code == 200
    assert logout_response.status_code == 204
    assert unauthenticated.status_code == 401


def test_change_password_rejects_incorrect_current_password(client: TestClient) -> None:
    response = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "wrong-current-password",
            "new_password": "new-pass-1234",
        },
    )
    old_password_login = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Your current Content-Flow password is incorrect."
    assert old_password_login.status_code == 200


def test_change_password_updates_password_and_revokes_other_sessions(
    client: TestClient,
) -> None:
    with TestClient(main.app) as other_session:
        other_login = other_session.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "correct-horse-battery"},
        )
        changed = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "correct-horse-battery",
                "new_password": "new-pass-1234",
            },
        )
        current_session = client.get("/api/auth/me")
        revoked_session = other_session.get("/api/auth/me")
        old_password_login = other_session.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "correct-horse-battery"},
        )
        new_password_login = other_session.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "new-pass-1234"},
        )

    assert other_login.status_code == 200
    assert changed.status_code == 204
    assert current_session.status_code == 200
    assert revoked_session.status_code == 401
    assert old_password_login.status_code == 401
    assert new_password_login.status_code == 200


def test_change_password_rejects_same_or_short_new_password(client: TestClient) -> None:
    same_password = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "correct-horse-battery",
            "new_password": "correct-horse-battery",
        },
    )
    short_password = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "correct-horse-battery",
            "new_password": "short7!",
        },
    )

    assert same_password.status_code == 400
    assert short_password.status_code == 422


def test_login_uses_generic_error_for_unknown_email_and_wrong_password(client: TestClient) -> None:
    unknown_email = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "correct-horse-battery"},
    )
    wrong_password = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "wrong-password-here"},
    )

    assert unknown_email.status_code == 401
    assert unknown_email.json() == wrong_password.json()


def test_user_cannot_read_another_users_submissions(client: TestClient) -> None:
    created = client.post(
        "/api/submissions",
        json={
            "campaign": "Private campaign",
            "audience": "Students",
            "instructions": "Keep this private.",
            "language": "English",
            "platforms": ["instagram"],
        },
    )
    client.post("/api/auth/logout")
    other_user = client.post(
        "/api/auth/register",
        json={
            "full_name": "Other User",
            "workspace_name": "Other Workspace",
            "email": "other@example.com",
            "password": "another-strong-password",
        },
    )

    assert other_user.status_code == 201
    assert client.get("/api/submissions").json() == []
    assert client.get(f"/api/submissions/{created.json()['id']}").status_code == 404


def test_user_cannot_attach_another_users_asset(client: TestClient) -> None:
    uploaded = client.post(
        "/api/assets",
        files={"file": ("private.png", b"private image", "image/png")},
    )
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={
            "full_name": "Other User",
            "workspace_name": "Other Workspace",
            "email": "other@example.com",
            "password": "another-strong-password",
        },
    )

    response = client.post(
        "/api/submissions",
        json={
            "campaign": "Another user's campaign",
            "audience": "Students",
            "instructions": "Use only the supplied information.",
            "language": "English",
            "platforms": ["instagram"],
            "asset_ids": [uploaded.json()["id"]],
        },
    )

    assert uploaded.status_code == 201
    assert response.status_code == 400


def test_health_check(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_list_submission(client: TestClient) -> None:
    payload = {
        "campaign": "AI course launch",
        "audience": "University students",
        "instructions": "Promote admissions. Do not invent dates or fees.",
        "language": "English",
        "platforms": ["instagram", "linkedin"],
    }

    created = client.post("/api/submissions", json=payload)
    listed = client.get("/api/submissions")

    assert created.status_code == 201
    assert created.json()["campaign"] == payload["campaign"]
    assert created.json()["status"] == "submitted"
    assert created.json()["assets"] == []
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == created.json()["id"]

def test_caption_generation_requires_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "caption-unauthenticated-data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")

    with TestClient(main.app) as unauthenticated_client:
        response = unauthenticated_client.post(
            "/api/ai/captions",
            json={"topic": "A new course", "audience": "Students", "platforms": ["instagram"]},
        )

    assert response.status_code == 401


def test_social_provider_list_requires_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "social-unauthenticated-data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")

    with TestClient(main.app) as unauthenticated_client:
        response = unauthenticated_client.get("/api/social/providers")
        start = unauthenticated_client.get("/api/social/oauth/meta/start", follow_redirects=False)

    assert response.status_code == 401
    assert start.status_code == 401


def test_meta_oauth_start_requires_app_credentials(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("META_APP_ID", raising=False)
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    response = client.get("/api/social/oauth/meta/start")

    assert response.status_code == 503
    assert response.json()["detail"] == "Configure META_APP_ID and META_APP_SECRET on the backend."


def test_meta_oauth_start_requires_https_callback_url(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_APP_ID", "test-meta-app")
    monkeypatch.setenv("META_APP_SECRET", "test-meta-secret")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("CONTENT_FLOW_API_PUBLIC_URL", "http://127.0.0.1:8000")

    insecure = client.get("/api/social/oauth/meta/start", follow_redirects=False)
    monkeypatch.setenv("CONTENT_FLOW_API_PUBLIC_URL", "https://contentflow-api.example.com")
    secure = client.get("/api/social/oauth/meta/start", follow_redirects=False)

    assert insecure.status_code == 503
    assert "requires an HTTPS API callback" in insecure.json()["detail"]
    assert secure.status_code == 302
    assert "redirect_uri=https%3A%2F%2Fcontentflow-api.example.com" in secure.headers["location"]
    authorization_params = parse_qs(urlparse(secure.headers["location"]).query)
    assert authorization_params["auth_type"] == ["rerequest"]
    # Exactly the permissions the product uses (publishing and analytics); any change
    # here affects Meta App Review and should be deliberate.
    assert sorted(authorization_params["scope"][0].split(",")) == sorted([
        "pages_show_list", "business_management", "pages_read_engagement", "read_insights",
        "pages_manage_posts", "instagram_basic", "instagram_content_publish", "instagram_manage_insights",
    ])


def test_backend_environment_loads_env_file_without_overriding_process_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "META_APP_ID=file-app-id\nMETA_APP_SECRET=file-app-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("META_APP_ID", "process-app-id")
    monkeypatch.delenv("META_APP_SECRET", raising=False)

    config.load_backend_environment(env_file)

    assert os.environ["META_APP_ID"] == "process-app-id"
    assert os.environ["META_APP_SECRET"] == "file-app-secret"


def test_meta_provider_status_requires_app_credentials_and_encryption_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_APP_ID", "test-meta-app")
    monkeypatch.setenv("META_APP_SECRET", "test-meta-secret")
    monkeypatch.delenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", raising=False)

    without_encryption = client.get("/api/social/providers")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    configured = client.get("/api/social/providers")

    assert without_encryption.status_code == 200
    assert len(without_encryption.json()) == 1
    assert without_encryption.json()[0]["provider"] == "meta"
    assert without_encryption.json()[0]["configured"] is False
    assert configured.json()[0]["configured"] is True
    unsupported = client.get("/api/social/oauth/tiktok/start")
    assert unsupported.status_code == 404


def test_meta_oauth_lets_the_user_choose_accounts_and_stores_tokens_encrypted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encryption_key = Fernet.generate_key()
    monkeypatch.setenv("META_APP_ID", "test-meta-app")
    monkeypatch.setenv("META_APP_SECRET", "test-meta-secret")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", encryption_key.decode("ascii"))
    monkeypatch.setenv("CONTENT_FLOW_API_PUBLIC_URL", "https://contentflow-api.example.com")
    monkeypatch.setenv("CONTENT_FLOW_FRONTEND_URL", "https://contentflow-web.example.com")

    async def fake_exchange(provider: str, settings: dict[str, str], code: str, redirect_uri: str) -> dict[str, object]:
        assert provider == "meta"
        assert code == "meta-auth-code"
        assert redirect_uri == "https://contentflow-api.example.com/api/social/oauth/meta/callback"
        return {"access_token": "user-access-token", "expires_at": "2026-10-15T00:00:00+00:00"}

    page_tokens = {"access_token": "page-access-token", "refresh_token": None, "expires_at": None}

    async def fake_accounts(provider: str, token_data: dict[str, object]) -> dict[str, object]:
        return {"external_user_id": "meta-user-1", "external_user_name": "Mo", "accounts": [
            {"platform": "facebook", "account_id": "page-42", "account_name": "ContentFlow Page", "account_type": "page",
             "profile_picture_url": "https://cdn.example.com/p.jpg", "parent_account_id": None,
             "details": {"can_publish": True}, "tokens": page_tokens},
            {"platform": "facebook", "account_id": "page-99", "account_name": "Other Page", "account_type": "page",
             "parent_account_id": None, "details": {"can_publish": True}, "tokens": page_tokens},
            {"platform": "instagram", "account_id": "instagram-77", "account_name": "contentflow.official",
             "account_type": "professional", "parent_account_id": "page-42",
             "details": {"followers_count": 1200, "can_publish": True, "linked_page_name": "ContentFlow Page"},
             "tokens": page_tokens},
        ]}

    monkeypatch.setattr(social_oauth, "exchange_authorization_code", fake_exchange)
    monkeypatch.setattr(social_oauth, "retrieve_connected_accounts", fake_accounts)

    start = client.get("/api/social/oauth/meta/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(
        "/api/social/oauth/meta/callback",
        params={"state": state, "code": "meta-auth-code"},
        follow_redirects=False,
    )
    assert start.status_code == 302
    assert callback.status_code == 303
    location = urlparse(callback.headers["location"])
    assert location.path == "/accounts" and parse_qs(location.query)["social"] == ["select"]
    connection_id = parse_qs(location.query)["connection"][0]

    # Nothing is saved until the user chooses.
    meta = next(provider for provider in client.get("/api/social/providers").json() if provider["provider"] == "meta")
    assert meta["accounts"] == []
    pending = client.get(f"/api/social/connections/{connection_id}").json()
    assert pending["signed_in_as"] == "Mo"
    assert [c["key"] for c in pending["candidates"]] == ["facebook:page-42", "facebook:page-99", "instagram:instagram-77"]
    assert "page-access-token" not in json.dumps(pending)

    selected = client.post(f"/api/social/connections/{connection_id}/select",
                           json={"keys": ["instagram:instagram-77", "facebook:page-42"]})
    assert selected.status_code == 200
    by_platform = {a["platform"]: a for a in selected.json()}
    assert set(by_platform) == {"facebook", "instagram"}  # page-99 was not chosen
    assert by_platform["instagram"]["parent_account_id"] == by_platform["facebook"]["id"]
    assert by_platform["instagram"]["followers_count"] == 1200
    assert by_platform["facebook"]["status"] == "active"
    assert all("access_token" not in account for account in selected.json())
    # The pending sign-in is single use.
    assert client.get(f"/api/social/connections/{connection_id}").status_code == 404

    with database.connect_database() as connection:
        stored = connection.execute("SELECT encrypted_tokens, external_user_id FROM social_accounts").fetchall()
    assert all(json.loads(Fernet(encryption_key).decrypt(r["encrypted_tokens"].encode()))["access_token"]
               == "page-access-token" for r in stored)
    assert {r["external_user_id"] for r in stored} == {"meta-user-1"}

    replay = client.get(
        "/api/social/oauth/meta/callback",
        params={"state": state, "code": "meta-auth-code"},
        follow_redirects=False,
    )
    assert replay.headers["location"].endswith("/accounts?social=invalid_state")

    with TestClient(main.app) as another_workspace:
        another_workspace.post("/api/auth/register", json={
            "full_name": "Different User", "workspace_name": "Different Workspace",
            "email": "different@example.com", "password": "another-safe-password",
        })
        assert another_workspace.delete(f"/api/social/accounts/{by_platform['instagram']['id']}").status_code == 404
        assert another_workspace.get(f"/api/social/connections/{connection_id}").status_code == 404

    assert client.delete(f"/api/social/accounts/{by_platform['facebook']['id']}").status_code == 204
    remaining = client.get("/api/social/providers").json()[0]["accounts"]
    assert [account["platform"] for account in remaining] == ["instagram"]
    assert remaining[0]["parent_account_id"] is None


def test_meta_exchange_and_discovery_follow_pagination_and_page_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {"client_id_value": "test-meta-app", "client_secret_value": "test-meta-secret"}
    seen_pages: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        path = request.url.path
        assert path.startswith("/v26.0/")
        if params.get("code") == "meta-auth-code":
            return httpx.Response(200, json={"access_token": "short-user-token", "expires_in": 3600})
        if params.get("grant_type") == "fb_exchange_token":
            assert params["fb_exchange_token"] == "short-user-token"
            return httpx.Response(200, json={"access_token": "long-user-token", "expires_in": 5184000})
        if path.endswith("/me"):
            return httpx.Response(200, json={"id": "meta-user-1", "name": "Mo"})
        if path.endswith("/me/accounts"):
            assert params["access_token"] == "long-user-token"
            if "after" not in params:
                return httpx.Response(200, json={
                    "data": [{"id": "page-42", "name": "First Page", "access_token": "page-42-token",
                              "tasks": ["CREATE_CONTENT", "ANALYZE"], "category": "Restaurant"}],
                    "paging": {"cursors": {"after": "cursor-1"}, "next": "https://graph.facebook.com/next"},
                })
            assert params["after"] == "cursor-1"
            return httpx.Response(200, json={"data": [
                {"id": "page-43", "name": "Read-only Page", "access_token": "page-43-token", "tasks": ["ANALYZE"]},
                {"id": "page-44", "name": "No token Page"},
            ]})
        page_id = path.rsplit("/", 1)[-1]
        seen_pages.append(page_id)
        assert params["access_token"] == f"{page_id}-token"
        if page_id == "page-42":
            return httpx.Response(200, json={"instagram_business_account": {
                "id": "instagram-77", "username": "contentflow.official", "followers_count": 1200}})
        return httpx.Response(200, json={"id": page_id})

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handle_request)
    for module in (social_oauth.httpx, meta_graph.httpx):
        monkeypatch.setattr(module, "AsyncClient", lambda **kwargs: real_async_client(transport=transport, **kwargs))

    async def connect_and_discover():  # type: ignore[no-untyped-def]
        token_data = await social_oauth.exchange_authorization_code(
            "meta", settings, "meta-auth-code", "https://contentflow.example.com/callback",
        )
        return token_data, await social_oauth.retrieve_connected_accounts("meta", token_data)

    token_data, discovered = asyncio.run(connect_and_discover())

    assert token_data["access_token"] == "long-user-token"
    assert discovered["external_user_id"] == "meta-user-1"
    accounts = {(a["platform"], a["account_id"]): a for a in discovered["accounts"]}
    assert sorted(accounts) == [("facebook", "page-42"), ("facebook", "page-43"), ("instagram", "instagram-77")]
    assert seen_pages == ["page-42", "page-43"]  # the Page without a token was skipped
    assert accounts[("facebook", "page-42")]["details"]["can_publish"] is True
    assert accounts[("facebook", "page-43")]["details"]["can_publish"] is False
    instagram = accounts[("instagram", "instagram-77")]
    assert instagram["parent_account_id"] == "page-42"
    assert instagram["details"]["followers_count"] == 1200
    assert instagram["tokens"]["access_token"] == "page-42-token"


def test_facebook_photo_publisher_uploads_the_image_to_the_selected_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "post.jpg"
    image_path.write_bytes(b"test image bytes")
    real_async_client = httpx.AsyncClient

    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v26.0/page-42/photos"
        body = request.read()
        assert b"name=\"caption\"" in body
        assert b"A Facebook caption" in body
        assert b"page-token" in body
        assert b"filename=\"post.jpg\"" in body
        assert b"test image bytes" in body
        return httpx.Response(200, json={"id": "facebook-photo-99"})

    transport = httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        social_oauth.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )
    post_id = asyncio.run(social_oauth.publish_facebook_photo(
        "page-42",
        "page-token",
        image_path,
        "post.jpg",
        "image/jpeg",
        "A Facebook caption",
    ))

    assert post_id == "facebook-photo-99"


@pytest.mark.parametrize(
    ("graph_error", "expected_fragment"),
    [
        ({"message": "Invalid parameter", "code": 100}, "Facebook rejected the post: Invalid parameter (code 100)"),
        ({"message": "Session has expired", "code": 190}, "Reconnect the Page"),
    ],
)
def test_facebook_photo_publisher_reports_meta_error_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    graph_error: dict[str, object],
    expected_fragment: str,
) -> None:
    image_path = tmp_path / "post.jpg"
    image_path.write_bytes(b"test image bytes")
    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"error": graph_error}))
    monkeypatch.setattr(
        social_oauth.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(social_oauth.MetaAPIError) as raised:
        asyncio.run(social_oauth.publish_facebook_photo(
            "page-42", "secret-page-token", image_path, "post.jpg", "image/jpeg", "Caption",
        ))

    assert expected_fragment in str(raised.value)
    assert "secret-page-token" not in str(raised.value)


def test_caption_generation_requires_provider_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENT_FLOW_AI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post(
        "/api/ai/captions",
        json={"topic": "A new course", "audience": "Students", "platforms": ["instagram"]},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Configure OPENAI_API_KEY on the backend to generate captions."


def test_caption_generation_returns_one_draft_per_platform(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENT_FLOW_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def fake_provider(provider: str, api_key: str, model: str, prompt: str) -> str:
        assert provider == "openai"
        assert api_key == "test-key"
        assert model == "gpt-5-mini"
        assert "distinct post for each requested platform" in prompt
        return (
            '{"posts":['
            '{"platform":"instagram","caption":"A visual launch.","hashtags":["CourseLaunch"]},'
            '{"platform":"linkedin","caption":"A professional launch.","hashtags":["Education"]}'
            ']}'
        )

    monkeypatch.setattr(ai_service, "call_caption_provider", fake_provider)
    response = client.post(
        "/api/ai/captions",
        json={
            "topic": "A new course",
            "audience": "Students",
            "instructions": "Do not invent dates.",
            "platforms": ["instagram", "linkedin"],
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "openai"
    assert [post["platform"] for post in response.json()["posts"]] == ["instagram", "linkedin"]
    assert response.json()["posts"][0]["caption"] != response.json()["posts"][1]["caption"]


def test_claude_caption_generation_uses_configured_model_and_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENT_FLOW_AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5-5")

    async def fake_provider(provider: str, api_key: str, model: str, prompt: str) -> str:
        assert provider == "claude"
        assert api_key == "test-anthropic-key"
        assert model == "claude-sonnet-5-5"
        assert "instagram" in prompt
        return '{"posts":[{"platform":"instagram","caption":"A fresh start.","hashtags":["NewCourse"]}]}'

    monkeypatch.setattr(ai_service, "call_caption_provider", fake_provider)
    response = client.post(
        "/api/ai/captions",
        json={"topic": "A new course", "audience": "Students", "platforms": ["instagram"]},
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "claude"
    assert response.json()["posts"][0]["caption"] == "A fresh start."


def test_claude_provider_sends_anthropic_messages_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "test-anthropic-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "claude-sonnet-5-5"
        assert body["system"] == "Write platform-specific captions."
        assert body["max_tokens"] > 0
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '{"posts":[]}'}]},
        )

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        ai_service.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    response_text = asyncio.run(
        ai_service.call_caption_provider(
            "claude",
            "test-anthropic-key",
            "claude-sonnet-5-5",
            "Write platform-specific captions.",
        )
    )

    assert response_text == '{"posts":[]}'


def test_create_and_list_scheduled_posts(client: TestClient) -> None:
    payload = {
        "posts": [
            {
                "media_name": "Campaign image.png",
                "date": "2026-11-03",
                "time": "10:30",
                "platforms": ["instagram", "linkedin"],
                "caption": "A launch is coming soon.",
            },
            {
                "media_name": "Behind the scenes.mp4",
                "date": "2026-11-04",
                "time": "11:00",
                "platforms": ["facebook"],
                "caption": "A little look behind the scenes.",
            },
        ]
    }

    created = client.post("/api/scheduled-posts", json=payload)
    listed = client.get("/api/scheduled-posts")

    assert created.status_code == 201
    assert len(created.json()) == 2
    assert created.json()[0]["media_name"] == payload["posts"][0]["media_name"]
    assert created.json()[0]["date"] == payload["posts"][0]["date"]
    assert created.json()[0]["time"] == payload["posts"][0]["time"]
    assert created.json()[0]["platforms"] == payload["posts"][0]["platforms"]
    assert listed.status_code == 200
    assert [post["id"] for post in listed.json()] == [
        post["id"] for post in created.json()
    ]


def test_scheduled_facebook_image_posts_to_the_selected_page(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", encryption_key)
    page_record_id = "connected-facebook-page"
    with database.connect_database() as connection:
        user = connection.execute(
            "SELECT users.id, memberships.workspace_id FROM users JOIN memberships ON memberships.user_id = users.id "
            "WHERE users.email = ?",
            ("test@example.com",),
        ).fetchone()
        assert user is not None
        connection.execute(
            """
            INSERT INTO social_accounts (
                id, user_id, provider, platform, account_id, account_name, account_type,
                encrypted_tokens, expires_at, connected_at, updated_at, workspace_id
            ) VALUES (?, ?, 'meta', 'facebook', 'meta-page-42', 'Rahat Pizza Islamabad', 'page', ?, NULL, ?, ?, ?)
            """,
            (
                page_record_id,
                user["id"],
                Fernet(encryption_key).encrypt(json.dumps({"access_token": "page-token"}).encode()).decode("ascii"),
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                user["workspace_id"],
            ),
        )

    uploaded = client.post(
        "/api/assets",
        files={"file": ("poster.jpg", b"image bytes", "image/jpeg")},
    )
    assert uploaded.status_code == 201
    scheduled_for = datetime.now(timezone.utc) + timedelta(days=1)
    scheduled_for = scheduled_for.replace(hour=10, minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/scheduled-posts",
        json={
            "posts": [{
                "media_name": "poster.jpg",
                "date": scheduled_for.date().isoformat(),
                "time": "10:00",
                "platforms": ["facebook"],
                "caption": "A new menu is here.",
                "asset_id": uploaded.json()["id"],
                "facebook_account_id": page_record_id,
                "timezone_offset_minutes": 0,
            }],
        },
    )
    assert created.status_code == 201
    scheduled_post = created.json()[0]
    assert scheduled_post["publish_status"] == "scheduled"
    assert scheduled_post["facebook_account_id"] == page_record_id

    with database.connect_database() as connection:
        connection.execute(
            "UPDATE scheduled_posts SET scheduled_date = '2020-01-01', scheduled_time = '00:00' WHERE id = ?",
            (scheduled_post["id"],),
        )

    published: list[tuple[str, str, bytes, str]] = []

    async def fake_publish(
        page_id: str,
        access_token: str,
        media_path: Path,
        filename: str,
        media_type: str,
        caption: str,
    ) -> str:
        assert access_token == "page-token"
        assert filename == "poster.jpg"
        assert media_type == "image/jpeg"
        published.append((page_id, caption, media_path.read_bytes(), filename))
        return "meta-post-123"

    monkeypatch.setattr(social_oauth, "publish_facebook_photo", fake_publish)
    asyncio.run(publisher.publish_due_scheduled_posts())

    refreshed = client.get("/api/scheduled-posts")
    assert refreshed.status_code == 200
    assert refreshed.json()[0]["publish_status"] == "published"
    assert published == [("meta-page-42", "A new menu is here.", b"image bytes", "poster.jpg")]


def test_facebook_post_cannot_be_rescheduled_into_the_past(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", encryption_key)
    with database.connect_database() as connection:
        user = connection.execute(
            "SELECT users.id, memberships.workspace_id FROM users JOIN memberships ON memberships.user_id = users.id "
            "WHERE users.email = ?",
            ("test@example.com",),
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO social_accounts (
                id, user_id, provider, platform, account_id, account_name, account_type,
                encrypted_tokens, expires_at, connected_at, updated_at, workspace_id
            ) VALUES ('page-record', ?, 'meta', 'facebook', 'meta-page-1', 'Test Page', 'page', ?, NULL, ?, ?, ?)
            """,
            (user["id"], Fernet(encryption_key).encrypt(b'{"access_token": "t"}').decode("ascii"), now, now,
             user["workspace_id"]),
        )
    uploaded = client.post("/api/assets", files={"file": ("poster.jpg", b"image bytes", "image/jpeg")})
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    created = client.post(
        "/api/scheduled-posts",
        json={"posts": [{
            "media_name": "poster.jpg",
            "date": tomorrow.isoformat(),
            "time": "23:00",
            "platforms": ["facebook"],
            "caption": "Caption",
            "asset_id": uploaded.json()["id"],
            "facebook_account_id": "page-record",
            "timezone_offset_minutes": 0,
        }]},
    )
    assert created.status_code == 201
    post_id = created.json()[0]["id"]

    past = client.patch(f"/api/scheduled-posts/{post_id}", json={"date": "2020-01-01"})
    future = client.patch(
        f"/api/scheduled-posts/{post_id}",
        json={"date": (tomorrow + timedelta(days=1)).isoformat()},
    )

    assert past.status_code == 422
    assert past.json()["detail"] == "Choose a future date for automatic Facebook publishing."
    assert future.status_code == 200


def test_scheduled_posts_reject_channel_time_conflicts_atomically(client: TestClient) -> None:
    first = client.post(
        "/api/scheduled-posts",
        json={
            "posts": [
                {
                    "media_name": "First post.png",
                    "date": "2026-11-03",
                    "time": "10:30",
                    "platforms": ["instagram"],
                    "caption": "First.",
                }
            ]
        },
    )
    conflict = client.post(
        "/api/scheduled-posts",
        json={
            "posts": [
                {
                    "media_name": "Would be rolled back.png",
                    "date": "2026-11-04",
                    "time": "09:00",
                    "platforms": ["facebook"],
                    "caption": "This must not partially save.",
                },
                {
                    "media_name": "Conflicting post.png",
                    "date": "2026-11-03",
                    "time": "10:30",
                    "platforms": ["instagram", "linkedin"],
                    "caption": "This conflicts with the first post.",
                },
            ]
        },
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert len(client.get("/api/scheduled-posts").json()) == 1


def test_scheduled_post_date_update_and_delete(client: TestClient) -> None:
    created = client.post(
        "/api/scheduled-posts",
        json={
            "posts": [
                {
                    "media_name": "Campaign image.png",
                    "date": "2026-11-03",
                    "time": "10:30",
                    "platforms": ["instagram"],
                    "caption": "A launch is coming soon.",
                }
            ]
        },
    )
    post_id = created.json()[0]["id"]
    rescheduled = client.patch(
        f"/api/scheduled-posts/{post_id}",
        json={"date": "2026-11-05"},
    )
    deleted = client.delete(f"/api/scheduled-posts/{post_id}")

    assert rescheduled.status_code == 200
    assert rescheduled.json()["date"] == "2026-11-05"
    assert deleted.status_code == 204
    assert client.get("/api/scheduled-posts").json() == []


def test_reschedule_rejects_a_channel_time_collision(client: TestClient) -> None:
    created = client.post(
        "/api/scheduled-posts",
        json={
            "posts": [
                {
                    "media_name": "First post.png",
                    "date": "2026-11-03",
                    "time": "10:30",
                    "platforms": ["instagram"],
                    "caption": "First.",
                },
                {
                    "media_name": "Second post.png",
                    "date": "2026-11-04",
                    "time": "10:30",
                    "platforms": ["instagram"],
                    "caption": "Second.",
                },
            ]
        },
    )
    first_id = created.json()[0]["id"]
    conflict = client.patch(
        f"/api/scheduled-posts/{first_id}",
        json={"date": "2026-11-04"},
    )

    assert created.status_code == 201
    assert conflict.status_code == 409
    assert client.get("/api/scheduled-posts").json()[0]["date"] == "2026-11-03"


def test_scheduled_posts_are_private_to_each_user(client: TestClient) -> None:
    created = client.post(
        "/api/scheduled-posts",
        json={
            "posts": [
                {
                    "media_name": "Private plan.png",
                    "date": "2026-11-03",
                    "time": "10:30",
                    "platforms": ["instagram"],
                    "caption": "Private schedule.",
                }
            ]
        },
    )
    post_id = created.json()[0]["id"]
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={
            "full_name": "Other User",
            "workspace_name": "Other Workspace",
            "email": "other@example.com",
            "password": "another-strong-password",
        },
    )

    assert client.get("/api/scheduled-posts").json() == []
    assert client.patch(f"/api/scheduled-posts/{post_id}", json={"date": "2026-11-06"}).status_code == 404
    assert client.delete(f"/api/scheduled-posts/{post_id}").status_code == 404


def test_scheduled_posts_validate_payload_and_idempotent_retry(client: TestClient) -> None:
    payload = {
        "posts": [
            {
                "media_name": "Campaign image.png",
                "date": "2026-11-03",
                "time": "10:30",
                "platforms": ["instagram"],
                "caption": "A launch is coming soon.",
            }
        ]
    }
    created = client.post("/api/scheduled-posts", json=payload)
    retry = client.post("/api/scheduled-posts", json=payload)
    invalid = client.post(
        "/api/scheduled-posts",
        json={
            "posts": [
                {
                    **payload["posts"][0],
                    "platforms": ["not-a-platform"],
                }
            ]
        },
    )
    invalid_precision = client.post(
        "/api/scheduled-posts",
        json={
            "posts": [
                {
                    **payload["posts"][0],
                    "time": "10:30:01",
                }
            ]
        },
    )

    assert created.status_code == 201
    assert retry.status_code == 201
    assert retry.json()[0]["id"] == created.json()[0]["id"]
    assert invalid.status_code == 422
    assert invalid_precision.status_code == 422
    assert len(client.get("/api/scheduled-posts").json()) == 1


def test_reject_invalid_platform_and_duplicate_platforms(client: TestClient) -> None:
    payload = {
        "campaign": "",
        "audience": "Students",
        "instructions": "Share course details.",
        "language": "English",
        "platforms": ["unknown-platform"],
    }
    invalid_platform = client.post("/api/submissions", json=payload)
    duplicate_platform = client.post(
        "/api/submissions",
        json={**payload, "platforms": ["instagram", "instagram"]},
    )

    assert invalid_platform.status_code == 422
    assert duplicate_platform.status_code == 422


def test_required_submission_text_cannot_be_blank(client: TestClient) -> None:
    response = client.post(
        "/api/submissions",
        json={
            "campaign": "   ",
            "audience": "   ",
            "instructions": "Write an announcement.",
            "language": "English",
            "platforms": ["instagram"],
        },
    )

    assert response.status_code == 422


def test_upload_asset_and_attach_it_to_submission(client: TestClient) -> None:
    uploaded = client.post(
        "/api/assets",
        files={"file": ("poster.png", b"image bytes", "image/png")},
    )
    assert uploaded.status_code == 201
    asset = uploaded.json()

    created = client.post(
        "/api/submissions",
        json={
            "campaign": "Course poster",
            "audience": "Prospective students",
            "instructions": "Use only the supplied information.",
            "language": "English",
            "platforms": ["facebook"],
            "asset_ids": [asset["id"]],
        },
    )
    listed = client.get("/api/submissions")

    assert created.status_code == 201
    assert created.json()["assets"] == [asset]
    retrieved = client.get(f"/api/submissions/{created.json()['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == created.json()["id"]
    assert retrieved.json()["assets"] == [asset]
    assert listed.json()[0]["assets"] == [asset]


def test_asset_cannot_be_attached_to_multiple_submissions(client: TestClient) -> None:
    uploaded = client.post(
        "/api/assets",
        files={"file": ("poster.png", b"image bytes", "image/png")},
    )
    asset_id = uploaded.json()["id"]
    payload = {
        "campaign": "Course poster",
        "audience": "Prospective students",
        "instructions": "Use only the supplied information.",
        "language": "English",
        "platforms": ["facebook"],
        "asset_ids": [asset_id],
    }
    first = client.post("/api/submissions", json=payload)
    second = client.post("/api/submissions", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert client.get("/api/submissions").status_code == 200


def test_reject_unsupported_and_empty_uploads(client: TestClient) -> None:
    unsupported = client.post(
        "/api/assets",
        files={"file": ("notes.txt", b"not media", "text/plain")},
    )
    empty = client.post(
        "/api/assets",
        files={"file": ("empty.png", b"", "image/png")},
    )

    assert unsupported.status_code == 415
    assert empty.status_code == 400


def test_submission_requires_existing_asset(client: TestClient) -> None:
    response = client.post(
        "/api/submissions",
        json={
            "campaign": "",
            "audience": "Students",
            "instructions": "Write a course announcement.",
            "language": "English",
            "platforms": ["instagram"],
            "asset_ids": ["missing-asset"],
        },
    )

    assert response.status_code == 400


def _signed_webhook(client: TestClient, body: bytes, secret: str, signature: str = "") -> httpx.Response:
    import hashlib
    import hmac

    header = signature or "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/social/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": header},
    )


def test_webhook_is_closed_until_a_verify_token_is_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("META_WEBHOOK_VERIFY_TOKEN", raising=False)
    verify = client.get(
        "/api/social/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "insta_hook_99", "hub.challenge": "42"},
    )
    receive = client.post("/api/social/webhook", json={"object": "page"})

    assert verify.status_code == 503
    assert receive.status_code == 503


def test_webhook_verification_uses_configured_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "configured-verify-token")
    params = {"hub.mode": "subscribe", "hub.challenge": "challenge-123"}

    accepted = client.get("/api/social/webhook", params={**params, "hub.verify_token": "configured-verify-token"})
    rejected = client.get("/api/social/webhook", params={**params, "hub.verify_token": "insta_hook_99"})

    assert accepted.status_code == 200
    assert accepted.text == "challenge-123"
    assert rejected.status_code == 403


def test_webhook_events_require_a_valid_meta_signature(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "configured-verify-token")
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret")
    body = b'{"object":"page","entry":[{"id":"1"}]}'

    valid = _signed_webhook(client, body, "test-app-secret")
    wrong_secret = _signed_webhook(client, body, "another-secret")
    missing = client.post("/api/social/webhook", content=body, headers={"Content-Type": "application/json"})
    tampered = _signed_webhook(
        client,
        b'{"object":"page","entry":[]}',
        "test-app-secret",
        signature=valid.request.headers["X-Hub-Signature-256"],
    )

    assert valid.status_code == 200
    assert wrong_secret.status_code == 401
    assert missing.status_code == 401
    assert tampered.status_code == 401


def test_repeated_failed_logins_lock_the_email_temporarily(client: TestClient) -> None:
    client.post("/api/auth/logout")
    for _ in range(5):
        failed = client.post("/api/auth/login", json={"email": "test@example.com", "password": "wrong-password"})
        assert failed.status_code == 401

    locked = client.post("/api/auth/login", json={"email": "test@example.com", "password": "correct-horse-battery"})

    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    other_account = client.post("/api/auth/login", json={"email": "other@example.com", "password": "anything"})
    assert other_account.status_code == 401


def test_registration_is_rate_limited_per_network(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_FLOW_REGISTER_PER_HOUR_LIMIT", "2")
    account = {"full_name": "New Person", "workspace_name": "New Workspace", "password": "correct-horse-battery"}

    second = client.post("/api/auth/register", json={**account, "email": "second@example.com"})
    third = client.post("/api/auth/register", json={**account, "email": "third@example.com"})

    assert second.status_code == 201
    assert third.status_code == 429


def test_ai_caption_daily_quota_counts_every_provider_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENT_FLOW_AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("CONTENT_FLOW_AI_DAILY_LIMIT", "2")
    calls: list[str] = []

    async def fake_provider(provider: str, api_key: str, model: str, prompt: str) -> str:
        calls.append(provider)
        if len(calls) == 1:
            raise httpx.ConnectError("provider unavailable")
        return '{"posts":[{"platform":"instagram","caption":"Hello.","hashtags":[]}]}'

    monkeypatch.setattr(ai_service, "call_caption_provider", fake_provider)
    request = {"topic": "A new course", "audience": "Students", "platforms": ["instagram"]}

    failed = client.post("/api/ai/captions", json=request)
    succeeded = client.post("/api/ai/captions", json=request)
    over_quota = client.post("/api/ai/captions", json=request)
    usage = client.get("/api/ai/usage")

    assert failed.status_code == 502
    assert succeeded.status_code == 200
    assert over_quota.status_code == 429
    assert len(calls) == 2
    assert usage.json() == {"used_last_24h": 2, "daily_limit": 2, "remaining": 0}


def test_ai_quota_is_tracked_per_user(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_FLOW_AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("CONTENT_FLOW_AI_DAILY_LIMIT", "1")

    async def fake_provider(provider: str, api_key: str, model: str, prompt: str) -> str:
        return '{"posts":[{"platform":"instagram","caption":"Hello.","hashtags":[]}]}'

    monkeypatch.setattr(ai_service, "call_caption_provider", fake_provider)
    request = {"topic": "A new course", "audience": "Students", "platforms": ["instagram"]}
    assert client.post("/api/ai/captions", json=request).status_code == 200
    assert client.post("/api/ai/captions", json=request).status_code == 429

    client.post(
        "/api/auth/register",
        json={
            "full_name": "Second User",
            "workspace_name": "Second Workspace",
            "email": "second@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert client.post("/api/ai/captions", json=request).status_code == 200


def test_client_ip_uses_render_proxy_address_only_on_render(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request as StarletteRequest

    request = StarletteRequest({
        "type": "http",
        "headers": [(b"x-forwarded-for", b"1.1.1.1, 203.0.113.9")],
        "client": ("10.0.0.5", 1234),
    })

    monkeypatch.delenv("RENDER", raising=False)
    assert security.client_ip(request) == "10.0.0.5"
    monkeypatch.setenv("RENDER", "true")
    assert security.client_ip(request) == "203.0.113.9"


@pytest.fixture()
def app_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    import logging

    app_logger = logging.getLogger("app")
    app_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="app")
    try:
        yield caplog
    finally:
        app_logger.removeHandler(caplog.handler)


def test_oauth_failures_are_logged_without_secrets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    app_logs: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("META_APP_ID", "test-meta-app")
    monkeypatch.setenv("META_APP_SECRET", "super-secret-app-value")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("CONTENT_FLOW_API_PUBLIC_URL", "https://contentflow-api.example.com")

    async def failing_exchange(provider: str, settings: dict[str, str], code: str, redirect_uri: str) -> dict[str, object]:
        request = httpx.Request(
            "GET",
            "https://graph.facebook.com/v25.0/oauth/access_token",
            params={"client_secret": "super-secret-app-value", "code": "private-auth-code"},
        )
        response = httpx.Response(
            400,
            request=request,
            json={"error": {"message": "Invalid verification code format.", "type": "OAuthException", "code": 100}},
        )
        response.raise_for_status()
        return {}

    monkeypatch.setattr(social_oauth, "exchange_authorization_code", failing_exchange)
    start = client.get("/api/social/oauth/meta/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    callback = client.get(
        "/api/social/oauth/meta/callback",
        params={"state": state, "code": "private-auth-code"},
        follow_redirects=False,
    )

    assert callback.headers["location"].endswith("/accounts?social=connect_failed")
    assert "Invalid verification code format." in app_logs.text
    assert "super-secret-app-value" not in app_logs.text
    assert "private-auth-code" not in app_logs.text


def test_responses_carry_a_request_id(client: TestClient) -> None:
    generated = client.get("/api/health")
    forwarded = client.get("/api/health", headers={"X-Request-ID": "trace-abc.123"})
    unsafe = client.get("/api/health", headers={"X-Request-ID": "bad id\nwith newline"})

    assert len(generated.headers["X-Request-ID"]) == 32
    assert forwarded.headers["X-Request-ID"] == "trace-abc.123"
    assert unsafe.headers["X-Request-ID"] != "bad id\nwith newline"


def test_unhandled_errors_return_json_with_request_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    app_logs: pytest.LogCaptureFixture,
) -> None:
    from app.routers import submissions

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database exploded")

    monkeypatch.setattr(submissions, "connect_database", explode)
    with TestClient(main.app, raise_server_exceptions=False) as raw_client:
        raw_client.cookies.update(client.cookies)
        response = raw_client.get(
            "/api/submissions",
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "database exploded" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "database exploded" in app_logs.text
