"""Media library: upload, list, view, delete; signed public links for Meta."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app import config, media
from app.config import ALLOWED_MEDIA_TYPES, MAX_UPLOAD_BYTES, UPLOAD_CHUNK_BYTES
from app.database import Row, connect_database, utc_now
from app.schemas import AssetResponse
from app.security import record_audit, require_content_role, require_member

router = APIRouter()


def asset_response(row: Row, used_by: int = 0) -> AssetResponse:
    return AssetResponse(
        id=row["id"], filename=row["filename"], media_type=row["media_type"], size=row["size"],
        width=row.get("width"), height=row.get("height"), created_at=row.get("created_at"), used_by_posts=used_by,
    )


@router.post(
    "/api/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    file: Annotated[UploadFile, File()],
    user: Annotated[Row, Depends(require_content_role)],
) -> AssetResponse:
    media_type = (file.content_type or "").lower()
    if not media_type.startswith(ALLOWED_MEDIA_TYPES):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only image and video files are accepted.",
        )

    asset_id = str(uuid4())
    storage_name = f"{asset_id}.upload"
    destination = config.UPLOAD_DIR / storage_name
    total_bytes = 0

    try:
        with destination.open("wb") as output:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Each uploaded file must be 50 MB or smaller.",
                    )
                output.write(chunk)

        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded file is empty.",
            )
        try:
            width, height = media.inspect_upload(destination, media_type)
        except media.MediaError as error:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(error)) from error

        filename = Path(file.filename or "upload").name
        created_at = utc_now()
        with connect_database() as connection:
            connection.execute(
                """
                INSERT INTO assets (id, filename, media_type, size, storage_name, created_at, user_id, workspace_id,
                                    width, height)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (asset_id, filename, media_type, total_bytes, storage_name, created_at, user["id"],
                 user["workspace_id"], width, height),
            )
        return AssetResponse(id=asset_id, filename=filename, media_type=media_type, size=total_bytes,
                             width=width, height=height, created_at=created_at)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/api/assets", response_model=list[AssetResponse])
def list_assets(
    user: Annotated[Row, Depends(require_content_role)],
    kind: Annotated[Optional[str], Query(pattern="^(image|video)$")] = None,
) -> list[AssetResponse]:
    with connect_database() as connection:
        rows = connection.execute(
            """
            SELECT assets.*, (SELECT COUNT(DISTINCT post_id) FROM post_media WHERE post_media.asset_id = assets.id) AS used_by
            FROM assets WHERE workspace_id = ? ORDER BY created_at DESC
            """,
            (user["workspace_id"],),
        ).fetchall()
    return [asset_response(row, row["used_by"]) for row in rows if not kind or row["media_type"].startswith(kind)]


def _viewable_asset(user: Row, asset_id: str) -> Row:
    """Content roles see the workspace library; a client only sees media of posts sent to them."""
    with connect_database() as connection:
        row = connection.execute(
            "SELECT * FROM assets WHERE id = ? AND workspace_id = ?", (asset_id, user["workspace_id"])
        ).fetchone()
        if row is not None and user["role"] == "client":
            assigned = connection.execute(
                """
                SELECT 1 FROM post_media JOIN posts ON posts.id = post_media.post_id
                WHERE post_media.asset_id = ? AND posts.workspace_id = ? AND posts.reviewer_user_id = ?
                """,
                (asset_id, user["workspace_id"], user["id"]),
            ).fetchone()
            if assigned is None:
                row = None
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    return row


@router.get("/api/assets/{asset_id}/content")
def view_asset(asset_id: str, user: Annotated[Row, Depends(require_member)]) -> FileResponse:
    row = _viewable_asset(user, asset_id)
    path = media.asset_path(row["storage_name"])
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The media file is missing.")
    return FileResponse(path, media_type=row["media_type"], filename=row["filename"],
                        content_disposition_type="inline", headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/api/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: str, user: Annotated[Row, Depends(require_content_role)]) -> Response:
    with connect_database() as connection:
        connection.lock_for_write()
        row = connection.execute(
            "SELECT * FROM assets WHERE id = ? AND workspace_id = ?", (asset_id, user["workspace_id"])
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
        in_use = connection.execute(
            """
            SELECT (SELECT COUNT(*) FROM post_media WHERE asset_id = ?)
                 + (SELECT COUNT(*) FROM scheduled_posts WHERE asset_id = ?) AS uses
            """,
            (asset_id, asset_id),
        ).fetchone()["uses"]
        if in_use or row["submission_id"] is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This media is used by a post or submission. Remove it there first.",
            )
        connection.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        record_audit(connection, user["workspace_id"], user["id"], "asset.deleted", "asset", asset_id,
                     {"filename": row["filename"]})
    for name in (row["storage_name"], f"{row['storage_name']}.instagram.jpg"):
        media.asset_path(name).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/media/{storage_name}")
def public_media(storage_name: str, expires: int, signature: str) -> FileResponse:
    """Signed, expiring links so Meta can download media when publishing to Instagram."""
    if "/" in storage_name or "\\" in storage_name or not storage_name.endswith((".upload", ".instagram.jpg")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if not media.verify_media_signature(storage_name, expires, signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This media link is invalid or has expired.")
    base_name = storage_name.removesuffix(".instagram.jpg")
    with connect_database() as connection:
        row = connection.execute("SELECT media_type FROM assets WHERE storage_name = ?", (base_name,)).fetchone()
    path = media.asset_path(storage_name)
    if row is None or not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    media_type = "image/jpeg" if storage_name.endswith(".instagram.jpg") else row["media_type"]
    return FileResponse(path, media_type=media_type)
