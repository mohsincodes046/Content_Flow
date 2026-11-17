"""Analytics: Meta insights parsing, unavailable metrics, caching, isolation."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import config, database, main, meta_graph

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def graph(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    calls: list[httpx.Request] = []
    real = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path, params = request.url.path, dict(request.url.params)
        object_id = path.split("/")[2]
        if path.endswith("/insights"):
            metric = params["metric"]
            if metric == "page_views_total":  # a metric Meta has retired
                return httpx.Response(400, json={"error": {"message": "(#100) The value must be a valid insights metric", "code": 100}})
            if object_id == "ig-1":
                return httpx.Response(200, json={"data": [{"name": metric, "total_value": {"value": 120}}]})
            if object_id == "fb-post-1" and metric == "post_reactions_by_type_total":
                return httpx.Response(200, json={"data": [{"name": metric, "values": [{"value": {"like": 9, "love": 3}}]}]})
            if object_id == "fb-post-1":
                return httpx.Response(200, json={"data": [{"name": metric, "values": [{"value": 40}]}]})
            if metric == "page_media_view":
                return httpx.Response(200, json={"data": [{"name": metric, "values": [{"value": 10}, {"value": 15}, {"value": 5}]}]})
            if metric == "page_total_media_view_unique":
                return httpx.Response(200, json={"data": []})  # no data for the period
            return httpx.Response(200, json={"data": [{"name": metric, "values": [{"value": 2}, {"value": 3}]}]})
        if object_id == "fb-1":
            return httpx.Response(200, json={"followers_count": 1500})
        if object_id == "ig-1":
            return httpx.Response(200, json={"followers_count": 4821, "media_count": 80})
        if object_id == "fb-post-1":
            return httpx.Response(200, json={"shares": {"count": 4}, "comments": {"summary": {"total_count": 7}}})
        return httpx.Response(404, json={"error": {"message": "unknown", "code": 803}})

    monkeypatch.setattr(meta_graph.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handle), **kw))
    return calls


@pytest.fixture()
def owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "test.sqlite3")
    monkeypatch.setenv("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CONTENT_FLOW_REGISTER_PER_HOUR_LIMIT", "100")
    with TestClient(main.app) as client:
        client.post("/api/auth/register", json={"full_name": "Owner", "workspace_name": "W",
                                                "email": "o@example.com", "password": PASSWORD})
        me = client.get("/api/auth/me").json()
        from app.security import token_cipher

        with database.connect_database() as connection:
            for row_id, platform, external in (("fb", "facebook", "fb-1"), ("ig", "instagram", "ig-1")):
                connection.execute(
                    "INSERT INTO social_accounts (id, user_id, workspace_id, provider, platform, account_id, account_name, "
                    "account_type, encrypted_tokens, expires_at, connected_at, updated_at) "
                    "VALUES (?, ?, ?, 'meta', ?, ?, ?, 'page', ?, NULL, ?, ?)",
                    (row_id, me["id"], me["workspace_id"], platform, external, f"{platform} account",
                     token_cipher().encrypt(b'{"access_token": "tok"}').decode(), database.utc_now(), database.utc_now()),
                )
            now = database.utc_now()
            connection.execute(
                "INSERT INTO posts (id, workspace_id, title, caption, status, planned_platforms_json, created_at, updated_at) "
                "VALUES ('p1', ?, 'Launch', 'c', 'published', '[]', ?, ?)", (me["workspace_id"], now, now))
            connection.execute(
                "INSERT INTO post_targets (id, post_id, social_account_id, platform, account_name, status, external_id, "
                "external_url, published_at) VALUES ('t1', 'p1', 'fb', 'facebook', 'facebook account', 'published', "
                "'fb-post-1', 'https://facebook.com/fb-post-1', ?)", (now,))
        yield client


def metrics_of(report: dict) -> dict:
    return {m["key"]: m for m in report["metrics"]}


def test_account_insights_with_unavailable_metrics(owner: TestClient, graph: list) -> None:
    reports = {r["platform"]: r for r in owner.get("/api/analytics/accounts?days=7").json()}

    facebook = metrics_of(reports["facebook"])
    assert facebook["page_media_view"]["value"] == 30  # daily values summed
    assert facebook["page_post_engagements"]["value"] == 5
    assert facebook["page_views_total"] == {"key": "page_views_total", "label": "Profile visits", "value": None,
                                            "available": False, "note": "(#100) The value must be a valid insights metric"}
    assert facebook["page_total_media_view_unique"]["available"] is False  # no data is not zero
    assert reports["facebook"]["followers"] == 1500

    instagram = metrics_of(reports["instagram"])
    assert {k: m["value"] for k, m in instagram.items()} == {
        "views": 120, "reach": 120, "accounts_engaged": 120, "total_interactions": 120}
    assert reports["instagram"]["followers"] == 4821
    insight_call = next(r for r in graph if r.url.path.endswith("/ig-1/insights"))
    assert insight_call.url.params["metric_type"] == "total_value"
    assert int(insight_call.url.params["until"]) - int(insight_call.url.params["since"]) == 7 * 86400


def test_results_are_cached_until_refresh(owner: TestClient, graph: list) -> None:
    owner.get("/api/analytics/accounts?days=7")
    first = len(graph)
    cached = owner.get("/api/analytics/accounts?days=7").json()
    assert len(graph) == first and all(r["cached"] for r in cached)
    owner.get("/api/analytics/accounts?days=7&refresh=true")
    assert len(graph) == 2 * first


def test_post_insights(owner: TestClient, graph: list) -> None:
    (post,) = owner.get("/api/analytics/posts").json()
    values = {m["key"]: m["value"] for m in post["metrics"]}
    assert values == {"post_media_view": 40, "post_total_media_view_unique": 40, "post_reactions_by_type_total": 12,
                      "post_clicks": 40, "comments": 7, "shares": 4}
    assert post["external_url"] == "https://facebook.com/fb-post-1"


def test_expired_connections_are_reported_not_hidden(owner: TestClient, graph: list) -> None:
    with database.connect_database() as connection:
        connection.execute("UPDATE social_accounts SET status = 'needs_reconnect' WHERE id = 'fb'")
    reports = {r["platform"]: r for r in owner.get("/api/analytics/accounts").json()}
    assert "reconnected" in reports["facebook"]["error"] and reports["facebook"]["metrics"] == []
    assert not any("/fb-1/" in str(r.url) for r in graph)  # no call with a known-bad token
    assert "Reconnect" in owner.get("/api/analytics/posts").json()[0]["error"]


def test_publishing_summary_and_isolation(owner: TestClient, graph: list) -> None:
    summary = owner.get("/api/analytics/summary").json()
    assert summary["posts_by_status"] == {"published": 1}
    assert summary["targets_by_platform"] == [{"platform": "facebook", "status": "published", "n": 1}]
    with TestClient(main.app) as other:
        other.post("/api/auth/register", json={"full_name": "X", "workspace_name": "X", "email": "x@example.com",
                                               "password": PASSWORD})
        assert other.get("/api/analytics/accounts").json() == []
        assert other.get("/api/analytics/posts").json() == []
        assert other.get("/api/analytics/summary").json()["posts_by_status"] == {}
