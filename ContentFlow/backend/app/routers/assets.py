"""Media library: upload, list, view, delete; signed public links for Meta."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

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


class CloudinaryUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    filename: str = Field(default="upload", max_length=255)


def _cloudinary_or_none() -> Optional[media.CloudinaryConfig]:
    try:
        return media.cloudinary_config()
    except media.MediaError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


@router.get("/api/assets/upload-target")
def upload_target(user: Annotated[Row, Depends(require_content_role)]) -> dict[str, object]:
    """Where the browser should send a file: this API (local disk) or Cloudinary (signed, one file)."""
    if _cloudinary_or_none() is None:
        return {"mode": "local"}
    asset_id = str(uuid4())
    return {"mode": "cloudinary", "asset_id": asset_id, **media.cloudinary_upload_target(user["workspace_id"], asset_id)}


@router.post("/api/assets/cloudinary", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def register_cloudinary_asset(
    payload: CloudinaryUpload, user: Annotated[Row, Depends(require_content_role)],
) -> AssetResponse:
    if _cloudinary_or_none() is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cloudinary storage is not enabled.")
    public_id = media.cloudinary_public_id(user["workspace_id"], payload.asset_id)
    details: Optional[dict] = None
    for resource_type in ("image", "video"):
        try:
            details = await asyncio.to_thread(media.cloudinary_resource, resource_type, public_id)
            break
        except media.MediaError:
            continue
        except httpx.HTTPError as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="Could not confirm the upload with Cloudinary. Try again.") from error
    if details is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The upload was not found. Upload the file again.")
    resource_type, fmt = details.get("resource_type"), str(details.get("format", "")).lower()
    media_type = media.CLOUDINARY_FORMATS.get((resource_type, fmt))
    size = int(details.get("bytes") or 0)
    storage_name = media.cloudinary_storage_name(resource_type, public_id, fmt)
    if media_type is None or size <= 0 or size > MAX_UPLOAD_BYTES:
        await asyncio.to_thread(media.cloudinary_destroy, storage_name)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE if media_type is None else status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Upload JPEG, PNG, WebP or GIF images, or MP4 or MOV videos." if media_type is None
            else "Each uploaded file must be 50 MB or smaller.",
        )
    width, height = details.get("width"), details.get("height")
    filename = Path(payload.filename).name or "upload"
    created_at = utc_now()
    with connect_database() as connection:
        if connection.execute("SELECT 1 FROM assets WHERE id = ?", (payload.asset_id,)).fetchone():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This upload is already in your library.")
        connection.execute(
            """
            INSERT INTO assets (id, filename, media_type, size, storage_name, created_at, user_id, workspace_id,
                                width, height)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (payload.asset_id, filename, media_type, size, storage_name, created_at, user["id"], user["workspace_id"],
             width if isinstance(width, int) else None, height if isinstance(height, int) else None),
        )
    return AssetResponse(id=payload.asset_id, filename=filename, media_type=media_type, size=size,
                         width=width if isinstance(width, int) else None,
                         height=height if isinstance(height, int) else None, created_at=created_at)


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
def view_asset(asset_id: str, user: Annotated[Row, Depends(require_member)]) -> Response:
    row = _viewable_asset(user, asset_id)
    if media.is_cloudinary(row["storage_name"]):
        return RedirectResponse(media.cloudinary_url(row["storage_name"]), status_code=status.HTTP_302_FOUND,
                                headers={"Cache-Control": "private, max-age=3600"})
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
        # Only a post that may still publish needs its media. Drafts, rejected, published
        # and failed posts keep their caption, status and published links; they just no
        # longer show this file.
        pending = connection.execute(
            """
            SELECT COUNT(*) AS uses FROM post_media JOIN posts ON posts.id = post_media.post_id
            WHERE post_media.asset_id = ? AND posts.status IN ('in_review', 'approved', 'scheduled', 'publishing')
            """,
            (asset_id,),
        ).fetchone()["uses"]
        if pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This media is in a post that is waiting for review or scheduled to publish. "
                       "Remove it from that post, or unschedule or delete the post, first.",
            )
        connection.execute("DELETE FROM post_media WHERE asset_id = ?", (asset_id,))
        connection.execute("UPDATE scheduled_posts SET asset_id = NULL WHERE asset_id = ?", (asset_id,))
        connection.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        record_audit(connection, user["workspace_id"], user["id"], "asset.deleted", "asset", asset_id,
                     {"filename": row["filename"]})
    if media.is_cloudinary(row["storage_name"]):
        try:
            media.cloudinary_destroy(row["storage_name"])
        except httpx.HTTPError:
            pass  # the library entry is gone; an orphaned remote file is harmless
        return Response(status_code=status.HTTP_204_NO_CONTENT)
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
