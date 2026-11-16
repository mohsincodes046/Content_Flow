from __future__ import annotations

import json
import sqlite3
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import connect_database, utc_now
from app.schemas import AssetResponse, SubmissionCreate, SubmissionResponse
from app.security import get_current_user

router = APIRouter()


def get_assets(asset_ids: list[str], user_id: str) -> list[AssetResponse]:
    if not asset_ids:
        return []

    placeholders = ",".join("?" for _ in asset_ids)
    with connect_database() as connection:
        rows = connection.execute(
            f"""
            SELECT id, filename, media_type, size, submission_id
            FROM assets
            WHERE id IN ({placeholders}) AND user_id = ?
            """,
            [*asset_ids, user_id],
        ).fetchall()

    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(asset_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more uploaded assets could not be found.",
        )

    attached_assets = [by_id[asset_id] for asset_id in asset_ids]
    if any(row["submission_id"] is not None for row in attached_assets):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An uploaded asset is already attached to a submission.",
        )

    return [
        AssetResponse(
            id=row["id"],
            filename=row["filename"],
            media_type=row["media_type"],
            size=row["size"],
        )
        for row in attached_assets
    ]


def submission_from_row(
    row: sqlite3.Row,
    assets: list[AssetResponse],
) -> SubmissionResponse:
    return SubmissionResponse(
        id=row["id"],
        campaign=row["campaign"],
        audience=row["audience"],
        instructions=row["instructions"],
        language=row["language"],
        platforms=json.loads(row["platforms_json"]),
        assets=assets,
        status=row["status"],
        created_at=row["created_at"],
    )



@router.post(
    "/api/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_submission(
    payload: SubmissionCreate,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> SubmissionResponse:
    assets = get_assets(payload.asset_ids, user["id"])
    submission_id = str(uuid4())
    created_at = utc_now()

    with connect_database() as connection:
        connection.execute(
            """
            INSERT INTO submissions (
                id, campaign, audience, instructions, language,
                platforms_json, status, created_at, user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, 'submitted', ?, ?)
            """,
            (
                submission_id,
                payload.campaign,
                payload.audience,
                payload.instructions,
                payload.language,
                json.dumps(payload.platforms),
                created_at,
                user["id"],
            ),
        )
        if payload.asset_ids:
            placeholders = ",".join("?" for _ in payload.asset_ids)
            cursor = connection.execute(
                f"""
                UPDATE assets SET submission_id = ?
                WHERE id IN ({placeholders}) AND submission_id IS NULL
                """,
                [submission_id, *payload.asset_ids],
            )
            if cursor.rowcount != len(payload.asset_ids):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An uploaded asset was attached by another submission.",
                )

        row = connection.execute(
            "SELECT * FROM submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("The saved submission could not be read back.")
    return submission_from_row(row, assets)


@router.get("/api/submissions", response_model=list[SubmissionResponse])
def list_submissions(
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SubmissionResponse]:
    with connect_database() as connection:
        rows = connection.execute(
            "SELECT * FROM submissions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()

        result: list[SubmissionResponse] = []
        for row in rows:
            asset_rows = connection.execute(
                """
                SELECT id, filename, media_type, size
                FROM assets
                WHERE submission_id = ?
                ORDER BY created_at, id
                """,
                (row["id"],),
            ).fetchall()
            assets = [
                AssetResponse(
                    id=asset["id"],
                    filename=asset["filename"],
                    media_type=asset["media_type"],
                    size=asset["size"],
                )
                for asset in asset_rows
            ]
            result.append(submission_from_row(row, assets))

    return result


@router.get("/api/submissions/{submission_id}", response_model=SubmissionResponse)
def read_submission(
    submission_id: str,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> SubmissionResponse:
    with connect_database() as connection:
        row = connection.execute(
            "SELECT * FROM submissions WHERE id = ? AND user_id = ?",
            (submission_id, user["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found.",
            )

        asset_rows = connection.execute(
            """
            SELECT id, filename, media_type, size
            FROM assets
            WHERE submission_id = ?
            ORDER BY created_at, id
            """,
            (submission_id,),
        ).fetchall()

    assets = [
        AssetResponse(
            id=asset["id"],
            filename=asset["filename"],
            media_type=asset["media_type"],
            size=asset["size"],
        )
        for asset in asset_rows
    ]
    return submission_from_row(row, assets)
