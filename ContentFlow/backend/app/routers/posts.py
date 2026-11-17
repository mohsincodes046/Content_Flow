"""Posts: drafts, platform versions, client review, scheduling, publishing and retries."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status

from app import publisher
from app.database import DatabaseConnection, Row, connect_database, utc_now
from app.posts import (
    EDITABLE_STATUSES,
    LOCKED_STATUSES,
    add_event,
    load_post,
    refresh_publish_status,
    require_future,
    to_utc,
)
from app.schemas import (
    PostBulkCreate,
    PostComment,
    PostCreate,
    PostResponse,
    PostReview,
    PostScheduleRequest,
    PostSubmit,
    PostWrite,
)
from app.security import CONTENT_ROLES, REVIEWERS, record_audit, require_content_role, require_member

router = APIRouter()


def _write_content(connection: DatabaseConnection, user: Row, post_id: str, payload: PostWrite) -> None:
    """Replace a post's media and targets after checking they belong to this workspace."""
    if payload.asset_ids:
        placeholders = ",".join("?" for _ in payload.asset_ids)
        found = {row["id"] for row in connection.execute(
            f"SELECT id FROM assets WHERE workspace_id = ? AND id IN ({placeholders})",
            [user["workspace_id"], *payload.asset_ids],
        ).fetchall()}
        if found != set(payload.asset_ids):
            raise HTTPException(status_code=400, detail="One or more media items could not be found.")
    accounts = {}
    if payload.targets:
        ids = [target.social_account_id for target in payload.targets]
        placeholders = ",".join("?" for _ in ids)
        accounts = {row["id"]: row for row in connection.execute(
            f"SELECT id, platform, account_name FROM social_accounts WHERE workspace_id = ? AND id IN ({placeholders})",
            [user["workspace_id"], *ids],
        ).fetchall()}
        if set(accounts) != set(ids):
            raise HTTPException(status_code=400, detail="Choose social accounts connected to this workspace.")

    connection.execute("DELETE FROM post_media WHERE post_id = ?", (post_id,))
    for position, asset_id in enumerate(payload.asset_ids):
        connection.execute("INSERT INTO post_media (post_id, position, asset_id) VALUES (?, ?, ?)",
                           (post_id, position, asset_id))
    existing = {row["social_account_id"]: row for row in connection.execute(
        "SELECT * FROM post_targets WHERE post_id = ?", (post_id,)
    ).fetchall()}
    wanted = {target.social_account_id: target for target in payload.targets}
    for account_id, row in existing.items():
        if account_id not in wanted and row["status"] != "published":
            connection.execute("DELETE FROM post_targets WHERE id = ?", (row["id"],))
    for account_id, target in wanted.items():
        override = target.caption_override if target.caption_override not in (None, "") else None
        if account_id in existing:
            connection.execute("UPDATE post_targets SET caption_override = ? WHERE id = ?",
                               (override, existing[account_id]["id"]))
        else:
            account = accounts[account_id]
            connection.execute(
                "INSERT INTO post_targets (id, post_id, social_account_id, platform, account_name, caption_override, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                (str(uuid4()), post_id, account_id, account["platform"], account["account_name"], override),
            )


def _check_reviewer(connection: DatabaseConnection, workspace_id: str, reviewer_user_id: str) -> None:
    member = connection.execute(
        "SELECT role FROM memberships WHERE workspace_id = ? AND user_id = ?", (workspace_id, reviewer_user_id)
    ).fetchone()
    if member is None or member["role"] not in REVIEWERS:
        raise HTTPException(status_code=400, detail="Choose a client, admin or owner of this workspace as the reviewer.")


def _schedule(connection: DatabaseConnection, user: Row, post_id: str, scheduled_at: str, timezone_name: Optional[str]) -> PostResponse:
    """Validate and queue every target of the post for `scheduled_at` (UTC)."""
    post = load_post(connection, post_id, user["workspace_id"], include_events=False)
    if post.reviewer_user_id and post.status not in ("approved", "scheduled", "failed", "partially_published"):
        raise HTTPException(status_code=409, detail="This post is waiting for review. It can be scheduled once approved.")
    if post.status in ("publishing", "published", "in_review", "rejected"):
        raise HTTPException(status_code=409, detail=f"A {post.status.replace('_', ' ')} post cannot be scheduled.")
    if not post.targets:
        raise HTTPException(status_code=422, detail="Choose at least one connected account to publish to.")
    if post.issues:
        raise HTTPException(status_code=422, detail="Fix these first: " + " ".join(
            f"[{i.account or i.platform}] {i.message}" for i in post.issues))
    clash = connection.execute(
        """
        SELECT 1 FROM post_targets mine JOIN post_targets other ON other.social_account_id = mine.social_account_id
        JOIN posts ON posts.id = other.post_id
        WHERE mine.post_id = ? AND other.post_id <> ? AND posts.workspace_id = ? AND posts.scheduled_at = ?
          AND other.status IN ('queued', 'publishing')
        """,
        (post_id, post_id, user["workspace_id"], scheduled_at),
    ).fetchone()
    if clash:
        raise HTTPException(status_code=409, detail="Another post is already scheduled for one of these accounts at that exact time.")
    connection.execute(
        "UPDATE posts SET status = 'scheduled', scheduled_at = ?, timezone = ?, updated_at = ? WHERE id = ?",
        (scheduled_at, timezone_name, utc_now(), post_id),
    )
    connection.execute(
        "UPDATE post_targets SET status = 'queued', next_attempt_at = NULL WHERE post_id = ? AND status IN ('pending', 'failed')",
        (post_id,),
    )
    add_event(connection, post_id, user["id"], "scheduled", scheduled_at)
    return load_post(connection, post_id, user["workspace_id"])


def _create(connection: DatabaseConnection, user: Row, payload: PostCreate) -> str:
    post_id = str(uuid4())
    now = utc_now()
    connection.execute(
        "INSERT INTO posts (id, workspace_id, created_by_user_id, title, caption, status, planned_platforms_json, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
        (post_id, user["workspace_id"], user["id"], payload.title.strip(), payload.caption,
         json.dumps(payload.planned_platforms), now, now),
    )
    _write_content(connection, user, post_id, payload)
    add_event(connection, post_id, user["id"], "created")
    if payload.schedule is not None:
        scheduled_at = to_utc(payload.schedule)
        connection.execute("UPDATE posts SET scheduled_at = ?, timezone = ? WHERE id = ?",
                           (scheduled_at, payload.schedule.timezone, post_id))
    if payload.action == "submit":
        if not payload.reviewer_user_id:
            raise HTTPException(status_code=422, detail="Choose who should review this post.")
        _submit(connection, user, post_id, payload.reviewer_user_id, "")
    elif payload.action == "schedule":
        if payload.schedule is None:
            raise HTTPException(status_code=422, detail="Choose when to publish.")
        scheduled_at = to_utc(payload.schedule)
        require_future(scheduled_at)
        _schedule(connection, user, post_id, scheduled_at, payload.schedule.timezone)
    return post_id


def _submit(connection: DatabaseConnection, user: Row, post_id: str, reviewer_user_id: str, message: str) -> None:
    _check_reviewer(connection, user["workspace_id"], reviewer_user_id)
    post = connection.execute("SELECT status FROM posts WHERE id = ?", (post_id,)).fetchone()
    if post["status"] not in ("draft", "changes_requested", "rejected", "approved"):
        raise HTTPException(status_code=409, detail="Only drafts and posts with requested changes can be sent for review.")
    connection.execute(
        "UPDATE posts SET status = 'in_review', reviewer_user_id = ?, submitted_at = ?, decided_at = NULL, updated_at = ? "
        "WHERE id = ?",
        (reviewer_user_id, utc_now(), utc_now(), post_id),
    )
    add_event(connection, post_id, user["id"], "submitted", message or None)


def _visible_post_ids_clause(user: Row) -> tuple[str, list]:
    if user["role"] == "client":
        return "posts.workspace_id = ? AND posts.reviewer_user_id = ?", [user["workspace_id"], user["id"]]
    return "posts.workspace_id = ?", [user["workspace_id"]]


def _get_visible(connection: DatabaseConnection, user: Row, post_id: str) -> PostResponse:
    post = load_post(connection, post_id, user["workspace_id"])
    if user["role"] == "client" and post.reviewer_user_id != user["id"]:
        raise HTTPException(status_code=404, detail="Post not found.")
    return post


@router.get("/api/posts", response_model=list[PostResponse])
def list_posts(
    user: Annotated[Row, Depends(require_member)],
    status_filter: Annotated[Optional[str], Query(alias="status")] = None,
    start: Annotated[Optional[str], Query(alias="from")] = None,
    end: Annotated[Optional[str], Query(alias="to")] = None,
) -> list[PostResponse]:
    clause, params = _visible_post_ids_clause(user)
    if status_filter:
        statuses = [s for s in status_filter.split(",") if s]
        clause += f" AND posts.status IN ({','.join('?' for _ in statuses)})"
        params += statuses
    if start:
        clause += " AND posts.scheduled_at >= ?"
        params.append(start)
    if end:
        clause += " AND posts.scheduled_at < ?"
        params.append(end)
    with connect_database() as connection:
        ids = [row["id"] for row in connection.execute(
            f"SELECT posts.id FROM posts WHERE {clause} "
            "ORDER BY CASE WHEN posts.scheduled_at IS NULL THEN 1 ELSE 0 END, posts.scheduled_at, posts.created_at",
            params,
        ).fetchall()]
        return [load_post(connection, post_id, user["workspace_id"], include_events=False) for post_id in ids]


@router.post("/api/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
def create_post(payload: PostCreate, user: Annotated[Row, Depends(require_content_role)]) -> PostResponse:
    with connect_database() as connection:
        connection.lock_for_write()
        post_id = _create(connection, user, payload)
        return load_post(connection, post_id, user["workspace_id"])


@router.post("/api/posts/bulk", response_model=list[PostResponse], status_code=status.HTTP_201_CREATED)
def create_posts_in_bulk(payload: PostBulkCreate, user: Annotated[Row, Depends(require_content_role)]) -> list[PostResponse]:
    """Create many posts in one all-or-nothing transaction (the bulk scheduler)."""
    with connect_database() as connection:
        connection.lock_for_write()
        ids = []
        for index, item in enumerate(payload.posts, start=1):
            try:
                ids.append(_create(connection, user, item))
            except HTTPException as error:
                raise HTTPException(status_code=error.status_code, detail=f"Post {index}: {error.detail}") from error
        return [load_post(connection, post_id, user["workspace_id"], include_events=False) for post_id in ids]


@router.get("/api/posts/{post_id}", response_model=PostResponse)
def get_post(post_id: str, user: Annotated[Row, Depends(require_member)]) -> PostResponse:
    with connect_database() as connection:
        return _get_visible(connection, user, post_id)


@router.patch("/api/posts/{post_id}", response_model=PostResponse)
def update_post(post_id: str, payload: PostWrite, user: Annotated[Row, Depends(require_content_role)]) -> PostResponse:
    with connect_database() as connection:
        connection.lock_for_write()
        before = load_post(connection, post_id, user["workspace_id"], include_events=False)
        if before.status in LOCKED_STATUSES or before.status not in EDITABLE_STATUSES:
            raise HTTPException(status_code=409, detail="Published posts and posts being published cannot be edited.")
        connection.execute(
            "UPDATE posts SET title = ?, caption = ?, planned_platforms_json = ?, updated_at = ? WHERE id = ?",
            (payload.title.strip(), payload.caption, json.dumps(payload.planned_platforms), utc_now(), post_id),
        )
        _write_content(connection, user, post_id, payload)
        after = load_post(connection, post_id, user["workspace_id"], include_events=False)
        content_changed = (
            before.title != after.title or before.caption != after.caption
            or [m.id for m in before.media] != [m.id for m in after.media]
            or sorted((t.social_account_id, t.caption_override) for t in before.targets)
            != sorted((t.social_account_id, t.caption_override) for t in after.targets)
        )
        new_schedule = to_utc(payload.schedule) if payload.schedule else None
        if before.reviewer_user_id and content_changed and before.status in ("in_review", "approved", "scheduled"):
            # The reviewer approved different content; it needs another look.
            connection.execute("UPDATE posts SET status = 'draft', decided_at = NULL WHERE id = ?", (post_id,))
            connection.execute("UPDATE post_targets SET status = 'pending' WHERE post_id = ? AND status = 'queued'", (post_id,))
            add_event(connection, post_id, user["id"], "edited", "Edited after review was requested; send it for review again.")
        elif before.status == "scheduled":
            add_event(connection, post_id, user["id"], "edited")
            _schedule(connection, user, post_id, new_schedule or before.scheduled_at,
                      payload.schedule.timezone if payload.schedule else before.timezone)
        else:
            if content_changed:
                add_event(connection, post_id, user["id"], "edited")
        if new_schedule and before.status != "scheduled":
            connection.execute("UPDATE posts SET scheduled_at = ?, timezone = ? WHERE id = ?",
                               (new_schedule, payload.schedule.timezone, post_id))
        return load_post(connection, post_id, user["workspace_id"])


@router.delete("/api/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: str, user: Annotated[Row, Depends(require_content_role)]) -> Response:
    with connect_database() as connection:
        connection.lock_for_write()
        post = load_post(connection, post_id, user["workspace_id"], include_events=False)
        if post.status in LOCKED_STATUSES or any(t.status == "published" for t in post.targets):
            raise HTTPException(status_code=409, detail="Posts that were published are kept as a record and cannot be deleted.")
        connection.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        record_audit(connection, user["workspace_id"], user["id"], "post.deleted", "post", post_id, {"title": post.title})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/posts/{post_id}/submit", response_model=PostResponse)
def submit_for_review(post_id: str, payload: PostSubmit, user: Annotated[Row, Depends(require_content_role)]) -> PostResponse:
    with connect_database() as connection:
        connection.lock_for_write()
        load_post(connection, post_id, user["workspace_id"], include_events=False)
        _submit(connection, user, post_id, payload.reviewer_user_id, payload.message)
        return load_post(connection, post_id, user["workspace_id"])


@router.post("/api/posts/{post_id}/review", response_model=PostResponse)
def review_post(post_id: str, payload: PostReview, user: Annotated[Row, Depends(require_member)]) -> PostResponse:
    with connect_database() as connection:
        connection.lock_for_write()
        post = _get_visible(connection, user, post_id)
        if user["id"] != post.reviewer_user_id and user["role"] not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Only the assigned reviewer, an owner or an admin can review this post.")
        if post.status != "in_review":
            raise HTTPException(status_code=409, detail="This post is not waiting for review.")
        if payload.decision != "approve" and not payload.comment.strip():
            raise HTTPException(status_code=422, detail="Tell the team what to change.")
        new_status = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}[payload.decision]
        connection.execute("UPDATE posts SET status = ?, decided_at = ?, updated_at = ? WHERE id = ?",
                           (new_status, utc_now(), utc_now(), post_id))
        add_event(connection, post_id, user["id"], new_status, payload.comment.strip() or None)
        return load_post(connection, post_id, user["workspace_id"])


@router.post("/api/posts/{post_id}/comments", response_model=PostResponse)
def comment_on_post(post_id: str, payload: PostComment, user: Annotated[Row, Depends(require_member)]) -> PostResponse:
    with connect_database() as connection:
        post = _get_visible(connection, user, post_id)
        if user["role"] not in CONTENT_ROLES and user["id"] != post.reviewer_user_id:
            raise HTTPException(status_code=403, detail="You can't comment on this post.")
        add_event(connection, post_id, user["id"], "comment", payload.message.strip())
        return load_post(connection, post_id, user["workspace_id"])


@router.post("/api/posts/{post_id}/schedule", response_model=PostResponse)
def schedule_post(post_id: str, payload: PostScheduleRequest, user: Annotated[Row, Depends(require_content_role)]) -> PostResponse:
    scheduled_at = to_utc(payload.schedule)
    require_future(scheduled_at)
    with connect_database() as connection:
        connection.lock_for_write()
        return _schedule(connection, user, post_id, scheduled_at, payload.schedule.timezone)


@router.post("/api/posts/{post_id}/unschedule", response_model=PostResponse)
def unschedule_post(post_id: str, user: Annotated[Row, Depends(require_content_role)]) -> PostResponse:
    with connect_database() as connection:
        connection.lock_for_write()
        post = load_post(connection, post_id, user["workspace_id"], include_events=False)
        if post.status != "scheduled":
            raise HTTPException(status_code=409, detail="Only scheduled posts can be unscheduled.")
        back_to = "approved" if post.reviewer_user_id else "draft"
        connection.execute("UPDATE posts SET status = ?, updated_at = ? WHERE id = ?", (back_to, utc_now(), post_id))
        connection.execute("UPDATE post_targets SET status = 'pending' WHERE post_id = ? AND status = 'queued'", (post_id,))
        add_event(connection, post_id, user["id"], "unscheduled")
        return load_post(connection, post_id, user["workspace_id"])


@router.post("/api/posts/{post_id}/publish-now", response_model=PostResponse, status_code=status.HTTP_202_ACCEPTED)
def publish_now(post_id: str, background: BackgroundTasks, user: Annotated[Row, Depends(require_content_role)]) -> PostResponse:
    now = datetime.now(timezone.utc).isoformat()
    with connect_database() as connection:
        connection.lock_for_write()
        post = _schedule(connection, user, post_id, now, None)
        add_event(connection, post_id, user["id"], "publish_requested")
    background.add_task(publisher.publish_due, None, post_id)
    return post


@router.post("/api/posts/{post_id}/retry", response_model=PostResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_post(post_id: str, background: BackgroundTasks, user: Annotated[Row, Depends(require_content_role)]) -> PostResponse:
    with connect_database() as connection:
        connection.lock_for_write()
        post = load_post(connection, post_id, user["workspace_id"], include_events=False)
        failed = [t for t in post.targets if t.status == "failed"]
        if not failed:
            raise HTTPException(status_code=409, detail="Nothing failed on this post.")
        blocking = [i for i in post.issues if any(i.account == t.account_name for t in failed)]
        if blocking:
            raise HTTPException(status_code=422, detail="Fix these first: " + " ".join(i.message for i in blocking))
        connection.execute(
            "UPDATE post_targets SET status = 'queued', next_attempt_at = NULL, last_error = NULL "
            "WHERE post_id = ? AND status = 'failed'",
            (post_id,),
        )
        connection.execute("UPDATE posts SET status = 'publishing', updated_at = ? WHERE id = ?", (utc_now(), post_id))
        if not post.scheduled_at or post.scheduled_at > utc_now():
            connection.execute("UPDATE posts SET scheduled_at = ? WHERE id = ?", (utc_now(), post_id))
        add_event(connection, post_id, user["id"], "retried", ", ".join(t.account_name for t in failed))
        refresh_publish_status(connection, post_id)
        result = load_post(connection, post_id, user["workspace_id"])
    background.add_task(publisher.publish_due, None, post_id)
    return result
