"""Meta Graph client: publishing calls, error handling, connection health and Meta callbacks.

Requests are checked against the shapes in Meta's documentation; responses are
recorded examples. These prove our side of the contract, not Meta's behavior,
which is verified in manual testing with a real Page.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import config, database, main, meta_graph

Handler = Callable[[httpx.Request], httpx.Response]


class Recorder(list):
    """Recorded Graph requests; `handler(fn)` sets how Graph answers."""

    def handler(self, fn: Handler) -> None:
        self.respond = fn


@pytest.fixture()
def graph(monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    requests = Recorder()
    real_client = httpx.AsyncClient

    def dispatch(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return requests.respond(request)

    monkeypatch.setattr(meta_graph.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(dispatch), **kw))

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(meta_graph, "sleep", no_sleep)
    yield requests


def form(request: httpx.Request) -> dict[str, str]:
    body = request.read()
    if b"Content-Disposition" in body:  # multipart: pull simple fields
        fields = {}
        for part in body.split(b"--"):
            if b'name="' in part and b"filename=" not in part:
                name = part.split(b'name="', 1)[1].split(b'"', 1)[0].decode()
                fields[name] = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0].decode()
        return fields
    return dict(httpx.QueryParams(body.decode()))


def image(tmp_path: Path, name: str = "a.jpg", kind: str = "image/jpeg") -> meta_graph.MediaFile:
    path = tmp_path / name
    path.write_bytes(b"bytes-of-" + name.encode())
    return meta_graph.MediaFile(path, name, kind)


def test_facebook_text_post(graph: list[httpx.Request]) -> None:
    graph.handler(lambda r: httpx.Response(200, json={"id": "page_1_post_9"}))
    result = asyncio.run(meta_graph.publish_facebook("page_1", "tok", "Hello world", [], link="https://ex.com"))
    assert result.external_id == "page_1_post_9"
    assert graph[0].url.path == "/v26.0/page_1/feed"
    assert form(graph[0]) == {"message": "Hello world", "link": "https://ex.com"}
    assert graph[0].url.params["access_token"] == "tok"


def test_facebook_multi_photo_post_attaches_unpublished_photos(graph: list[httpx.Request], tmp_path: Path) -> None:
    ids = iter(["photo_a", "photo_b"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/photos"):
            assert form(request)["published"] == "false"
            return httpx.Response(200, json={"id": next(ids)})
        return httpx.Response(200, json={"id": "page_1_post_5"})

    graph.handler(handler)
    result = asyncio.run(meta_graph.publish_facebook("page_1", "tok", "Two photos",
                                                     [image(tmp_path, "a.jpg"), image(tmp_path, "b.jpg")]))
    assert result.external_id == "page_1_post_5"
    feed = form(graph[-1])
    assert feed["message"] == "Two photos"
    assert json.loads(feed["attached_media[0]"]) == {"media_fbid": "photo_a"}
    assert json.loads(feed["attached_media[1]"]) == {"media_fbid": "photo_b"}


def test_facebook_video_uses_the_video_host(graph: list[httpx.Request], tmp_path: Path) -> None:
    graph.handler(lambda r: httpx.Response(200, json={"id": "video_7"}))
    result = asyncio.run(meta_graph.publish_facebook("page_1", "tok", "Watch", [image(tmp_path, "v.mp4", "video/mp4")]))
    assert result.external_id == "video_7"
    assert graph[0].url.host == "graph-video.facebook.com"
    assert graph[0].url.path == "/v26.0/page_1/videos"
    assert form(graph[0])["description"] == "Watch"


def test_facebook_rejects_mixing_photos_and_video(graph: list[httpx.Request], tmp_path: Path) -> None:
    with pytest.raises(meta_graph.GraphError, match="not a mix"):
        asyncio.run(meta_graph.publish_facebook(
            "page_1", "tok", "x", [image(tmp_path, "a.jpg"), image(tmp_path, "v.mp4", "video/mp4")]))
    assert graph == []


def ig_handler(statuses: dict[str, list[str]], quota: tuple[int, int] = (0, 100)) -> Handler:
    counter = iter(range(1, 100))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/content_publishing_limit"):
            return httpx.Response(200, json={"data": [{"quota_usage": quota[0], "config": {"quota_total": quota[1]}}]})
        if path.endswith("/media") and request.method == "POST":
            return httpx.Response(200, json={"id": f"container_{next(counter)}"})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "ig_media_1"})
        object_id = path.rsplit("/", 1)[-1]
        if object_id.startswith("container_"):
            return httpx.Response(200, json={"status_code": statuses.get(object_id, ["FINISHED"]).pop(0)})
        return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/abc/"})

    return handler


def test_instagram_single_image(graph: list[httpx.Request]) -> None:
    graph.handler(ig_handler({}))
    result = asyncio.run(meta_graph.publish_instagram("ig_1", "tok", "Caption #tag",
                                                      [("image/jpeg", "https://api.example.com/m/1.jpg")]))
    assert (result.external_id, result.url) == ("ig_media_1", "https://www.instagram.com/p/abc/")
    container = next(r for r in graph if r.url.path.endswith("/ig_1/media"))
    assert form(container) == {"image_url": "https://api.example.com/m/1.jpg", "caption": "Caption #tag"}
    publish = next(r for r in graph if r.url.path.endswith("/media_publish"))
    assert form(publish) == {"creation_id": "container_1"}


def test_instagram_video_waits_until_processing_finishes(graph: list[httpx.Request]) -> None:
    graph.handler(ig_handler({"container_1": ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]}))
    asyncio.run(meta_graph.publish_instagram("ig_1", "tok", "Reel", [("video/mp4", "https://api.example.com/v.mp4")]))
    container = next(r for r in graph if r.url.path.endswith("/ig_1/media"))
    assert form(container)["media_type"] == "REELS"
    status_checks = [r for r in graph if r.url.path.endswith("/container_1")]
    assert len(status_checks) == 3
    assert graph.index(status_checks[-1]) < graph.index(next(r for r in graph if r.url.path.endswith("/media_publish")))


def test_instagram_carousel(graph: list[httpx.Request]) -> None:
    graph.handler(ig_handler({}))
    asyncio.run(meta_graph.publish_instagram("ig_1", "tok", "Carousel", [
        ("image/jpeg", "https://api.example.com/1.jpg"), ("video/mp4", "https://api.example.com/2.mp4")]))
    creates = [form(r) for r in graph if r.url.path.endswith("/ig_1/media")]
    assert creates[0] == {"image_url": "https://api.example.com/1.jpg", "is_carousel_item": "true"}
    assert creates[1] == {"video_url": "https://api.example.com/2.mp4", "media_type": "VIDEO", "is_carousel_item": "true"}
    assert creates[2] == {"media_type": "CAROUSEL", "children": "container_1,container_2", "caption": "Carousel"}


def test_instagram_failed_processing_is_reported(graph: list[httpx.Request]) -> None:
    graph.handler(ig_handler({"container_1": ["ERROR"]}))
    with pytest.raises(meta_graph.GraphError, match="could not process"):
        asyncio.run(meta_graph.publish_instagram("ig_1", "tok", "x", [("image/jpeg", "https://a/1.jpg")]))
    assert not any(r.url.path.endswith("/media_publish") for r in graph)


def test_instagram_daily_limit_stops_before_creating_anything(graph: list[httpx.Request]) -> None:
    graph.handler(ig_handler({}, quota=(100, 100)))
    with pytest.raises(meta_graph.GraphError) as raised:
        asyncio.run(meta_graph.publish_instagram("ig_1", "tok", "x", [("image/jpeg", "https://a/1.jpg")]))
    assert raised.value.retryable
    assert not any(r.url.path.endswith("/media") for r in graph)


@pytest.mark.parametrize(("error", "reconnect", "retryable"), [
    ({"message": "Session has expired", "code": 190, "error_subcode": 463}, True, False),
    ({"message": "(#200) Permissions error", "code": 200}, False, False),
    ({"message": "Please retry", "code": 2, "is_transient": True}, False, True),
    ({"message": "Too many calls", "code": 4}, False, True),
])
def test_graph_errors_are_classified(graph: list[httpx.Request], error: dict[str, Any], reconnect: bool,
                                     retryable: bool) -> None:
    graph.handler(lambda r: httpx.Response(400, json={"error": error}))
    with pytest.raises(meta_graph.GraphError) as raised:
        asyncio.run(meta_graph.publish_facebook("page_1", "secret-token", "x", []))
    assert raised.value.needs_reconnect is reconnect
    assert raised.value.retryable is retryable
    assert "secret-token" not in str(raised.value)


def test_network_errors_never_include_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(meta_graph.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(boom), **kw))
    with pytest.raises(meta_graph.GraphError) as raised:
        asyncio.run(meta_graph.request("GET", "me", token="secret-token"))
    assert raised.value.retryable and "secret-token" not in str(raised.value)


# --- Connection health and Meta callbacks ------------------------------------------------------

@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("META_APP_SECRET", "app-secret")
    with TestClient(main.app) as test_client:
        assert test_client.post("/api/auth/register", json={
            "full_name": "Owner", "workspace_name": "W", "email": "o@example.com", "password": "correct-horse-battery",
        }).status_code == 201
        yield test_client


def add_account(client: TestClient, external_user: str = "meta-user-1") -> str:
    me = client.get("/api/auth/me").json()
    from app.security import token_cipher

    with database.connect_database() as connection:
        connection.execute(
            "INSERT INTO social_accounts (id, user_id, workspace_id, provider, platform, account_id, account_name, "
            "account_type, encrypted_tokens, expires_at, connected_at, updated_at, external_user_id) "
            "VALUES ('acct', ?, ?, 'meta', 'facebook', 'page_1', 'Page', 'page', ?, NULL, ?, ?, ?)",
            (me["id"], me["workspace_id"], token_cipher().encrypt(b'{"access_token": "tok"}').decode(),
             database.utc_now(), database.utc_now(), external_user),
        )
    return "acct"


def test_connection_check_marks_expired_tokens(client: TestClient, graph: list[httpx.Request]) -> None:
    account = add_account(client)
    graph.handler(lambda r: httpx.Response(200, json={"id": "page_1", "name": "Page"}))
    healthy = client.post(f"/api/social/accounts/{account}/check").json()
    assert healthy["status"] == "active" and healthy["last_checked_at"]

    graph.handler(lambda r: httpx.Response(400, json={"error": {"message": "Session expired", "code": 190}}))
    expired = client.post(f"/api/social/accounts/{account}/check").json()
    assert expired["status"] == "needs_reconnect"
    assert "Reconnect" in expired["last_error"]


def signed_request(payload: dict[str, Any], secret: str = "app-secret") -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature).decode().rstrip("=") + "." + encoded


def test_meta_deauthorize_flags_accounts_for_reconnection(client: TestClient) -> None:
    add_account(client)
    forged = client.post("/api/social/meta/deauthorize",
                         data={"signed_request": signed_request({"algorithm": "HMAC-SHA256", "user_id": "meta-user-1"}, "wrong")})
    assert forged.status_code == 401
    ok = client.post("/api/social/meta/deauthorize",
                     data={"signed_request": signed_request({"algorithm": "HMAC-SHA256", "user_id": "meta-user-1"})})
    assert ok.status_code == 200
    assert client.get("/api/social/providers").json()[0]["accounts"][0]["status"] == "needs_reconnect"


def test_meta_data_deletion_removes_tokens_and_reports_status(client: TestClient) -> None:
    add_account(client)
    response = client.post("/api/social/meta/data-deletion",
                           data={"signed_request": signed_request({"algorithm": "HMAC-SHA256", "user_id": "meta-user-1"})})
    assert response.status_code == 200
    body = response.json()
    assert body["url"].endswith(f"/api/social/meta/data-deletion/{body['confirmation_code']}")
    assert client.get("/api/social/providers").json()[0]["accounts"] == []
    status = client.get(f"/api/social/meta/data-deletion/{body['confirmation_code']}").json()
    assert status["status"] == "completed" and status["accounts_deleted"] == 1
