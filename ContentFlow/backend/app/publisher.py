from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta, timezone

import httpx

from app import config, social_oauth
from app.config import publisher_interval_seconds
from app.database import Row, connect_database
from app.schemas import ScheduledPostCreate
from app.security import token_cipher

logger = logging.getLogger(__name__)


def scheduled_post_utc(row: Row) -> datetime:
    local_datetime = datetime.combine(
        date.fromisoformat(row["scheduled_date"]),
        time.fromisoformat(row["scheduled_time"]),
    )
    local_timezone = timezone(timedelta(minutes=-row["timezone_offset_minutes"]))
    return local_datetime.replace(tzinfo=local_timezone).astimezone(timezone.utc)


def scheduled_create_utc(post: ScheduledPostCreate) -> datetime:
    local_datetime = datetime.combine(post.date, post.time)
    local_timezone = timezone(timedelta(minutes=-post.timezone_offset_minutes))
    return local_datetime.replace(tzinfo=local_timezone).astimezone(timezone.utc)


async def publish_due_scheduled_posts(now: datetime | None = None) -> None:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("Publisher time must be timezone-aware.")
    current_time = current_time.astimezone(timezone.utc)
    claimed_posts: list[Row] = []
    with connect_database() as connection:
        connection.lock_for_write()
        candidates = connection.execute(
            """
            SELECT * FROM scheduled_posts
            WHERE publish_status = 'scheduled'
                AND asset_id IS NOT NULL
                AND facebook_account_id IS NOT NULL
            ORDER BY scheduled_date, scheduled_time, created_at
            """
        ).fetchall()
        for row in candidates:
            if "facebook" not in json.loads(row["platforms_json"]):
                continue
            if scheduled_post_utc(row) > current_time:
                continue
            updated = connection.execute(
                """
                UPDATE scheduled_posts
                SET publish_status = 'publishing', publish_error = NULL
                WHERE id = ? AND publish_status = 'scheduled'
                """,
                (row["id"],),
            )
            if updated.rowcount:
                claimed_posts.append(row)

    for row in claimed_posts:
        try:
            cipher = token_cipher()
            with connect_database() as connection:
                account = connection.execute(
                    """
                    SELECT account_id, encrypted_tokens FROM social_accounts
                    WHERE id = ? AND user_id = ? AND provider = 'meta' AND platform = 'facebook'
                    """,
                    (row["facebook_account_id"], row["user_id"]),
                ).fetchone()
                asset = connection.execute(
                    """
                    SELECT filename, media_type, storage_name FROM assets
                    WHERE id = ? AND user_id = ?
                    """,
                    (row["asset_id"], row["user_id"]),
                ).fetchone()
            if account is None:
                raise ValueError("The selected Facebook Page is no longer connected.")
            if asset is None:
                raise ValueError("The scheduled image is no longer available.")
            if not asset["media_type"].startswith("image/"):
                raise ValueError("Facebook scheduled publishing currently supports images only.")
            media_path = config.UPLOAD_DIR / asset["storage_name"]
            tokens = json.loads(cipher.decrypt(account["encrypted_tokens"].encode("ascii")))
            access_token = tokens.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ValueError("The Facebook Page authorization has expired. Reconnect the Page.")
            external_post_id = await social_oauth.publish_facebook_photo(
                account["account_id"],
                access_token,
                media_path,
                asset["filename"],
                asset["media_type"],
                row["caption"],
            )
            with connect_database() as connection:
                connection.execute(
                    """
                    UPDATE scheduled_posts
                    SET publish_status = 'published', publish_error = NULL, published_post_id = ?
                    WHERE id = ? AND publish_status = 'publishing'
                    """,
                    (external_post_id, row["id"]),
                )
        except (httpx.HTTPError, OSError, RuntimeError, ValueError, KeyError) as error:
            message = str(error) or "Facebook could not publish this post."
            with connect_database() as connection:
                connection.execute(
                    """
                    UPDATE scheduled_posts
                    SET publish_status = 'failed', publish_error = ?
                    WHERE id = ? AND publish_status = 'publishing'
                    """,
                    (message[:500], row["id"]),
                )
            logger.exception("Facebook publishing failed for scheduled post %s.", row["id"])
        except Exception:
            with connect_database() as connection:
                connection.execute(
                    """
                    UPDATE scheduled_posts
                    SET publish_status = 'failed',
                        publish_error = 'An unexpected publishing error occurred. Check the backend logs.'
                    WHERE id = ? AND publish_status = 'publishing'
                    """,
                    (row["id"],),
                )
            logger.exception("Unexpected Facebook publishing failure for scheduled post %s.", row["id"])


async def run_publisher_scheduler() -> None:
    interval = publisher_interval_seconds()
    while True:
        try:
            await publish_due_scheduled_posts()
        except Exception:
            logger.exception("The scheduled-post publisher could not process its queue.")
        await asyncio.sleep(interval)
