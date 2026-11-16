from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.config import Platform
from app.database import Row, connect_database, utc_now
from app.publisher import scheduled_create_utc
from app.schemas import ScheduledPostBatchCreate, ScheduledPostDateUpdate, ScheduledPostResponse
from app.security import get_current_user

router = APIRouter()


def scheduled_post_from_row(row: Row) -> ScheduledPostResponse:
    return ScheduledPostResponse(
        id=row["id"],
        media_name=row["media_name"],
        date=row["scheduled_date"],
        time=row["scheduled_time"],
        platforms=json.loads(row["platforms_json"]),
        caption=row["caption"],
        asset_id=row["asset_id"],
        facebook_account_id=row["facebook_account_id"],
        publish_status=row["publish_status"],
        publish_error=row["publish_error"],
    )



def scheduled_post_conflicts(
    platforms: list[Platform],
    scheduled_date: str,
    scheduled_time: str,
    existing_rows: list[Row],
    *,
    exclude_id: Optional[str] = None,
) -> bool:
    for row in existing_rows:
        if row["id"] == exclude_id:
            continue
        if row["scheduled_date"] != scheduled_date or row["scheduled_time"] != scheduled_time:
            continue
        existing_platforms = set(json.loads(row["platforms_json"]))
        if existing_platforms.intersection(platforms):
            return True
    return False



@router.get("/api/scheduled-posts", response_model=list[ScheduledPostResponse])
def list_scheduled_posts(
    user: Annotated[Row, Depends(get_current_user)],
) -> list[ScheduledPostResponse]:
    with connect_database() as connection:
        rows = connection.execute(
            """
            SELECT * FROM scheduled_posts
            WHERE user_id = ?
            ORDER BY scheduled_date, scheduled_time, created_at
            """,
            (user["id"],),
        ).fetchall()
    return [scheduled_post_from_row(row) for row in rows]


@router.post(
    "/api/scheduled-posts",
    response_model=list[ScheduledPostResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_scheduled_posts(
    payload: ScheduledPostBatchCreate,
    user: Annotated[Row, Depends(get_current_user)],
) -> list[ScheduledPostResponse]:
    incoming = payload.posts
    for post in incoming:
        if post.facebook_account_id and "facebook" not in post.platforms:
            raise HTTPException(
                status_code=422,
                detail="Select Facebook as a channel for the chosen Facebook Page.",
            )
        if post.asset_id and "facebook" in post.platforms and not post.facebook_account_id:
            raise HTTPException(
                status_code=422,
                detail="Choose a connected Facebook Page before scheduling this post.",
            )
        if post.facebook_account_id and not post.asset_id:
            raise HTTPException(
                status_code=422,
                detail="Upload an image before scheduling it to Facebook.",
            )
        if post.asset_id:
            with connect_database() as connection:
                asset = connection.execute(
                    "SELECT media_type FROM assets WHERE id = ? AND user_id = ?",
                    (post.asset_id, user["id"]),
                ).fetchone()
            if asset is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="One or more uploaded assets could not be found.",
                )
            if post.facebook_account_id and not asset["media_type"].startswith("image/"):
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Facebook scheduled publishing currently supports images only.",
                )
        if post.facebook_account_id:
            with connect_database() as connection:
                page = connection.execute(
                    """
                    SELECT id FROM social_accounts
                    WHERE id = ? AND user_id = ? AND provider = 'meta' AND platform = 'facebook'
                    """,
                    (post.facebook_account_id, user["id"]),
                ).fetchone()
            if page is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Choose a Facebook Page connected to this workspace.",
                )
            if scheduled_create_utc(post) <= datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=422,
                    detail="Choose a future date and time for automatic Facebook publishing.",
                )

    for index, post in enumerate(incoming):
        for other in incoming[index + 1 :]:
            if (
                post.date == other.date
                and post.time == other.time
                and set(post.platforms).intersection(other.platforms)
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Two posts cannot use the same channel at the same time.",
                )

    with connect_database() as connection:
        connection.lock_for_write()
        existing_rows = connection.execute(
            "SELECT * FROM scheduled_posts WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        response_rows: list[Row] = []

        for post in incoming:
            scheduled_date = post.date.isoformat()
            scheduled_time = post.time.strftime("%H:%M")
            same_slot = [
                row
                for row in existing_rows
                if row["scheduled_date"] == scheduled_date
                and row["scheduled_time"] == scheduled_time
                and set(json.loads(row["platforms_json"])).intersection(post.platforms)
            ]
            if same_slot:
                identical = next(
                    (
                        row
                        for row in same_slot
                        if row["media_name"] == post.media_name
                        and row["platforms_json"] == json.dumps(post.platforms)
                        and row["caption"] == post.caption
                        and row["asset_id"] == post.asset_id
                        and row["facebook_account_id"] == post.facebook_account_id
                    ),
                    None,
                )
                if identical is not None and len(same_slot) == 1:
                    response_rows.append(identical)
                    continue
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A post is already scheduled for one of these channels at that time.",
                )

            post_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO scheduled_posts (
                    id, media_name, scheduled_date, scheduled_time,
                    platforms_json, caption, created_at, user_id,
                    asset_id, facebook_account_id, timezone_offset_minutes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post_id,
                    post.media_name,
                    scheduled_date,
                    scheduled_time,
                    json.dumps(post.platforms),
                    post.caption,
                    utc_now(),
                    user["id"],
                    post.asset_id,
                    post.facebook_account_id,
                    post.timezone_offset_minutes,
                ),
            )
            row = connection.execute(
                "SELECT * FROM scheduled_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("The scheduled post could not be read back.")
            response_rows.append(row)
            existing_rows.append(row)

    return [scheduled_post_from_row(row) for row in response_rows]


@router.patch("/api/scheduled-posts/{post_id}", response_model=ScheduledPostResponse)
def reschedule_post(
    post_id: str,
    payload: ScheduledPostDateUpdate,
    user: Annotated[Row, Depends(get_current_user)],
) -> ScheduledPostResponse:
    with connect_database() as connection:
        connection.lock_for_write()
        row = connection.execute(
            "SELECT * FROM scheduled_posts WHERE id = ? AND user_id = ?",
            (post_id, user["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scheduled post not found.",
            )
        if row["publish_status"] != "scheduled":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only posts that are still scheduled can be moved.",
            )

        scheduled_date = payload.date.isoformat()
        if row["facebook_account_id"]:
            moved_utc = datetime.combine(
                payload.date, time.fromisoformat(row["scheduled_time"])
            ).replace(
                tzinfo=timezone(timedelta(minutes=-row["timezone_offset_minutes"]))
            )
            if moved_utc <= datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=422,
                    detail="Choose a future date for automatic Facebook publishing.",
                )
        existing_rows = connection.execute(
            "SELECT * FROM scheduled_posts WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        if scheduled_post_conflicts(
            json.loads(row["platforms_json"]),
            scheduled_date,
            row["scheduled_time"],
            existing_rows,
            exclude_id=post_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A post is already scheduled for one of these channels at that time.",
            )

        connection.execute(
            "UPDATE scheduled_posts SET scheduled_date = ? WHERE id = ? AND user_id = ?",
            (scheduled_date, post_id, user["id"]),
        )
        updated = connection.execute(
            "SELECT * FROM scheduled_posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        if updated is None:
            raise RuntimeError("The rescheduled post could not be read back.")

    return scheduled_post_from_row(updated)


@router.delete("/api/scheduled-posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scheduled_post(
    post_id: str,
    user: Annotated[Row, Depends(get_current_user)],
) -> Response:
    with connect_database() as connection:
        cursor = connection.execute(
            """
            DELETE FROM scheduled_posts
            WHERE id = ? AND user_id = ? AND publish_status IN ('scheduled', 'failed')
            """,
            (post_id, user["id"]),
        )
        if cursor.rowcount == 0:
            exists = connection.execute(
                "SELECT 1 FROM scheduled_posts WHERE id = ? AND user_id = ?",
                (post_id, user["id"]),
            ).fetchone()
            if exists is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A post that is publishing or already published cannot be removed.",
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scheduled post not found.",
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
