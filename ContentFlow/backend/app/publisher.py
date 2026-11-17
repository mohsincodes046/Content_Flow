"""Background publisher: sends due post targets to Facebook and Instagram.

Guarantees:
  * A target is claimed atomically (queued -> publishing) under the write lock, so
    concurrent workers never publish it twice.
  * Only failures where Meta clearly answered "not now" (rate limits, temporary
    errors, 5xx) are retried automatically, with backoff. A network timeout may
    mean the post went out, so it is never retried automatically.
  * Expired or revoked tokens flag the account as needing reconnection.
  * A post is "published" only when Meta returned its id.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from app import linkedin_api, media, meta_graph, tiktok_api
from app.config import env_int, publisher_interval_seconds
from app.database import connect_database, utc_now
from app.posts import add_event, post_media, refresh_publish_status
from app.security import token_cipher

logger = logging.getLogger(__name__)

RETRY_DELAYS = (timedelta(minutes=2), timedelta(minutes=10), timedelta(minutes=30))
STALE_CLAIM = timedelta(minutes=15)
BATCH_SIZE = 20


def max_attempts() -> int:
    return env_int("CONTENT_FLOW_PUBLISH_MAX_ATTEMPTS", 3)


def recover_interrupted(now: Optional[datetime] = None) -> int:
    """Targets left "publishing" by a crash: Meta may or may not have received them."""
    cutoff = ((now or datetime.now(timezone.utc)) - STALE_CLAIM).isoformat()
    with connect_database() as connection:
        connection.lock_for_write()
        rows = connection.execute(
            "SELECT id, post_id FROM post_targets WHERE status = 'publishing' AND (claimed_at IS NULL OR claimed_at < ?)",
            (cutoff,),
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE post_targets SET status = 'failed', last_error = ? WHERE id = ?",
                ("Publishing was interrupted. Check the account to see whether the post went out before retrying.", row["id"]),
            )
            refresh_publish_status(connection, row["post_id"])
    return len(rows)


def _claim(now: datetime, post_id: Optional[str]) -> list[str]:
    stamp = now.isoformat()
    with connect_database() as connection:
        connection.lock_for_write()
        query = (
            "SELECT post_targets.id, post_targets.post_id FROM post_targets JOIN posts ON posts.id = post_targets.post_id "
            "WHERE post_targets.status = 'queued' AND posts.status IN ('scheduled', 'publishing') "
            "AND posts.scheduled_at <= ? AND (post_targets.next_attempt_at IS NULL OR post_targets.next_attempt_at <= ?)"
        )
        params: list = [stamp, stamp]
        if post_id:
            query += " AND posts.id = ?"
            params.append(post_id)
        rows = connection.execute(query + f" ORDER BY posts.scheduled_at LIMIT {BATCH_SIZE}", params).fetchall()
        claimed = []
        for row in rows:
            updated = connection.execute(
                "UPDATE post_targets SET status = 'publishing', claimed_at = ? WHERE id = ? AND status = 'queued'",
                (stamp, row["id"]),
            )
            if updated.rowcount:
                claimed.append(row["id"])
                connection.execute(
                    "UPDATE posts SET status = 'publishing', updated_at = ? WHERE id = ? AND status = 'scheduled'",
                    (stamp, row["post_id"]),
                )
    return claimed


def _save_tokens(account_id: str, tokens: dict) -> None:
    with connect_database() as connection:
        connection.execute(
            "UPDATE social_accounts SET encrypted_tokens = ?, expires_at = ?, updated_at = ? WHERE id = ?",
            (token_cipher().encrypt(json.dumps(tokens).encode("utf-8")).decode("ascii"), tokens.get("expires_at"),
             utc_now(), account_id),
        )


async def _send(target: dict, post: dict, account: dict, media_rows: list[dict]) -> meta_graph.PublishResult:
    tokens = json.loads(token_cipher().decrypt(account["encrypted_tokens"].encode("ascii")))
    caption = target["caption_override"] if target["caption_override"] is not None else post["caption"]
    if target["platform"] == "tiktok":
        if tiktok_api.needs_refresh(tokens):
            tokens = await tiktok_api.refresh(tokens)
            _save_tokens(account["id"], tokens)
        video = media_rows[0]
        return await tiktok_api.publish_video(tokens["access_token"], caption, await asyncio.to_thread(media.local_file, video["storage_name"]),
                                              video["media_type"])
    if target["platform"] == "linkedin":
        if linkedin_api.expired(tokens):
            raise meta_graph.GraphError("The LinkedIn connection has expired. Reconnect it.", code=190)
        images = [(await asyncio.to_thread(media.local_file, m["storage_name"]), m["media_type"]) for m in media_rows]
        return await linkedin_api.publish(account["account_id"], tokens["access_token"], caption, images)
    token = tokens.get("access_token")
    if not token:
        raise meta_graph.GraphError("No access token is stored for this account. Reconnect it.", code=190)
    if target["platform"] == "facebook":
        files = [meta_graph.MediaFile(await asyncio.to_thread(media.local_file, m["storage_name"]), m["filename"], m["media_type"])
                 for m in media_rows]
        return await meta_graph.publish_facebook(account["account_id"], token, caption, files)
    if target["platform"] == "instagram":
        items = [("image/jpeg" if m["media_type"].startswith("image/") else m["media_type"],
                  await asyncio.to_thread(media.instagram_media_url, m["storage_name"], m["media_type"]))
                 for m in media_rows]
        return await meta_graph.publish_instagram(account["account_id"], token, caption, items)
    raise meta_graph.GraphError(f"Publishing to {target['platform']} is not available yet.")


async def publish_target(target_id: str) -> None:
    started = utc_now()
    with connect_database() as connection:
        target = dict(connection.execute("SELECT * FROM post_targets WHERE id = ?", (target_id,)).fetchone())
        post = dict(connection.execute("SELECT * FROM posts WHERE id = ?", (target["post_id"],)).fetchone())
        account_row = connection.execute(
            "SELECT * FROM social_accounts WHERE id = ? AND workspace_id = ?",
            (target["social_account_id"], post["workspace_id"]),
        ).fetchone() if target["social_account_id"] else None
        account = dict(account_row) if account_row else None
        media_rows = [dict(row) for row in post_media(connection, post["id"])]

    outcome, error_text, result, retry_at = "failed", None, None, None
    try:
        if account is None:
            raise meta_graph.GraphError("The account was disconnected. Connect it again or remove it from the post.")
        if account["status"] == "needs_reconnect":
            raise meta_graph.GraphError("This account needs to be reconnected before it can publish.", code=190)
        result = await _send(target, post, account, media_rows)
        outcome = "published"
    except meta_graph.GraphError as error:
        error_text = error.message
        attempt_number = target["attempts"] + 1
        if error.needs_reconnect and account is not None:
            with connect_database() as connection:
                connection.execute(
                    "UPDATE social_accounts SET status = 'needs_reconnect', last_error = ?, last_checked_at = ? WHERE id = ?",
                    (error.message[:500], utc_now(), account["id"]),
                )
        elif error.status == 0 and error.transient:
            error_text = (f"{error.message} Meta did not confirm the result, so it was not retried automatically. "
                          "Check the account before retrying.")
        elif error.retryable and attempt_number < max_attempts():
            outcome = "retry"
            delay = RETRY_DELAYS[min(attempt_number - 1, len(RETRY_DELAYS) - 1)]
            retry_at = (datetime.now(timezone.utc) + delay).isoformat()
    except media.MediaError as error:
        error_text = str(error)
    except Exception:
        logger.exception("Unexpected error publishing target %s", target_id)
        error_text = "An unexpected error occurred while publishing. Details are in the server logs."

    finished = utc_now()
    with connect_database() as connection:
        connection.lock_for_write()
        if outcome == "published":
            connection.execute(
                "UPDATE post_targets SET status = 'published', attempts = attempts + 1, external_id = ?, external_url = ?, "
                "published_at = ?, last_error = NULL, next_attempt_at = NULL WHERE id = ?",
                (result.external_id, result.url, finished, target_id),
            )
            add_event(connection, post["id"], None, "published", f"{target['platform']}: {target['account_name']}")
            connection.execute(
                "UPDATE social_accounts SET status = 'active', last_error = NULL, last_checked_at = ? WHERE id = ?",
                (finished, account["id"]),
            )
        else:
            new_status = "queued" if outcome == "retry" else "failed"
            connection.execute(
                "UPDATE post_targets SET status = ?, attempts = attempts + 1, last_error = ?, next_attempt_at = ? WHERE id = ?",
                (new_status, (error_text or "")[:1000], retry_at, target_id),
            )
            add_event(connection, post["id"], None, "retry_scheduled" if outcome == "retry" else "failed",
                      f"{target['platform']}: {target['account_name']}: {error_text}")
        connection.execute(
            "INSERT INTO publish_attempts (id, target_id, started_at, finished_at, outcome, error, external_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), target_id, started, finished, outcome, error_text, result.external_id if result else None),
        )
        refresh_publish_status(connection, post["id"])
    log = logger.info if outcome == "published" else logger.warning
    log("Target %s (%s) %s%s", target_id, target["platform"], outcome, f": {error_text}" if error_text else "")


async def publish_due(now: Optional[datetime] = None, post_id: Optional[str] = None) -> int:
    """Publish every due target (optionally only one post's). Returns how many were attempted."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    attempted = 0
    while True:
        claimed = _claim(current, post_id)
        if not claimed:
            return attempted
        for target_id in claimed:
            await publish_target(target_id)
            attempted += 1


async def run_publisher_scheduler() -> None:
    interval = publisher_interval_seconds()
    while True:
        try:
            recover_interrupted()
            await publish_due()
        except Exception:
            logger.exception("The publisher could not process its queue.")
        await asyncio.sleep(interval)
