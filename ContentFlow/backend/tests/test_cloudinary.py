"""Cloudinary storage: signed direct uploads, registration from Cloudinary's own record,
publishing with Cloudinary URLs, viewing and deleting. Cloudinary's HTTP API is mocked."""
from __future__ import annotations

import hashlib
from typing import Any

import httpx
import pytest
from media_samples import jpeg
from test_posts import FakeMeta, env, upload  # noqa: F401  (fixture re-export)

from app import media

CLOUD = "cloudinary://key123:secret456@democloud"


@pytest.fixture()
def cloud(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("CLOUDINARY_URL", CLOUD)
    state: dict[str, Any] = {"resources": {}, "destroyed": [], "downloads": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/resources/" in url:
            assert request.headers["authorization"].startswith("Basic ")
            resource_type = url.split("/resources/")[1].split("/")[0]
            public_id = url.split("/upload/", 1)[1]
            found = state["resources"].get(public_id)
            if not found or found["resource_type"] != resource_type:
                return httpx.Response(404, json={"error": {"message": "Resource not found"}})
            return httpx.Response(200, json=found)
        if url.endswith("/destroy"):
            state["destroyed"].append(dict(httpx.QueryParams(request.content.decode())))
            return httpx.Response(200, json={"result": "ok"})
        if url.startswith("https://res.cloudinary.com/"):
            state["downloads"] += 1
            return httpx.Response(200, content=jpeg())
        return httpx.Response(500)

    transport = httpx.MockTransport(handle)
    real_client = httpx.Client

    def get(url: str, **kwargs: Any) -> httpx.Response:
        with real_client(transport=transport) as c:
            return c.get(url, **{k: v for k, v in kwargs.items() if k != "timeout"})

    def post(url: str, **kwargs: Any) -> httpx.Response:
        with real_client(transport=transport) as c:
            return c.post(url, **{k: v for k, v in kwargs.items() if k != "timeout"})

    class _Stream:
        def __init__(self, method: str, url: str, **kwargs: Any) -> None:
            self.client = real_client(transport=transport)
            self.response = self.client.send(self.client.build_request(method, url), stream=True)

        def __enter__(self) -> httpx.Response:
            return self.response

        def __exit__(self, *exc: Any) -> None:
            self.response.close()
            self.client.close()

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "stream", _Stream)
    yield state


def direct_upload(c, cloud: dict, resource_type: str = "image", fmt: str = "png", size: int = 1234,
                  width: int = 1080, height: int = 1080) -> dict:
    target = c.get("/api/assets/upload-target").json()
    assert target["mode"] == "cloudinary"
    public_id = target["fields"]["public_id"]
    # What the browser's upload to Cloudinary leaves behind:
    cloud["resources"][public_id] = {"public_id": public_id, "resource_type": resource_type, "format": fmt,
                                     "bytes": size, "width": width, "height": height}
    return target


def test_signature_matches_cloudinary_algorithm() -> None:
    params = {"timestamp": 1315060510, "public_id": "sample_image", "eager": "w_400,h_300,c_pad|w_260,h_200,c_crop"}
    # Example from Cloudinary's "Generating authentication signatures" documentation.
    assert media.cloudinary_sign(params, "abcd") == hashlib.sha1(
        b"eager=w_400,h_300,c_pad|w_260,h_200,c_crop&public_id=sample_image&timestamp=1315060510abcd").hexdigest()
    assert media.cloudinary_sign(params, "abcd") == "bfd09f95f331f558cbd1320e67aa8d488770583e"


def test_local_mode_when_cloudinary_is_not_configured(env: dict) -> None:
    assert env["editor"].get("/api/assets/upload-target").json() == {"mode": "local"}
    assert env["editor"].post("/api/assets/cloudinary", json={"asset_id": "0" * 8 + "-0000-0000-0000-" + "0" * 12}).status_code == 409


def test_signed_target_and_registration_use_cloudinarys_record(env: dict, cloud: dict) -> None:
    editor, client = env["editor"], env["client"]
    assert client.get("/api/assets/upload-target").status_code == 403
    target = direct_upload(editor, cloud)
    fields = target["fields"]
    assert target["upload_url"] == "https://api.cloudinary.com/v1_1/democloud/auto/upload"
    assert fields["api_key"] == "key123" and "secret456" not in str(target)
    me = editor.get("/api/auth/me").json()
    assert fields["public_id"] == f"contentflow/{me['workspace_id']}/{target['asset_id']}"
    signed = {k: v for k, v in fields.items() if k not in ("api_key", "signature")}
    assert fields["signature"] == media.cloudinary_sign(signed, "secret456")

    response = editor.post("/api/assets/cloudinary", json={"asset_id": target["asset_id"], "filename": "C:\\pics\\square.png"})
    assert response.status_code == 201, response.text
    asset = response.json()
    assert (asset["media_type"], asset["size"], asset["width"], asset["filename"]) == ("image/png", 1234, 1080, "square.png")
    assert editor.post("/api/assets/cloudinary", json={"asset_id": target["asset_id"]}).status_code == 409

    view = editor.get(f"/api/assets/{asset['id']}/content", follow_redirects=False)
    assert view.status_code == 302
    assert view.headers["location"] == f"https://res.cloudinary.com/democloud/image/upload/{fields['public_id']}.png"


def test_registration_rejects_missing_unsupported_and_oversized_uploads(env: dict, cloud: dict) -> None:
    editor = env["editor"]
    missing = editor.get("/api/assets/upload-target").json()
    assert editor.post("/api/assets/cloudinary", json={"asset_id": missing["asset_id"]}).status_code == 400

    odd = direct_upload(editor, cloud, "image", "tiff")
    assert editor.post("/api/assets/cloudinary", json={"asset_id": odd["asset_id"]}).status_code == 415
    huge = direct_upload(editor, cloud, "video", "mp4", size=60 * 1024 * 1024)
    assert editor.post("/api/assets/cloudinary", json={"asset_id": huge["asset_id"]}).status_code == 413
    assert {d["public_id"] for d in cloud["destroyed"]} == {odd["fields"]["public_id"], huge["fields"]["public_id"]}
    assert editor.get("/api/assets").json() == []


def test_publishing_uses_cloudinary_urls_for_instagram_and_bytes_for_facebook(
    env: dict, cloud: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta = FakeMeta(monkeypatch)
    editor = env["editor"]
    image = direct_upload(editor, cloud, "image", "png")
    video = direct_upload(editor, cloud, "video", "mp4", width=1080, height=1920)
    ids = [editor.post("/api/assets/cloudinary", json={"asset_id": t["asset_id"], "filename": n}).json()["id"]
           for t, n in ((image, "a.png"), (video, "b.mp4"))]
    post = editor.post("/api/posts", json={"caption": "Hello", "asset_ids": ids[:1],
                                           "targets": [{"social_account_id": "fb"}, {"social_account_id": "ig"}]}).json()
    assert editor.post(f"/api/posts/{post['id']}/publish-now").status_code == 202
    assert editor.get(f"/api/posts/{post['id']}").json()["status"] == "published"
    sent = {call[0]: call for call in meta.calls}
    assert sent["instagram"][3] == [("image/jpeg",
        f"https://res.cloudinary.com/democloud/image/upload/c_limit,w_1440,q_90/{image['fields']['public_id']}.jpg")]
    assert sent["facebook"][3] == [("a.png", "image/png")]
    assert cloud["downloads"] == 1  # Facebook got the bytes, downloaded once and cached

    reel = editor.post("/api/posts", json={"caption": "Reel", "asset_ids": ids[1:], "targets": [{"social_account_id": "ig"}]}).json()
    editor.post(f"/api/posts/{reel['id']}/publish-now")
    assert meta.calls[-1][3] == [("video/mp4", f"https://res.cloudinary.com/democloud/video/upload/{video['fields']['public_id']}.mp4")]


def test_deleting_a_cloudinary_asset_removes_the_remote_file(env: dict, cloud: dict) -> None:
    editor = env["editor"]
    target = direct_upload(editor, cloud)
    asset_id = editor.post("/api/assets/cloudinary", json={"asset_id": target["asset_id"]}).json()["id"]
    assert editor.delete(f"/api/assets/{asset_id}").status_code == 204
    assert cloud["destroyed"][-1]["public_id"] == target["fields"]["public_id"]
    assert cloud["destroyed"][-1]["api_key"] == "key123"


def test_local_uploads_still_work_alongside(env: dict) -> None:
    assert upload(env["editor"])
