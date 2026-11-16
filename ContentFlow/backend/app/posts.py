"""Post rules shared by the API and the publisher."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status

from app import content_rules
from app.database import DatabaseConnection, Row, utc_now
from app.schemas import (
    AssetResponse,
    PostEventResponse,
    PostResponse,
    PostSchedule,
    PostTargetResponse,
    ValidationIssue,
)

EDITABLE_STATUSES = {"draft", "in_review", "changes_requested", "approved", "rejected", "scheduled", "failed"}
LOCKED_STATUSES = {"publishing", "published", "partially_published"}


def to_utc(schedule: PostSchedule) -> str:
    """Convert a local wall-clock time in an IANA zone to UTC (handles daylight saving)."""
    try:
        zone = ZoneInfo(schedule.timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"Unknown timezone {schedule.timezone!r}.") from error
    local = schedule.local_datetime.replace(tzinfo=None, second=0, microsecond=0)
    return local.replace(tzinfo=zone).astimezone(timezone.utc).isoformat()


def require_future(scheduled_at: str) -> None:
    if datetime.fromisoformat(scheduled_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Choose a time in the future, or use Publish now.")


def add_event(connection: DatabaseConnection, post_id: str, actor_user_id: Optional[str], kind: str,
              message: Optional[str] = None) -> None:
    connection.execute(
        "INSERT INTO post_events (id, post_id, actor_user_id, seq, kind, message, created_at) "
        "VALUES (?, ?, ?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM post_events WHERE post_id = ?), ?, ?, ?)",
        (str(uuid4()), post_id, actor_user_id, post_id, kind, message, utc_now()),
    )


def post_media(connection: DatabaseConnection, post_id: str) -> list[Row]:
    return connection.execute(
        """
        SELECT assets.* FROM post_media JOIN assets ON assets.id = post_media.asset_id
        WHERE post_media.post_id = ? ORDER BY post_media.position
        """,
        (post_id,),
    ).fetchall()


def post_targets(connection: DatabaseConnection, post_id: str) -> list[Row]:
    return connection.execute(
        """
        SELECT post_targets.*, social_accounts.status AS account_status, social_accounts.account_name AS current_name
        FROM post_targets LEFT JOIN social_accounts ON social_accounts.id = post_targets.social_account_id
        WHERE post_targets.post_id = ? ORDER BY post_targets.platform, post_targets.account_name
        """,
        (post_id,),
    ).fetchall()


def validation_issues(post: Row, media_rows: list[Row], target_rows: list[Row]) -> list[ValidationIssue]:
    media_items = [content_rules.Media(m["media_type"], m.get("width"), m.get("height"), m["size"]) for m in media_rows]
    issues: list[ValidationIssue] = []
    for target in target_rows:
        if target["status"] in ("published", "cancelled"):
            continue
        caption = target["caption_override"] if target["caption_override"] is not None else post["caption"]
        name = target.get("current_name") or target["account_name"]
        if target["social_account_id"] is None:
            issues.append(ValidationIssue(platform=target["platform"], account=name,
                                          message="This account was disconnected. Remove it or connect it again."))
            continue
        if target.get("account_status") == "needs_reconnect":
            issues.append(ValidationIssue(platform=target["platform"], account=name,
                                          message="This account needs to be reconnected before publishing."))
        for issue in content_rules.check(target["platform"], caption, media_items, name):
            issues.append(ValidationIssue(platform=issue.platform, account=issue.account, message=issue.message))
    return issues


def load_post(connection: DatabaseConnection, post_id: str, workspace_id: str, *, include_events: bool = True) -> PostResponse:
    post = connection.execute(
        """
        SELECT posts.*, reviewer.full_name AS reviewer_name, creator.full_name AS created_by_name
        FROM posts LEFT JOIN users AS reviewer ON reviewer.id = posts.reviewer_user_id
        LEFT JOIN users AS creator ON creator.id = posts.created_by_user_id
        WHERE posts.id = ? AND posts.workspace_id = ?
        """,
        (post_id, workspace_id),
    ).fetchone()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    media_rows = post_media(connection, post_id)
    target_rows = post_targets(connection, post_id)
    events = connection.execute(
        """
        SELECT post_events.*, users.full_name AS actor_name FROM post_events
        LEFT JOIN users ON users.id = post_events.actor_user_id
        WHERE post_events.post_id = ? ORDER BY post_events.seq
        """,
        (post_id,),
    ).fetchall() if include_events else []
    return PostResponse(
        id=post["id"], title=post["title"], caption=post["caption"], status=post["status"],
        scheduled_at=post["scheduled_at"], timezone=post["timezone"],
        planned_platforms=json.loads(post["planned_platforms_json"] or "[]"),
        reviewer_user_id=post["reviewer_user_id"], reviewer_name=post["reviewer_name"],
        created_by_name=post["created_by_name"], created_at=post["created_at"], updated_at=post["updated_at"],
        media=[AssetResponse(id=m["id"], filename=m["filename"], media_type=m["media_type"], size=m["size"],
                             width=m.get("width"), height=m.get("height"), created_at=m["created_at"])
               for m in media_rows],
        targets=[PostTargetResponse(
            id=t["id"], social_account_id=t["social_account_id"], platform=t["platform"],
            account_name=t.get("current_name") or t["account_name"], caption_override=t["caption_override"],
            status=t["status"], attempts=t["attempts"], next_attempt_at=t["next_attempt_at"],
            last_error=t["last_error"], external_id=t["external_id"], external_url=t["external_url"],
            published_at=t["published_at"], account_status=t.get("account_status"),
        ) for t in target_rows],
        issues=validation_issues(post, media_rows, target_rows),
        events=[PostEventResponse(id=e["id"], kind=e["kind"], message=e["message"], actor_name=e["actor_name"],
                                  created_at=e["created_at"]) for e in events],
    )


def refresh_publish_status(connection: DatabaseConnection, post_id: str) -> str:
    """Derive the post's status from its targets once publishing has started."""
    statuses = [row["status"] for row in connection.execute(
        "SELECT status FROM post_targets WHERE post_id = ? AND status <> 'cancelled'", (post_id,)
    ).fetchall()]
    current = connection.execute("SELECT status FROM posts WHERE id = ?", (post_id,)).fetchone()["status"]
    if not statuses or current not in ("scheduled", "publishing", "failed", "partially_published"):
        return current
    if any(s in ("queued", "publishing") for s in statuses):
        new = "publishing" if any(s in ("publishing", "published", "failed") for s in statuses) else "scheduled"
    elif all(s == "published" for s in statuses):
        new = "published"
    elif any(s == "published" for s in statuses):
        new = "partially_published"
    else:
        new = "failed"
    if new != current:
        connection.execute("UPDATE posts SET status = ?, updated_at = ? WHERE id = ?", (new, utc_now(), post_id))
    return new
