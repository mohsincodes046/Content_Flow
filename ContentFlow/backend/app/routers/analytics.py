"""Analytics: Facebook Page and Instagram insights, post performance, publishing summary.

Unavailable data is reported as unavailable (with the reason), never as zero.
Results are cached for an hour per workspace, account or post, and date range.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query

from app import meta_graph
from app.database import Row, connect_database, utc_now
from app.routers.social import account_token, mark_account_status
from app.security import require_content_role

router = APIRouter()
CACHE_LIFETIME = timedelta(hours=1)
MAX_DAYS = 30


def _metric_json(metric: meta_graph.Metric) -> dict[str, Any]:
    return {"key": metric.key, "label": metric.label, "value": metric.value, "available": metric.available,
            "note": metric.note}


def _cached(workspace_id: str, key: str, refresh: bool) -> Optional[dict[str, Any]]:
    if refresh:
        return None
    with connect_database() as connection:
        row = connection.execute(
            "SELECT payload_json, fetched_at FROM analytics_cache WHERE cache_key = ? AND workspace_id = ?",
            (key, workspace_id),
        ).fetchone()
    if row and datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - CACHE_LIFETIME:
        return json.loads(row["payload_json"])
    return None


def _store(workspace_id: str, key: str, payload: dict[str, Any]) -> None:
    with connect_database() as connection:
        connection.execute("DELETE FROM analytics_cache WHERE cache_key = ?", (key,))
        connection.execute(
            "INSERT INTO analytics_cache (cache_key, workspace_id, payload_json, fetched_at) VALUES (?, ?, ?, ?)",
            (key, workspace_id, json.dumps(payload), payload["fetched_at"]),
        )


async def _account_report(user: Row, account: Row, days: int, refresh: bool) -> dict[str, Any]:
    until = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    since = until - timedelta(days=days)
    key = f"account:{account['id']}:{days}"
    cached = _cached(user["workspace_id"], key, refresh)
    base = {"account_id": account["id"], "platform": account["platform"], "account_name": account["account_name"],
            "profile_picture_url": account.get("profile_picture_url"), "days": days}
    if cached:
        return {**base, **cached, "cached": True}
    if account["status"] == "needs_reconnect":
        return {**base, "metrics": [], "followers": None, "fetched_at": None, "cached": False,
                "error": "This account needs to be reconnected before its insights can be read."}
    try:
        result = await meta_graph.account_insights(
            account["platform"], account["account_id"], account_token(account), int(since.timestamp()), int(until.timestamp()))
    except meta_graph.GraphError as error:
        with connect_database() as connection:
            mark_account_status(connection, account["id"], error if error.needs_reconnect else None)
        return {**base, "metrics": [], "followers": None, "fetched_at": None, "cached": False, "error": error.message}
    payload = {"metrics": [_metric_json(m) for m in result["metrics"]], "followers": result["followers"],
               "since": since.isoformat(), "until": until.isoformat(), "fetched_at": utc_now(), "error": None}
    _store(user["workspace_id"], key, payload)
    return {**base, **payload, "cached": False}


@router.get("/api/analytics/accounts")
async def account_analytics(
    user: Annotated[Row, Depends(require_content_role)],
    days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 28,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    with connect_database() as connection:
        accounts = [dict(row) for row in connection.execute(
            "SELECT * FROM social_accounts WHERE workspace_id = ? AND platform IN ('facebook', 'instagram') "
            "ORDER BY platform, account_name",
            (user["workspace_id"],),
        ).fetchall()]
    return [await _account_report(user, account, days, refresh) for account in accounts]


@router.get("/api/analytics/posts")
async def post_analytics(
    user: Annotated[Row, Depends(require_content_role)],
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """Performance of posts Content Flow published in the last `days` days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect_database() as connection:
        rows = [dict(row) for row in connection.execute(
            """
            SELECT post_targets.*, posts.title, posts.caption, social_accounts.id AS account_row_id,
                   social_accounts.account_id AS external_account_id, social_accounts.encrypted_tokens,
                   social_accounts.status AS account_status
            FROM post_targets JOIN posts ON posts.id = post_targets.post_id
            LEFT JOIN social_accounts ON social_accounts.id = post_targets.social_account_id
            WHERE posts.workspace_id = ? AND post_targets.status = 'published' AND post_targets.external_id IS NOT NULL
              AND post_targets.published_at >= ?
            ORDER BY post_targets.published_at DESC LIMIT 50
            """,
            (user["workspace_id"], since),
        ).fetchall()]
    results = []
    for row in rows:
        base = {"post_id": row["post_id"], "target_id": row["id"], "title": row["title"] or row["caption"][:60],
                "platform": row["platform"], "account_name": row["account_name"], "published_at": row["published_at"],
                "external_url": row["external_url"]}
        key = f"post:{row['id']}"
        cached = _cached(user["workspace_id"], key, refresh)
        if cached:
            results.append({**base, **cached, "cached": True})
            continue
        if row["account_row_id"] is None or row["account_status"] == "needs_reconnect":
            results.append({**base, "metrics": [], "fetched_at": None, "cached": False,
                            "error": "Reconnect this account to read the post's insights."})
            continue
        try:
            metrics = await meta_graph.post_insights(row["platform"], row["external_id"],
                                                     account_token({"encrypted_tokens": row["encrypted_tokens"]}))
        except meta_graph.GraphError as error:
            results.append({**base, "metrics": [], "fetched_at": None, "cached": False, "error": error.message})
            continue
        payload = {"metrics": [_metric_json(m) for m in metrics], "fetched_at": utc_now(), "error": None}
        _store(user["workspace_id"], key, payload)
        results.append({**base, **payload, "cached": False})
    return results


@router.get("/api/analytics/summary")
def publishing_summary(
    user: Annotated[Row, Depends(require_content_role)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """What Content Flow itself knows: posts and publishing outcomes in the period."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect_database() as connection:
        statuses = {row["status"]: row["n"] for row in connection.execute(
            "SELECT status, COUNT(*) AS n FROM posts WHERE workspace_id = ? GROUP BY status", (user["workspace_id"],)
        ).fetchall()}
        by_platform = [dict(row) for row in connection.execute(
            """
            SELECT post_targets.platform, post_targets.status, COUNT(*) AS n
            FROM post_targets JOIN posts ON posts.id = post_targets.post_id
            WHERE posts.workspace_id = ? AND (post_targets.published_at >= ? OR post_targets.status <> 'published')
            GROUP BY post_targets.platform, post_targets.status
            """,
            (user["workspace_id"], since),
        ).fetchall()]
        attempts = connection.execute(
            """
            SELECT outcome, COUNT(*) AS n FROM publish_attempts
            JOIN post_targets ON post_targets.id = publish_attempts.target_id
            JOIN posts ON posts.id = post_targets.post_id
            WHERE posts.workspace_id = ? AND publish_attempts.started_at >= ?
            GROUP BY outcome
            """,
            (user["workspace_id"], since),
        ).fetchall()
    return {"days": days, "posts_by_status": statuses, "targets_by_platform": by_platform,
            "attempts": {row["outcome"]: row["n"] for row in attempts}}
