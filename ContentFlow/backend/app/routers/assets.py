from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app import config
from app.config import ALLOWED_MEDIA_TYPES, MAX_UPLOAD_BYTES, UPLOAD_CHUNK_BYTES
from app.database import Row, connect_database, utc_now
from app.schemas import AssetResponse
from app.security import get_current_user

router = APIRouter()


@router.post(
    "/api/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    file: Annotated[UploadFile, File()],
    user: Annotated[Row, Depends(get_current_user)],
) -> AssetResponse:
    media_type = file.content_type or ""
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

        filename = Path(file.filename or "upload").name
        created_at = utc_now()
        with connect_database() as connection:
            connection.execute(
                """
                INSERT INTO assets (id, filename, media_type, size, storage_name, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (asset_id, filename, media_type, total_bytes, storage_name, created_at, user["id"]),
            )
        return AssetResponse(
            id=asset_id,
            filename=filename,
            media_type=media_type,
            size=total_bytes,
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
