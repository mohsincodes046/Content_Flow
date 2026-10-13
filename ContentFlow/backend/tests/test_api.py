from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
