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


# --- Cloudinary storage (production on hosts without a persistent disk) ------------------
#
# Enabled by CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>. The browser
# uploads straight to Cloudinary with a short-lived signature for a public_id the API
# chose (contentflow/<workspace>/<asset>), then registers it; the API reads the stored
# file's real type, size and dimensions from Cloudinary rather than trusting the browser.
# Assets keep working in local mode: their storage_name is a plain "<id>.upload" file.

CLOUDINARY_PREFIX = "cloudinary:"
CLOUDINARY_FORMATS = {
    ("image", "jpg"): "image/jpeg", ("image", "jpeg"): "image/jpeg", ("image", "png"): "image/png",
    ("image", "webp"): "image/webp", ("image", "gif"): "image/gif",
    ("video", "mp4"): "video/mp4", ("video", "mov"): "video/quicktime",
}
CLOUDINARY_SIGNATURE_LIFETIME_SECONDS = 15 * 60


class CloudinaryConfig:
    def __init__(self, cloud_name: str, api_key: str, api_secret: str) -> None:
        self.cloud_name, self.api_key, self.api_secret = cloud_name, api_key, api_secret


def cloudinary_config() -> Optional[CloudinaryConfig]:
    from urllib.parse import unquote, urlparse

    raw = os.environ.get("CLOUDINARY_URL", "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme != "cloudinary" or not (parsed.username and parsed.password and parsed.hostname):
        raise MediaError("CLOUDINARY_URL must look like cloudinary://<api_key>:<api_secret>@<cloud_name>.")
    return CloudinaryConfig(parsed.hostname, unquote(parsed.username), unquote(parsed.password))


def cloudinary_sign(params: dict[str, object], api_secret: str) -> str:
    """Cloudinary's request signature: SHA-1 of the sorted, non-empty params followed by the secret."""
    payload = "&".join(f"{key}={params[key]}" for key in sorted(params) if params[key] not in (None, ""))
    return hashlib.sha1(f"{payload}{api_secret}".encode("utf-8")).hexdigest()


def cloudinary_public_id(workspace_id: str, asset_id: str) -> str:
    return f"contentflow/{workspace_id}/{asset_id}"


def cloudinary_upload_target(workspace_id: str, asset_id: str, now: Optional[float] = None) -> dict[str, object]:
    cfg = cloudinary_config()
    if cfg is None:
        raise MediaError("Cloudinary is not configured.")
    params: dict[str, object] = {
        "public_id": cloudinary_public_id(workspace_id, asset_id),
        "timestamp": int(time.time() if now is None else now),
        "allowed_formats": "jpg,jpeg,png,webp,gif,mp4,mov",
        "overwrite": "false",
    }
    return {
        "upload_url": f"https://api.cloudinary.com/v1_1/{cfg.cloud_name}/auto/upload",
        "fields": {**params, "api_key": cfg.api_key, "signature": cloudinary_sign(params, cfg.api_secret)},
    }


def is_cloudinary(storage_name: str) -> bool:
    return storage_name.startswith(CLOUDINARY_PREFIX)


def cloudinary_storage_name(resource_type: str, public_id: str, fmt: str) -> str:
    return f"{CLOUDINARY_PREFIX}{resource_type}:{public_id}:{fmt}"


def _parse_cloudinary(storage_name: str) -> tuple[str, str, str]:
    resource_type, public_id, fmt = storage_name[len(CLOUDINARY_PREFIX):].split(":", 2)
    return resource_type, public_id, fmt


def cloudinary_url(storage_name: str, instagram_jpeg: bool = False) -> str:
    """Public HTTPS delivery URL; for Instagram, a JPEG ≤ 1440 px wide converted by Cloudinary."""
    cfg = cloudinary_config()
    if cfg is None:
        raise MediaError("Cloudinary is not configured.")
    resource_type, public_id, fmt = _parse_cloudinary(storage_name)
    if instagram_jpeg and resource_type == "image":
        return f"https://res.cloudinary.com/{cfg.cloud_name}/image/upload/c_limit,w_{INSTAGRAM_MAX_WIDTH},q_90/{public_id}.jpg"
    return f"https://res.cloudinary.com/{cfg.cloud_name}/{resource_type}/upload/{public_id}.{fmt}"


def cloudinary_resource(resource_type: str, public_id: str) -> dict:
    """The stored file's details from Cloudinary's Admin API (authoritative type, size, dimensions)."""
    import httpx

    cfg = cloudinary_config()
    if cfg is None:
        raise MediaError("Cloudinary is not configured.")
    response = httpx.get(
        f"https://api.cloudinary.com/v1_1/{cfg.cloud_name}/resources/{resource_type}/upload/{public_id}",
        auth=(cfg.api_key, cfg.api_secret), timeout=20,
    )
    if response.status_code == 404:
        raise MediaError("The upload was not found in Cloudinary. Upload the file again.")
    response.raise_for_status()
    return response.json()


def cloudinary_destroy(storage_name: str) -> None:
    import httpx

    cfg = cloudinary_config()
    if cfg is None:
        return
    resource_type, public_id, _ = _parse_cloudinary(storage_name)
    params: dict[str, object] = {"public_id": public_id, "timestamp": int(time.time()), "invalidate": "true"}
    httpx.post(
        f"https://api.cloudinary.com/v1_1/{cfg.cloud_name}/{resource_type}/destroy",
        data={**params, "api_key": cfg.api_key, "signature": cloudinary_sign(params, cfg.api_secret)}, timeout=20,
    )


def local_file(storage_name: str) -> Path:
    """A local path to the media bytes (downloaded once and cached for Cloudinary assets)."""
    if not is_cloudinary(storage_name):
        return asset_path(storage_name)
    import httpx

    _, public_id, fmt = _parse_cloudinary(storage_name)
    target = config.UPLOAD_DIR / "cache" / f"{hashlib.sha256(public_id.encode()).hexdigest()}.{fmt}"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        with httpx.stream("GET", cloudinary_url(storage_name), timeout=120, follow_redirects=True) as response:
            response.raise_for_status()
            with partial.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    output.write(chunk)
        partial.replace(target)
    return target


def instagram_media_url(storage_name: str, media_type: str) -> str:
    """The public URL Instagram downloads the media from."""
    if is_cloudinary(storage_name):
        return cloudinary_url(storage_name, instagram_jpeg=media_type.startswith("image/"))
    if media_type.startswith("image/"):
        return signed_media_url(instagram_image(storage_name, media_type))
    return signed_media_url(storage_name)
