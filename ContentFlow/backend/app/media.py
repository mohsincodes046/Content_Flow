"""Uploaded media: verification, Instagram-ready JPEG copies and signed public URLs.

Instagram fetches media from a public URL at publish time. Those URLs are
signed (HMAC) and expire, so a link cannot be guessed or reused later.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError

from app import config

MEDIA_URL_LIFETIME_SECONDS = 2 * 60 * 60
INSTAGRAM_MAX_IMAGE_BYTES = 8 * 1024 * 1024
INSTAGRAM_MAX_WIDTH = 1440
VIDEO_TYPES = {"video/mp4", "video/quicktime"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

Image.MAX_IMAGE_PIXELS = 80_000_000  # refuse decompression bombs


class MediaError(ValueError):
    pass


def inspect_upload(path: Path, media_type: str) -> tuple[Optional[int], Optional[int]]:
    """Check that the bytes really are what the declared type says; return (width, height) for images."""
    if media_type.startswith("image/"):
        if media_type not in IMAGE_TYPES:
            raise MediaError("Upload JPEG, PNG, WebP or GIF images.")
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                return image.size
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise MediaError("This file is not a readable image.") from error
    if media_type.startswith("video/"):
        if media_type not in VIDEO_TYPES:
            raise MediaError("Upload MP4 or MOV videos.")
        with path.open("rb") as handle:
            header = handle.read(12)
        if len(header) < 12 or header[4:8] != b"ftyp":
            raise MediaError("This file is not a readable MP4 or MOV video.")
        return None, None
    raise MediaError("Only image and video files are accepted.")


def asset_path(storage_name: str) -> Path:
    return config.UPLOAD_DIR / storage_name


def instagram_image(storage_name: str, media_type: str) -> str:
    """Storage name of a JPEG Instagram accepts (≤ 8 MB, ≤ 1440 px wide), creating it if needed."""
    source = asset_path(storage_name)
    if media_type == "image/jpeg" and source.stat().st_size <= INSTAGRAM_MAX_IMAGE_BYTES:
        with Image.open(source) as image:
            if image.width <= INSTAGRAM_MAX_WIDTH:
                return storage_name
    derived = f"{storage_name}.instagram.jpg"
    target = asset_path(derived)
    if not target.exists():
        with Image.open(source) as image:
            image = image.convert("RGB")
            if image.width > INSTAGRAM_MAX_WIDTH:
                image = image.resize((INSTAGRAM_MAX_WIDTH, round(image.height * INSTAGRAM_MAX_WIDTH / image.width)))
            image.save(target, "JPEG", quality=90, optimize=True)
    return derived


def _signing_key() -> bytes:
    secret = os.environ.get("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", "").strip()
    if not secret:
        raise MediaError("Configure CONTENT_FLOW_TOKEN_ENCRYPTION_KEY on the backend.")
    return hmac.new(secret.encode("utf-8"), b"content-flow-media-url", hashlib.sha256).digest()


def _signature(storage_name: str, expires: int) -> str:
    return hmac.new(_signing_key(), f"{storage_name}|{expires}".encode("utf-8"), hashlib.sha256).hexdigest()


def signed_media_url(storage_name: str, now: Optional[float] = None) -> str:
    base = config.public_api_url()
    if not base.startswith("https://"):
        raise MediaError(
            "Instagram needs to download the media from a public HTTPS address. "
            "Set CONTENT_FLOW_API_PUBLIC_URL to the API's public HTTPS URL."
        )
    expires = int((time.time() if now is None else now) + MEDIA_URL_LIFETIME_SECONDS)
    return f"{base}/api/media/{storage_name}?expires={expires}&signature={_signature(storage_name, expires)}"


def verify_media_signature(storage_name: str, expires: int, signature: str, now: Optional[float] = None) -> bool:
    if expires < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(signature, _signature(storage_name, expires))
