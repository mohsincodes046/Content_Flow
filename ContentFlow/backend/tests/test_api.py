import asyncio
import json
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from urllib.parse import parse_qs, urlparse

from app import main


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(main, "DATABASE_PATH", data_dir / "test.sqlite3")
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
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(main, "DATABASE_PATH", data_dir / "test.sqlite3")

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
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(main, "DATABASE_PATH", data_dir / "test.sqlite3")

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
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(main, "DATABASE_PATH", data_dir / "test.sqlite3")

    with TestClient(main.app) as unauthenticated_client:
        response = unauthenticated_client.post(
            "/api/ai/captions",
            json={"topic": "A new course", "audience": "Students", "platforms": ["instagram"]},
        )

    assert response.status_code == 401


def test_social_provider_list_requires_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "social-unauthenticated-data"
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(main, "DATABASE_PATH", data_dir / "test.sqlite3")

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
    scopes = parse_qs(urlparse(secure.headers["location"]).query)["scope"][0].split(",")
    assert "read_insights" not in scopes
    assert "pages_read_user_content" not in scopes


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

    main.load_backend_environment(env_file)

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


def test_meta_oauth_saves_page_and_instagram_tokens_encrypted(
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

    async def fake_accounts(provider: str, token_data: dict[str, object]) -> list[dict[str, object]]:
        assert provider == "meta"
        return [
            {
                "platform": "facebook",
                "account_id": "page-42",
                "account_name": "ContentFlow Page",
                "account_type": "page",
                "tokens": {"access_token": "page-access-token", "refresh_token": None, "expires_at": None},
            },
            {
                "platform": "instagram",
                "account_id": "instagram-77",
                "account_name": "contentflow.official",
                "account_type": "professional",
                "tokens": {"access_token": "page-access-token", "refresh_token": None, "expires_at": None},
            },
        ]

    monkeypatch.setattr(main.social_oauth, "exchange_authorization_code", fake_exchange)
    monkeypatch.setattr(main.social_oauth, "retrieve_connected_accounts", fake_accounts)

    start = client.get("/api/social/oauth/meta/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(
        "/api/social/oauth/meta/callback",
        params={"state": state, "code": "meta-auth-code"},
        follow_redirects=False,
    )
    providers = client.get("/api/social/providers")

    assert start.status_code == 302
    assert callback.status_code == 303
    assert callback.headers["location"] == "https://contentflow-web.example.com/accounts?social=connected"
    assert providers.status_code == 200
    meta = next(provider for provider in providers.json() if provider["provider"] == "meta")
    assert [account["platform"] for account in meta["accounts"]] == ["facebook", "instagram"]
    assert all("access_token" not in account for account in meta["accounts"])

    with main.connect_database() as connection:
        stored_tokens = connection.execute(
            "SELECT encrypted_tokens FROM social_accounts ORDER BY platform"
        ).fetchall()
    decoded_tokens = [json.loads(Fernet(encryption_key).decrypt(row["encrypted_tokens"].encode("ascii"))) for row in stored_tokens]
    assert [tokens["access_token"] for tokens in decoded_tokens] == ["page-access-token", "page-access-token"]

    replay = client.get(
        "/api/social/oauth/meta/callback",
        params={"state": state, "code": "meta-auth-code"},
        follow_redirects=False,
    )
    assert replay.headers["location"].endswith("/accounts?social=invalid_state")

    facebook_id = next(account["id"] for account in meta["accounts"] if account["platform"] == "facebook")
    instagram_id = next(account["id"] for account in meta["accounts"] if account["platform"] == "instagram")
    with TestClient(main.app) as another_workspace:
        another_workspace.post(
            "/api/auth/register",
            json={
                "full_name": "Different User",
                "workspace_name": "Different Workspace",
                "email": "different@example.com",
                "password": "another-safe-password",
            },
        )
        cross_workspace_delete = another_workspace.delete(f"/api/social/accounts/{instagram_id}")
    assert cross_workspace_delete.status_code == 404

    disconnected = client.delete(f"/api/social/accounts/{facebook_id}")
    remaining_accounts = client.get("/api/social/providers").json()[0]["accounts"]
    assert disconnected.status_code == 204
    assert [account["platform"] for account in remaining_accounts] == ["instagram"]


def test_meta_exchange_uses_long_lived_token_for_facebook_page_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {
        "token_url": "https://graph.facebook.com/v25.0/oauth/access_token",
        "client_id_value": "test-meta-app",
        "client_secret_value": "test-meta-secret",
    }

    def handle_request(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("code") == "meta-auth-code":
            return httpx.Response(200, json={"access_token": "short-user-token", "expires_in": 3600})
        if params.get("grant_type") == "fb_exchange_token":
            assert params["fb_exchange_token"] == "short-user-token"
            return httpx.Response(200, json={"access_token": "long-user-token", "expires_in": 5184000})
        assert request.url.path.endswith("/me/accounts")
        assert params["access_token"] == "long-user-token"
        return httpx.Response(200, json={"data": [{
            "id": "page-42",
            "name": "ContentFlow Page",
            "access_token": "long-page-token",
            "instagram_business_account": {"id": "instagram-77", "username": "contentflow.official"},
        }]})

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        main.social_oauth.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    async def connect_and_discover() -> tuple[dict[str, object], list[dict[str, object]]]:
        token_data = await main.social_oauth.exchange_authorization_code(
            "meta", settings, "meta-auth-code", "https://contentflow.example.com/callback",
        )
        discovered = await main.social_oauth.retrieve_connected_accounts("meta", token_data)
        return token_data, discovered

    token_data, discovered_accounts = asyncio.run(connect_and_discover())

    assert token_data["access_token"] == "long-user-token"
    assert len(discovered_accounts) == 2
    assert [account["platform"] for account in discovered_accounts] == ["facebook", "instagram"]
    assert all(account["tokens"]["access_token"] == "long-page-token" for account in discovered_accounts)
    assert all(account["tokens"]["expires_at"] is None for account in discovered_accounts)


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

    monkeypatch.setattr(main, "call_caption_provider", fake_provider)
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

    monkeypatch.setattr(main, "call_caption_provider", fake_provider)
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
        main.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    response_text = asyncio.run(
        main.call_caption_provider(
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
