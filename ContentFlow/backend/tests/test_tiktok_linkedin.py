"""TikTok and LinkedIn clients against their documented request/response shapes."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import content_rules, linkedin_api, tiktok_api


def mock(monkeypatch: pytest.MonkeyPatch, module, handler) -> list[httpx.Request]:  # type: ignore[no-untyped-def]
    calls: list[httpx.Request] = []
    real = httpx.AsyncClient

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(record), **kw))
    return calls


def test_authorization_urls() -> None:
    tiktok = parse_qs(urlparse(tiktok_api.authorization_url("key", "https://api/cb", "s")).query)
    assert tiktok["scope"] == ["user.info.basic,video.publish"] and tiktok["client_key"] == ["key"]
    linkedin = parse_qs(urlparse(linkedin_api.authorization_url("id", "https://api/cb", "s")).query)
    assert linkedin["scope"] == ["openid profile w_member_social"]


def test_tiktok_video_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1000)
    statuses = iter(["PROCESSING_UPLOAD", "PUBLISH_COMPLETE"])

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/creator_info/query/"):
            return httpx.Response(200, json={"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}})
        if path.endswith("/video/init/"):
            body = json.loads(request.content)
            assert body["post_info"]["privacy_level"] == "SELF_ONLY"  # unaudited apps: private only
            assert body["source_info"] == {"source": "FILE_UPLOAD", "video_size": 1000, "chunk_size": 1000, "total_chunk_count": 1}
            return httpx.Response(200, json={"data": {"publish_id": "pub-1", "upload_url": "https://upload.tiktok/u"}, "error": {"code": "ok"}})
        if request.url.host == "upload.tiktok":
            assert request.headers["Content-Range"] == "bytes 0-999/1000"
            return httpx.Response(201)
        return httpx.Response(200, json={"data": {"status": next(statuses), "publicaly_available_post_id": [7311]}, "error": {"code": "ok"}})

    calls = mock(monkeypatch, tiktok_api, handler)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(tiktok_api, "sleep", no_sleep)
    result = asyncio.run(tiktok_api.publish_video("tok", "Caption", video, "video/mp4"))
    assert result.external_id == "7311"
    assert calls[0].headers["Authorization"] == "Bearer tok"


def test_tiktok_expired_token_needs_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    mock(monkeypatch, tiktok_api, lambda r: httpx.Response(401, json={"error": {"code": "access_token_invalid", "message": "expired"}}))
    with pytest.raises(tiktok_api.GraphError) as raised:
        asyncio.run(tiktok_api.discover({"access_token": "t"}))
    assert raised.value.needs_reconnect


def test_tiktok_refresh_timing() -> None:
    soon = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    assert tiktok_api.needs_refresh({"expires_at": soon}) and not tiktok_api.needs_refresh({"expires_at": later})


def test_linkedin_image_post(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "a.jpg"
    image.write_bytes(b"jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        if "initializeUpload" in str(request.url):
            assert json.loads(request.content) == {"initializeUploadRequest": {"owner": "urn:li:person:abc"}}
            return httpx.Response(200, json={"value": {"uploadUrl": "https://upload.linkedin/x", "image": "urn:li:image:9"}})
        if request.url.host == "upload.linkedin":
            return httpx.Response(201)
        body = json.loads(request.content)
        assert request.headers["LinkedIn-Version"] == "202610" and request.headers["X-Restli-Protocol-Version"] == "2.0.0"
        assert body["author"] == "urn:li:person:abc" and body["content"] == {"media": {"id": "urn:li:image:9"}}
        assert body["lifecycleState"] == "PUBLISHED" and body["visibility"] == "PUBLIC"
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:123"})

    mock(monkeypatch, linkedin_api, handler)
    result = asyncio.run(linkedin_api.publish("abc", "tok", "Hello", [(image, "image/jpeg")]))
    assert result.external_id == "urn:li:share:123"
    assert result.url == "https://www.linkedin.com/feed/update/urn:li:share:123/"


def test_linkedin_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    mock(monkeypatch, linkedin_api, lambda r: httpx.Response(401, json={"message": "Expired"}))
    with pytest.raises(linkedin_api.GraphError) as raised:
        asyncio.run(linkedin_api.publish("abc", "tok", "Hi", []))
    assert raised.value.needs_reconnect
    assert linkedin_api.expired({"expires_at": "2020-01-01T00:00:00+00:00"})


def test_platform_rules() -> None:
    video, image = content_rules.Media("video/mp4"), content_rules.Media("image/jpeg", 800, 800)
    assert content_rules.check("tiktok", "x", [video]) == []
    assert content_rules.check("tiktok", "x", [image])[0].message == "TikTok posts need exactly one video."
    assert content_rules.check("linkedin", "Hello", [image]) == []
    assert "video" in content_rules.check("linkedin", "Hello", [video])[0].message
