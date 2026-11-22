"""AI content studio: caption variations, tone/length/CTA, the content tools and image
generation. Every provider call is mocked here; no real AI request is made."""
from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient
from test_api import client  # noqa: F401  (fixture re-export)

from app import ai as ai_service


@pytest.fixture(autouse=True)
def gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_FLOW_AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("CONTENT_FLOW_AI_IMAGE_MODEL", raising=False)


def fake(monkeypatch: pytest.MonkeyPatch, reply: dict, seen: list) -> None:
    async def provider(provider: str, api_key: str, model: str, prompt: str, timeout: float = 45, **kwargs: object) -> str:
        seen.append((prompt, kwargs.get("user_message")))
        return "```json\n" + json.dumps(reply) + "\n```"  # fenced, as some models do

    monkeypatch.setattr(ai_service, "call_caption_provider", provider)


def test_caption_variations_tone_length_and_cta(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list = []
    posts = [{"platform": p, "variant": 7, "caption": f"{p} {n}", "hashtags": ["Launch"], "call_to_action": "Shop now"}
             for p in ("linkedin", "tiktok") for n in (1, 2)]
    fake(monkeypatch, {"posts": posts}, seen)
    response = client.post("/api/ai/captions", json={
        "topic": "Spring menu", "audience": "Food lovers", "platforms": ["linkedin", "tiktok"],
        "tone": "professional", "length": "short", "variations": 2, "include_call_to_action": True,
    })
    assert response.status_code == 200, response.text
    got = response.json()["posts"]
    assert [(p["platform"], p["variant"]) for p in got] == [("linkedin", 1), ("linkedin", 2), ("tiktok", 1), ("tiktok", 2)]
    assert got[0]["call_to_action"] == "Shop now"
    prompt = seen[0][0]
    assert "exactly 2 clearly different variation(s)" in prompt
    assert "polished, credible" in prompt and "short:" in prompt and "call to action" in prompt
    assert "- linkedin:" in prompt and "- tiktok:" in prompt


def test_caption_variation_count_is_enforced(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, {"posts": [{"platform": "instagram", "caption": "only one", "hashtags": []}]}, [])
    response = client.post("/api/ai/captions", json={
        "topic": "x", "audience": "y", "platforms": ["instagram"], "variations": 2})
    assert response.status_code == 502


def test_old_caption_requests_still_work(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, {"posts": [{"platform": "facebook", "caption": "Hi", "hashtags": []}]}, [])
    response = client.post("/api/ai/captions", json={"topic": "x", "audience": "y", "platforms": ["facebook"]})
    assert response.status_code == 200
    assert response.json()["posts"][0] | {} == {"platform": "facebook", "caption": "Hi", "hashtags": [],
                                                "call_to_action": "", "variant": 1}


@pytest.mark.parametrize("task", ["ideas", "rewrite", "hashtags", "call_to_action"])
def test_content_tools(client: TestClient, monkeypatch: pytest.MonkeyPatch, task: str) -> None:
    seen: list = []
    fake(monkeypatch, {"items": [{"platform": "instagram", "title": "One", "text": "Do this", "hashtags": ["a"]},
                                 {"platform": None, "title": "Two", "text": "Or that", "hashtags": []},
                                 {"platform": "youtube", "title": "Off", "text": "not requested", "hashtags": []}]}, seen)
    response = client.post("/api/ai/assist", json={"task": task, "text": "Our new bakery opens Friday",
                                                   "platforms": ["instagram", "facebook"], "count": 2, "tone": "playful"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task"] == task and [i["title"] for i in body["items"]] == ["One", "Two"]  # unrequested platform dropped
    assert "Our new bakery opens Friday" in seen[0][0] and "light, witty" in seen[0][0]


def test_repurpose_needs_every_platform(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, {"items": [{"platform": "instagram", "text": "IG version"}]}, [])
    payload = {"task": "repurpose", "text": "A long blog post", "platforms": ["instagram", "linkedin"]}
    assert client.post("/api/ai/assist", json=payload).status_code == 502
    fake(monkeypatch, {"items": [{"platform": "instagram", "text": "IG"}, {"platform": "linkedin", "text": "LI"}]}, [])
    assert [i["platform"] for i in client.post("/api/ai/assist", json=payload).json()["items"]] == ["instagram", "linkedin"]


def test_assist_validation_and_quota(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.post("/api/ai/assist", json={"task": "summarise", "text": "x", "platforms": ["instagram"]}).status_code == 422
    assert client.post("/api/ai/assist", json={"task": "ideas", "text": "  ", "platforms": ["instagram"]}).status_code == 422
    monkeypatch.setenv("CONTENT_FLOW_AI_DAILY_LIMIT", "1")
    fake(monkeypatch, {"items": [{"text": "idea"}]}, [])
    payload = {"task": "ideas", "text": "coffee", "platforms": ["instagram"]}
    assert client.post("/api/ai/assist", json=payload).status_code == 200
    limited = client.post("/api/ai/assist", json=payload)
    assert limited.status_code == 429 and "AI generations" in limited.json()["detail"]


def test_provider_errors_are_explained(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    async def busy(*args: object, **kwargs: object) -> str:
        raise httpx.HTTPStatusError("busy", request=httpx.Request("POST", "https://x"), response=httpx.Response(429))

    monkeypatch.setattr(ai_service, "call_caption_provider", busy)
    response = client.post("/api/ai/assist", json={"task": "ideas", "text": "x", "platforms": ["tiktok"]})
    assert response.status_code == 503 and "usage limit" in response.json()["detail"]


def test_image_generation_only_when_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    usage = client.get("/api/ai/usage").json()
    assert usage["image_generation_enabled"] is False
    off = client.post("/api/ai/image", json={"prompt": "a sunny cafe"})
    assert off.status_code == 503 and "not set up" in off.json()["detail"]

    monkeypatch.setenv("CONTENT_FLOW_AI_IMAGE_MODEL", "gemini-image-test")
    monkeypatch.setenv("CONTENT_FLOW_AI_IMAGE_DAILY_LIMIT", "1")
    calls: list = []

    async def fake_image(api_key: str, model: str, prompt: str, aspect_ratio: str, timeout: float = 90) -> tuple[str, bytes]:
        calls.append((model, aspect_ratio))
        return "image/png", b"\x89PNG fake"

    monkeypatch.setattr(ai_service, "generate_image", fake_image)
    made = client.post("/api/ai/image", json={"prompt": "a sunny cafe", "aspect_ratio": "4:5"})
    assert made.status_code == 200, made.text
    assert base64.b64decode(made.json()["data_base64"]) == b"\x89PNG fake" and calls == [("gemini-image-test", "4:5")]
    assert client.post("/api/ai/image", json={"prompt": "again"}).status_code == 429
    usage = client.get("/api/ai/usage").json()
    assert (usage["image_generation_enabled"], usage["images_used_last_24h"], usage["image_daily_limit"]) == (True, 1, 1)
    assert client.post("/api/ai/image", json={"prompt": "a sunny cafe", "aspect_ratio": "3:2"}).status_code == 422


def test_gemini_image_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import httpx

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path.endswith("/models/img-model:generateContent")
        assert body["generationConfig"] == {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}
        data = base64.b64encode(b"jpegbytes").decode()
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "here you go"}, {"inlineData": {"mimeType": "image/jpeg", "data": data}}]}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(ai_service.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handle), **kw))
    assert asyncio.run(ai_service.generate_image("k", "img-model", "p", "9:16")) == ("image/jpeg", b"jpegbytes")
